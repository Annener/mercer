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
- Точные названия полей в таблице `documents` (особенно: `chunks_count` или другое название)
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

## ✅ Unit-тесты для этого этапа

**Файл:** `tests/db_api_server/test_documents_all.py`

```bash
pytest tests/db_api_server/test_documents_all.py -v
```

```python
# tests/db_api_server/test_documents_all.py
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

# Адаптируй импорт под фактическую структуру db-api-server
# from db_api_server.main import app

@pytest.mark.asyncio
async def test_get_all_documents_returns_list():
    """Endpoint возвращает список документов для vault_id."""
    mock_rows = [
        {"relative_path": "a.pdf", "md5": "aaa", "mtime": 1000, "status": "indexed", "chunks_count": 10},
        {"relative_path": "b.pdf", "md5": "bbb", "mtime": 2000, "status": "stale", "chunks_count": 5},
    ]
    with patch("<модуль>.db.fetch_all", new_callable=AsyncMock, return_value=mock_rows):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get("/vaults/vault-1/documents/all")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["relative_path"] == "a.pdf"
    assert data[0]["chunks_count"] == 10

@pytest.mark.asyncio
async def test_get_all_documents_empty_vault():
    """Для пустого vault'а возвращается пустой список, не 404."""
    with patch("<модуль>.db.fetch_all", new_callable=AsyncMock, return_value=[]):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get("/vaults/empty-vault/documents/all")
    assert resp.status_code == 200
    assert resp.json() == []

@pytest.mark.asyncio
async def test_get_all_documents_response_schema():
    """Каждый элемент содержит обязательные поля."""
    required_fields = {"relative_path", "md5", "status"}
    mock_rows = [{"relative_path": "x.pdf", "md5": "ccc", "mtime": 0, "status": "indexed", "chunks_count": 1}]
    with patch("<модуль>.db.fetch_all", new_callable=AsyncMock, return_value=mock_rows):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get("/vaults/v1/documents/all")
    for item in resp.json():
        assert required_fields.issubset(item.keys())
```

> 💡 **Как запустить в чате:**  
> Приведи мне содержимое `db-api-server/app/main.py` и нужного router-файла —  
> я подставлю правильный импорт и выполню тесты.

## После завершения
Обнови `STATUS.md` — строку этапа 3: поставь ✅, запиши коммит, добавь в историю.
