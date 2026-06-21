# Этап 4 — rag-indexer: интеграция watchdog в lifespan

## Цель

Запустить `watchdog_loop` как фоновый asyncio-таск в lifespan `rag-indexer/app/main.py`.
При шатдауне — корректно отменять.

## Контекст из кодовой базы

### `rag-indexer/app/main.py` — текущий lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ... Redis, DB, rebuild_vault_cache ...
    app.state.indexer_service = IndexerService(
        db_client=db_client,
        state_manager=state_manager,
    )
    logger.info("Service started. DB client connected. Redis ready.")

    try:
        yield
    finally:
        logger.info("Service shutdown requested. Cancelling active indexer tasks.")
        await app.state.indexer_service.shutdown(timeout_seconds=30)
        await db_client.close()
        await redis_client.aclose()
        logger.info("Service stopped.")
```

`VAULT_DATA_ROOT` и `REDIS_URL` уже читаются из `os.getenv`.
Нужно добавить новые env-переменные: `WATCHDOG_INTERVAL_SEC` (default `"60"`)
и `STORAGE_API_URL` (default `"http://db-api-server:8080"`).

## Что нужно сделать

### Изменения в `rag-indexer/app/main.py`

#### 1. Добавить импорты

```python
from parser.watchdog.vault_watchdog import watchdog_loop
from storage.storage_client import StorageClient
```

#### 2. Добавить создание `StorageClient` и watchdog-таска в lifespan

`StorageClient` создаётся один раз в lifespan и передаётся в `watchdog_loop` —
а не создаётся на каждой итерации watchdog.

Добавить после `app.state.indexer_service = IndexerService(...)`,
но **до** `try: yield`:

```python
# Watchdog
watchdog_interval = int(os.getenv("WATCHDOG_INTERVAL_SEC", "60"))
storage_client = StorageClient(
    os.getenv("STORAGE_API_URL", "http://db-api-server:8080")
)
watchdog_task: asyncio.Task[None] | None = None  # guard: None если задача не успела создаться
watchdog_task = asyncio.create_task(
    watchdog_loop(
        db_client=db_client,
        state_manager=state_manager,
        indexer_service=app.state.indexer_service,
        storage_client=storage_client,
        interval_sec=watchdog_interval,
    ),
    name="vault-watchdog",
)
logger.info("Vault watchdog scheduled (interval=%ds)", watchdog_interval)
```

> ⚠️ `watchdog_task` инициализируется `None` перед созданием `create_task`.
> Если исключение возникнет между `IndexerService(...)` и `create_task`,
> `finally` не упадёт с `NameError`.

#### 3. Отмена в `finally`

В `finally`-блоке, до `indexer_service.shutdown`:

```python
finally:
    logger.info("Service shutdown requested. Cancelling active indexer tasks.")
    # Отменяем watchdog
    if watchdog_task is not None:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
    # Остальное по старому
    await app.state.indexer_service.shutdown(timeout_seconds=30)
    await db_client.close()
    await redis_client.aclose()
    logger.info("Service stopped.")
```

### Изменения в `docker-compose.yml` / `.env.example`

Добавить в секцию `rag-indexer` новые env-переменные:

```yaml
environment:
  WATCHDOG_INTERVAL_SEC: "60"
  STORAGE_API_URL: "http://db-api-server:8080"
```

И в `.env.example`:

```
# Vault Watchdog
WATCHDOG_INTERVAL_SEC=60
STORAGE_API_URL=http://db-api-server:8080
```

## Файлы для изменения

| Файл | Действие |
|---|---|
| `rag-indexer/app/main.py` | `+import watchdog_loop`, `+import StorageClient`, `+storage_client`, `+watchdog_task` в lifespan, `+cancel` в finally |
| `docker-compose.yml` | `+WATCHDOG_INTERVAL_SEC`, `+STORAGE_API_URL` в rag-indexer env |
| `.env.example` | `+WATCHDOG_INTERVAL_SEC=60`, `+STORAGE_API_URL=...` |

## ✅ Unit-тесты

Unit-тесты lifespan сложны без полного ASGITransport + реальных зависимостей.
Достаточно проверить два аспекта: `watchdog_loop` корректно
останавливается по `CancelledError` и вызывает `_run_once` хотя бы один раз.

```
rag-indexer/tests/test_watchdog_lifespan.py
```

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from storage.storage_client import StorageClient
from parser.watchdog.vault_watchdog import watchdog_loop


async def test_watchdog_loop_stops_on_cancel():
    db = AsyncMock()
    db.get_setting.return_value = ".md,.pdf"
    db.get_all_vaults.return_value = []
    state = AsyncMock()
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    task = asyncio.create_task(
        watchdog_loop(
            db_client=db,
            state_manager=state,
            indexer_service=svc,
            storage_client=storage,
            interval_sec=9999,
        )
    )
    await asyncio.sleep(0)  # даём loop запуститься
    task.cancel()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.cancelled() or task.done()


async def test_watchdog_loop_calls_run_once():
    """After one iteration, _run_once is called at least once."""
    call_count = 0

    async def fake_run_once(db, state, svc, storage):  # четыре параметра, как в _run_once
        nonlocal call_count
        call_count += 1

    db = AsyncMock()
    state = AsyncMock()
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    with patch(
        "parser.watchdog.vault_watchdog._run_once",
        side_effect=fake_run_once,
    ):
        task = asyncio.create_task(
            watchdog_loop(
                db_client=db,
                state_manager=state,
                indexer_service=svc,
                storage_client=storage,
                interval_sec=0,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert call_count >= 1
```

## Критерий готовности

- [ ] `StorageClient` создан в lifespan и передан в `watchdog_loop`
- [ ] `watchdog_task` инициализирован `None` перед `create_task`
- [ ] `watchdog_task` создаётся после `indexer_service` в lifespan
- [ ] В `finally` есть `if watchdog_task is not None: watchdog_task.cancel()` + `await` в try/except CancelledError
- [ ] `WATCHDOG_INTERVAL_SEC` и `STORAGE_API_URL` есть в docker-compose + .env.example
- [ ] unit-тесты проходят
- [ ] `STATUS.md` обновлён: этап 4 → ✅
