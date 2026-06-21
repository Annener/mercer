# Статус реализации плана

> Этот файл актуализируется после каждого завершённого этапа.  
> Модель, работающая над этапом, **обязана** обновить строку таблицы ниже:
> - поставить ✅ в колонку **Статус**
> - вписать коммит/ветку в колонку **Коммит**
> - добавить строку в **Историю изменений**
>
> Формат обновления строки:  
> `| N | Название | ✅ завершён | <sha7 или ветка> | <примечание или —> |`

## Этапы

| # | Название | Файл с деталями | Статус | Коммит | Примечания |
|---|---|---|---|---|---|
| 1 | Инфраструктура: Redis в docker-compose | [step-01](step-01-docker-compose.md) | ✅ завершён | feat(infra): add Redis service to docker-compose (step-01) | Сеть rag-net, redis:7-alpine, AOF, noeviction, REDIS_URL в rag-indexer и rag-backend |
| 2 | shared_contracts: удалить chunk_ids | [step-02](step-02-shared-contracts.md) | ✅ завершён | feat(shared_contracts): remove chunk_ids from FileIndexState (step-02) | Поле удалено из модели |
| 3 | db-api-server: новый endpoint documents/all | [step-03](step-03-db-api-server.md) | ✅ завершён | feat(rag-indexer): add GET /api/v1/vaults/{vault_id}/documents/all (step-03) | Точка доступа в rag-indexer (арх. решение) |
| 4 | rag-indexer: RedisStateManager | [step-04](step-04-redis-state-manager.md) | ✅ завершён | feat(rag-indexer): add RedisStateManager, replace JSON state_manager (step-04) | Новый parser/state/redis_state_manager.py. redis[asyncio]>=5.0 в requirements.txt |
| 5 | rag-indexer: rebuild vault cache при старте | [step-05](step-05-vault-cache-rebuild.md) | ✅ завершён | feat(rag-indexer): rebuild vault cache on startup via RedisStateManager (step-05) | get_all_vaults() добавлен в db_client. _rebuild_one_vault: skip missing path, gather+return_exceptions. app.state.state_manager сет. Тесты: test_startup_vault_rebuild.py |
| 6 | rag-indexer: indexer_worker — убрать chunk_ids и broadcast | [step-06](step-06-indexer-worker.md) | ✅ завершён | ef3d737 | run_indexing принимает state_manager: RedisStateManager. Убран broadcast, is_cancelled-callable, WS-модели, JSON state_manager. Добавлены mark_file_indexed, increment_files_done, check_cancel в embed loop. Тесты: tests/rag_indexer/test_indexer_worker.py |
| 7 | rag-indexer: indexer_service — async cancel, убрать broadcaster | [step-07](step-07-indexer-service.md) | ⬜ не начат | — | — |
| 8 | rag-indexer: удалить WebSocket | [step-08](step-08-remove-websocket.md) | ⬜ не начат | — | — |
| 9 | rag-backend: Redis client + polling endpoint | [step-09-10](step-09-10-rag-backend.md) | ⬜ не начат | — | — |
| 10 | rag-backend: vault index-state endpoint | [step-09-10](step-09-10-rag-backend.md) | ⬜ не начат | — | — |
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

Этапы 2, 3 независимы друг от друга и от 4–10, можно делать параллельно после этапа 1.  
Этапы 4–8 последовательны внутри rag-indexer.  
Этапы 9–10 независимы от 4–8, требуют только этап 1.

## История изменений

| Дата | Этап | Действие |
|---|---|---|
| — | — | Файл создан |
| 2026-06-21 | 1 | ✅ Redis в docker-compose |
| 2026-06-21 | 2 | ✅ Удален chunk_ids из FileIndexState |
| 2026-06-21 | 3 | ✅ GET /api/v1/vaults/{vault_id}/documents/all в rag-indexer |
| 2026-06-21 | 4 | ✅ RedisStateManager: task/vault HASH, cancel, active_tasks SET |
| 2026-06-21 | 5 | ✅ rebuild_vault_cache при старте: get_all_vaults + _rebuild_one_vault + gather. get_all_vaults() добавлен в db_client. Отклонение: _rebuild_one_vault пробрасывает исключение (caller перехватывает через return_exceptions=True) |
| 2026-06-21 | 6 | ✅ indexer_worker: run_indexing → state_manager: RedisStateManager. Удалены broadcast, is_cancelled callable, WS-модели, JSON state_manager импорты. increment_files_done + mark_file_indexed после каждого файла. CHECK_CANCEL_INTERVAL в embed loop. Тесты: tests/rag_indexer/test_indexer_worker.py |
