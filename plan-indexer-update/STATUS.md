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
| 1 | Инфраструктура: Redis в docker-compose | [step-01](step-01-docker-compose.md) | ⬜ не начат | — | — |
| 2 | shared_contracts: удалить chunk_ids | [step-02](step-02-shared-contracts.md) | ⬜ не начат | — | — |
| 3 | db-api-server: новый endpoint documents/all | [step-03](step-03-db-api-server.md) | ⬜ не начат | — | — |
| 4 | rag-indexer: RedisStateManager | [step-04](step-04-redis-state-manager.md) | ⬜ не начат | — | — |
| 5 | rag-indexer: rebuild vault cache при старте | [step-05](step-05-vault-cache-rebuild.md) | ⬜ не начат | — | — |
| 6 | rag-indexer: indexer_worker — убрать chunk_ids и broadcast | [step-06](step-06-indexer-worker.md) | ⬜ не начат | — | — |
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
