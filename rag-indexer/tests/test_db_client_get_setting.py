import pytest
from unittest.mock import AsyncMock, MagicMock
from app.db_client import IndexerDBClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    c = IndexerDBClient()
    c.pool = MagicMock()  # pool не None — не вызывает RuntimeError
    return c


async def test_get_setting_returns_typed_value(client):
    row = {"value": "true", "value_type": "bool"}
    client._fetchrow = AsyncMock(return_value=row)
    result = await client.get_setting("some_flag")
    assert result is True


async def test_get_setting_returns_none_if_missing(client):
    client._fetchrow = AsyncMock(return_value=None)
    result = await client.get_setting("nonexistent_key")
    assert result is None


async def test_get_setting_returns_string_list_extensions(client):
    row = {"value": ".md,.pdf", "value_type": "str"}
    client._fetchrow = AsyncMock(return_value=row)
    raw = await client.get_setting("watchdog_auto_index_extensions")
    extensions = [e.strip() for e in raw.split(",") if e.strip()] if raw else []
    assert extensions == [".md", ".pdf"]


async def test_get_setting_returns_none_for_empty_string(client):
    # _cast_value при value_type='str' возвращает `value or None`,
    # поэтому пустая строка (сценарий 3 — только ручная индексация) → None.
    row = {"value": "", "value_type": "str"}
    client._fetchrow = AsyncMock(return_value=row)
    raw = await client.get_setting("watchdog_auto_index_extensions")
    assert raw is None
    # Паттерн разбора в watchdog должен корректно обработать None → []
    extensions = [e.strip() for e in raw.split(",") if e.strip()] if raw else []
    assert extensions == []
