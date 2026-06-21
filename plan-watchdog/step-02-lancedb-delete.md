# Этап 2 — переименован

> ⚠️ Этот файл устарел и заменён на [`step-02-indexer-support-methods.md`](./step-02-indexer-support-methods.md).
>
> Причина переименования: содержимое описывает вспомогательные методы
> `IndexerDBClient` (PostgreSQL) и `RedisStateManager` (Redis),
> а не операции с LanceDB (удаление из LanceDB выполняет уже существующий
> `StorageClient.delete_document()` и в рамках этого этапа не требует изменений).
