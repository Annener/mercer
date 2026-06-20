# Этап 5: rag-indexer — rebuild vault cache при старте

## Цель
Добавить в `rag-indexer/app/main.py` инициализацию Redis-клиента и
вызов `rebuild_vault_cache` для всех vault'ов при старте сервиса.

## Зависимости
- Этап 1 (Redis) — завершён
- Этап 3 (db-api-server endpoint) — завершён
- Этап 4 (RedisStateManager) — завершён

## Перед началом — прочитай текущие файлы
- `rag-indexer/app/main.py` — текущий lifespan, инициализация сервисов
- `rag-indexer/app/db_client.py` — доступные методы, паттерн создания клиента
- `rag-indexer/app/indexer_service.py` — как сейчас передаётся db_client

## Что изменить в `app/main.py`

### Добавить импорты
```python
import redis.asyncio as aioredis
from parser.state.redis_state_manager import RedisStateManager
from parser.scanning.vault_scanner import scan_vault
```

### Изменить lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis
    redis_client = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379"),
        decode_responses=True,
    )
    state_manager = RedisStateManager(redis_client)

    # DB client (как сейчас — не меняй инициализацию)
    db_client = ...  # существующая инициализация

    # Восстанавливаем vault cache из PostgreSQL + disk scan
    try:
        vaults = await db_client.get_all_vaults()
        rebuild_tasks = []
        for vault in vaults:
            vault_id = vault["id"]
            vault_path = f"/data/vaults/{vault_id}"
            rebuild_tasks.append(
                _rebuild_one_vault(state_manager, db_client, vault_id, vault_path)
            )
        await asyncio.gather(*rebuild_tasks, return_exceptions=True)
    except Exception:
        logger.exception("Failed to rebuild vault cache on startup — continuing")

    app.state.state_manager = state_manager
    app.state.indexer_service = IndexerService(
        db_client=db_client,
        state_manager=state_manager,
        # broadcaster убран в этапе 7
    )
    yield

    await redis_client.aclose()


async def _rebuild_one_vault(state_manager, db_client, vault_id: str, vault_path: str):
    import os
    if not os.path.isdir(vault_path):
        logger.warning("Vault path not found, skipping cache rebuild: %s", vault_path)
        return
    try:
        pg_docs = await db_client.get_all_documents(vault_id)
        disk_files = await asyncio.to_thread(scan_vault, vault_path)
        await state_manager.rebuild_vault_cache(vault_id, pg_docs, disk_files)
        logger.info("Vault cache rebuilt: vault_id=%s, files=%d", vault_id, len(disk_files))
    except Exception:
        logger.exception("Error rebuilding vault cache: vault_id=%s", vault_id)
```

## Важные детали

- `return_exceptions=True` в `gather` — ошибка одного vault'а не роняет всё
- Логируй успех и ошибки для каждого vault'а
- Если `get_all_vaults` не существует в `db_client` — уточни через MCP как получить
  список всех vault'ов (может называться иначе)
- Не меняй `IndexerService` на этом этапе — broadcaster пока остаётся,
  он удаляется в этапе 7

## После завершения
Обнови `STATUS.md` — этап 5 -> завершён.
