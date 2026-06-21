# Этап 2 — rag-indexer: вспомогательные методы IndexerDBClient + RedisStateManager

## Цель

Добавить методы, необходимые watchdog-у для:
- удаления исчезнувшего файла из PostgreSQL (`documents`)
- чтения одной настройки из `platform_settings` с правильной типизацией
- пометки файла как `pending` в vault-кэше Redis
- удаления файла из vault-кэша Redis
- чтения одной и всех записей vault-кэша

## Контекст из кодовой базы

### `StorageClient` (уже есть — не трогать)

`rag-indexer/storage/storage_client.py` уже содержит `delete_document(document_id, vault_id)` —
делает `DELETE /index/document/{document_id}?vault_id=...` к `db-api-server` и удаляет чанки из **LanceDB**.
**Этот метод используется watchdog-ом для удаления из векторного хранилища. Добавлять ничего не нужно.**

### `IndexerDBClient` (уже есть)

`rag-indexer/app/db_client.py` уже содержит:
- `get_document_by_path(vault_id, source_path)` — получить `id` документа
- `get_platform_settings()` — вернёт dict со всеми настройками (с типизацией через `_cast_value`)

### `RedisStateManager` (уже есть)

`rag-indexer/parser/state/redis_state_manager.py` уже содержит:
- `mark_file_indexed(vault_id, relative_path, md5, chunks_total)` — помечает `index_status="indexed"`
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
    """Deletes a document record from PostgreSQL by id.

    NOTE: does NOT touch LanceDB — use StorageClient.delete_document() for that.
    """
    await self._execute(
        "DELETE FROM documents WHERE id = $1",
        document_id,
    )
```

> ❗ Не путать с `StorageClient.delete_document(document_id, vault_id)` —
> это другой метод с другим назначением. `StorageClient` удаляет из **LanceDB**,
> `IndexerDBClient` удаляет из **PostgreSQL**.

### 2. `IndexerDBClient.get_setting(key)` — в `db_client.py`

Watchdog читает настройку на каждой итерации из БД. Вместо `get_platform_settings()` (читает всё)
делаем точечный запрос по ключу. Возвращает значение с типизацией через уже существующий `_cast_value`,
либо `None` если ключ не найден.

```python
async def get_setting(self, key: str) -> Any:
    """Returns the typed value of a platform_settings key.

    Uses _cast_value() consistent with get_platform_settings().
    Returns None if the key does not exist OR if value is an empty string
    (because _cast_value returns `value or None` for value_type='str').
    """
    row = await self._fetchrow(
        "SELECT value, value_type FROM platform_settings WHERE key = $1",
        key,
    )
    if row is None:
        return None
    return self._cast_value(row["value"], row["value_type"])
```

> ⚠️ Возвращает `None` как если ключ отсутствует, **так и если value — пустая строка**
> (это поведение `_cast_value` при `value_type='str'`: `return value or None`).
> Вызывающий код **обязан** проверять на `None` перед использованием.

#### Правильный паттерн разбора в watchdog

Пример использования `get_setting` для чтения расширений:

```python
raw = await db_client.get_setting("watchdog_auto_index_extensions")
# raw: str | None
# None если ключ не найден ИЛИ если value="" (сценарий 3 — только ручная индексация)
extensions = (
    [e.strip() for e in raw.split(",") if e.strip()]
    if raw
    else []
)
# extensions: list[str], например [".md", ".pdf"]
# Если ключ не найден или пуст — пустой список, авто-индексация не выполняется
```

> ⚠️ Не писать `"".split(",")` без проверки — это вернёт `[""]` (список
> с одной пустой строкой), а не `[]`. Всегда использовать паттерн выше.

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
    # Guard `!= "1"` защищает от нечаянного коллижена с сентинелом __empty__,
    # который хранит значение "1" (аналогично mark_file_indexed).
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

### RedisStateManager — `rag-indexer/tests/test_redis_state_manager.py`

Тесты с `fakeredis[aioredis]>=2.0`.

> ⚠️ Обязательно добавить `pytestmark = pytest.mark.asyncio` на уровне модуля
> или декоратор `@pytest.mark.asyncio` на каждую async-функцию,
> иначе pytest не будет запускать корутины как тесты.

```python
import fakeredis.aioredis
import pytest
from parser.state.redis_state_manager import RedisStateManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def mgr():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisStateManager(r)


async def test_mark_file_pending_sets_status(mgr):
    await mgr.mark_file_indexed("v1", "a.md", "abc", 5)
    await mgr.mark_file_pending("v1", "a.md")
    entry = await mgr.get_vault_file_entry("v1", "a.md")
    assert entry["index_status"] == "pending"
    # Остальные поля сохранены
    assert entry["indexed_md5"] == "abc"
    assert entry["chunks_total"] == 5


async def test_mark_file_pending_creates_entry_if_missing(mgr):
    await mgr.mark_file_pending("v1", "new.md")
    entry = await mgr.get_vault_file_entry("v1", "new.md")
    assert entry is not None
    assert entry["index_status"] == "pending"


async def test_remove_file_from_vault_cache(mgr):
    await mgr.mark_file_indexed("v1", "a.md", "abc", 5)
    await mgr.remove_file_from_vault_cache("v1", "a.md")
    entry = await mgr.get_vault_file_entry("v1", "a.md")
    assert entry is None


async def test_get_vault_file_entry_returns_none_for_missing(mgr):
    entry = await mgr.get_vault_file_entry("v1", "nonexistent.md")
    assert entry is None


async def test_get_all_vault_file_entries_skips_empty_sentinel(mgr):
    # Имитируем пустой vault (rebuild с пустым состоянием создаёт __empty__)
    await mgr._r.hset("vault:v1:files", "__empty__", "1")
    entries = await mgr.get_all_vault_file_entries("v1")
    assert "__empty__" not in entries
    assert entries == {}


async def test_get_all_vault_file_entries_returns_all(mgr):
    await mgr.mark_file_indexed("v1", "a.md", "abc", 3)
    await mgr.mark_file_pending("v1", "b.md")
    entries = await mgr.get_all_vault_file_entries("v1")
    assert set(entries.keys()) == {"a.md", "b.md"}
    assert entries["a.md"]["index_status"] == "indexed"
    assert entries["b.md"]["index_status"] == "pending"
```

### IndexerDBClient.get_setting — `rag-indexer/tests/test_db_client_get_setting.py`

Тест с `asyncpg` mock (monkeypatch пула).

> ⚠️ Аналогично — добавить `pytestmark = pytest.mark.asyncio` на уровне модуля.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.db_client import IndexerDBClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    c = IndexerDBClient()
    c.pool = MagicMock()  # pool не None — не вызывает RuntimeError
    return c


async def test_get_setting_returns_typed_value(client):
    row = {"value": "true", "value_type": "bool"}
    client._fetchrow = AsyncMock(return_value=row)
    result = await client.get_setting("some_flag")
    assert result is True


async def test_get_setting_returns_none_if_missing(client):
    client._fetchrow = AsyncMock(return_value=None)
    result = await client.get_setting("nonexistent_key")
    assert result is None


async def test_get_setting_returns_string_list_extensions(client):
    row = {"value": ".md,.pdf", "value_type": "str"}
    client._fetchrow = AsyncMock(return_value=row)
    raw = await client.get_setting("watchdog_auto_index_extensions")
    extensions = [e.strip() for e in raw.split(",") if e.strip()] if raw else []
    assert extensions == [".md", ".pdf"]


async def test_get_setting_returns_none_for_empty_string(client):
    # _cast_value при value_type='str' возвращает `value or None`,
    # поэтому пустая строка (сценарий 3 — только ручная индексация) → None.
    row = {"value": "", "value_type": "str"}
    client._fetchrow = AsyncMock(return_value=row)
    raw = await client.get_setting("watchdog_auto_index_extensions")
    assert raw is None
    # Паттерн разбора в watchdog должен корректно обработать None → []
    extensions = [e.strip() for e in raw.split(",") if e.strip()] if raw else []
    assert extensions == []
```
