"""Tests for Stage 6: GET /campaigns/{id}/effective-context endpoint.

Стратегия: подменяем `build_effective_context` через monkeypatch.
Тестируем HTTP-маршрутизацию и формат ответа.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.api.settings import campaigns as api_module
from app.api.settings.campaigns import router
from app.db.models import Campaign, Chat
from app.db.session import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared_contracts.models import EffectiveContextBlock, EffectiveContextRead

# ---------------------------------------------------------------------------
# Fake service
# ---------------------------------------------------------------------------


class _FakeEffectiveContext:
    """Подмена `build_effective_context` для предсказуемого вывода."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        campaign_id: str | None,
        chat_id: str | None,
        domain_id: str | None,
        db: Any,
        **kwargs: Any,
    ) -> EffectiveContextRead:
        self.calls.append({
            "campaign_id": campaign_id,
            "chat_id": chat_id,
            "domain_id": domain_id,
        })
        return EffectiveContextRead(
            campaign_id=campaign_id,
            chat_id=chat_id,
            domain_id=domain_id,
            blocks=[
                EffectiveContextBlock(
                    name="system_prompt",
                    text="You are a helpful assistant.",
                    estimated_tokens=5,
                ),
                EffectiveContextBlock(
                    name="campaign_state",
                    text="Фокус: дизайн",
                    estimated_tokens=3,
                ),
            ],
            total_tokens=8,
            budget=800,
            truncated_fields=[],
            state_version=1,
        )


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------


class _FakeCampaign:
    """Минимальный stub Campaign для db.get(Campaign, uuid)."""

    def __init__(self, campaign_id: uuid.UUID, domain_id: str) -> None:
        self.id = campaign_id
        self.domain_id = domain_id
        self.name = "Test"
        self.description = None
        self.system_prompt = None
        self.last_session_at = None
        self.created_at = None
        self.config_version = 1


class _FakeChat:
    def __init__(self, chat_id: uuid.UUID, domain_id: str) -> None:
        self.id = chat_id
        self.domain_id = domain_id


class _FakeDBSession:
    """Эмуляция AsyncSession.get(Campaign|Chat, uuid)."""

    def __init__(
        self,
        campaign: _FakeCampaign | None = None,
        chat: _FakeChat | None = None,
    ) -> None:
        self._campaign = campaign
        self._chat = chat

    async def get(self, model: Any, key: Any):
        if model is Campaign:
            return self._campaign
        if model is Chat:
            return self._chat
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_ctx() -> _FakeEffectiveContext:
    return _FakeEffectiveContext()


@pytest.fixture
def client(monkeypatch, fake_ctx: _FakeEffectiveContext):
    monkeypatch.setattr(api_module, "build_effective_context", fake_ctx)

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")

    return TestClient(app), fake_ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_effective_context_returns_200_with_blocks(client):
    cli, fake = client
    cid = uuid.uuid4()
    fake_campaign = _FakeCampaign(cid, "dnd")
    db = _FakeDBSession(campaign=fake_campaign)
    app = cli.app

    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db

    r = cli.get(f"/api/settings/campaigns/{cid}/effective-context")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == str(cid)
    assert body["domain_id"] == "dnd"
    assert body["state_version"] == 1
    assert len(body["blocks"]) == 2
    assert body["blocks"][0]["name"] == "system_prompt"
    assert body["blocks"][1]["name"] == "campaign_state"
    assert body["total_tokens"] == 8
    assert body["budget"] == 800
    assert fake.calls[0]["campaign_id"] == str(cid)


def test_get_effective_context_404_for_unknown_campaign(client):
    cli, _fake = client
    cid = uuid.uuid4()
    db = _FakeDBSession(campaign=None)
    app = cli.app

    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db

    r = cli.get(f"/api/settings/campaigns/{cid}/effective-context")
    assert r.status_code == 404
    assert r.json()["detail"] == "Campaign not found"


def test_get_effective_context_404_for_invalid_uuid(client):
    cli, _fake = client
    r = cli.get("/api/settings/campaigns/not-a-uuid/effective-context")
    assert r.status_code == 404


def test_get_effective_context_uses_chat_domain_when_provided(client):
    cli, _fake = client
    cid = uuid.uuid4()
    chat_id = uuid.uuid4()
    fake_campaign = _FakeCampaign(cid, "dnd")
    fake_chat = _FakeChat(chat_id, "work")  # другой домен
    db = _FakeDBSession(campaign=fake_campaign, chat=fake_chat)
    app = cli.app

    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db

    r = cli.get(
        f"/api/settings/campaigns/{cid}/effective-context?chat_id={chat_id}"
    )
    assert r.status_code == 200
    body = r.json()
    # chat.domain_id должен быть выбран вместо campaign.domain_id.
    assert body["domain_id"] == "work"
    assert body["chat_id"] == str(chat_id)


def test_get_effective_context_with_truncated_fields(client, monkeypatch):
    cli, _fake = client

    async def stub(*args: Any, **kwargs: Any) -> EffectiveContextRead:
        return EffectiveContextRead(
            campaign_id=args[0] if args else None,
            chat_id=args[1] if len(args) > 1 else None,
            domain_id=args[2] if len(args) > 2 else None,
            blocks=[
                EffectiveContextBlock(
                    name="system_prompt", text="X", estimated_tokens=1,
                ),
            ],
            total_tokens=1,
            budget=800,
            truncated_fields=["big_field", "another_field"],
            state_version=2,
        )

    monkeypatch.setattr(api_module, "build_effective_context", stub)
    cid = uuid.uuid4()
    fake_campaign = _FakeCampaign(cid, "dnd")
    db = _FakeDBSession(campaign=fake_campaign)
    app = cli.app

    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db

    r = cli.get(f"/api/settings/campaigns/{cid}/effective-context")
    assert r.status_code == 200
    body = r.json()
    assert body["truncated_fields"] == ["big_field", "another_field"]
    assert body["state_version"] == 2


def test_get_effective_context_handles_empty_state(client, monkeypatch):
    cli, _fake = client

    async def stub(*args: Any, **kwargs: Any) -> EffectiveContextRead:
        # Кампания есть, но state нет → блоков нет.
        return EffectiveContextRead(
            campaign_id=args[0] if args else None,
            chat_id=args[1] if len(args) > 1 else None,
            domain_id=args[2] if len(args) > 2 else None,
            blocks=[
                EffectiveContextBlock(
                    name="system_prompt", text="X", estimated_tokens=1,
                ),
            ],
            total_tokens=1,
            budget=800,
            truncated_fields=[],
            state_version=None,
        )

    monkeypatch.setattr(api_module, "build_effective_context", stub)
    cid = uuid.uuid4()
    fake_campaign = _FakeCampaign(cid, "dnd")
    db = _FakeDBSession(campaign=fake_campaign)
    app = cli.app

    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db

    r = cli.get(f"/api/settings/campaigns/{cid}/effective-context")
    assert r.status_code == 200
    body = r.json()
    assert body["state_version"] is None
    # Только system_prompt без campaign_state.
    assert all(b["name"] != "campaign_state" for b in body["blocks"])
