# Этап 4: rag-indexer — RedisStateManager

## Цель
Создать `rag-indexer/parser/state/redis_state_manager.py` — полная замена
`parser/state/state_manager.py`. Удалить старый файл.

## Зависимости
- Этап 1 (Redis в docker-compose) — завершён
- Этап 2 (удалён chunk_ids из FileIndexState) — завершён

## Перед началом — прочитай текущие файлы
- `rag-indexer/parser/state/state_manager.py` — текущая реализация, контракт функций
- `rag-indexer/requirements.txt` — добавить зависимость

## Что добавить в requirements.txt

```
redis[asyncio]>=5.0
```

Удалить (если есть):
```
websockets
```

## Новый файл: `rag-indexer/parser/state/redis_state_manager.py`

### Публичный контракт (все методы async)

```python
class RedisStateManager:
    def __init__(self, redis: aioredis.Redis): ...

    # --- Задачи индексации (TTL 24ч) ---

    async def create_task(
        self,
        task_id: str,
        vault_id: str,
        files_to_index: list[dict],   # только новые/изменённые файлы
        files_skipped: int,           # кол-во пропущенных (неизменённых)
        files_total: int,
    ) -> None: ...
    # Создаёт task:{task_id} HASH и task:{task_id}:files HASH
    # Устанавливает TTL 86400 на оба ключа
    # Добавляет task_id в SET active_tasks

    async def update_file_stage(
        self,
        task_id: str,
        relative_path: str,
        stage: str,                   # pending|parsing|chunking|indexing|done|error|empty
        chunks_total: int = 0,
        chunks_done: int = 0,
        checksum_md5: str = "",
        error: str | None = None,
    ) -> None: ...
    # Обновляет поле в task:{task_id}:files HASH

    async def increment_files_done(self, task_id: str) -> None: ...
    # HINCRBY task:{task_id} files_done 1

    async def mark_task_done(self, task_id: str, error: str | None = None) -> None: ...
    # Устанавливает status=done/error, finished_at
    # SREM active_tasks task_id

    async def mark_task_cancelled(self, task_id: str) -> None: ...
    # status=cancelled, SREM active_tasks task_id

    async def get_task_state(self, task_id: str) -> dict | None: ...
    # Возвращает task HASH + files HASH
    # {"status":..., "files": {"path": {...}, ...}}

    # --- Vault cache (без TTL, восстанавливается из PostgreSQL) ---

    async def rebuild_vault_cache(
        self,
        vault_id: str,
        pg_documents: list[dict],     # из db-api-server: relative_path, md5, status, chunks_count
        disk_files: list[dict],       # из scan_vault: relative_path, checksum, ...
    ) -> None: ...
    # Определяет index_status для каждого файла:
    #   нет на диске                    -> "deleted"
    #   нет в pg или status != indexed  -> "pending"
    #   disk.checksum == pg.md5         -> "indexed"
    #   иначе                           -> "stale"
    # Пишет vault:{vault_id}:files HASH (без TTL)

    async def mark_file_indexed(
        self,
        vault_id: str,
        relative_path: str,
        md5: str,
        chunks_total: int,
    ) -> None: ...
    # Обновляет запись в vault:{vault_id}:files:
    #   index_status = "indexed", indexed_md5 = md5, chunks_total = chunks_total

    async def get_vault_state(self, vault_id: str) -> dict | None: ...
    # Возвращает все файлы + счётчики по статусам

    # --- Cancel ---

    async def request_cancel(self, task_id: str) -> None: ...
    # SET cancel:{task_id} 1 EX 3600

    async def is_cancelled(self, task_id: str) -> bool: ...
    # EXISTS cancel:{task_id}

    async def clear_cancel(self, task_id: str) -> None: ...
    # DEL cancel:{task_id}
```

### Формат task:{task_id} HASH

```
status        running|done|error|cancelled
vault_id      str
started_at    ISO datetime
finished_at   ISO datetime (пусто пока running)
files_total   int (str в Redis)
files_skipped int
files_to_index int
files_done    int
error         str (пусто если нет)
```

### Формат task:{task_id}:files HASH

Ключ = relative_path, значение = JSON-строка:
```json
{"stage": "indexing", "chunks_total": 40, "chunks_done": 26, "checksum_md5": "abc123", "error": null}
```

### Формат vault:{vault_id}:files HASH

Ключ = relative_path, значение = JSON-строка:
```json
{"md5": "abc123", "index_status": "indexed", "indexed_md5": "abc123", "chunks_total": 40}
```

## Удалить после создания нового файла
- `rag-indexer/parser/state/state_manager.py`
- Директорию `/app/state/` можно убрать из Dockerfile если она там явно создаётся

## ✅ Unit-тесты для этого этапа

**Файл:** `tests/rag_indexer/test_redis_state_manager.py`  
**Зависимость:** `fakeredis[aioredis]>=2.0` (добавь в `requirements-dev.txt`)

```bash
pytest tests/rag_indexer/test_redis_state_manager.py -v
```

```python
# tests/rag_indexer/test_redis_state_manager.py
import pytest
import fakeredis.aioredis as fakeredis
from rag_indexer.parser.state.redis_state_manager import RedisStateManager
# Адаптируй импорт под фактический путь

@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)

@pytest.fixture
def mgr(redis):
    return RedisStateManager(redis)

# --- create_task ---

@pytest.mark.asyncio
async def test_create_task_sets_status_running(mgr, redis):
    await mgr.create_task("t1", "v1", [{"relative_path": "a.pdf"}], files_skipped=0, files_total=1)
    status = await redis.hget("task:t1", "status")
    assert status == "running"

@pytest.mark.asyncio
async def test_create_task_sets_ttl(mgr, redis):
    await mgr.create_task("t2", "v1", [], files_skipped=0, files_total=0)
    ttl = await redis.ttl("task:t2")
    assert 86390 < ttl <= 86400

@pytest.mark.asyncio
async def test_create_task_adds_to_active_tasks(mgr, redis):
    await mgr.create_task("t3", "v1", [], files_skipped=0, files_total=0)
    members = await redis.smembers("active_tasks")
    assert "t3" in members

@pytest.mark.asyncio
async def test_create_task_files_hash_populated(mgr, redis):
    files = [{"relative_path": "doc.pdf"}, {"relative_path": "img.png"}]
    await mgr.create_task("t4", "v1", files, files_skipped=1, files_total=3)
    keys = await redis.hkeys("task:t4:files")
    assert "doc.pdf" in keys
    assert "img.png" in keys

# --- update_file_stage ---

@pytest.mark.asyncio
async def test_update_file_stage(mgr, redis):
    import json
    await mgr.create_task("t5", "v1", [{"relative_path": "a.pdf"}], 0, 1)
    await mgr.update_file_stage("t5", "a.pdf", stage="indexing", chunks_total=10, chunks_done=3)
    raw = await redis.hget("task:t5:files", "a.pdf")
    data = json.loads(raw)
    assert data["stage"] == "indexing"
    assert data["chunks_total"] == 10
    assert data["chunks_done"] == 3

# --- increment_files_done ---

@pytest.mark.asyncio
async def test_increment_files_done(mgr, redis):
    await mgr.create_task("t6", "v1", [], 0, 2)
    await mgr.increment_files_done("t6")
    await mgr.increment_files_done("t6")
    val = await redis.hget("task:t6", "files_done")
    assert int(val) == 2

# --- mark_task_done ---

@pytest.mark.asyncio
async def test_mark_task_done(mgr, redis):
    await mgr.create_task("t7", "v1", [], 0, 0)
    await mgr.mark_task_done("t7")
    status = await redis.hget("task:t7", "status")
    assert status == "done"
    members = await redis.smembers("active_tasks")
    assert "t7" not in members

@pytest.mark.asyncio
async def test_mark_task_done_with_error(mgr, redis):
    await mgr.create_task("t8", "v1", [], 0, 0)
    await mgr.mark_task_done("t8", error="connection refused")
    status = await redis.hget("task:t8", "status")
    assert status == "error"
    error = await redis.hget("task:t8", "error")
    assert "connection refused" in error

# --- cancel ---

@pytest.mark.asyncio
async def test_request_cancel_and_is_cancelled(mgr, redis):
    await mgr.request_cancel("t9")
    assert await mgr.is_cancelled("t9") is True

@pytest.mark.asyncio
async def test_is_cancelled_false_before_request(mgr):
    assert await mgr.is_cancelled("t_none") is False

@pytest.mark.asyncio
async def test_clear_cancel(mgr):
    await mgr.request_cancel("t10")
    await mgr.clear_cancel("t10")
    assert await mgr.is_cancelled("t10") is False

# --- rebuild_vault_cache ---

@pytest.mark.asyncio
async def test_rebuild_vault_cache_indexed(mgr, redis):
    import json
    pg_docs = [{"relative_path": "a.pdf", "md5": "aaa", "status": "indexed", "chunks_count": 5}]
    disk_files = [{"relative_path": "a.pdf", "checksum": "aaa"}]
    await mgr.rebuild_vault_cache("v1", pg_docs, disk_files)
    raw = await redis.hget("vault:v1:files", "a.pdf")
    assert json.loads(raw)["index_status"] == "indexed"

@pytest.mark.asyncio
async def test_rebuild_vault_cache_stale(mgr, redis):
    import json
    pg_docs = [{"relative_path": "b.pdf", "md5": "old", "status": "indexed", "chunks_count": 3}]
    disk_files = [{"relative_path": "b.pdf", "checksum": "new"}]
    await mgr.rebuild_vault_cache("v1", pg_docs, disk_files)
    raw = await redis.hget("vault:v1:files", "b.pdf")
    assert json.loads(raw)["index_status"] == "stale"

@pytest.mark.asyncio
async def test_rebuild_vault_cache_deleted(mgr, redis):
    import json
    pg_docs = [{"relative_path": "c.pdf", "md5": "ccc", "status": "indexed", "chunks_count": 2}]
    disk_files = []  # файла нет на диске
    await mgr.rebuild_vault_cache("v1", pg_docs, disk_files)
    raw = await redis.hget("vault:v1:files", "c.pdf")
    assert json.loads(raw)["index_status"] == "deleted"

@pytest.mark.asyncio
async def test_rebuild_vault_cache_pending(mgr, redis):
    import json
    pg_docs = []  # нет в PostgreSQL
    disk_files = [{"relative_path": "d.pdf", "checksum": "ddd"}]
    await mgr.rebuild_vault_cache("v1", pg_docs, disk_files)
    raw = await redis.hget("vault:v1:files", "d.pdf")
    assert json.loads(raw)["index_status"] == "pending"

@pytest.mark.asyncio
async def test_rebuild_vault_cache_no_ttl(mgr, redis):
    """vault:*:files не должен иметь TTL."""
    await mgr.rebuild_vault_cache("v2", [], [])
    ttl = await redis.ttl("vault:v2:files")
    assert ttl == -1  # -1 = нет TTL, -2 = ключ не существует
```

> 💡 **Как запустить в чате:**  
> Приведи мне содержимое `redis_state_manager.py` — я запущу эти тесты и покажу результат.

## После завершения
Обнови `STATUS.md` — строку этапа 4: поставь ✅, запиши коммит, добавь в историю.
