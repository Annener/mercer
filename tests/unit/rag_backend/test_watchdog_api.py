import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.db.session import get_db

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    return db


async def test_get_watchdog_settings_default(mock_db):
    result_mock = MagicMock()
    result_mock.fetchone.return_value = None
    mock_db.execute.return_value = result_mock

    mock_redis = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/api/v1/settings/watchdog")
        assert r.status_code == 200
        data = r.json()
        assert set(data["auto_index_extensions"]) == {".md", ".pdf"}
    finally:
        app.dependency_overrides.clear()


async def test_patch_watchdog_settings(mock_db):
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_redis = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            payload = {"auto_index_extensions": [".md", ".txt"]}
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.patch("/api/v1/settings/watchdog", json=payload)
        assert r.status_code == 200
        assert ".txt" in r.json()["auto_index_extensions"]
        mock_db.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()


async def test_patch_invalid_extension(mock_db):
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_redis = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            payload = {"auto_index_extensions": ["md"]}  # bez tochki
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.patch("/api/v1/settings/watchdog", json=payload)
        assert r.status_code == 422
        mock_db.commit.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


async def test_get_pending_files():
    mock_redis = AsyncMock()
    mock_redis.hgetall.return_value = {
        "notes.md": json.dumps({"index_status": "pending", "md5": "abc"}),
        "report.pdf": json.dumps({"index_status": "indexed", "md5": "def"}),
        "new.txt": json.dumps({"index_status": "pending", "md5": ""}),
        "__empty__": "1",
    }
    with patch("redis.asyncio.from_url", return_value=mock_redis):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            app.state.redis = mock_redis
            r = await c.get("/api/v1/vaults/v1/pending-files")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert set(data["pending_files"]) == {"notes.md", "new.txt"}


async def test_get_domain_pending_files(mock_db):
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [("vault-1",), ("vault-2",)]
    mock_db.execute.return_value = result_mock

    mock_redis = AsyncMock()
    async def hgetall_side(key):
        if key == "vault:vault-1:files":
            return {
                "a.md": json.dumps({"index_status": "pending"}),
                "b.md": json.dumps({"index_status": "pending"}),
                "c.md": json.dumps({"index_status": "indexed"}),
            }
        if key == "vault:vault-2:files":
            return {
                "d.md": json.dumps({"index_status": "indexed"}),
            }
        return {}
    mock_redis.hgetall.side_effect = hgetall_side

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                app.state.redis = mock_redis
                r = await c.get("/api/v1/domains/dnd/pending-files")
        assert r.status_code == 200
        data = r.json()
        assert data["total_pending"] == 2
        assert data["domain_id"] == "dnd"
        vault_map = {v["vault_id"]: v["pending_count"] for v in data["vaults"]}
        assert vault_map["vault-1"] == 2
        assert vault_map["vault-2"] == 0
    finally:
        app.dependency_overrides.clear()


async def test_post_domain_index(mock_db):
    """POST /domains/{domain_id}/index queues tasks for pending files only."""
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [("vault-1",), ("vault-2",)]
    mock_db.execute.return_value = result_mock

    mock_redis = AsyncMock()
    async def hgetall_side(key):
        if key == "vault:vault-1:files":
            return {
                "a.md": json.dumps({"index_status": "pending"}),
                "b.md": json.dumps({"index_status": "indexed"}),
            }
        if key == "vault:vault-2:files":
            return {
                "c.md": json.dumps({"index_status": "pending"}),
                "__empty__": "1",
            }
        return {}
    mock_redis.hgetall.side_effect = hgetall_side
    mock_redis.lpush = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                app.state.redis = mock_redis
                r = await c.post("/api/v1/domains/dnd/index")
        assert r.status_code == 200
        data = r.json()
        assert data["queued"] == 2
        assert data["domain_id"] == "dnd"
        assert mock_redis.lpush.await_count == 2
        queued_tasks = [
            json.loads(call.args[1])
            for call in mock_redis.lpush.call_args_list
        ]
        paths = {t["path"] for t in queued_tasks}
        assert paths == {"a.md", "c.md"}
    finally:
        app.dependency_overrides.clear()
