# Этап 7: rag-indexer — indexer_service.py

## Цель
Переключить `IndexerService` на async cancel через Redis.
Удалить broadcaster (ConnectionManager) из сервиса.

## Зависимости
- Этап 4 (RedisStateManager) — завершён
- Этап 6 (indexer_worker без broadcaster) — завершён

## Перед началом — прочитай текущие файлы
- `rag-indexer/app/indexer_service.py`
- `rag-indexer/app/websocket_manager.py`

## Что изменить

### Убрать из `__init__`

```python
# УДАЛИТЬ
self._cancel_flags: dict[str, bool] = {}
self._broadcaster = ConnectionManager()
```

### Добавить в `__init__`

```python
def __init__(self, db_client: IndexerDBClient, state_manager: RedisStateManager):
    self._db_client = db_client
    self._state_manager = state_manager
    self._tasks: dict[str, asyncio.Task] = {}  # in-memory, только для управления asyncio.Task
```

`_tasks` остаётся in-memory — это нужно для `asyncio.Task.cancel()`.
Сам state задачи при этом в Redis.

### `cancel_task` — было sync/pseudo-async

Было:
```python
def cancel_task(self, task_id: str) -> bool:
    if task_id in self._cancel_flags:
        self._cancel_flags[task_id] = True
        return True
    return False
```

Стало:
```python
async def cancel_task(self, task_id: str) -> bool:
    if task_id not in self._tasks:
        return False
    await self._state_manager.request_cancel(task_id)
    return True
```

Worker сам проверяет флаг через `is_cancelled()` и завершается gracefully.
`asyncio.Task.cancel()` — не используем, даём worker'у завершиться чисто.

### Убрать метод `get_broadcaster`

Если он есть — удалить. WebSocket manager удаляется целиком в этапе 8.

### Обновить `start_indexing`

Убрать передачу broadcaster в IndexerWorker:
```python
# БЫЛО
worker = IndexerWorker(..., broadcaster=self._broadcaster)
# СТАЛО
worker = IndexerWorker(..., state_manager=self._state_manager)
```

### Cleanup в callback после завершения задачи

```python
def _on_task_done(self, task_id: str, task: asyncio.Task):
    self._tasks.pop(task_id, None)
    if task.cancelled():
        logger.info("Task cancelled: %s", task_id)
    elif exc := task.exception():
        logger.error("Task failed: %s — %s", task_id, exc)
```

Подключи callback: `asyncio_task.add_done_callback(lambda t: self._on_task_done(task_id, t))`

## ✅ Unit-тесты для этого этапа

**Файл:** `tests/rag_indexer/test_indexer_service.py`

```bash
pytest tests/rag_indexer/test_indexer_service.py -v
```

```python
# tests/rag_indexer/test_indexer_service.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from rag_indexer.app.indexer_service import IndexerService
from rag_indexer.parser.state.redis_state_manager import RedisStateManager
import fakeredis.aioredis as fakeredis

@pytest.fixture
def state_manager():
    return RedisStateManager(fakeredis.FakeRedis(decode_responses=True))

@pytest.fixture
def service(state_manager):
    db_client = AsyncMock()
    return IndexerService(db_client=db_client, state_manager=state_manager)

def test_service_has_no_broadcaster(service):
    """После рефакторинга у сервиса нет поля broadcaster."""
    assert not hasattr(service, '_broadcaster'), "_broadcaster должен быть удалён"
    assert not hasattr(service, 'broadcaster'), "broadcaster должен быть удалён"

def test_service_has_no_cancel_flags(service):
    """_cancel_flags (dict) заменён на Redis — не должен быть в сервисе."""
    assert not hasattr(service, '_cancel_flags'), "_cancel_flags должен быть удалён"

def test_service_has_no_get_broadcaster(service):
    """get_broadcaster удалён."""
    assert not hasattr(service, 'get_broadcaster'), "get_broadcaster должен быть удалён"

@pytest.mark.asyncio
async def test_cancel_task_returns_false_for_unknown(service):
    """cancel_task возвращает False для незапущенной задачи."""
    result = await service.cancel_task("nonexistent")
    assert result is False

@pytest.mark.asyncio
async def test_cancel_task_sets_redis_flag(service, state_manager):
    """cancel_task записывает флаг отмены в Redis."""
    # Регистрируем фиктивный asyncio.Task
    async def dummy(): await asyncio.sleep(100)
    task = asyncio.create_task(dummy())
    service._tasks["t1"] = task

    result = await service.cancel_task("t1")
    assert result is True
    assert await state_manager.is_cancelled("t1") is True

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

@pytest.mark.asyncio
async def test_on_task_done_removes_from_tasks(service):
    """_on_task_done чистит _tasks после завершения."""
    async def dummy(): pass
    task = asyncio.create_task(dummy())
    service._tasks["t2"] = task
    await task
    service._on_task_done("t2", task)
    assert "t2" not in service._tasks
```

> 💡 **Как запустить в чате:**  
> Приведи мне содержимое `indexer_service.py` после изменений — я запущу тесты.

## После завершения
Обнови `STATUS.md` — строку этапа 7: поставь ✅, запиши коммит, добавь в историю.
