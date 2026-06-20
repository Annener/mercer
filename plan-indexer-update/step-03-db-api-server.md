# Этап 3: db-api-server — endpoint GET /vaults/{vault_id}/documents/all

## Цель
Добавить endpoint который возвращает все документы vault'а из PostgreSQL.
Нужен `rag-indexer` при старте для инициализации vault-кэша в Redis.

## Контекст: зачем этот endpoint

При старте `rag-indexer` выполняет `rebuild_vault_cache` для каждого vault'а.
Логика: берёт список документов из PostgreSQL (с их `md5` и `status`),
сверяет с файлами на диске, определяет `index_status` каждого файла
(`indexed` / `stale` / `pending` / `deleted`) и пишет в `vault:{vault_id}:files` в Redis.

PostgreSQL — источник правды о том что было проиндексировано. Redis — только кэш.

## Файлы для изменения
Прочитай через GitHub MCP структуру `db-api-server/api/` чтобы найти
правильное место для нового endpoint (скорее всего рядом с существующими
document-related роутами).

## Зависимости
Этап не зависит от других этапов (кроме 1). Можно выполнять параллельно с этапом 2.

## Что добавить

### Новый endpoint в db-api-server

```python
@router.get("/vaults/{vault_id}/documents/all")
async def get_all_documents(vault_id: str) -> list[dict]:
    rows = await db.fetch_all(
        "SELECT relative_path, md5, mtime, status, chunks_count "
        "FROM documents WHERE vault_id = :vault_id",
        {"vault_id": vault_id}
    )
    return [dict(row) for row in rows]
```

Уточни через MCP:
- Точные названия полей в таблице `documents` (особенно: chunks_count или другое название)
- Паттерн работы с БД в существующих handlers
- Есть ли уже аналогичный endpoint который можно расширить

### Новый метод в IndexerDBClient (`rag-indexer/app/db_client.py`)

```python
async def get_all_documents(self, vault_id: str) -> list[dict]:
    url = f"{self.base_url}/vaults/{vault_id}/documents/all"
    async with self._session.get(url) as resp:
        resp.raise_for_status()
        return await resp.json()
```

## Ожидаемый ответ endpoint'а
```json
[
  {
    "relative_path": "docs/report.pdf",
    "md5": "abc123",
    "mtime": 1750000000,
    "status": "indexed",
    "chunks_count": 40
  }
]
```

## После завершения
Обнови `STATUS.md` — этап 3 -> завершён.
