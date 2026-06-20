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

## Unit-тесты
Напиши тесты с `fakeredis` (или `redis.asyncio` + `pytest-asyncio` с mock).
Покрыть: create_task, update_file_stage, increment_files_done, mark_task_done,
rebuild_vault_cache (все 4 статуса), is_cancelled.

## После завершения
Обнови `STATUS.md` — этап 4 -> завершён.
