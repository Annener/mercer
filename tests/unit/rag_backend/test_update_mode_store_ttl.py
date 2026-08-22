"""TTL renewal verification for UpdateModeStore Lua calls.

Verifies that update_review() and begin_apply() pass the correct
(key, ttl_seconds) arguments to the Lua evalsha call — i.e. the store
actually renews the Redis key TTL on every write.

All Redis calls are mocked; no real Redis is required.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, call, patch

import pytest

from app.services.update_mode_store import (
    UpdateModeStore,
    _SESSION_TTL_SECONDS,  # noqa: WPS450 (intentional private import for testing)
)
from shared_contracts.models import (
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeChangeStatus,
    UpdateModeOperation,
    UpdateModeSession,
)

_KEY_PREFIX = "update_mode:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_change(
    change_id: str = "ch-1",
    status: UpdateModeChangeStatus = UpdateModeChangeStatus.PENDING,
) -> ResolvedUpdateModeChange:
    return ResolvedUpdateModeChange(
        change_id=change_id,
        vault_id="vault-1",
        document_id=None,
        file_path="notes/session1.md",
        action=UpdateModeAction.CREATE,
        description="Add session recap",
        original_content="",
        proposed_content="# Session 1",
        unified_diff="",
        expected_sha256=None,
        status=status,
    )


def _make_session(
    chat_id: str = "chat-ttl-test",
    changes: list[ResolvedUpdateModeChange] | None = None,
) -> UpdateModeSession:
    now = datetime.now(timezone.utc)
    return UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id=chat_id,
        campaign_id="camp-1",
        domain_id="domain-1",
        vault_ids=["vault-1"],
        default_vault_id="vault-1",
        candidate_document_ids=[],
        note="session recap",
        changes=changes or [_make_change()],
        created_at=now,
        expires_at=now + timedelta(hours=3),
    )


def _redis_mock(session: UpdateModeSession) -> AsyncMock:
    redis = AsyncMock()
    redis.script_load = AsyncMock(return_value="faksha")
    # evalsha returns the serialised session (simulates CAS success)
    redis.evalsha = AsyncMock(return_value=session.model_dump_json())
    redis.get = AsyncMock(return_value=session.model_dump_json())
    return redis


# ---------------------------------------------------------------------------
# update_review() — TTL renewal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_review_renews_ttl() -> None:
    """update_review must call evalsha with the session key and the correct TTL."""
    chat_id = "chat-ttl-test"
    session = _make_session(chat_id=chat_id, changes=[_make_change()])
    redis = _redis_mock(session)

    store = UpdateModeStore()
    await store.update_review(
        redis,
        chat_id,
        accepted_change_ids={"ch-1"},
        rejected_change_ids=set(),
    )

    redis.evalsha.assert_awaited_once()
    args = redis.evalsha.call_args
    # evalsha(sha, numkeys, key, ...payload...)
    # The third positional argument (index 2) is the Redis key
    positional = args.args if args.args else args[0]
    key_arg = positional[2]  # KEYS[1]
    assert key_arg == f"{_KEY_PREFIX}{chat_id}", (
        f"Expected key '{_KEY_PREFIX}{chat_id}', got '{key_arg}'"
    )

    # TTL must be present in the args (passed as ARGV)
    # The store passes ttl as ARGV[1] or a keyword arg; verify it equals
    # _SESSION_TTL_SECONDS (or is > 0).
    all_args = list(positional)
    ttl_candidates = [
        a for a in all_args
        if isinstance(a, (int, float)) and int(a) > 0
    ]
    assert ttl_candidates, (
        "No positive TTL value found in evalsha args. "
        f"Full args: {all_args}"
    )
    assert int(ttl_candidates[0]) == _SESSION_TTL_SECONDS, (
        f"Expected TTL={_SESSION_TTL_SECONDS}, got {ttl_candidates[0]}"
    )


# ---------------------------------------------------------------------------
# begin_apply() — TTL renewal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_apply_renews_ttl() -> None:
    """begin_apply must call evalsha with the session key and the correct TTL."""
    chat_id = "chat-ttl-apply"
    session = _make_session(
        chat_id=chat_id,
        changes=[
            _make_change(status=UpdateModeChangeStatus.ACCEPTED)
        ],
    )
    redis = _redis_mock(session)

    store = UpdateModeStore()
    await store.begin_apply(redis, chat_id, apply_id=None)

    redis.evalsha.assert_awaited_once()
    args = redis.evalsha.call_args
    positional = args.args if args.args else args[0]
    key_arg = positional[2]
    assert key_arg == f"{_KEY_PREFIX}{chat_id}"

    all_args = list(positional)
    ttl_candidates = [
        a for a in all_args
        if isinstance(a, (int, float)) and int(a) > 0
    ]
    assert ttl_candidates, "No positive TTL value found in begin_apply evalsha args."
    assert int(ttl_candidates[0]) == _SESSION_TTL_SECONDS


# ---------------------------------------------------------------------------
# Regression: TTL must match the SESSION_TTL constant, not a hard-coded value
# ---------------------------------------------------------------------------


def test_session_ttl_constant_matches_three_hours() -> None:
    """_SESSION_TTL_SECONDS must be 3 hours (10800 s) per the plan spec."""
    assert _SESSION_TTL_SECONDS == 10_800, (
        f"Expected _SESSION_TTL_SECONDS == 10800 (3 h), got {_SESSION_TTL_SECONDS}"
    )
