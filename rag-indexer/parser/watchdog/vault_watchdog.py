"""Vault Watchdog — фоновый asyncio-луп обнаружения изменений vault.

Алгоритм:
  1. Запросить все активные vault из БД (только enabled=true)
  2. Для каждого vault: скан диска, diff с Redis-кэшем
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
WATCHDOG_SETTING_KEY = "watchdog_auto_index_extensions"


async def watchdog_loop(
    db_client: "IndexerDBClient",
    state_manager: RedisStateManager,
    indexer_service: "IndexerService",
    storage_client: StorageClient,
    interval_sec: int = 60,
) -> None:
    """Фоновый луп. Запускается через asyncio.create_task в lifespan.

    storage_client передаётся снаружи (создаётся один раз в lifespan),
    а не создаётся на каждой итерации.
    """
    logger.info("Vault watchdog started (interval=%ds)", interval_sec)
    while True:
        try:
            await _run_once(db_client, state_manager, indexer_service, storage_client)
        except asyncio.CancelledError:
            logger.info("Vault watchdog stopped.")
            return
        except Exception:
            logger.exception("Vault watchdog iteration failed, will retry")
        await asyncio.sleep(interval_sec)


async def _run_once(
    db_client: "IndexerDBClient",
    state_manager: RedisStateManager,
    indexer_service: "IndexerService",
    storage_client: StorageClient,
) -> None:
    """One watchdog iteration across all enabled vaults."""
    # get_setting возвращает None если ключ не найден ИЛИ value=""
    # (сценарий 3 — только ручная индексация): используем `or ""` как guard.
    raw_setting: str = await db_client.get_setting(WATCHDOG_SETTING_KEY) or ""
    auto_extensions: set[str] = {
        ext.strip() for ext in raw_setting.split(",") if ext.strip()
    }

    # get_all_vaults возвращает только enabled=true вольты
    vaults = await db_client.get_all_vaults()

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
    db_client: "IndexerDBClient",
    state_manager: RedisStateManager,
    indexer_service: "IndexerService",
    storage_client: StorageClient,
) -> None:
    # vault_path строится из env, т.к. vault_path — не колонка в БД
    vault_path = f"{VAULT_DATA_ROOT}/{vault_id}"
    if not os.path.isdir(vault_path):
        return

    # Скан диска (в потоке — блокирующая операция)
    # Отдельно перехватываем FS-ошибки: директория могла исчезнуть между
    # проверкой isdir и вызовом scan_vault (race condition).
    try:
        disk_files: list[dict[str, Any]] = await asyncio.to_thread(scan_vault, vault_path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        logger.warning(
            "Watchdog: vault directory unavailable vault_id=%s: %s",
            vault_id, exc,
        )
        return

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
            # Файл изменён.
            # indexed_md5 — поле vault:{vault_id}:files HASH, пишется в
            # mark_file_indexed и rebuild_vault_cache. Не путать с
            # checksum_md5, которое живёт только в task:{task_id}:files.
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
        # is_vault_indexing использует Redis (переживает рестарт процесса),
        # а не in-memory IndexerService.get_active_tasks()
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
    db_client: "IndexerDBClient",
    state_manager: RedisStateManager,
    storage_client: StorageClient,
) -> None:
    """Atomically remove a deleted file from LanceDB + PostgreSQL + Redis.

    Order: LanceDB → PG → Redis.
    Redis удаляется последним — при сбое на предыдущих шагах
    следующая итерация watchdog повторит попытку.
    """
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
    # else: файл никогда не был проиндексирован (нет записи в documents) —
    # LanceDB и PG пропускаем, очищаем только Redis-кэш (шаг 3).

    # 3. Redis cache (всегда, даже если doc not in PG)
    await state_manager.remove_file_from_vault_cache(vault_id, relative_path)
