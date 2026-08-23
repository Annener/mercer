"""
Интеграционные тесты роутера update_mode.

Эти сценарии требуют полной симуляции update_mode_executor (БД-сессии, теги,
документы, Redis-сессия) и запускаются отдельно от unit-тестов.

Запуск:
    pytest tests/integration/test_update_mode_router_integration.py
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
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeChangeStatus,
    UpdateModeResolveResponse,
    UpdateModeSession,
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
        description="Add session update",
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
        note="session update",
        changes=changes or [_make_change()],
        created_at=now,
        expires_at=now + timedelta(hours=3),
    )


def _make_db_override(campaign_id: str = CAMPAIGN_ID):
    """Return async override for get_db that yields a mock AsyncSession."""
    from app.db.models import Campaign, Vault

    mock_campaign = MagicMock(spec=Campaign)
    mock_campaign.id = campaign_id
    mock_campaign.domain_id = "domain-1"

    mock_vault = MagicMock(spec=Vault)
    mock_vault.vault_id = "vault-1"
    mock_vault.domain_id = "domain-1"

    async def _fake_execute(stmt):
        result = MagicMock()
        stmt_str = str(stmt)
        if "campaign" in stmt_str.lower():
            result.scalar_one_or_none.return_value = mock_campaign
            result.scalars.return_value.all.return_value = []
        elif "vault" in stmt_str.lower():
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = [mock_vault]
        else:
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
    """Успешный старт возвращает 200 и сессию с изменениями."""
    app = _make_app()
    app.dependency_overrides[get_db] = _make_db_override()

    fake_redis = AsyncMock()
    app.state.redis = fake_redis

    resolve_resp = UpdateModeResolveResponse(changes=[_make_change()])
    session = _make_session(changes=[_make_change()])

    with (
        patch(
            "app.api.update_mode.indexer_client.resolve",
            new=AsyncMock(return_value=resolve_resp),
        ),
        patch(
            "app.api.update_mode.update_mode_store.get",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.api.update_mode.update_mode_store.create",
            new=AsyncMock(return_value=session),
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
    """Когда активная сессия уже есть — возвращаем 409."""
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
            "app.api.update_mode.update_mode_store.get",
            new=AsyncMock(return_value=None),
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
    """Когда rag-indexer недоступен — возвращаем 503 (UpdateModeIndexerUnavailableError)."""
    from app.services.indexer_client import IndexerUnavailableError

    app = _make_app()
    app.dependency_overrides[get_db] = _make_db_override()
    app.state.redis = AsyncMock()

    with (
        patch(
            "app.api.update_mode.indexer_client.resolve",
            new=AsyncMock(
                side_effect=IndexerUnavailableError(status_code=None, detail="connect refused")
            ),
        ),
        patch(
            "app.api.update_mode.update_mode_store.get",
            new=AsyncMock(return_value=None),
        ),
    ):
        with TestClient(app) as client:
            resp = client.post(
                f"/api/chats/{CHAT_ID}/update-mode/start",
                params={"campaign_id": CAMPAIGN_ID},
                json={"note": "note"},
            )

    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /apply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_returns_200_with_accepted_changes():
    """Успешный apply: возвращает 200 и список результатов по vault'ам."""
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