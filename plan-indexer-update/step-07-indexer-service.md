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

## После завершения
Обнови `STATUS.md` — этап 7 -> завершён.
