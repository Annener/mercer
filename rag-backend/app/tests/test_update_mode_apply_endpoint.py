"""Integration tests for POST /apply endpoint (Phase 4 gap-2).

Verifies:
  - complete_apply is called after successful indexer response
  - AuditLog write is attempted
  - 409 on ApplyConflict from store
  - 410 on expired session
  - 422 when no accepted changes exist
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared_contracts.models import (
    ApplyUpdateModeRequest,
    UpdateModeApplyResponse,
    UpdateModeApplyVaultResult,
    UpdateModeApplyVaultStatus,
    UpdateModeChange,
    UpdateModeChangeStatus,
    UpdateModeSession,
)


def _make_session(
    chat_id: str = "chat-1",
    apply_id: str | None = None,
    status: UpdateModeChangeStatus = UpdateModeChangeStatus.ACCEPTED,
) -> UpdateModeSession:
    s = UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id=chat_id,
        campaign_id="camp-1",
        domain_id="dom-1",
        vault_ids=["vault-1"],
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        changes=[
            UpdateModeChange(
                change_id="chg-1",
                vault_id="vault-1",
                file_path="docs/a.md",
                status=status,
                action="update",
                proposed_content="# New",
                original_content="# Old",
            )
        ],
        warnings=[],
        apply_id=apply_id,
    )
    return s


def _make_apply_resp(apply_id: str = "aid-1") -> UpdateModeApplyResponse:
    return UpdateModeApplyResponse(
        apply_id=apply_id,
        results=[
            UpdateModeApplyVaultResult(
                vault_id="vault-1",
                status=UpdateModeApplyVaultStatus.SUCCESS,
                applied_count=1,
                commit_sha="abc123",
                reindex_task_id="task-1",
                failed_changes=[],
            )
        ],
    )


@pytest.mark.asyncio
async def test_apply_calls_complete_apply_on_success():
    """After a successful indexer apply, complete_apply must be called."""
    session = _make_session(apply_id="aid-1")
    apply_resp = _make_apply_resp(apply_id="aid-1")

    with (
        patch(
            "app.api.update_mode.update_mode_store.begin_apply",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.api.update_mode.indexer_client.apply",
            new=AsyncMock(return_value=apply_resp),
        ),
        patch(
            "app.api.update_mode.update_mode_store.complete_apply",
            new=AsyncMock(return_value=session),
        ) as mock_complete,
        patch(
            "app.api.update_mode._write_audit_log",
            new=AsyncMock(),
        ),
    ):
        from app.api.update_mode import apply_changes

        mock_request = MagicMock()
        mock_request.app.state.redis = MagicMock()
        mock_db = AsyncMock()

        result = await apply_changes(
            chat_id="chat-1",
            body=ApplyUpdateModeRequest(apply_id="aid-1"),
            request=mock_request,
            db=mock_db,
        )

    mock_complete.assert_awaited_once()
    args = mock_complete.call_args
    assert args.kwargs.get("chat_id") == "chat-1" or args.args[1] == "chat-1"


@pytest.mark.asyncio
async def test_apply_calls_audit_log_on_success():
    """_write_audit_log must be called with action='update_mode.apply'."""
    session = _make_session(apply_id="aid-2")
    apply_resp = _make_apply_resp(apply_id="aid-2")

    with (
        patch(
            "app.api.update_mode.update_mode_store.begin_apply",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.api.update_mode.indexer_client.apply",
            new=AsyncMock(return_value=apply_resp),
        ),
        patch(
            "app.api.update_mode.update_mode_store.complete_apply",
            new=AsyncMock(return_value=session),
        ),
        patch(
            "app.api.update_mode._write_audit_log",
            new=AsyncMock(),
        ) as mock_audit,
    ):
        from app.api.update_mode import apply_changes

        mock_request = MagicMock()
        mock_request.app.state.redis = MagicMock()
        mock_db = AsyncMock()

        await apply_changes(
            chat_id="chat-1",
            body=ApplyUpdateModeRequest(apply_id="aid-2"),
            request=mock_request,
            db=mock_db,
        )

    mock_audit.assert_awaited_once()
    call_kwargs = mock_audit.call_args.kwargs
    assert call_kwargs["action"] == "update_mode.apply"
    assert call_kwargs["entity_type"] == "campaign"
    assert call_kwargs["entity_id"] == session.campaign_id


@pytest.mark.asyncio
async def test_apply_422_when_no_accepted_changes():
    """422 when all changes are still in pending/rejected status."""
    from fastapi import HTTPException

    session = _make_session(apply_id="aid-3", status=UpdateModeChangeStatus.PENDING)

    with (
        patch(
            "app.api.update_mode.update_mode_store.begin_apply",
            new=AsyncMock(return_value=session),
        ),
    ):
        from app.api.update_mode import apply_changes

        mock_request = MagicMock()
        mock_request.app.state.redis = MagicMock()
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await apply_changes(
                chat_id="chat-1",
                body=ApplyUpdateModeRequest(apply_id="aid-3"),
                request=mock_request,
                db=mock_db,
            )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_apply_410_on_expired_session():
    """410 when begin_apply raises SessionExpiredError."""
    from fastapi import HTTPException

    from app.services.update_mode_store import SessionExpiredError

    with patch(
        "app.api.update_mode.update_mode_store.begin_apply",
        new=AsyncMock(side_effect=SessionExpiredError("chat-1")),
    ):
        from app.api.update_mode import apply_changes

        mock_request = MagicMock()
        mock_request.app.state.redis = MagicMock()
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await apply_changes(
                chat_id="chat-1",
                body=ApplyUpdateModeRequest(apply_id="aid-4"),
                request=mock_request,
                db=mock_db,
            )

    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_apply_409_on_apply_conflict():
    """409 when begin_apply raises ApplyConflictError."""
    from fastapi import HTTPException

    from app.services.update_mode_store import ApplyConflictError

    with patch(
        "app.api.update_mode.update_mode_store.begin_apply",
        new=AsyncMock(side_effect=ApplyConflictError("new-id", "existing-id")),
    ):
        from app.api.update_mode import apply_changes

        mock_request = MagicMock()
        mock_request.app.state.redis = MagicMock()
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await apply_changes(
                chat_id="chat-1",
                body=ApplyUpdateModeRequest(apply_id="new-id"),
                request=mock_request,
                db=mock_db,
            )

    assert exc_info.value.status_code == 409
