# Этап 2 — rag-indexer: новые методы db_client + RedisStateManager

## Цель

Добавить методы, необходимые watchdog-у для:
- удаления исчезнувшего файла из всех хранилищ
- пометки файла как `pending` в vault-кэше
- чтения настройки `watchdog_auto_index_extensions` из БД

## Контекст из кодовой базы

### `StorageClient` (уже есть)

`rag-indexer/storage/storage_client.py` уже содержит `delete_document(document_id, vault_id)` —
делает `DELETE /index/document/{document_id}?vault_id=...` к `db-api-server`.
**Добавлять ничего не нужно.** Этот метод и есть `delete_chunks_by_document_id` для watchdog.

### `IndexerDBClient` (уже есть)

`rag-indexer/app/db_client.py` уже содержит:
- `get_document_by_path(vault_id, source_path)` — получить `id` документа
- `get_platform_settings()` — вернёт dict со всеми настройками

### `RedisStateManager` (уже есть)

`rag-indexer/parser/state/redis_state_manager.py` уже содержит:
- `mark_file_indexed(vault_id, relative_path, md5, chunks_total)` — помечает `index_status="indexed"` в vault-кэше
- `get_vault_state(vault_id)` — возвращает `{files, counts}`

### Структура `vault:{vault_id}:files` HASH (entry)

```json
{
  "md5": "...",
  "index_status": "indexed",  // pending | indexed | stale | deleted
  "indexed_md5": "...",
  "chunks_total": 0
}
```

`indexed_md5` — md5 на момент последней успешной индексации.  
`md5` — текущий md5 файла на диске.

Watchdog сравнивает: `disk_checksum != entry["indexed_md5"]` → файл изменён.

## Что нужно добавить

### 1. `IndexerDBClient.delete_document(document_id)` — в `db_client.py`

Удаляет запись из `documents` по `id`.

```python
async def delete_document(self, document_id: str) -> None:
    await self._execute(
        "DELETE FROM documents WHERE id = $1",
        document_id,
    )
```

> ❗ Не путать с `StorageClient.delete_document(document_id, vault_id)` —
> это другой метод с другим назначением. `StorageClient` удаляет из LanceDB,
> `IndexerDBClient` удаляет из PostgreSQL.

### 2. `IndexerDBClient.get_setting(key)` — в `db_client.py`

Watchdog читает настройку на каждой итерации из БД. Вместо `get_platform_settings()` (читает всё)
делаем точечный запрос по ключу:

```python
async def get_setting(self, key: str) -> str:
    """Returns the raw string value of a platform_settings key.

    Returns '' if the key does not exist.
    """
    row = await self._fetchrow(
        "SELECT value FROM platform_settings WHERE key = $1",
        key,
    )
    return row["value"] if row is not None else ""
```

Возвращает рав `str` — watchdog сам разбивает `','.split()`.

### 3. `RedisStateManager.mark_file_pending(vault_id, relative_path)` — в `redis_state_manager.py`

Устанавливает `index_status="pending"` в vault-кэше (не запуская задачу индексации).
Используется в сценариях 2 и 3 (выборочная / ручная индексация).

```python
async def mark_file_pending(
    self,
    vault_id: str,
    relative_path: str,
) -> None:
    """Sets index_status='pending' in vault:{vault_id}:files.

    Preserves existing md5/indexed_md5/chunks_total fields.
    Does NOT remove the file from vault cache.
    """
    vault_key = f"vault:{vault_id}:files"
    existing_raw = await self._r.hget(vault_key, relative_path)
    if existing_raw and existing_raw != "1":
        try:
            existing = json.loads(existing_raw)
        except json.JSONDecodeError:
            existing = {}
    else:
        existing = {}

    existing["index_status"] = "pending"
    await self._r.hset(
        vault_key, relative_path, json.dumps(existing, ensure_ascii=False)
    )
```

### 4. `RedisStateManager.remove_file_from_vault_cache(vault_id, relative_path)` — в `redis_state_manager.py`

Удаляет ключ файла из vault-кэша (для удалённых с диска файлов).

```python
async def remove_file_from_vault_cache(
    self,
    vault_id: str,
    relative_path: str,
) -> None:
    """HDEL vault:{vault_id}:files relative_path."""
    await self._r.hdel(f"vault:{vault_id}:files", relative_path)
```

### 5. `RedisStateManager.get_vault_file_entry(vault_id, relative_path)` — в `redis_state_manager.py`

Читает один файл из vault-кэша. Watchdog использует для mtime-оптимизации.

```python
async def get_vault_file_entry(
    self,
    vault_id: str,
    relative_path: str,
) -> dict[str, Any] | None:
    """Returns parsed entry from vault:{vault_id}:files or None."""
    raw = await self._r.hget(f"vault:{vault_id}:files", relative_path)
    if not raw or raw == "1":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
```

### 6. `RedisStateManager.get_all_vault_file_entries(vault_id)` — в `redis_state_manager.py`

Watchdog читает весь vault-кэш за один `HGETALL` для diff.

```python
async def get_all_vault_file_entries(
    self,
    vault_id: str,
) -> dict[str, dict[str, Any]]:
    """Returns all file entries from vault:{vault_id}:files.

    Skips the __empty__ sentinel.
    Returns {relative_path: entry_dict}.
    """
    raw = await self._r.hgetall(f"vault:{vault_id}:files")
    result: dict[str, dict[str, Any]] = {}
    for path, value in raw.items():
        if path == "__empty__":
            continue
        try:
            result[path] = json.loads(value)
        except json.JSONDecodeError:
            result[path] = {"index_status": "unknown"}
    return result
```

## Файлы для изменения

| Файл | Действие |
|---|---|
| `rag-indexer/app/db_client.py` | `+delete_document(document_id)`, `+get_setting(key)` |
| `rag-indexer/parser/state/redis_state_manager.py` | `+mark_file_pending`, `+remove_file_from_vault_cache`, `+get_vault_file_entry`, `+get_all_vault_file_entries` |

## ✅ Unit-тесты

```
rag-indexer/tests/test_redis_state_manager.py
```

Тесты с `fakeredis[aioredis]>=2.0`:

```python
import fakeredis.aioredis
import pytest
from parser.state.redis_state_manager import RedisStateManager


@pytest.fixture
async def mgr():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisStateManager(r)


async def test_mark_file_pending_sets_status(mgr):
    await mgr.mark_file_indexed("v1", "a.md", "abc", 5)
    await mgr.mark_file_pending("v1", "a.md")
    entry = await mgr.get_vault_file_entry("v1", "a.md")
    assert entry["index_status"] == "pending"
    # indexed_md5 сохранился
    assert entry["indexed_md5"] == "abc"


async def test_remove_file_from_vault_cache(mgr):
    await mgr.mark_file_indexed("v1", "b.pdf", "xyz", 3)
    await mgr.remove_file_from_vault_cache("v1", "b.pdf")
    entry = await mgr.get_vault_file_entry("v1", "b.pdf")
    assert entry is None


async def test_get_all_vault_file_entries_skips_sentinel(mgr):
    # Сентинел не должен попасть в результат
    await mgr._r.hset("vault:v2:files", "__empty__", "1")
    entries = await mgr.get_all_vault_file_entries("v2")
    assert "__empty__" not in entries
```

## Критерий готовности

- [ ] `db_client.delete_document(document_id)` — удаляет из `documents` по `id`
- [ ] `db_client.get_setting(key)` — возвращает `''` если ключ не найден
- [ ] все методы `RedisStateManager` добавлены
- [ ] unit-тесты проходят с `fakeredis`
- [ ] `STATUS.md` обновлён: этап 2 → ✅
