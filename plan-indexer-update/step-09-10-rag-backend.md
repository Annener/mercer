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
from parser.state.redis_state_manager import RedisStateManager
# или импортировать только нужные методы, не весь класс

redis_client = aioredis.from_url(
    os.getenv("REDIS_URL", "redis://redis:6379"),
    decode_responses=True,
)
app.state.redis = redis_client

yield

await redis_client.aclose()
```

Примечание: `rag-backend` может работать с Redis напрямую (без RedisStateManager)
если хочется минимальной зависимости. Или можно переиспользовать класс из
`shared_contracts` или скопировать read-only методы. Реши по месту.

## Этап 10: новые endpoints

### `GET /index-tasks/{task_id}/state`

Читает из Redis напрямую — не делает HTTP к rag-indexer.

```python
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
    by_status = {}
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

## После завершения
Обнови `STATUS.md` — этапы 9 и 10 -> завершены.
