# Этап 6: rag-indexer — indexer_worker.py

## Цель
Переключить `indexer_worker.py` с JSON-файлового state на `RedisStateManager`.
Убрать `chunk_ids`, убрать `broadcast`.

## Зависимости
- Этап 2 (chunk_ids удалён из модели) — завершён
- Этап 4 (RedisStateManager) — завершён

## Перед началом — прочитай текущий файл
Прочитай `rag-indexer/indexer_worker.py` полностью через GitHub MCP.
Это большой файл (~800 строк). Изучи все вызовы state_manager и broadcaster.

## Ключевые замены

### 1. Параметр функции/класса

Было:
```python
def __init__(self, state_manager: StateManager, broadcaster, ...):
```
Стало:
```python
def __init__(self, state_manager: RedisStateManager, ...):
```
Убрать `broadcaster` из сигнатуры.

### 2. Создание задачи

Было:
```python
state = state_manager.create_state(task_id, vault_id, files_to_index)
```
Стало:
```python
await state_manager.create_task(
    task_id=task_id,
    vault_id=vault_id,
    files_to_index=[{"relative_path": f["relative_path"]} for f in new_and_changed],
    files_skipped=len(skipped_files),
    files_total=len(all_files),
)
```

### 3. Обновление статуса файла

Было:
```python
state_manager.update_file_status(
    state, relative_path, stage="indexing",
    chunks_total=n, chunks_done=k, chunk_ids=[...], checksum_md5=md5
)
```
Стало:
```python
await state_manager.update_file_stage(
    task_id, relative_path, stage="indexing",
    chunks_total=n, chunks_done=k, checksum_md5=md5
)
```

### 4. Счётчик завершённых файлов

Было (если было):
```python
state["files_done"] += 1
state_manager.save_state(state)
```
Стало:
```python
await state_manager.increment_files_done(task_id)
await state_manager.mark_file_indexed(vault_id, relative_path, md5, chunks_total)
```

### 5. Проверка отмены

Было:
```python
if self._cancel_flags.get(task_id):
    ...
```
Стало:
```python
if await state_manager.is_cancelled(task_id):
    await state_manager.mark_task_cancelled(task_id)
    return
```

### 6. Завершение задачи

Было:
```python
state_manager.finalize_state(state)
```
Стало:
```python
await state_manager.mark_task_done(task_id)
```

При ошибке:
```python
await state_manager.mark_task_done(task_id, error=str(e))
```

### 7. Убрать broadcast

Найди все вызовы вида:
```python
await self.broadcaster.broadcast(task_id, event)
await broadcaster.send(...)
```
Удали их. Никакой замены не нужно — прогресс теперь доставляется через polling Redis.

### 8. Пропущенные файлы

Убери код который переносил данные из прошлого state для пропущенных файлов.
Пропущенные файлы теперь не хранятся в `task:{task_id}:files` вообще —
только их количество в `files_skipped`. Это упрощает логику.

### 9. last_successful state

Убрать любые вызовы вида:
```python
state_manager.save_last_successful(vault_id, ...)
state_manager.load_last_successful(vault_id, ...)
```
Теперь актуальное состояние vault'а живёт в `vault:{vault_id}:files` в Redis
(обновляется через `mark_file_indexed`). При рестарте восстанавливается из PostgreSQL.

## Паттерн проверки отмены

Рекомендуется проверять в нескольких точках:
1. После парсинга каждого файла
2. После каждого батча чанков при эмбеддинге (уже есть)
3. После каждого файла перед переходом к следующему

```python
CHECK_CANCEL_INTERVAL = 10  # каждые N чанков

for i, chunk in enumerate(chunks):
    if i % CHECK_CANCEL_INTERVAL == 0:
        if await state_manager.is_cancelled(task_id):
            ...
```

## ✅ Unit-тесты для этого этапа

**Файл:** `tests/rag_indexer/test_indexer_worker.py`  
**Зависимость:** `fakeredis[aioredis]>=2.0`

```bash
pytest tests/rag_indexer/test_indexer_worker.py -v
```

```python
# tests/rag_indexer/test_indexer_worker.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

# Адаптируй под фактический импорт
from rag_indexer.indexer_worker import IndexerWorker
from rag_indexer.parser.state.redis_state_manager import RedisStateManager
import fakeredis.aioredis as fakeredis

@pytest.fixture
def state_manager():
    redis = fakeredis.FakeRedis(decode_responses=True)
    return RedisStateManager(redis)

@pytest.fixture
def worker(state_manager):
    db_client = AsyncMock()
    return IndexerWorker(state_manager=state_manager, db_client=db_client)

def test_worker_init_no_broadcaster(worker):
    """IndexerWorker после рефакторинга не должен иметь поля broadcaster."""
    assert not hasattr(worker, 'broadcaster'), "broadcaster должен быть удалён"
    assert not hasattr(worker, '_broadcaster'), "_broadcaster должен быть удалён"

def test_worker_accepts_redis_state_manager(state_manager):
    """IndexerWorker принимает RedisStateManager без ошибок."""
    db_client = AsyncMock()
    # Не должно бросить TypeError
    worker = IndexerWorker(state_manager=state_manager, db_client=db_client)
    assert worker is not None

@pytest.mark.asyncio
async def test_cancel_check_stops_processing(state_manager):
    """Worker проверяет is_cancelled и завершается при отмене."""
    await state_manager.create_task("t1", "v1", [{"relative_path": "a.pdf"}], 0, 1)
    await state_manager.request_cancel("t1")

    db_client = AsyncMock()
    # Мокируем тяжёлые операции чтобы не вызывать реальный парсинг
    with patch.object(IndexerWorker, '_process_file', new_callable=AsyncMock) as mock_process:
        worker = IndexerWorker(state_manager=state_manager, db_client=db_client)
        await worker.run(task_id="t1", vault_id="v1", vault_path="/tmp")

    status = await state_manager.get_task_state("t1")
    assert status["status"] == "cancelled"

@pytest.mark.asyncio
async def test_no_chunk_ids_in_state_update(state_manager):
    """update_file_stage не принимает chunk_ids (поле удалено)."""
    import inspect
    sig = inspect.signature(state_manager.update_file_stage)
    assert "chunk_ids" not in sig.parameters, "chunk_ids не должен быть в update_file_stage"
```

> 💡 **Как запустить в чате:**  
> Приведи мне содержимое `indexer_worker.py` после изменений —  
> я запущу тесты и проверю корректность рефакторинга.

## После завершения
Обнови `STATUS.md` — строку этапа 6: поставь ✅, запиши коммит, добавь в историю.
