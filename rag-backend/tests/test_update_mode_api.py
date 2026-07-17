from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.update_mode import router
from app.services.update_mode_executor import (
    UpdateModeCampaignDomainMismatchError,
    UpdateModeCampaignRequiredError,
    UpdateModeGenerationProviderUnavailableError,
    UpdateModeIndexerInvalidResponseError,
    UpdateModeIndexerUnavailableError,
    UpdateModeInvalidGenerationOutputError,
    UpdateModeNoEnabledVaultsError,
    UpdateModeNoIndexedMarkdownError,
    UpdateModeNoRelevantContextError,
    UpdateModeNoUsableContextError,
    UpdateModeReviewStoreUnavailableError,
    UpdateModeSessionAlreadyActiveError,
)
from shared_contracts.models import (
    CancelUpdateModeResponse,
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeChangeStatus,
    UpdateModeSession,
)


class DummyRedis:
    pass


class DummyAppState:
    def __init__(self):
        self.redis = DummyRedis()


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.redis = DummyRedis()

    async def fake_get_db():
        yield object()

    from app.api import update_mode as update_mode_module
    from app.db.session import get_db

    app.dependency_overrides[get_db] = fake_get_db
    return TestClient(app)


def _session() -> UpdateModeSession:
    now = datetime.now(timezone.utc)
    return UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id="chat-1",
        campaign_id=str(uuid.uuid4()),
        domain_id="dnd",
        vault_ids=["vault-main"],
        default_vault_id="vault-main",
        candidate_document_ids=[str(uuid.uuid4())],
        note="note",
        warnings=["warn-1"],
        changes=[
            ResolvedUpdateModeChange(
                change_id="chg-1",
                vault_id="vault-main",
                document_id=str(uuid.uuid4()),
                file_path="sessions/session-12.md",
                action=UpdateModeAction.UPDATE,
                description="append",
                proposed_content="## Update\nText",
                unified_diff="diff",
                status=UpdateModeChangeStatus.PENDING,
            )
        ],
        created_at=now,
        expires_at=now + timedelta(hours=3),
    )


def test_post_start_success(client, monkeypatch):
    sess = _session()

    class DummyExecutor:
        def __init__(self, db, store, indexer_client):
            pass

        async def start(self, chat_id: str, redis, note: str):
            assert chat_id == "chat-1"
            assert note == "hello"
            return sess

    monkeypatch.setattr("app.api.update_mode.UpdateModeExecutor", DummyExecutor)

    resp = client.post("/api/chats/chat-1/update-mode/start", json={"note": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["chat_id"] == "chat-1"
    assert body["warnings"] == ["warn-1"]
    assert body["changes"][0]["change_id"] == "chg-1"


@pytest.mark.parametrize(
    ("exc", "status", "detail"),
    [
        (UpdateModeSessionAlreadyActiveError("x"), 409, "session_already_active"),
        (UpdateModeCampaignRequiredError("x"), 422, "campaign_required"),
        (UpdateModeCampaignDomainMismatchError("x"), 409, "campaign_domain_mismatch"),
        (UpdateModeNoEnabledVaultsError("x"), 422, "no_enabled_vaults"),
        (UpdateModeNoIndexedMarkdownError("x"), 422, "campaign_has_no_indexed_markdown"),
        (UpdateModeNoRelevantContextError("x"), 422, "no_relevant_campaign_context"),
        (UpdateModeNoUsableContextError("x"), 422, "no_usable_indexed_context"),
        (UpdateModeInvalidGenerationOutputError("x"), 422, "invalid_generation_output"),
        (UpdateModeGenerationProviderUnavailableError("x"), 503, "generation_provider_unavailable"),
        (UpdateModeIndexerUnavailableError("x"), 503, "indexer_unavailable"),
        (UpdateModeIndexerInvalidResponseError("x"), 502, "indexer_invalid_response"),
        (UpdateModeReviewStoreUnavailableError("x"), 503, "review_store_unavailable"),
    ],
)
def test_post_start_error_mapping(client, monkeypatch, exc, status, detail):
    class DummyExecutor:
        def __init__(self, db, store, indexer_client):
            pass

        async def start(self, chat_id: str, redis, note: str):
            raise exc

    monkeypatch.setattr("app.api.update_mode.UpdateModeExecutor", DummyExecutor)

    resp = client.post("/api/chats/chat-1/update-mode/start", json={"note": "hello"})
    assert resp.status_code == status
    assert resp.json()["detail"] == detail


def test_get_session_returns_410_when_missing(client, monkeypatch):
    class DummyStore:
        async def get(self, redis, chat_id):
            return None

    monkeypatch.setattr("app.api.update_mode.update_mode_store", DummyStore())

    resp = client.get("/api/chats/chat-1/update-mode/session")
    assert resp.status_code == 410
    assert resp.json()["detail"] == "session_expired"


def test_get_session_returns_session(client, monkeypatch):
    sess = _session()

    class DummyStore:
        async def get(self, redis, chat_id):
            return sess

    monkeypatch.setattr("app.api.update_mode.update_mode_store", DummyStore())

    resp = client.get("/api/chats/chat-1/update-mode/session")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chat_id"] == sess.chat_id
    assert body["domain_id"] == "dnd"
    assert body["vault_ids"] == ["vault-main"]
    assert body["changes"][0]["change_id"] == "chg-1"


def test_delete_session(client, monkeypatch):
    deleted = {"called": False}

    class DummyStore:
        async def delete(self, redis, chat_id):
            deleted["called"] = True

    monkeypatch.setattr("app.api.update_mode.update_mode_store", DummyStore())

    resp = client.delete("/api/chats/chat-1/update-mode/session")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cancelled"}
    assert deleted["called"] is True
