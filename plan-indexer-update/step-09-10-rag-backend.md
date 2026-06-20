# Этапы 9–10: rag-backend — Redis client и polling endpoints

## Цель
Добавить в `rag-backend` Redis-клиент, endpoint для получения состояния задачи
(читает из Redis напрямую, без HTTP-запроса к rag-indexer),
и endpoint для общего состояния vault'а.

## Зависимости
- Этап 1 (Redis) — завершён
- Этап 8 (rag-indexer: polling endpoint готов) — завершён

## Перед началом — прочитай текущие файлы
Прочитай через GitHub MCP:
- `rag-backend/app/main.py` — lifespan, роуты
- Файл где сейчас проксируется WS или опрашивается состояние задачи

## Этап 9: Redis client в lifespan

### В `requirements.txt` добавить
```
redis[asyncio]>=5.0
```

### В lifespan добавить инициализацию

```python
import redis.asyncio as aioredis

redis_client = aioredis.from_url(
    os.getenv("REDIS_URL", "redis://redis:6379"),
    decode_responses=True,
)
app.state.redis = redis_client

yield

await redis_client.aclose()
```

**Важно:** `rag-backend` работает с Redis **напрямую** — не через `RedisStateManager`.  
Класс `RedisStateManager` живёт в `rag-indexer/parser/state/` и **не доступен** в rag-backend  
(разные контейнеры, нет общего Python-пакета). Используй `redis.asyncio` напрямую  
или перенеси read-only методы в `shared_contracts` если это потребуется в будущем.

## Этап 10: новые endpoints

### `GET /index-tasks/{task_id}/state`

Читает из Redis напрямую — не делает HTTP к rag-indexer.

```python
import json

@router.get("/index-tasks/{task_id}/state")
async def get_task_state(task_id: str, request: Request) -> dict:
    redis = request.app.state.redis

    task_data = await redis.hgetall(f"task:{task_id}")
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")

    files_raw = await redis.hgetall(f"task:{task_id}:files")
    files = {path: json.loads(data) for path, data in files_raw.items()}

    return {**task_data, "files": files}
```

### `GET /vaults/{vault_id}/index-state`

Возвращает текущее состояние vault'а по данным из Redis.

```python
@router.get("/vaults/{vault_id}/index-state")
async def get_vault_index_state(vault_id: str, request: Request) -> dict:
    redis = request.app.state.redis

    files_raw = await redis.hgetall(f"vault:{vault_id}:files")
    if not files_raw:
        raise HTTPException(status_code=404, detail="Vault not found in cache")

    files = {path: json.loads(data) for path, data in files_raw.items()}

    # Считаем сводку
    by_status: dict[str, int] = {}
    for f in files.values():
        s = f.get("index_status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "vault_id": vault_id,
        "files_total": len(files),
        "by_status": by_status,
        "files": files,
    }
```

## Что удалить из rag-backend

- WS-прокси endpoint (если есть): `@app.websocket(...)` который пробрасывал
  соединение к `rag-indexer`
- Зависимость `websockets` из `requirements.txt`

## Проверь через MCP
Найди в `rag-backend` всё что связано с WebSocket и удали.
Роут `GET /index-tasks/{task_id}/state` уже мог существовать как HTTP-прокси к
rag-indexer — замени его реализацию на чтение из Redis.

## ✅ Unit-тесты для этого этапа

**Файл:** `tests/rag_backend/test_redis_endpoints.py`

```bash
pytest tests/rag_backend/test_redis_endpoints.py -v
```

```python
# tests/rag_backend/test_redis_endpoints.py
import json
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock
# Адаптируй импорт под фактическую структуру
# from rag_backend.app.main import app

# --- /index-tasks/{task_id}/state ---

@pytest.mark.asyncio
async def test_get_task_state_running(app):
    """Возвращает состояние бегущей задачи."""
    task_hash = {"status": "running", "vault_id": "v1", "files_total": "10", "files_done": "3"}
    files_hash = {"a.pdf": json.dumps({"stage": "indexing", "chunks_done": 5, "chunks_total": 20})}

    redis_mock = AsyncMock()
    redis_mock.hgetall.side_effect = [task_hash, files_hash]
    app.state.redis = redis_mock

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/index-tasks/task-1/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert "a.pdf" in data["files"]
    assert data["files"]["a.pdf"]["stage"] == "indexing"

@pytest.mark.asyncio
async def test_get_task_state_not_found(app):
    """404 если task_id не существует в Redis."""
    redis_mock = AsyncMock()
    redis_mock.hgetall.return_value = {}  # пустой hgetall = ключа нет
    app.state.redis = redis_mock

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/index-tasks/ghost/state")
    assert resp.status_code == 404

# --- /vaults/{vault_id}/index-state ---

@pytest.mark.asyncio
async def test_get_vault_index_state(app):
    """Возвращает сводку по статусам файлов vault'а."""
    vault_files = {
        "a.pdf": json.dumps({"md5": "aaa", "index_status": "indexed", "chunks_total": 5}),
        "b.pdf": json.dumps({"md5": "bbb", "index_status": "stale", "chunks_total": 3}),
        "c.pdf": json.dumps({"md5": "ccc", "index_status": "indexed", "chunks_total": 8}),
    }
    redis_mock = AsyncMock()
    redis_mock.hgetall.return_value = vault_files
    app.state.redis = redis_mock

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/vaults/vault-1/index-state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["files_total"] == 3
    assert data["by_status"]["indexed"] == 2
    assert data["by_status"]["stale"] == 1

@pytest.mark.asyncio
async def test_get_vault_index_state_not_found(app):
    """404 если vault не найден в Redis."""
    redis_mock = AsyncMock()
    redis_mock.hgetall.return_value = {}
    app.state.redis = redis_mock

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/vaults/ghost-vault/index-state")
    assert resp.status_code == 404

def test_no_websocket_in_rag_backend():
    """В rag-backend нет WebSocket-кода после рефакторинга."""
    import subprocess
    result = subprocess.run(
        ["grep", "-r", "websocket", "rag-backend/", "--include=*.py", "-l"],
        capture_output=True, text=True
    )
    assert result.stdout.strip() == "", f"Найдены WS-файлы: {result.stdout}"
```

> 💡 **Как запустить в чате:**  
> Приведи мне содержимое `rag-backend/app/main.py` и router-файла с endpoints —  
> я подставлю правильные импорты и запущу тесты.

## После завершения
Обнови `STATUS.md` — строки этапов 9 и 10: поставь ✅, запиши коммит, добавь в историю.
