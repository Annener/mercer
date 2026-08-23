"""Integration tests for campaign_state_stale endpoint.

Covers:
  - GET /api/settings/campaigns/{cid}/state/stale-status
  - HTTP-level response shape (200 + CampaignStateStaleStatus)
  - CampaignNotFound → 404
  - Зависимости (db, redis) переопределяются через dependency_overrides.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure repo-root and rag-backend on sys.path (conftest pattern).
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "rag-backend"
for p in (ROOT, BACKEND):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.strings[key] = value


class _FakeExecuteResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeExecuteResult":
        return self

    def all(self) -> list:
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeVersion:
    def __init__(self, state_version: int, campaign_id: str) -> None:
        self.id = uuid.uuid4()
        self.campaign_id = uuid.UUID(campaign_id)
        self.state_version = state_version
        self.config_version = 1


class _FakeDocument:
    def __init__(
        self,
        *,
        doc_id: str,
        vault_id: str,
        source_path: str,
        md5: str,
        status: str = "indexed",
    ) -> None:
        self.id = uuid.UUID(doc_id)
        self.vault_id = vault_id
        self.source_path = source_path
        self.md5 = md5
        self.status = status


class _FakeDb:
    def __init__(
        self,
        *,
        campaign_exists: bool = True,
        version: _FakeVersion | None = None,
        values_source_refs: list | None = None,
        items_source_refs: list | None = None,
        documents: list | None = None,
    ) -> None:
        self._campaign_exists = campaign_exists
        self._version = version
        self._values_source_refs = values_source_refs or []
        self._items_source_refs = items_source_refs or []
        self._documents = documents or []
        self.commits = 0
        self._call_count = 0

    async def get(self, model, pk):
        return object() if self._campaign_exists else None

    async def execute(self, stmt):
        self._call_count += 1
        n = self._call_count
        if n == 1:
            return _FakeExecuteResult([self._version] if self._version else [])
        if n == 2:
            return _FakeExecuteResult(self._values_source_refs)
        if n == 3:
            return _FakeExecuteResult(self._items_source_refs)
        if n == 4:
            return _FakeExecuteResult(self._documents)
        return _FakeExecuteResult([])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from app.api.settings.campaigns import router
    from app.db.session import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")
    app.state.redis = _FakeRedis()

    fake_db = _FakeDb()
    fake_redis = app.state.redis

    async def fake_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = fake_get_db

    return TestClient(app), fake_db, fake_redis


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_endpoint_returns_404_for_missing_campaign(client):
    test_client, db, redis = client
    db._campaign_exists = False
    cid = str(uuid.uuid4())

    resp = test_client.get(f"/api/settings/campaigns/{cid}/state/stale-status")

    assert resp.status_code == 404
    body = resp.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "campaign_not_found"
    else:
        assert detail == "campaign_not_found"


def test_endpoint_returns_no_state(client):
    test_client, db, redis = client
    cid = str(uuid.uuid4())
    db._version = None

    resp = test_client.get(f"/api/settings/campaigns/{cid}/state/stale-status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["potentially_stale"] is False
    assert body["stale_documents"] == []
    assert body["active_state_version"] is None
    assert "checked_at" in body


def test_endpoint_returns_fresh(client):
    test_client, db, redis = client
    cid = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    db._version = _FakeVersion(1, cid)
    db._values_source_refs = [[f"file:{doc_id}:sha:abc"]]
    db._items_source_refs = [[]]
    db._documents = [
        _FakeDocument(doc_id=doc_id, vault_id="v1", source_path="session.md", md5="abc"),
    ]
    redis.hashes["vault:v1:files"] = {
        "session.md": json.dumps({
            "md5": "abc",
            "indexed_md5": "abc",
            "index_status": "indexed",
        }),
    }

    resp = test_client.get(f"/api/settings/campaigns/{cid}/state/stale-status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["potentially_stale"] is False
    assert body["active_state_version"] == 1


def test_endpoint_returns_stale_after_md5_change(client):
    test_client, db, redis = client
    cid = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    db._version = _FakeVersion(2, cid)
    db._values_source_refs = [[f"file:{doc_id}:sha:oldhash"]]
    db._items_source_refs = [[]]
    db._documents = [
        _FakeDocument(doc_id=doc_id, vault_id="v1", source_path="session.md", md5="newhash"),
    ]
    redis.hashes["vault:v1:files"] = {
        "session.md": json.dumps({
            "md5": "oldhash",
            "indexed_md5": "oldhash",
            "index_status": "indexed",
        }),
    }

    resp = test_client.get(f"/api/settings/campaigns/{cid}/state/stale-status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["potentially_stale"] is True
    assert doc_id in body["stale_documents"]


def test_endpoint_invalid_uuid_returns_404(client):
    """Невалидный UUID → 404 (campaign_not_found)."""
    test_client, db, redis = client
    resp = test_client.get("/api/settings/campaigns/not-a-uuid/state/stale-status")
    assert resp.status_code in (404, 422)


def test_endpoint_response_shape(client):
    """Проверка всех полей ответа."""
    test_client, db, redis = client
    cid = str(uuid.uuid4())
    db._version = _FakeVersion(3, cid)

    resp = test_client.get(f"/api/settings/campaigns/{cid}/state/stale-status")

    assert resp.status_code == 200
    body = resp.json()
    # Обязательные поля per CampaignStateStaleStatus.
    assert set(body.keys()) == {
        "potentially_stale",
        "stale_documents",
        "active_state_version",
        "checked_at",
    }
    assert isinstance(body["potentially_stale"], bool)
    assert isinstance(body["stale_documents"], list)
    # Проверка формата checked_at (ISO 8601).
    parsed = datetime.fromisoformat(body["checked_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None