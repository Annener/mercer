"""Tests for Context Draft API (Phase 4).

Endpoints:
  GET  /api/chats/{chat_id}/context-draft
  POST /api/chats/{chat_id}/context-draft/accept
  POST /api/chats/{chat_id}/context-draft/reject
  POST /api/chats/{chat_id}/context-draft/check-files   (501 — Phase 5 TODO)

Coverage:
- GET returns {"draft": null} when Redis empty / chat has no campaign
- GET returns payload when present in Redis
- GET returns 404-equivalent ({"draft": null}) semantics via chat_not_found path
- Accept parses payload, applies via stubbed service, clears drift, writes audit
- Accept returns 404 when no draft in Redis
- Accept returns 409 when apply_patch raises
- Accept returns 400 for invalid state_patch
- Reject deletes draft, clears drift, writes audit
- Reject returns 422 if chat has no campaign
- Check-files returns 501 with detail "check_files_pending_phase_5"

Тесты не поднимают БД — Chat / Campaign и apply_patch подменяются
через fake-session / monkeypatch на campaign_state_value_service.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.api.context_draft import router as context_draft_router
from app.db.models import AuditLog
from app.db.session import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from shared_contracts.models import CampaignStatePatchResponse

# ---------------------------------------------------------------------------
# Fake DB session
# ---------------------------------------------------------------------------


class _FakeChat:
    def __init__(self, chat_id: uuid.UUID, campaign_id: uuid.UUID | None) -> None:
        self.id = chat_id
        self.campaign_id = campaign_id
        self.metadata_json = {"scene_state": {"explicit": {}, "drift": {}}}


class _FakeCampaign:
    def __init__(self, campaign_id: uuid.UUID, config_version: int = 1) -> None:
        self.id = campaign_id
        self.config_version = config_version


class _FakeResult:
    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar(self) -> Any:
        return self._scalar


class _FakeDBSession:
    """Минимальная AsyncSession-совместимая заглушка.

    Поддерживает:
      - ``db.get(Model, pk)`` для Chat и Campaign
      - ``db.execute(stmt)`` для SELECT скаляров
      - ``db.add(obj)``
      - ``db.commit()`` (AsyncMock)
      - ``db.refresh(obj)``
    """

    def __init__(
        self,
        chat: _FakeChat | None = None,
        campaign: _FakeCampaign | None = None,
        active_state=None,
    ) -> None:
        self._chat = chat
        self._campaign = campaign
        self._active_state = active_state
        self.added: list[Any] = []
        self.commits: int = 0

    async def get(self, model: type, pk: Any) -> Any:
        if model.__name__ == "Chat":
            return self._chat
        if model.__name__ == "Campaign":
            return self._campaign
        return None

    async def execute(self, stmt: Any) -> _FakeResult:
        # Заглушка — реальные SELECT не нужны в тестах API.
        return _FakeResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Fake Redis
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets: list[str] = []
        self.deletes: list[str] = []

    async def get(self, key: str) -> str | None:
        self.gets.append(key)
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> Any:
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        self.deletes.append(key)
        if key in self.store:
            del self.store[key]
            return 1
        return 0


# ---------------------------------------------------------------------------
# Fake campaign_state_value_service
# ---------------------------------------------------------------------------


class _FakeValueService:
    def __init__(
        self,
        active_state=None,
        *,
        apply_error: Exception | None = None,
        applied_state_version: int = 7,
    ) -> None:
        self._active_state = active_state
        self._apply_error = apply_error
        self._applied_state_version = applied_state_version
        self.apply_patch_calls: list[Any] = []

    async def get_active_state(self, db: AsyncSession, campaign_id: uuid.UUID):
        return self._active_state

    async def apply_patch(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        request: Any,
    ) -> CampaignStatePatchResponse:
        self.apply_patch_calls.append(
            {
                "campaign_id": campaign_id,
                "base_state_version": request.base_state_version,
                "config_version": request.config_version,
                "operations": list(request.operations),
            }
        )
        if self._apply_error is not None:
            raise self._apply_error
        return CampaignStatePatchResponse(
            applied_state_version=self._applied_state_version,
            config_version=request.config_version,
            applied_operations=[op.type for op in request.operations],
            failed_operations=[],
        )


# ---------------------------------------------------------------------------
# Fake clear_drift (Phase 4: just record the call; Phase 2b already covers real impl)
# ---------------------------------------------------------------------------


def _install_clear_drift_recorder(monkeypatch) -> dict:
    """Подменяем ``clear_drift`` в scene_memory модуле — он вызывается
    lazy-import-ом из router, поэтому патчим по полному пути."""
    recorder: dict[str, list[str]] = {"calls": []}

    async def fake_clear_drift(chat_id: str, db: Any) -> None:
        recorder["calls"].append(chat_id)

    from app.services.context_engine import scene_memory

    monkeypatch.setattr(scene_memory, "clear_drift", fake_clear_drift)
    return recorder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAMPLE_OPS: list[dict[str, Any]] = [
    {
        "type": "replace_single",
        "field_key": "current_location",
        "text": "Таверна «Серебряный колокол»",
        "reason": "Игроки вошли в таверну",
        "source_refs": [],
    }
]


def _draft_payload(chat_id: str, campaign_id: str) -> dict:
    return {
        "chat_id": chat_id,
        "campaign_id": campaign_id,
        "state_patch": SAMPLE_OPS,
        "summary": "Персонажи вошли в таверну",
        "drift_hash": "abc123",
        "drift_hints": [
            {"fact": "Мы вошли в таверну", "confidence": 0.9, "adds_field": "current_location"}
        ],
        "created_at": "2026-09-01T00:00:00Z",
        "expires_at": "2026-09-01T03:00:00Z",
    }


def _make_client(
    *,
    fake_db: _FakeDBSession,
    fake_redis: _FakeRedis,
    fake_value_service: _FakeValueService,
    monkeypatch,
) -> TestClient:
    app = FastAPI()
    app.include_router(context_draft_router)
    app.state.redis = fake_redis

    # Подменяем глобальный service — router импортирует его через module-global.
    from app.api import context_draft as api_module

    monkeypatch.setattr(
        api_module, "campaign_state_value_service", fake_value_service
    )

    async def _override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET tests
# ---------------------------------------------------------------------------


class TestGetContextDraft:
    def test_returns_null_when_chat_has_no_campaign(
        self, monkeypatch
    ) -> None:
        chat_id = str(uuid.uuid4())
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id=None)
        fake_db = _FakeDBSession(chat=chat)
        fake_redis = _FakeRedis()
        service = _FakeValueService()
        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.get(f"/api/chats/{chat_id}/context-draft")
        assert resp.status_code == 200
        assert resp.json() == {"draft": None}
        assert fake_redis.gets == []  # нет ключа → Redis не дёргается

    def test_returns_null_when_no_redis_entry(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        campaign_id = uuid.uuid4()
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id)
        fake_db = _FakeDBSession(chat=chat)
        fake_redis = _FakeRedis()
        service = _FakeValueService()
        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.get(f"/api/chats/{chat_id}/context-draft")
        assert resp.status_code == 200
        assert resp.json() == {"draft": None}

    def test_returns_payload_when_present(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        campaign_id = uuid.uuid4()
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id)
        fake_db = _FakeDBSession(chat=chat)
        fake_redis = _FakeRedis()

        key = f"draft:campaign:{campaign_id}:chat:{chat_id}"
        payload = _draft_payload(chat_id, str(campaign_id))
        fake_redis.store[key] = json.dumps(payload, ensure_ascii=False)

        service = _FakeValueService()
        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.get(f"/api/chats/{chat_id}/context-draft")
        assert resp.status_code == 200
        body = resp.json()
        assert body["draft"] is not None
        assert body["draft"]["summary"] == payload["summary"]
        assert body["draft"]["state_patch"][0]["field_key"] == "current_location"


# ---------------------------------------------------------------------------
# Accept tests
# ---------------------------------------------------------------------------


class TestAcceptContextDraft:
    def test_accept_returns_404_when_no_draft(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        campaign_id = uuid.uuid4()
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id)
        fake_db = _FakeDBSession(chat=chat, campaign=_FakeCampaign(campaign_id))
        fake_redis = _FakeRedis()
        service = _FakeValueService()
        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/accept")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "draft_not_found"

    def test_accept_returns_400_for_invalid_patch(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        campaign_id = uuid.uuid4()
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id)
        fake_db = _FakeDBSession(chat=chat, campaign=_FakeCampaign(campaign_id))
        fake_redis = _FakeRedis()

        # Положили в Redis невалидный patch (несуществующий type).
        key = f"draft:campaign:{campaign_id}:chat:{chat_id}"
        bad_payload = _draft_payload(chat_id, str(campaign_id))
        bad_payload["state_patch"] = [
            {"type": "totally_invalid_type", "field_key": "x"}
        ]
        fake_redis.store[key] = json.dumps(bad_payload)

        service = _FakeValueService()
        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/accept")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_patch"

    def test_accept_applies_patch_clears_drift_writes_audit(
        self, monkeypatch
    ) -> None:
        chat_id = str(uuid.uuid4())
        campaign_id = uuid.uuid4()
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id)
        campaign = _FakeCampaign(campaign_id, config_version=3)
        fake_db = _FakeDBSession(chat=chat, campaign=campaign)
        fake_redis = _FakeRedis()

        key = f"draft:campaign:{campaign_id}:chat:{chat_id}"
        fake_redis.store[key] = json.dumps(
            _draft_payload(chat_id, str(campaign_id)),
            ensure_ascii=False,
        )

        # active_state без summary нам не нужен — router использует None fallback.
        # base_state_version -> None, config_version -> 3 (из campaign).
        service = _FakeValueService(active_state=None, applied_state_version=11)
        clear_drift_rec = _install_clear_drift_recorder(monkeypatch)

        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/accept")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "applied_state_version": 11,
            "operations_count": 1,
        }

        # apply_patch вызван с правильным config_version и операциями
        assert len(service.apply_patch_calls) == 1
        call = service.apply_patch_calls[0]
        assert call["campaign_id"] == campaign_id
        assert call["config_version"] == 3
        assert call["base_state_version"] is None
        assert len(call["operations"]) == 1
        assert call["operations"][0].type == "replace_single"

        # Redis-ключ удалён
        assert fake_redis.deletes == [key]
        assert fake_redis.store == {}

        # clear_drift вызван на правильный chat_id
        assert clear_drift_rec["calls"] == [chat_id]

        # AuditLog записан и закоммичен
        assert len(fake_db.added) == 1
        audit = fake_db.added[0]
        assert isinstance(audit, AuditLog)
        assert audit.action == "context_draft_accepted"
        assert audit.entity_type == "chat"
        assert audit.entity_id == chat_id
        assert audit.payload["applied_state_version"] == 11
        assert audit.payload["operations_count"] == 1
        assert fake_db.commits == 1

    def test_accept_returns_409_on_apply_failure(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        campaign_id = uuid.uuid4()
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id)
        fake_db = _FakeDBSession(chat=chat, campaign=_FakeCampaign(campaign_id))
        fake_redis = _FakeRedis()
        key = f"draft:campaign:{campaign_id}:chat:{chat_id}"
        fake_redis.store[key] = json.dumps(
            _draft_payload(chat_id, str(campaign_id)),
            ensure_ascii=False,
        )

        service = _FakeValueService(
            apply_error=RuntimeError("config_version_conflict"),
        )
        _install_clear_drift_recorder(monkeypatch)

        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/accept")
        assert resp.status_code == 409
        assert "config_version_conflict" in resp.json()["detail"]

        # При сбое Redis-ключ НЕ удаляется и drift НЕ очищается
        assert fake_redis.deletes == []
        assert key in fake_redis.store

    def test_accept_returns_422_when_no_campaign(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id=None)
        fake_db = _FakeDBSession(chat=chat)
        fake_redis = _FakeRedis()
        service = _FakeValueService()

        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/accept")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "campaign_required"


# ---------------------------------------------------------------------------
# Reject tests
# ---------------------------------------------------------------------------


class TestRejectContextDraft:
    def test_reject_deletes_draft_clears_drift_writes_audit(
        self, monkeypatch
    ) -> None:
        chat_id = str(uuid.uuid4())
        campaign_id = uuid.uuid4()
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id)
        fake_db = _FakeDBSession(chat=chat)
        fake_redis = _FakeRedis()
        key = f"draft:campaign:{campaign_id}:chat:{chat_id}"
        fake_redis.store[key] = json.dumps(
            _draft_payload(chat_id, str(campaign_id)),
            ensure_ascii=False,
        )

        service = _FakeValueService()
        clear_drift_rec = _install_clear_drift_recorder(monkeypatch)

        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/reject")
        assert resp.status_code == 200
        assert resp.json() == {"status": "rejected"}

        assert fake_redis.deletes == [key]
        assert clear_drift_rec["calls"] == [chat_id]
        assert len(fake_db.added) == 1
        audit = fake_db.added[0]
        assert isinstance(audit, AuditLog)
        assert audit.action == "context_draft_rejected"
        assert audit.entity_id == chat_id
        assert fake_db.commits == 1

    def test_reject_returns_422_when_no_campaign(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id=None)
        fake_db = _FakeDBSession(chat=chat)
        fake_redis = _FakeRedis()
        service = _FakeValueService()

        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/reject")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "campaign_required"


# ---------------------------------------------------------------------------
# Check-files tests
# ---------------------------------------------------------------------------


class TestCheckFilesEndpoint:
    def test_check_files_returns_501_phase_5_pending(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        campaign_id = uuid.uuid4()
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id)
        fake_db = _FakeDBSession(chat=chat, campaign=_FakeCampaign(campaign_id))
        fake_redis = _FakeRedis()
        service = _FakeValueService()

        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/check-files")
        assert resp.status_code == 501
        assert resp.json()["detail"] == "check_files_pending_phase_5"

    def test_check_files_returns_422_when_no_campaign(self, monkeypatch) -> None:
        chat_id = str(uuid.uuid4())
        chat = _FakeChat(uuid.UUID(chat_id), campaign_id=None)
        fake_db = _FakeDBSession(chat=chat)
        fake_redis = _FakeRedis()
        service = _FakeValueService()

        client = _make_client(
            fake_db=fake_db,
            fake_redis=fake_redis,
            fake_value_service=service,
            monkeypatch=monkeypatch,
        )

        resp = client.post(f"/api/chats/{chat_id}/context-draft/check-files")
        # campaign_required проверяется до 501.
        assert resp.status_code == 422
        assert resp.json()["detail"] == "campaign_required"
