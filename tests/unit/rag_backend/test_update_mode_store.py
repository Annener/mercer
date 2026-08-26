"""Tests for UpdateModeStore — Redis-backed session management.

All Redis calls are mocked with AsyncMock so no real Redis is required.
Lua evalsha results are also mocked to test the Python-side parsing.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from app.services.update_mode_store import (
    ApplyConflictError,
    CannotAcceptFailedChangeError,
    ReviewConflictError,
    SessionAlreadyActiveError,
    SessionExpiredError,
    UnknownChangeIdError,
    UpdateModeStore,
    update_mode_store,
)

from shared_contracts.models import (
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeChangeStatus,
    UpdateModeSession,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_change(
    change_id: str = "ch-1",
    status: UpdateModeChangeStatus = UpdateModeChangeStatus.PENDING,
    action: UpdateModeAction = UpdateModeAction.UPDATE,
) -> ResolvedUpdateModeChange:
    return ResolvedUpdateModeChange(
        change_id=change_id,
        vault_id="vault-1",
        document_id="doc-1",
        file_path="notes/session1.md",
        action=action,
        description="Add session recap",
        original_content="# Session 1",
        proposed_content="# Session 1\n\nPlayers arrived late.",
        unified_diff="@@ -1 +1,3 @@\n # Session 1\n+\n+Players arrived late.",
        expected_sha256="abc123",
        status=status,
    )


def _make_session(
    chat_id: str = "chat-test",
    campaign_id: str = "camp-1",
    changes: list[ResolvedUpdateModeChange] | None = None,
) -> UpdateModeSession:
    now = datetime.now(timezone.utc)
    return UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id=chat_id,
        campaign_id=campaign_id,
        domain_id="domain-1",
        vault_ids=["vault-1"],
        default_vault_id="vault-1",
        candidate_document_ids=["doc-1"],
        note="Add session recap",
        changes=changes or [_make_change()],
        created_at=now,
        expires_at=now + timedelta(hours=3),
    )


def _redis_mock() -> AsyncMock:
    """Create a minimal AsyncMock Redis."""
    redis = AsyncMock()
    # script_load returns a fake SHA
    redis.script_load = AsyncMock(return_value="faksha1234")
    return redis


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_none_when_key_missing() -> None:
    store = UpdateModeStore()
    redis = _redis_mock()
    redis.get = AsyncMock(return_value=None)

    result = await store.get(redis, "no-such-chat")
    assert result is None


@pytest.mark.asyncio
async def test_get_deserializes_session() -> None:
    store = UpdateModeStore()
    session = _make_session()
    redis = _redis_mock()
    redis.get = AsyncMock(return_value=session.model_dump_json())

    result = await store.get(redis, session.chat_id)
    assert result is not None
    assert result.chat_id == session.chat_id
    assert result.campaign_id == session.campaign_id
    assert len(result.changes) == 1


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_success() -> None:
    store = UpdateModeStore()
    session = _make_session()
    redis = _redis_mock()
    redis.set = AsyncMock(return_value=True)  # NX set succeeded

    await store.create(redis, session)  # should not raise
    redis.set.assert_called_once()
    call_kwargs = redis.set.call_args
    assert call_kwargs.kwargs.get("nx") is True or call_kwargs.args[-1] is True


@pytest.mark.asyncio
async def test_create_raises_if_already_active() -> None:
    store = UpdateModeStore()
    session = _make_session()
    redis = _redis_mock()
    redis.set = AsyncMock(return_value=None)  # NX returned None — key existed

    with pytest.raises(SessionAlreadyActiveError):
        await store.create(redis, session)


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_calls_redis_delete() -> None:
    store = UpdateModeStore()
    redis = _redis_mock()
    redis.delete = AsyncMock()

    await store.delete(redis, "chat-abc")
    redis.delete.assert_awaited_once_with("update_mode:chat-abc")


# ---------------------------------------------------------------------------
# update_review() — parsing side
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_review_happy_path() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha1234"  # pre-loaded

    session = _make_session(changes=[_make_change("ch-1"), _make_change("ch-2")])
    # Simulate Lua updating ch-1 to accepted
    updated_session = session.model_copy(deep=True)
    updated_session.changes[0].status = UpdateModeChangeStatus.ACCEPTED
    lua_response = updated_session.model_dump_json()

    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value=lua_response)

    result = await store.update_review(redis, session.chat_id, {"ch-1"}, set())
    assert result.changes[0].status == UpdateModeChangeStatus.ACCEPTED


@pytest.mark.asyncio
async def test_update_review_session_expired() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha1234"

    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value="ERR:session_expired")

    with pytest.raises(SessionExpiredError):
        await store.update_review(redis, "chat-x", {"ch-1"}, set())


@pytest.mark.asyncio
async def test_update_review_unknown_change_id() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha1234"

    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value="ERR:unknown_change_id:ch-99")

    with pytest.raises(UnknownChangeIdError) as exc_info:
        await store.update_review(redis, "chat-x", {"ch-99"}, set())
    assert "ch-99" in str(exc_info.value)


@pytest.mark.asyncio
async def test_update_review_cannot_accept_failed() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha1234"

    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value="ERR:cannot_accept_failed:ch-1")

    with pytest.raises(CannotAcceptFailedChangeError):
        await store.update_review(redis, "chat-x", {"ch-1"}, set())


@pytest.mark.asyncio
async def test_update_review_conflict() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha1234"

    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value="ERR:review_conflict:ch-1")

    with pytest.raises(ReviewConflictError):
        await store.update_review(redis, "chat-x", {"ch-1"}, set())


# ---------------------------------------------------------------------------
# begin_apply() — parsing side
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_apply_happy_path() -> None:
    store = UpdateModeStore()
    UpdateModeStore._apply_sha = "faksha5678"

    session = _make_session()
    apply_id = str(uuid.uuid4())
    applied = session.model_copy(deep=True)
    applied.apply_id = apply_id
    lua_response = applied.model_dump_json()

    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value=lua_response)

    result = await store.begin_apply(redis, session.chat_id, apply_id)
    assert result.apply_id == apply_id


@pytest.mark.asyncio
async def test_begin_apply_session_expired() -> None:
    store = UpdateModeStore()
    UpdateModeStore._apply_sha = "faksha5678"

    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value="ERR:session_expired")

    with pytest.raises(SessionExpiredError):
        await store.begin_apply(redis, "chat-x", None)


@pytest.mark.asyncio
async def test_begin_apply_conflict() -> None:
    store = UpdateModeStore()
    UpdateModeStore._apply_sha = "faksha5678"

    existing_id = "apply-old-id"
    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value=f"ERR:apply_conflict:{existing_id}")

    with pytest.raises(ApplyConflictError) as exc_info:
        await store.begin_apply(redis, "chat-x", "apply-new-id")
    assert existing_id in exc_info.value.detail


# ---------------------------------------------------------------------------
# Module-level singleton sanity
# ---------------------------------------------------------------------------


def test_module_singleton_is_store_instance() -> None:
    assert isinstance(update_mode_store, UpdateModeStore)


# ---------------------------------------------------------------------------
# Corrupted-session recovery: a stale payload from an older deploy schema
# must be dropped instead of propagating a 500. These regressions caused
# the chat-apply UI to white-screen because GET /session returned 500.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_none_for_unreadable_session() -> None:
    """A session whose inner payload is structurally invalid (e.g. a
    state-patch operation without a field_key) must not crash the read
    path. `get()` returns None so the API can answer 410 Gone instead
    of 500.
    """
    store = UpdateModeStore()
    redis = _redis_mock()
    # `source_refs` is repaired to `[]` by the normalizer, but the
    # enclosing patch entry is still missing `field_key` and `mode`,
    # which are still required. Pydantic rejects and `get()` returns None.
    redis.get = AsyncMock(
        return_value=json.dumps(
            {
                "note": "Пользователь предлагает...",
                "expires_at": "2026-08-25T18:19:21.817481Z",
                "state_patch_operations": [
                    {
                        "operation": {
                            "type": "replace_single",
                            "field_key": "k",
                            "text": "v",
                            "reason": "r",
                            "source_refs": {},
                        },
                    },
                ],
            }
        )
    )

    result = await store.get(redis, "chat-bad")

    assert result is None


def test_normalize_session_lists_repairs_nested_source_refs_dict() -> None:
    """Defence-in-depth: cjson turns empty arrays into {} on round-trip.
    `_normalize_session_lists` must recursively fix `source_refs` inside
    state_patch_operations so Pydantic accepts the payload.
    """
    from app.services.update_mode_store import _normalize_session_lists

    data = {
        "warnings": {},
        "vault_ids": {},
        "candidate_document_ids": {},
        "changes": {},
        "state_field_snapshot": {},
        "state_field_change_operations": {},
        "state_patch_operations": [
            {
                "operation": {
                    "type": "replace_single",
                    "source_refs": {},
                },
            },
            {
                "operation": {
                    "type": "add_list_item",
                    "source_refs": {},
                },
            },
        ],
    }

    normalised = _normalize_session_lists(data)

    assert normalised["warnings"] == []
    assert normalised["vault_ids"] == []
    assert normalised["candidate_document_ids"] == []
    assert normalised["changes"] == []
    for op in normalised["state_patch_operations"]:
        assert op["operation"]["source_refs"] == []


def test_normalize_session_lists_keeps_populated_lists_intact() -> None:
    """Non-empty list values must NOT be touched by the normalizer."""
    from app.services.update_mode_store import _normalize_session_lists

    data = {
        "warnings": ["a", "b"],
        "state_patch_operations": [
            {"operation": {"type": "replace_single", "source_refs": ["file:x:sha:y"]}},
        ],
    }

    normalised = _normalize_session_lists(data)

    assert normalised["warnings"] == ["a", "b"]
    assert normalised["state_patch_operations"][0]["operation"]["source_refs"] == [
        "file:x:sha:y"
    ]


def test_normalize_session_lists_inserts_missing_defaults() -> None:
    """Old payloads may omit fields that the current DTO declares as
    optional-with-default. The normalizer must fill them in so the
    session loads without breaking the read path.
    """
    from app.services.update_mode_store import _normalize_session_lists

    # No list/str fields at all — only the core identifying fields that
    # are still required by the DTO.
    data = {
        "session_id": "sid",
        "chat_id": "chat-x",
        "campaign_id": "camp-1",
        "domain_id": "domain-1",
        "created_at": "2026-08-25T18:00:00Z",
        "expires_at": "2026-08-25T21:00:00Z",
    }

    normalised = _normalize_session_lists(data)

    assert normalised["warnings"] == []
    assert normalised["vault_ids"] == []
    assert normalised["candidate_document_ids"] == []
    assert normalised["changes"] == []
    assert normalised["state_patch_operations"] == []
    assert normalised["state_field_snapshot"] == []
    assert normalised["state_field_change_operations"] == []
    assert normalised["note"] == ""
    assert normalised["default_vault_id"] == ""


@pytest.mark.asyncio
async def test_begin_apply_raises_expired_for_unreadable_session() -> None:
    """If the Lua round-trip returns a payload that no longer matches the
    current DTO schema, `begin_apply` must raise `SessionExpiredError` so
    the API can answer 410. The session itself is NOT deleted — the
    caller decides what to do next.
    """
    store = UpdateModeStore()
    UpdateModeStore._apply_sha = "faksha5678"

    # Mimic a payload produced by older code: missing top-level required
    # fields like `candidate_document_ids` and `changes`.
    corrupted_payload = json.dumps(
        {"note": "Фиксация из старой версии", "expires_at": "2026-08-25T18:31:44Z"}
    )

    redis = _redis_mock()
    redis.evalsha = AsyncMock(return_value=corrupted_payload)

    with pytest.raises(SessionExpiredError):
        await store.begin_apply(redis, "chat-x", None)
