"""Unit-тесты для GET /api/v1/vaults/{vault_id}/documents/all.

Проверяют:
- endpoint возвращает список документов
- пустой vault → пустой список (не 404)
- каждый элемент содержит обязательные поля
- IndexerDBClient.get_all_documents() корректно сериализует indexed_at
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _make_app_with_db(mock_db: MagicMock) -> None:
    """Подменяет db_client в app.state перед тестом."""
    app.state.db_client = mock_db


@pytest.mark.asyncio
async def test_get_all_documents_returns_list() -> None:
    """Endpoint возвращает список документов для vault_id."""
    mock_db = MagicMock()
    mock_db.get_all_documents = AsyncMock(return_value=[
        {"source_path": "docs/a.pdf", "md5": "aaa111", "mtime": 1000, "status": "indexed", "indexed_at": "2026-01-01T00:00:00+00:00"},
        {"source_path": "docs/b.pdf", "md5": "bbb222", "mtime": 2000, "status": "stale",   "indexed_at": None},
    ])
    _make_app_with_db(mock_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/vaults/vault-1/documents/all")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["source_path"] == "docs/a.pdf"
    assert data[0]["md5"] == "aaa111"
    assert data[1]["indexed_at"] is None

    mock_db.get_all_documents.assert_awaited_once_with("vault-1")


@pytest.mark.asyncio
async def test_get_all_documents_empty_vault() -> None:
    """Для пустого vault'а возвращается пустой список, не 404."""
    mock_db = MagicMock()
    mock_db.get_all_documents = AsyncMock(return_value=[])
    _make_app_with_db(mock_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/vaults/empty-vault/documents/all")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_all_documents_response_schema() -> None:
    """Каждый элемент содержит обязательные поля."""
    required_fields = {"source_path", "md5", "mtime", "status", "indexed_at"}
    mock_db = MagicMock()
    mock_db.get_all_documents = AsyncMock(return_value=[
        {"source_path": "x.pdf", "md5": "ccc333", "mtime": 0, "status": "indexed", "indexed_at": None},
    ])
    _make_app_with_db(mock_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/vaults/v1/documents/all")

    assert resp.status_code == 200
    for item in resp.json():
        assert required_fields.issubset(item.keys()), f"Missing fields: {required_fields - item.keys()}"


@pytest.mark.asyncio
async def test_get_all_documents_indexed_at_serialization() -> None:
    """IndexerDBClient сериализует datetime → ISO string."""
    from app.db_client import IndexerDBClient

    client = IndexerDBClient()

    # Эмулируем asyncpg.Record как dict-like объект
    ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    fake_record = {
        "source_path": "report.pdf",
        "md5": "deadbeef",
        "mtime": 1748779200,
        "status": "indexed",
        "indexed_at": ts,
    }

    # Патчим _fetch напрямую
    client._fetch = AsyncMock(return_value=[fake_record])  # type: ignore[method-assign]

    result = await client.get_all_documents("vault-x")

    assert len(result) == 1
    assert result[0]["indexed_at"] == "2026-06-01T12:00:00+00:00"
    assert result[0]["source_path"] == "report.pdf"


@pytest.mark.asyncio
async def test_get_all_documents_indexed_at_none() -> None:
    """indexed_at=None (документ не индексировался) сериализуется как null."""
    from app.db_client import IndexerDBClient

    client = IndexerDBClient()
    fake_record = {
        "source_path": "pending.pdf",
        "md5": "abc",
        "mtime": 0,
        "status": "pending",
        "indexed_at": None,
    }
    client._fetch = AsyncMock(return_value=[fake_record])  # type: ignore[method-assign]

    result = await client.get_all_documents("vault-y")
    assert result[0]["indexed_at"] is None
