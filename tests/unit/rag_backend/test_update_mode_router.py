"""Router-level integration tests for the Campaign Update Mode endpoints.

All external I/O (Redis, DB, indexer_client) is mocked so the tests run
without any live service.

Coverage:
  POST   /api/chats/{chat_id}/update-mode/start
  GET    /api/chats/{chat_id}/update-mode/session
  PATCH  /api/chats/{chat_id}/update-mode/review
  POST   /api/chats/{chat_id}/update-mode/apply
  DELETE /api/chats/{chat_id}/update-mode/session
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.update_mode import router
from app.db.session import get_db
from shared_contracts.models import (
    ApplyUpdateModeResponse,
    CancelUpdateModeResponse,
    ResolvedUpdateModeChange,
    StartUpdateModeResponse,
    UpdateModeAction,
    UpdateModeChangeStatus,
    UpdateModeOperation,
    UpdateModeResolveResponse,
    UpdateModeSession,
    UpdateModeSessionResponse,
    UpdateModeVaultApplyResult,
    UpdateModeVaultApplyStatus,
)


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


CHAT_ID = "chat-router-test"
CAMPAIGN_ID = "camp-router-test"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_change(
    status: UpdateModeChangeStatus = UpdateModeChangeStatus.PENDING,
) -> ResolvedUpdateModeChange:
    return ResolvedUpdateModeChange(
        change_id="ch-1",
        vault_id="vault-1",
        document_id=None,
        file_path="notes/session1.md",
        action=UpdateModeAction.CREATE,
        description="Add session recap",
        original_content="",
        proposed_content="# Session 1\n\nPlayers arrived late.",
        unified_diff="",
        expected_sha256=None,
        status=status,
    )


def _make_session(
    changes: list[ResolvedUpdateModeChange] | None = None,
) -> UpdateModeSession:
    now = _now()
    return UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id=CHAT_ID,
        campaign_id=CAMPAIGN_ID,
        domain_id="domain-1",
        vault_ids=["vault-1"],
        default_vault_id="vault-1",
        candidate_document_ids=[],
        note="session recap",
        changes=changes or [_make_change()],
        created_at=now,
        expires_at=now + timedelta(hours=3),
    )


# ---------------------------------------------------------------------------
# DB override helper
# ---------------------------------------------------------------------------


def _make_db_override(campaign_id: str = CAMPAIGN_ID):
    """Return async override for get_db that yields a mock AsyncSession.

    The mock is configured to return a fake Campaign, Vault, and empty docs.
    """
    from app.db.models import Campaign, Vault

    mock_campaign = MagicMock(spec=Campaign)
    mock_campaign.id = campaign_id
    mock_campaign.domain_id = "domain-1"

    mock_vault = MagicMock(spec=Vault)
    mock_vault.vault_id = "vault-1"
    mock_vault.domain_id = "domain-1"

    async def _fake_execute(stmt):
        # Return different scalars depending on the target model
        result = MagicMock()
        stmt_str = str(stmt)
        if "campaign" in stmt_str.lower():
            result.scalar_one_or_none.return_value = mock_campaign
            result.scalars.return_value.all.return_value = []
        elif "vault" in stmt_str.lower():
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = [mock_vault]
        else:
            # documents
            result.scalars.return_value.all.return_value = []
        return result

    async def override():
        db = AsyncMock(spec=AsyncSession)
        db.execute = _fake_execute
        yield db

    return override


# ---------------------------------------------------------------------------
# POST /start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_200_and_session():
    app = _make_app()
    app.dependency_overrides[get_db] = _make_db_override()

    fake_redis = AsyncMock()
    app.state.redis = fake_redis

    resolve_resp = UpdateModeResolveResponse(changes=[_make_change()])

    with (
        patch(
            "app.api.update_mode.indexer_client.resolve",
            new=AsyncMock(return_value=resolve_resp),
        ),
        patch(
            "app.api.update_mode.update_mode_store.create",
            new=AsyncMock(return_value=None),
        ),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/chats/{CHAT_ID}/update-mode/start",
                params={"campaign_id": CAMPAIGN_ID},
                json={"note": "Session 1 recap: players arrived late."},
            )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["chat_id"] == CHAT_ID
    assert len(data["changes"]) == 1


@pytest.mark.asyncio
async def test_start_returns_409_when_session_already_active():
    from app.services.update_mode_store import SessionAlreadyActiveError

    app = _make_app()
    app.dependency_overrides[get_db] = _make_db_override()
    app.state.redis = AsyncMock()

    resolve_resp = UpdateModeResolveResponse(changes=[_make_change()])

    with (
        patch(
            "app.api.update_mode.indexer_client.resolve",
            new=AsyncMock(return_value=resolve_resp),
        ),
        patch(
            "app.api.update_mode.update_mode_store.create",
            new=AsyncMock(side_effect=SessionAlreadyActiveError(CHAT_ID)),
        ),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/chats/{CHAT_ID}/update-mode/start",
                params={"campaign_id": CAMPAIGN_ID},
                json={"note": "note"},
            )

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_start_returns_502_on_indexer_unavailable():
    from app.services.indexer_client import IndexerUnavailableError

    app = _make_app()
    app.dependency_overrides[get_db] = _make_db_override()
    app.state.redis = AsyncMock()

    with patch(
        "app.api.update_mode.indexer_client.resolve",
        new=AsyncMock(side_effect=IndexerUnavailableError("connect refused")),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/chats/{CHAT_ID}/update-mode/start",
                params={"campaign_id": CAMPAIGN_ID},
                json={"note": "note"},
            )

    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_returns_200():
    app = _make_app()
    app.state.redis = AsyncMock()

    session = _make_session()

    with patch(
        "app.api.update_mode.update_mode_store.get",
        new=AsyncMock(return_value=session),
    ):
        with TestClient(app) as client:
            resp = client.get(f"/api/chats/{CHAT_ID}/update-mode/session")

    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_id"] == CHAT_ID
    assert data["campaign_id"] == CAMPAIGN_ID


@pytest.mark.asyncio
async def test_get_session_returns_410_when_missing():
    app = _make_app()
    app.state.redis = AsyncMock()

    with patch(
        "app.api.update_mode.update_mode_store.get",
        new=AsyncMock(return_value=None),
    ):
        with TestClient(app) as client:
            resp = client.get(f"/api/chats/{CHAT_ID}/update-mode/session")

    assert resp.status_code == 410


# ---------------------------------------------------------------------------
# PATCH /review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_accepts_changes():
    app = _make_app()
    app.state.redis = AsyncMock()

    accepted_session = _make_session(
        changes=[_make_change(status=UpdateModeChangeStatus.ACCEPTED)]
    )

    with patch(
        "app.api.update_mode.update_mode_store.update_review",
        new=AsyncMock(return_value=accepted_session),
    ):
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/chats/{CHAT_ID}/update-mode/review",
                json={"accepted_change_ids": ["ch-1"], "rejected_change_ids": []},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["changes"][0]["status"] == "accepted"


@pytest.mark.asyncio
async def test_review_returns_422_on_unknown_change():
    from app.services.update_mode_store import UnknownChangeIdError

    app = _make_app()
    app.state.redis = AsyncMock()

    with patch(
        "app.api.update_mode.update_mode_store.update_review",
        new=AsyncMock(side_effect=UnknownChangeIdError("ch-999")),
    ):
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/chats/{CHAT_ID}/update-mode/review",
                json={"accepted_change_ids": ["ch-999"], "rejected_change_ids": []},
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_review_returns_410_on_expired_session():
    from app.services.update_mode_store import SessionExpiredError

    app = _make_app()
    app.state.redis = AsyncMock()

    with patch(
        "app.api.update_mode.update_mode_store.update_review",
        new=AsyncMock(side_effect=SessionExpiredError(CHAT_ID)),
    ):
        with TestClient(app) as client:
            resp = client.patch(
                f"/api/chats/{CHAT_ID}/update-mode/review",
                json={"accepted_change_ids": ["ch-1"], "rejected_change_ids": []},
            )

    assert resp.status_code == 410


# ---------------------------------------------------------------------------
# POST /apply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_returns_200_with_accepted_changes():
    from app.services.update_mode_store import ApplyConflictError

    app = _make_app()
    app.state.redis = AsyncMock()

    accepted_session = _make_session(
        changes=[_make_change(status=UpdateModeChangeStatus.ACCEPTED)]
    )
    accepted_session.apply_id = str(uuid.uuid4())

    apply_resp = ApplyUpdateModeResponse(
        apply_id=accepted_session.apply_id,
        results=[
            UpdateModeVaultApplyResult(
                vault_id="vault-1",
                status=UpdateModeVaultApplyStatus.APPLIED,
                applied_count=1,
                commit_sha="abc123",
            )
        ],
    )

    with (
        patch(
            "app.api.update_mode.update_mode_store.begin_apply",
            new=AsyncMock(return_value=accepted_session),
        ),
        patch(
            "app.api.update_mode.indexer_client.apply",
            new=AsyncMock(return_value=apply_resp),
        ),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/chats/{CHAT_ID}/update-mode/apply",
                json={"apply_id": None},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["results"][0]["status"] == "applied"


@pytest.mark.asyncio
async def test_apply_returns_422_when_no_accepted_changes():
    app = _make_app()
    app.state.redis = AsyncMock()

    pending_session = _make_session(
        changes=[_make_change(status=UpdateModeChangeStatus.PENDING)]
    )

    with patch(
        "app.api.update_mode.update_mode_store.begin_apply",
        new=AsyncMock(return_value=pending_session),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/chats/{CHAT_ID}/update-mode/apply",
                json={"apply_id": None},
            )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_returns_cancelled():
    app = _make_app()
    app.state.redis = AsyncMock()

    with patch(
        "app.api.update_mode.update_mode_store.delete",
        new=AsyncMock(return_value=None),
    ):
        with TestClient(app) as client:
            resp = client.delete(f"/api/chats/{CHAT_ID}/update-mode/session")

    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
