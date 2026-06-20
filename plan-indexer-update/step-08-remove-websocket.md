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

## ✅ Unit-тесты для этого этапа

**Файл:** `tests/rag_indexer/test_task_state_endpoint.py`

```bash
pytest tests/rag_indexer/test_task_state_endpoint.py -v
```

```python
# tests/rag_indexer/test_task_state_endpoint.py
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock
# Адаптируй импорт под фактическую структуру
# from rag_indexer.app.main import app

@pytest.mark.asyncio
async def test_get_task_state_returns_state(app):
    """GET /index-tasks/{task_id}/state возвращает state из RedisStateManager."""
    mock_state = {"status": "running", "files_done": 3, "files_total": 10, "files": {}}
    app.state.state_manager = AsyncMock()
    app.state.state_manager.get_task_state.return_value = mock_state

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/index-tasks/task-abc/state")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    assert resp.json()["files_done"] == 3

@pytest.mark.asyncio
async def test_get_task_state_returns_404_if_not_found(app):
    """GET /index-tasks/{task_id}/state возвращает 404 если задача не найдена."""
    app.state.state_manager = AsyncMock()
    app.state.state_manager.get_task_state.return_value = None

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/index-tasks/nonexistent/state")
    assert resp.status_code == 404

def test_no_websocket_imports_in_codebase():
    """После удаления в коде rag-indexer нет импортов WebSocket."""
    import subprocess
    result = subprocess.run(
        ["grep", "-r", "websocket", "rag-indexer/", "--include=*.py", "-l"],
        capture_output=True, text=True
    )
    files_with_ws = result.stdout.strip()
    assert files_with_ws == "", f"Найдены файлы с websocket: {files_with_ws}"
```

> 💡 **Как запустить в чате:**  
> Приведи мне содержимое `app/main.py` после изменений — я запущу тесты endpoint'а.

## Проверка после реализации
```bash
grep -r "websocket\|WebSocket\|ConnectionManager" rag-indexer/
# Ожидается: нет вывода
```

## После завершения
Обнови `STATUS.md` — строку этапа 8: поставь ✅, запиши коммит, добавь в историю.
