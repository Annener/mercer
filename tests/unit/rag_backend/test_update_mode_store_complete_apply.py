"""Tests for UpdateModeStore.complete_apply (Phase 4 gap-1).

All tests use fakeredis so no real Redis instance is required.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
import fakeredis.aioredis as fakeredis

from app.services.update_mode_store import (
    SessionExpiredError,
    UpdateModeStore,
    update_mode_store,
)
from shared_contracts.models import (
    UpdateModeApplyResponse,
    UpdateModeApplyVaultResult,
    UpdateModeApplyVaultStatus,
    UpdateModeChange,
    UpdateModeChangeStatus,
    UpdateModeSession,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.FakeRedis()
    yield r
    await r.aclose()


def _make_session(chat_id: str = "chat-1") -> UpdateModeSession:
    return UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id=chat_id,
        campaign_id="camp-1",
        domain_id="domain-1",
        vault_ids=["vault-1"],
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        changes=[
            UpdateModeChange(
                change_id="chg-1",
                vault_id="vault-1",
                file_path="docs/plan.md",
                status=UpdateModeChangeStatus.ACCEPTED,
                action="update",
                proposed_content="# Updated",
                original_content="# Old",
            )
        ],
        warnings=[],
    )


def _make_apply_response(apply_id: str = "apply-abc") -> UpdateModeApplyResponse:
    return UpdateModeApplyResponse(
        apply_id=apply_id,
        results=[
            UpdateModeApplyVaultResult(
                vault_id="vault-1",
                status=UpdateModeApplyVaultStatus.SUCCESS,
                applied_count=1,
                commit_sha="deadbeef",
                reindex_task_id="task-xyz",
                failed_changes=[],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_apply_persists_result(redis):
    """complete_apply writes apply_result and sets apply_state='completed'."""
    store = UpdateModeStore()
    session = _make_session()
    await store.create(redis, session)

    resp = _make_apply_response()
    updated = await store.complete_apply(redis, session.chat_id, resp)

    assert updated is not None
    assert updated.apply_state == "completed"
    assert updated.apply_result is not None
    assert updated.apply_result.apply_id == resp.apply_id
    assert len(updated.apply_result.results) == 1
    assert updated.apply_result.results[0].vault_id == "vault-1"


@pytest.mark.asyncio
async def test_complete_apply_persisted_in_redis(redis):
    """Verify the Lua script actually writes back to Redis."""
    store = UpdateModeStore()
    session = _make_session()
    await store.create(redis, session)

    resp = _make_apply_response()
    await store.complete_apply(redis, session.chat_id, resp)

    # Re-fetch from Redis and verify state
    raw = await redis.get(f"update_mode:{session.chat_id}")
    assert raw is not None
    data = json.loads(raw)
    assert data["apply_state"] == "completed"
    assert data["apply_result"]["apply_id"] == resp.apply_id


@pytest.mark.asyncio
async def test_complete_apply_returns_none_on_expired_session(redis):
    """complete_apply returns None (not raises) when session key is gone."""
    store = UpdateModeStore()
    resp = _make_apply_response()

    result = await store.complete_apply(redis, "nonexistent-chat", resp)
    assert result is None


@pytest.mark.asyncio
async def test_complete_apply_renews_ttl(redis):
    """After complete_apply the TTL should be refreshed (≥ 1 hour)."""
    store = UpdateModeStore()
    session = _make_session()
    await store.create(redis, session)
    # Manually set a short TTL to simulate near-expiry
    await redis.expire(f"update_mode:{session.chat_id}", 60)

    resp = _make_apply_response()
    await store.complete_apply(redis, session.chat_id, resp)

    ttl = await redis.ttl(f"update_mode:{session.chat_id}")
    assert ttl > 3600  # should be reset to SESSION_TTL_SECONDS


@pytest.mark.asyncio
async def test_complete_apply_does_not_overwrite_other_fields(redis):
    """complete_apply must not lose changes list or other session fields."""
    store = UpdateModeStore()
    session = _make_session()
    await store.create(redis, session)

    resp = _make_apply_response()
    updated = await store.complete_apply(redis, session.chat_id, resp)

    assert updated is not None
    assert updated.campaign_id == session.campaign_id
    assert updated.domain_id == session.domain_id
    assert len(updated.changes) == len(session.changes)
    assert updated.changes[0].change_id == "chg-1"
