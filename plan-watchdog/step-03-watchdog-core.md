# Этап 3 — rag-indexer: vault_watchdog.py

## Цель

Создать `rag-indexer/parser/watchdog/vault_watchdog.py` — основной asyncio-луп
обнаружения изменений vault-директорий.

## Контекст из кодовой базы

### `scan_vault` (уже есть)

`rag-indexer/parser/scanning/vault_scanner.py` — возвращает список `dict`:
```python
{
    "path": str,           # абсолютный путь
    "relative_path": str,  # относительный путь от корня vault
    "extension": str,      # напр.: '.md'
    "checksum": str,       # md5-хеш
    "last_modified": float, # st_mtime
    "size_bytes": int,
}
```

Важно: `scan_vault` всегда считает md5. Watchdog использует его напрямую
(оптимизация mtime реализуется в самом watchdog перед запуском `scan_vault`).

### `IndexerService.start_task` (уже есть)

`rag-indexer/app/indexer_service.py` — `await service.start_task(vault_id, force_reindex=False)`.
Watchdog вызывает его напрямую.

### `IndexerService.get_active_tasks` (уже есть)

Возвращает `list[str]` task_id. Watchdog проверяет: если vault уже
индексируется — новую задачу не запускает.

❗ `get_active_tasks()` возвращает task_id, не vault_id. Watchdog не может
напрямую знать vault_id активных задач. Решение:
проверяем `vault:{vault_id}:files` в Redis на наличие `task_state="running"`
через новый метод `RedisStateManager.get_vault_active_task_id(vault_id)` —
см. раздел ниже.

## Что нужно создать

### Дополнительный метод в `RedisStateManager`

Добавить в `redis_state_manager.py` (как часть этапа 2 или сейчас):

```python
async def is_vault_indexing(self, vault_id: str) -> bool:
    """Returns True if there is a running task for this vault in Redis.

    Scans task:* HASHes for vault_id + status=running.
    Cheaper alternative: check active_tasks SET, then HGET each task HASH.
    """
    active_ids = await self._r.smembers("active_tasks")
    for task_id in active_ids:
        task_data = await self._r.hgetall(f"task:{task_id}")
        if (
            task_data.get("vault_id") == vault_id
            and task_data.get("status") == "running"
        ):
            return True
    return False
```

### `rag-indexer/parser/watchdog/__init__.py`

Пустой файл.

### `rag-indexer/parser/watchdog/vault_watchdog.py`

```python
"""Vault Watchdog — фоновый asyncio-луп обнаружения изменений vault.

Алгоритм:
  1. Запросить все активные vault из БД
  2. Для каждого vault: скан диска, diff с Redis-кэше
  3. Удалённые → атомарно: LanceDB + PG + Redis
  4. Изменённые/новые → авто-индексация или пометка pending
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from parser.scanning.vault_scanner import scan_vault
from parser.state.redis_state_manager import RedisStateManager
from storage.storage_client import StorageClient

if TYPE_CHECKING:
    from app.db_client import IndexerDBClient
    from app.indexer_service import IndexerService

logger = logging.getLogger(__name__)

VAULT_DATA_ROOT = os.getenv("VAULT_DATA_ROOT", "/data/vaults")
STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")
WATCHDOG_SETTING_KEY = "watchdog_auto_index_extensions"


async def watchdog_loop(
    db_client: IndexerDBClient,
    state_manager: RedisStateManager,
    indexer_service: IndexerService,
    interval_sec: int = 60,
) -> None:
    """Фоновый луп. Запускается через asyncio.create_task в lifespan."""
    logger.info("Vault watchdog started (interval=%ds)", interval_sec)
    while True:
        try:
            await _run_once(db_client, state_manager, indexer_service)
        except asyncio.CancelledError:
            logger.info("Vault watchdog stopped.")
            return
        except Exception:
            logger.exception("Vault watchdog iteration failed, will retry")
        await asyncio.sleep(interval_sec)


async def _run_once(
    db_client: IndexerDBClient,
    state_manager: RedisStateManager,
    indexer_service: IndexerService,
) -> None:
    """One watchdog iteration across all enabled vaults."""
    # Читаем настройку из БД на каждой итерации
    raw_setting = await db_client.get_setting(WATCHDOG_SETTING_KEY)
    auto_extensions: set[str] = {
        ext.strip() for ext in raw_setting.split(",") if ext.strip()
    }

    vaults = await db_client.get_all_vaults()
    storage_client = StorageClient(STORAGE_API_URL)

    for vault in vaults:
        vault_id = vault["vault_id"]
        try:
            await _process_vault(
                vault_id=vault_id,
                auto_extensions=auto_extensions,
                db_client=db_client,
                state_manager=state_manager,
                indexer_service=indexer_service,
                storage_client=storage_client,
            )
        except Exception:
            logger.exception("Watchdog: error processing vault_id=%s", vault_id)


async def _process_vault(
    vault_id: str,
    auto_extensions: set[str],
    db_client: IndexerDBClient,
    state_manager: RedisStateManager,
    indexer_service: IndexerService,
    storage_client: StorageClient,
) -> None:
    vault_path = f"{VAULT_DATA_ROOT}/{vault_id}"
    if not os.path.isdir(vault_path):
        return

    # Скан диска (в потоке — блокирующая операция)
    disk_files: list[dict[str, Any]] = await asyncio.to_thread(scan_vault, vault_path)
    disk_index = {f["relative_path"]: f for f in disk_files}

    # Читаем весь vault-кэш за один HGETALL
    cache = await state_manager.get_all_vault_file_entries(vault_id)

    # Обнаруживаем удалённые
    deleted_paths = [p for p in cache if p not in disk_index]
    for path in deleted_paths:
        await _handle_deleted(
            vault_id=vault_id,
            relative_path=path,
            db_client=db_client,
            state_manager=state_manager,
            storage_client=storage_client,
        )

    # Обнаруживаем новые / изменённые
    changed: list[dict[str, Any]] = []
    for path, disk_file in disk_index.items():
        entry = cache.get(path)
        if entry is None:
            # Новый файл
            changed.append(disk_file)
        elif disk_file["checksum"] != entry.get("indexed_md5", ""):
            # Файл изменён
            changed.append(disk_file)

    if not changed:
        return

    logger.info(
        "Watchdog: vault_id=%s changed=%d files",
        vault_id, len(changed),
    )

    to_auto = [f for f in changed if f["extension"] in auto_extensions]
    to_mark = [f for f in changed if f["extension"] not in auto_extensions]

    for f in to_mark:
        await state_manager.mark_file_pending(vault_id, f["relative_path"])
        logger.debug(
            "Watchdog: marked pending vault_id=%s path=%s",
            vault_id, f["relative_path"],
        )

    if to_auto:
        already_indexing = await state_manager.is_vault_indexing(vault_id)
        if not already_indexing:
            try:
                task_id = await indexer_service.start_task(vault_id, force_reindex=False)
                logger.info(
                    "Watchdog: started task task_id=%s vault_id=%s files=%d",
                    task_id, vault_id, len(to_auto),
                )
            except (KeyError, ValueError) as exc:
                logger.warning(
                    "Watchdog: could not start task vault_id=%s: %s",
                    vault_id, exc,
                )
        else:
            logger.debug(
                "Watchdog: vault_id=%s already indexing, skip auto-start",
                vault_id,
            )


async def _handle_deleted(
    vault_id: str,
    relative_path: str,
    db_client: IndexerDBClient,
    state_manager: RedisStateManager,
    storage_client: StorageClient,
) -> None:
    """Atomically remove a deleted file from LanceDB + PostgreSQL + Redis."""
    logger.info(
        "Watchdog: file deleted vault_id=%s path=%s",
        vault_id, relative_path,
    )
    doc = await db_client.get_document_by_path(vault_id, relative_path)
    if doc is not None:
        document_id = str(doc["id"])
        # 1. LanceDB
        try:
            await storage_client.delete_document(document_id, vault_id)
        except Exception:
            logger.warning(
                "Watchdog: failed to delete LanceDB chunks document_id=%s",
                document_id, exc_info=True,
            )
        # 2. PostgreSQL
        try:
            await db_client.delete_document(document_id)
        except Exception:
            logger.warning(
                "Watchdog: failed to delete PG document document_id=%s",
                document_id, exc_info=True,
            )
    # 3. Redis cache (всегда, даже если doc not in PG)
    await state_manager.remove_file_from_vault_cache(vault_id, relative_path)
```

## Файлы для создания / изменения

| Файл | Действие |
|---|---|
| `rag-indexer/parser/watchdog/__init__.py` | Создать (пустой) |
| `rag-indexer/parser/watchdog/vault_watchdog.py` | Создать по коду выше |
| `rag-indexer/parser/state/redis_state_manager.py` | `+is_vault_indexing(vault_id)` |

## ✅ Unit-тесты

```
rag-indexer/tests/test_vault_watchdog.py
```

C `fakeredis` + `unittest.mock.AsyncMock` для `db_client`, `indexer_service`, `storage_client`:

```python
import pytest
from unittest.mock import AsyncMock, patch
import fakeredis.aioredis
from parser.state.redis_state_manager import RedisStateManager
from parser.watchdog.vault_watchdog import _process_vault


@pytest.fixture
async def state_mgr():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisStateManager(r)


async def test_new_file_auto_indexed(state_mgr):
    """New .md file with .md in auto_extensions -> start_task called."""
    db = AsyncMock()
    db.get_document_by_path.return_value = None
    svc = AsyncMock()
    svc.start_task.return_value = "task-xyz"
    storage = AsyncMock()

    disk_file = {
        "relative_path": "notes.md",
        "extension": ".md",
        "checksum": "abc123",
        "path": "/data/vaults/v1/notes.md",
        "last_modified": 1700000000.0,
        "size_bytes": 100,
    }

    with patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        return_value=[disk_file],
    ), patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    svc.start_task.assert_awaited_once_with("v1", force_reindex=False)


async def test_new_file_marked_pending_when_not_in_auto(state_mgr):
    """New .pdf file with only .md in auto_extensions -> marked pending."""
    db = AsyncMock()
    svc = AsyncMock()
    storage = AsyncMock()

    disk_file = {
        "relative_path": "report.pdf",
        "extension": ".pdf",
        "checksum": "def456",
        "path": "/data/vaults/v1/report.pdf",
        "last_modified": 1700000001.0,
        "size_bytes": 200,
    }

    with patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        return_value=[disk_file],
    ), patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    svc.start_task.assert_not_awaited()
    entry = await state_mgr.get_vault_file_entry("v1", "report.pdf")
    assert entry["index_status"] == "pending"


async def test_deleted_file_removed_from_all_stores(state_mgr):
    """File in cache but not on disk -> LanceDB+PG+Redis cleanup."""
    await state_mgr.mark_file_indexed("v1", "old.md", "aaa", 3)

    db = AsyncMock()
    db.get_document_by_path.return_value = {"id": "doc-1"}
    svc = AsyncMock()
    storage = AsyncMock()

    with patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        return_value=[],  # диск пустой
    ), patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    storage.delete_document.assert_awaited_once()
    db.delete_document.assert_awaited_once_with("doc-1")
    entry = await state_mgr.get_vault_file_entry("v1", "old.md")
    assert entry is None
```

## Критерий готовности

- [ ] `vault_watchdog.py` создан, `watchdog_loop` запускается без ошибок
- [ ] Сценарий 1: новый файл + ext в auto_extensions → `start_task` вызван
- [ ] Сценарий 2: новый файл + ext НЕ в auto_extensions → `pending`, `start_task` не вызван
- [ ] Сценарий 3: файл исчез → LanceDB+PG+Redis очищены
- [ ] unit-тесты проходят
- [ ] `STATUS.md` обновлён: этап 3 → ✅
