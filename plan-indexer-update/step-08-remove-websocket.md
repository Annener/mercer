# Этап 8: rag-indexer — удалить WebSocket

## Цель
Полностью удалить WebSocket из `rag-indexer`. Прогресс теперь через polling Redis.

## Зависимости
- Этап 7 (indexer_service без broadcaster) — завершён

## Файлы для изменения
- `rag-indexer/app/websocket_manager.py` — удалить
- `rag-indexer/app/main.py` — удалить WS endpoint и импорты
- `rag-indexer/api/` — проверить, есть ли там WS-связанный код

## Что удалить

### В `app/main.py`
Найди и удали:
```python
from app.websocket_manager import ConnectionManager
@app.websocket("/ws/index-tasks/{task_id}")
async def websocket_endpoint(...):
    ...
```
И любые другие WS endpoints.

### Файл `app/websocket_manager.py`
Удалить через GitHub MCP `delete_file`.

### В `requirements.txt`
Удалить строку `websockets` если есть.

## Что добавить взамен — endpoint для polling

В `app/main.py` или в роутере `api/`:

```python
@router.get("/index-tasks/{task_id}/state")
async def get_task_state(
    task_id: str,
    request: Request,
) -> dict:
    state = await request.app.state.state_manager.get_task_state(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return state
```

Этот endpoint будет вызывать `rag-backend` для получения прогресса.

## Что НЕ трогать
- HTTP endpoints `/index-tasks` (POST, GET list)
- HTTP endpoint `/index-tasks/{task_id}/cancel`
- Всё остальное в `main.py`

## После завершения
Проверь: `grep -r "websocket\|WebSocket\|ConnectionManager" rag-indexer/`
Все вхождения должны быть удалены.

Обнови `STATUS.md` — этап 8 -> завершён.
