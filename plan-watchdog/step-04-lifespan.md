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
    app.state.indexer_service = IndexerService(...)
    logger.info("Service started.")

    try:
        yield
    finally:
        await app.state.indexer_service.shutdown(timeout_seconds=30)
        await db_client.close()
        await redis_client.aclose()
```

`VAULT_DATA_ROOT` и `REDIS_URL` уже читаются из `os.getenv`. Нужно добавить
новую env-переменную: `WATCHDOG_INTERVAL_SEC` (default `"60"`).

## Что нужно сделать

### Изменения в `rag-indexer/app/main.py`

#### 1. Добавить импорт

```python
from parser.watchdog.vault_watchdog import watchdog_loop
```

#### 2. Добавить переменную и таск в lifespan

После строки
`app.state.indexer_service = IndexerService(...)`, но до `yield`:

```python
# Watchdog
watchdog_interval = int(os.getenv("WATCHDOG_INTERVAL_SEC", "60"))
watchdog_task = asyncio.create_task(
    watchdog_loop(
        db_client=db_client,
        state_manager=state_manager,
        indexer_service=app.state.indexer_service,
        interval_sec=watchdog_interval,
    ),
    name="vault-watchdog",
)
logger.info("Vault watchdog scheduled (interval=%ds)", watchdog_interval)
```

#### 3. Отмена в `finally`

В `finally`-блоке, до закрытия `db_client` и `redis_client`:

```python
finally:
    logger.info("Service shutdown requested.")
    # Отменяем watchdog
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

Добавить в секцию `rag-indexer` новую env-переменную с значением по умолчанию:

```yaml
environment:
  WATCHDOG_INTERVAL_SEC: "60"
```

И в `.env.example`:

```
# Vault Watchdog
WATCHDOG_INTERVAL_SEC=60
```

## Файлы для изменения

| Файл | Действие |
|---|---|
| `rag-indexer/app/main.py` | `+import watchdog_loop`, `+watchdog_task` в lifespan, `+cancel` в finally |
| `docker-compose.yml` | `+WATCHDOG_INTERVAL_SEC: "60"` в rag-indexer env |
| `.env.example` | `+WATCHDOG_INTERVAL_SEC=60` |

## ✅ Unit-тесты

Unit-тесты lifespan сложны без полного ASGITransport + реальных зависимостей.
Достаточно проверить один аспект: что `watchdog_loop` вызывается без ошибок и корректно
останавливается по `CancelledError`.

```
rag-indexer/tests/test_watchdog_lifespan.py
```

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from parser.watchdog.vault_watchdog import watchdog_loop


async def test_watchdog_loop_stops_on_cancel():
    db = AsyncMock()
    db.get_setting.return_value = ".md,.pdf"
    db.get_all_vaults.return_value = []
    state = AsyncMock()
    svc = AsyncMock()

    task = asyncio.create_task(
        watchdog_loop(db, state, svc, interval_sec=9999)
    )
    await asyncio.sleep(0)  # даём loop запуститься
    task.cancel()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.cancelled() or task.done()


async def test_watchdog_loop_calls_run_once():
    """After one iteration, _run_once is called at least once."""
    call_count = 0

    async def fake_run_once(db, state, svc):
        nonlocal call_count
        call_count += 1

    db = AsyncMock()
    state = AsyncMock()
    svc = AsyncMock()

    with patch(
        "parser.watchdog.vault_watchdog._run_once",
        side_effect=fake_run_once,
    ):
        task = asyncio.create_task(
            watchdog_loop(db, state, svc, interval_sec=0)
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

- [ ] `watchdog_task` создаётся после `indexer_service` в lifespan
- [ ] В `finally` есть `watchdog_task.cancel()` + `await watchdog_task` в try/except CancelledError
- [ ] `WATCHDOG_INTERVAL_SEC` есть в docker-compose + .env.example
- [ ] unit-тесты проходят
- [ ] `STATUS.md` обновлён: этап 4 → ✅
