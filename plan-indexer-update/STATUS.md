# Статус реализации плана

> Этот файл актуализируется после каждого завершённого этапа.  
> Модель, работающая над этапом, **обязана** обновить строку таблицы ниже:
> - поставить ✅ в колонку **Статус**
> - вписать коммит/ветку в колонку **Коммит**
> - добавить строку в **Историю изменений**

## Этапы

| # | Название | Файл с деталями | Статус | Коммит | Примечания |
|---|---|---|---|---|---|
| 1 | Инфраструктура: Redis в docker-compose | [step-01](step-01-docker-compose.md) | ✅ завершён | feat(infra): add Redis service to docker-compose (step-01) | Сеть rag-net, redis:7-alpine, AOF, noeviction, REDIS_URL в rag-indexer и rag-backend |
| 2 | shared_contracts: удалить chunk_ids | [step-02](step-02-shared-contracts.md) | ✅ завершён | feat(shared_contracts): remove chunk_ids from FileIndexState (step-02) | Поле удалено из модели |
| 3 | db-api-server: новый endpoint documents/all | [step-03](step-03-db-api-server.md) | ✅ завершён | feat(rag-indexer): add GET /api/v1/vaults/{vault_id}/documents/all (step-03) | Точка доступа в rag-indexer (арх. решение) |
| 4 | rag-indexer: RedisStateManager | [step-04](step-04-redis-state-manager.md) | ✅ завершён | feat(rag-indexer): add RedisStateManager, replace JSON state_manager (step-04) | Новый parser/state/redis_state_manager.py. redis[asyncio]>=5.0 в requirements.txt |
| 5 | rag-indexer: rebuild vault cache при старте | [step-05](step-05-vault-cache-rebuild.md) | ✅ завершён | feat(rag-indexer): rebuild vault cache on startup via RedisStateManager (step-05) | get_all_vaults() добавлен в db_client. _rebuild_one_vault: skip missing path, gather+return_exceptions |
| 6 | rag-indexer: indexer_worker — убрать chunk_ids и broadcast | [step-06](step-06-indexer-worker.md) | ✅ завершён | ef3d737 | run_indexing принимает state_manager. Убран broadcast, is_cancelled-callable, WS-модели |
| 7 | rag-indexer: indexer_service — async cancel, убрать broadcaster | [step-07](step-07-indexer-service.md) | ✅ завершён | f0e1330 | Удалены _broadcaster, _cancel_flags, get_broadcaster. cancel_task → async Redis-флаг |
| 8 | rag-indexer: удалить WebSocket | [step-08](step-08-remove-websocket.md) | ✅ завершён | 0f0ca43 | Удалены: websocket_manager.py, WS-эндпоинт, ConnectionManager из main.py. Добавлен polling GET /api/v1/tasks/{task_id}/state. Тесты: test_task_state_endpoint.py |
| 9 | rag-backend: Redis client + polling endpoint | [step-09-10](step-09-10-rag-backend.md) | ✅ завершён | 7abc7eb | redis[asyncio]>=5.0 в requirements.txt. Redis lifespan в main.py. Новый роутер indexer_state.py. Удалён WS-прокси и HTTP-прокси /index-tasks/{task_id}/state из db_management.py |
| 10 | rag-backend: vault index-state endpoint | [step-09-10](step-09-10-rag-backend.md) | ✅ завершён | 7abc7eb | GET /vaults/{vault_id}/index-state в indexer_state.py — читает vault:{vault_id}:files из Redis, возвращает сводку by_status |
| 11 | Интеграционный тест | [step-11](step-11-integration-test.md) | ⬜ не начат | — | — |

## Статусы
- ⬜ не начат
- 🔄 в работе
- ✅ завершён
- ❌ заблокирован (причина в примечаниях)

## Зависимости между этапами

```
1 (Redis) ──────────────────────────────────────────► все остальные
2 (shared_contracts) ──► 4, 6
3 (db-api-server) ──────► 5
4 (RedisStateManager) ──► 5, 6, 7
5 (vault cache) ────────► 11
6 (worker) ─────────────► 11
7 (service) ────────────► 8
8 (удалить WS) ─────────► 11
9 (rag-backend) ────────► 10, 11
```

## История изменений

| Дата | Этап | Действие |
|---|---|---|
| — | — | Файл создан |
| 2026-06-21 | 1 | ✅ Redis в docker-compose |
| 2026-06-21 | 2 | ✅ Удален chunk_ids из FileIndexState |
| 2026-06-21 | 3 | ✅ GET /api/v1/vaults/{vault_id}/documents/all в rag-indexer |
| 2026-06-21 | 4 | ✅ RedisStateManager: task/vault HASH, cancel, active_tasks SET |
| 2026-06-21 | 5 | ✅ rebuild_vault_cache при старте |
| 2026-06-21 | 6 | ✅ indexer_worker: run_indexing → state_manager. Удалены broadcast, is_cancelled, WS-модели |
| 2026-06-21 | 7 | ✅ indexer_service: удалены _broadcaster, _cancel_flags, get_broadcaster. cancel_task → async Redis-флаг. shutdown() добавлен |
| 2026-06-21 | 8 | ✅ Удалены websocket_manager.py, WS-эндпоинт /api/v1/tasks/{task_id}/stream, ConnectionManager из main.py. Добавлен polling GET /api/v1/tasks/{task_id}/state |
| 2026-06-21 | 9-10 | ✅ redis[asyncio]>=5.0 в requirements.txt. Redis lifespan (app.state.redis). Новый indexer_state.py: GET /index-tasks/{task_id}/state и GET /vaults/{vault_id}/index-state — оба читают Redis напрямую. Удалён @router.websocket /ws/index-tasks/{task_id} и HTTP-прокси /index-tasks/{task_id}/state из db_management.py. Тесты: tests/rag_backend/test_redis_endpoints.py |
