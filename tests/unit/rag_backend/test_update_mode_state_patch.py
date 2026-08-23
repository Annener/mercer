"""Unit tests for Stage 5: state_patch in Campaign Update Mode.

Covers:
  - shared_contracts DTOs for state-patch operations
  - update_mode_executor._validate_state_patch_against_snapshot
  - update_mode_executor.build_state_patch_entries
  - update_mode_store.update_review with state-patch decisions
  - API PATCH /review with state_patch_decisions
  - API POST /apply with state_patch_result + audit log

All external dependencies (Redis, LLM provider, indexer) are mocked.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.api.update_mode import router
from app.services.update_mode_executor import (
    _validate_state_patch_against_snapshot,
    build_state_patch_entries,
)
from app.services.update_mode_store import (
    StateOpReviewConflictError,
    UnknownStateOpIndexError,
    UpdateModeStore,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared_contracts.models import (
    CampaignStateAddListItem,
    CampaignStateClearSingle,
    CampaignStateFieldSnapshot,
    CampaignStateFieldValuesRead,
    CampaignStateListItemRead,
    CampaignStatePatchResponse,
    CampaignStateRemoveListItem,
    CampaignStateReplaceSingle,
    CampaignStateResolveListItem,
    CampaignStateSingleValueRead,
    CampaignStateUpdateListItem,
    CampaignStateVersionRead,
    CampaignStateVersionSummary,
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeChangeStatus,
    UpdateModeGenerationResult,
    UpdateModeIntent,
    UpdateModeOperation,
    UpdateModeReviewRequest,
    UpdateModeSession,
    UpdateModeStatePatchDecisions,
    UpdateModeStatePatchEntry,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_field_snapshot(
    field_id: str | None = None,
    key: str = "current_focus",
    label: str = "Текущий фокус",
    mode: str = "single",
    display_order: int = 0,
    enabled: bool = True,
) -> CampaignStateFieldSnapshot:
    return CampaignStateFieldSnapshot(
        field_id=field_id or str(uuid.uuid4()),
        key=key,
        label=label,
        description="",
        mode=mode,  # type: ignore[arg-type]
        display_order=display_order,
    )


def _make_replace_single(
    field_key: str = "current_focus",
    text: str = "Новый фокус",
    reason: str = "обновлено по итогам сессии",
) -> CampaignStateReplaceSingle:
    return CampaignStateReplaceSingle(
        field_key=field_key, text=text, reason=reason, source_refs=[]
    )


def _make_add_list_item(
    field_key: str = "agreements",
    text: str = "Новая договорённость",
    reason: str = "зафиксировано на встрече",
) -> CampaignStateAddListItem:
    return CampaignStateAddListItem(
        field_key=field_key, text=text, reason=reason, source_refs=[]
    )


def _make_clear_single(field_key: str = "current_focus") -> CampaignStateClearSingle:
    return CampaignStateClearSingle(field_key=field_key, reason="сброс", source_refs=[])


def _make_remove_list_item(
    field_key: str = "agreements",
    item_key: str = "agreement-01",
) -> CampaignStateRemoveListItem:
    return CampaignStateRemoveListItem(
        field_key=field_key, item_key=item_key, reason="больше не актуально", source_refs=[]
    )


def _make_current_state(
    fields: list[CampaignStateFieldValuesRead] | None = None,
    state_version: int = 1,
) -> CampaignStateVersionRead:
    return CampaignStateVersionRead(
        summary=CampaignStateVersionSummary(
            id=str(uuid.uuid4()),
            campaign_id=str(uuid.uuid4()),
            state_version=state_version,
            config_version=1,
            source_kind="initial",
            base_state_version=None,
            created_at=datetime.now(timezone.utc),
            created_by=None,
        ),
        fields=fields or [],
    )


# ---------------------------------------------------------------------------
# shared_contracts DTO validation
# ---------------------------------------------------------------------------


def test_state_patch_decisions_rejects_overlap_accepted_rejected() -> None:
    with pytest.raises(ValueError):
        UpdateModeStatePatchDecisions(
            accepted_op_indexes=[0, 1],
            rejected_op_indexes=[1, 2],
        )


def test_state_patch_decisions_rejects_edited_with_rejected() -> None:
    from shared_contracts.models import UpdateModeStatePatchEdit

    with pytest.raises(ValueError):
        UpdateModeStatePatchDecisions(
            rejected_op_indexes=[0],
            edited=[UpdateModeStatePatchEdit(op_index=0, text="x")],
        )


def test_state_patch_decisions_accepts_edited_and_accepted_separately() -> None:
    from shared_contracts.models import UpdateModeStatePatchEdit

    decisions = UpdateModeStatePatchDecisions(
        accepted_op_indexes=[0],
        edited=[UpdateModeStatePatchEdit(op_index=1, text="y")],
    )
    assert decisions.accepted_op_indexes == [0]
    assert len(decisions.edited) == 1


def test_update_mode_review_request_accepts_state_patch_decisions_none() -> None:
    req = UpdateModeReviewRequest(
        accepted_change_ids=["chg-1"],
        rejected_change_ids=[],
        state_patch_decisions=None,
    )
    assert req.state_patch_decisions is None


def test_update_mode_review_request_rejects_all_empty_no_decisions() -> None:
    with pytest.raises(ValueError):
        UpdateModeReviewRequest(
            accepted_change_ids=[],
            rejected_change_ids=[],
            state_patch_decisions=None,
        )


def test_update_mode_review_request_accepts_state_only() -> None:
    req = UpdateModeReviewRequest(
        accepted_change_ids=[],
        rejected_change_ids=[],
        state_patch_decisions=UpdateModeStatePatchDecisions(accepted_op_indexes=[0]),
    )
    assert req.state_patch_decisions is not None


# ---------------------------------------------------------------------------
# _validate_state_patch_against_snapshot
# ---------------------------------------------------------------------------


def test_validate_drops_unknown_field_key() -> None:
    snapshot = [_make_field_snapshot(key="known")]
    warnings: list[str] = []
    ops = [_make_replace_single(field_key="unknown")]
    cleaned = _validate_state_patch_against_snapshot(ops, snapshot, None, warnings)
    assert cleaned == []
    assert any("field_not_found" in w for w in warnings)


def test_validate_drops_mode_mismatch_replace_on_list_field() -> None:
    snapshot = [_make_field_snapshot(key="agreements", mode="list")]
    warnings: list[str] = []
    ops = [_make_replace_single(field_key="agreements")]
    cleaned = _validate_state_patch_against_snapshot(ops, snapshot, None, warnings)
    assert cleaned == []
    assert any("mode_mismatch" in w for w in warnings)


def test_validate_drops_mode_mismatch_clear_on_list_field() -> None:
    snapshot = [_make_field_snapshot(key="agreements", mode="list")]
    warnings: list[str] = []
    ops = [_make_clear_single(field_key="agreements")]
    cleaned = _validate_state_patch_against_snapshot(ops, snapshot, None, warnings)
    assert cleaned == []
    assert any("mode_mismatch" in w for w in warnings)


def test_validate_drops_add_list_on_single_field() -> None:
    snapshot = [_make_field_snapshot(key="current_focus", mode="single")]
    warnings: list[str] = []
    ops = [_make_add_list_item(field_key="current_focus")]
    cleaned = _validate_state_patch_against_snapshot(ops, snapshot, None, warnings)
    assert cleaned == []
    assert any("mode_mismatch" in w for w in warnings)


def test_validate_drops_update_list_with_unknown_item() -> None:
    snapshot = [_make_field_snapshot(key="agreements", mode="list")]
    current_state = _make_current_state(
        fields=[
            CampaignStateFieldValuesRead(
                field_key="agreements",
                field_id="fid",
                mode="list",
                enabled=True,
                display_order=0,
                items=[
                    CampaignStateListItemRead(
                        field_key="agreements",
                        item_key="agreement-01",
                        text="real item",
                        resolved=False,
                    )
                ],
            )
        ]
    )
    warnings: list[str] = []
    ops = [
        CampaignStateUpdateListItem(
            field_key="agreements",
            item_key="agreement-99",
            text="x",
            reason="r",
        )
    ]
    cleaned = _validate_state_patch_against_snapshot(ops, snapshot, current_state, warnings)
    assert cleaned == []
    assert any("item_not_found" in w for w in warnings)


def test_validate_drops_empty_text_for_add_list_item() -> None:
    snapshot = [_make_field_snapshot(key="agreements", mode="list")]
    warnings: list[str] = []
    ops = [
        CampaignStateAddListItem(field_key="agreements", text="   ", reason="r")
    ]
    cleaned = _validate_state_patch_against_snapshot(ops, snapshot, None, warnings)
    assert cleaned == []
    assert any("empty_text" in w for w in warnings)


def test_validate_keeps_valid_ops_in_order() -> None:
    snapshot = [
        _make_field_snapshot(key="current_focus", mode="single"),
        _make_field_snapshot(key="agreements", mode="list", display_order=1),
    ]
    warnings: list[str] = []
    ops = [
        _make_replace_single(field_key="current_focus", text="A"),
        _make_add_list_item(field_key="agreements", text="B"),
    ]
    cleaned = _validate_state_patch_against_snapshot(ops, snapshot, None, warnings)
    assert len(cleaned) == 2
    assert cleaned[0].field_key == "current_focus"
    assert cleaned[1].field_key == "agreements"
    assert warnings == []


def test_validate_keeps_resolve_list_item_without_text_check() -> None:
    snapshot = [_make_field_snapshot(key="agreements", mode="list")]
    current_state = _make_current_state(
        fields=[
            CampaignStateFieldValuesRead(
                field_key="agreements",
                field_id="fid",
                mode="list",
                enabled=True,
                display_order=0,
                items=[
                    CampaignStateListItemRead(
                        field_key="agreements",
                        item_key="agreement-01",
                        text="real",
                        resolved=False,
                    )
                ],
            )
        ]
    )
    warnings: list[str] = []
    ops = [
        CampaignStateResolveListItem(
            field_key="agreements", item_key="agreement-01", reason="done"
        )
    ]
    cleaned = _validate_state_patch_against_snapshot(ops, snapshot, current_state, warnings)
    assert len(cleaned) == 1


# ---------------------------------------------------------------------------
# build_state_patch_entries
# ---------------------------------------------------------------------------


def test_build_state_patch_entries_assigns_op_index_and_status() -> None:
    snapshot = [
        _make_field_snapshot(field_id="fid-1", key="current_focus", label="Фокус", mode="single"),
        _make_field_snapshot(field_id="fid-2", key="agreements", label="Договорённости", mode="list"),
    ]
    ops = [
        _make_replace_single(field_key="current_focus", text="новое"),
        _make_add_list_item(field_key="agreements", text="пункт 1"),
    ]
    entries = build_state_patch_entries(ops, snapshot, None)

    assert len(entries) == 2
    assert entries[0].op_index == 0
    assert entries[0].field_key == "current_focus"
    assert entries[0].field_label == "Фокус"
    assert entries[0].status == "pending"
    assert entries[0].proposed_text == "новое"
    assert entries[0].previous_text is None
    assert entries[0].edited_text is None

    assert entries[1].op_index == 1
    assert entries[1].field_key == "agreements"
    assert entries[1].field_label == "Договорённости"
    assert entries[1].proposed_text == "пункт 1"


def test_build_state_patch_entries_reads_previous_text_from_current_state() -> None:
    snapshot = [_make_field_snapshot(key="current_focus", mode="single")]
    current_state = _make_current_state(
        fields=[
            CampaignStateFieldValuesRead(
                field_key="current_focus",
                field_id="fid",
                mode="single",
                enabled=True,
                display_order=0,
                single_value=CampaignStateSingleValueRead(
                    field_key="current_focus",
                    text="старое значение",
                    source_refs=[],
                ),
                items=[],
            )
        ]
    )
    ops = [_make_replace_single(field_key="current_focus", text="новое")]
    entries = build_state_patch_entries(ops, snapshot, current_state)
    assert entries[0].previous_text == "старое значение"


def test_build_state_patch_entries_uses_key_as_label_fallback() -> None:
    [_make_field_snapshot(field_id="fid-x", key="mystery", mode="single")]
    ops = [_make_replace_single(field_key="mystery", text="z")]
    # snapshot lookup is by key; label fallback applies when snapshot row absent
    entries = build_state_patch_entries(ops, [], None)
    assert entries[0].field_label == "mystery"


# ---------------------------------------------------------------------------
# UpdateModeStore.update_review — state-patch decisions
# ---------------------------------------------------------------------------


class _DummyRedis:
    def __init__(self) -> None:
        self.script_load = AsyncMock(return_value="faksha")
        self.evalsha = AsyncMock()
        self.get = AsyncMock(return_value=None)
        self.set = AsyncMock(return_value=True)


def _make_session_with_state_ops(
    state_ops: list[UpdateModeStatePatchEntry] | None = None,
    changes: list[ResolvedUpdateModeChange] | None = None,
) -> UpdateModeSession:
    now = datetime.now(timezone.utc)
    return UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id="chat-x",
        campaign_id=str(uuid.uuid4()),
        domain_id="dnd",
        vault_ids=["vault-main"],
        default_vault_id="vault-main",
        candidate_document_ids=[str(uuid.uuid4())],
        note="n",
        changes=changes or [],
        state_patch_operations=state_ops or [],
        created_at=now,
        expires_at=now + timedelta(hours=3),
    )


def _state_op_entry(
    op_index: int,
    field_key: str,
    op_type: str,
    text: str | None = None,
    item_key: str | None = None,
) -> UpdateModeStatePatchEntry:
    field_label = field_key
    if op_type in ("replace_single", "clear_single"):
        op: object
        if op_type == "replace_single":
            op = CampaignStateReplaceSingle(field_key=field_key, text=text or "x", reason="r")
        else:
            op = CampaignStateClearSingle(field_key=field_key, reason="r")
        mode = "single"
    elif op_type == "add_list_item":
        op = CampaignStateAddListItem(field_key=field_key, text=text or "x", reason="r")
        mode = "list"
    elif op_type == "update_list_item":
        op = CampaignStateUpdateListItem(field_key=field_key, item_key=item_key or "x", text=text or "x", reason="r")
        mode = "list"
    elif op_type == "resolve_list_item":
        op = CampaignStateResolveListItem(field_key=field_key, item_key=item_key or "x", reason="r")
        mode = "list"
    elif op_type == "remove_list_item":
        op = CampaignStateRemoveListItem(field_key=field_key, item_key=item_key or "x", reason="r")
        mode = "list"
    else:
        raise ValueError(op_type)

    return UpdateModeStatePatchEntry(
        op_index=op_index,
        field_key=field_key,
        field_label=field_label,
        mode=mode,  # type: ignore[arg-type]
        operation=op,  # type: ignore[arg-type]
        previous_text=None,
        proposed_text=text,
        edited_text=None,
        status="pending",
    )


@pytest.mark.asyncio
async def test_update_review_accepts_state_op_indexes() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha"

    entries = [
        _state_op_entry(0, "current_focus", "replace_single", text="new"),
        _state_op_entry(1, "current_focus", "clear_single"),
    ]
    session = _make_session_with_state_ops(state_ops=entries)
    accepted_session = session.model_copy(deep=True)
    accepted_session.state_patch_operations[0].status = "accepted"

    redis = _DummyRedis()
    redis.evalsha = AsyncMock(return_value=accepted_session.model_dump_json())

    result = await store.update_review(
        redis,
        session.chat_id,
        accepted_change_ids=set(),
        rejected_change_ids=set(),
        accepted_state_op_indexes={0},
        rejected_state_op_indexes=set(),
    )
    assert result.state_patch_operations[0].status == "accepted"
    assert result.state_patch_operations[1].status == "pending"


@pytest.mark.asyncio
async def test_update_review_rejects_state_op_indexes() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha"

    entries = [_state_op_entry(0, "agreements", "remove_list_item", item_key="agreement-01")]
    session = _make_session_with_state_ops(state_ops=entries)
    rejected_session = session.model_copy(deep=True)
    rejected_session.state_patch_operations[0].status = "rejected"

    redis = _DummyRedis()
    redis.evalsha = AsyncMock(return_value=rejected_session.model_dump_json())

    result = await store.update_review(
        redis,
        session.chat_id,
        accepted_change_ids=set(),
        rejected_change_ids=set(),
        accepted_state_op_indexes=set(),
        rejected_state_op_indexes={0},
    )
    assert result.state_patch_operations[0].status == "rejected"


@pytest.mark.asyncio
async def test_update_review_applies_edit_to_replace_single() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha"

    entries = [_state_op_entry(0, "current_focus", "replace_single", text="original")]
    session = _make_session_with_state_ops(state_ops=entries)
    edited_session = session.model_copy(deep=True)
    edited_session.state_patch_operations[0].edited_text = "edited text"
    edited_session.state_patch_operations[0].operation = (
        edited_session.state_patch_operations[0].operation.model_copy(update={"text": "edited text"})
    )

    redis = _DummyRedis()
    redis.evalsha = AsyncMock(return_value=edited_session.model_dump_json())

    result = await store.update_review(
        redis,
        session.chat_id,
        accepted_change_ids=set(),
        rejected_change_ids=set(),
        edited_state_ops={0: "edited text"},
    )
    assert result.state_patch_operations[0].edited_text == "edited text"


@pytest.mark.asyncio
async def test_update_review_raises_on_unknown_state_op() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha"

    redis = _DummyRedis()
    redis.evalsha = AsyncMock(return_value="ERR:unknown_state_op:42")

    with pytest.raises(UnknownStateOpIndexError):
        await store.update_review(
            redis,
            "chat-x",
            accepted_change_ids=set(),
            rejected_change_ids=set(),
            accepted_state_op_indexes={42},
        )


@pytest.mark.asyncio
async def test_update_review_raises_on_state_op_review_conflict() -> None:
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha"

    redis = _DummyRedis()
    redis.evalsha = AsyncMock(return_value="ERR:state_op_review_conflict:7")

    with pytest.raises(StateOpReviewConflictError):
        await store.update_review(
            redis,
            "chat-x",
            accepted_change_ids=set(),
            rejected_change_ids=set(),
            accepted_state_op_indexes={7},
        )


@pytest.mark.asyncio
async def test_update_review_backward_compat_without_state_decisions() -> None:
    """Existing clients that don't send state decisions still work."""
    store = UpdateModeStore()
    UpdateModeStore._review_sha = "faksha"

    change = ResolvedUpdateModeChange(
        change_id="chg-1",
        vault_id="vault-main",
        document_id="doc-1",
        file_path="notes/session.md",
        action=UpdateModeAction.UPDATE,
        description="append",
        proposed_content="body",
        unified_diff="diff",
        status=UpdateModeChangeStatus.PENDING,
    )
    session = _make_session_with_state_ops(changes=[change])
    updated = session.model_copy(deep=True)
    updated.changes[0].status = UpdateModeChangeStatus.ACCEPTED

    redis = _DummyRedis()
    redis.evalsha = AsyncMock(return_value=updated.model_dump_json())

    result = await store.update_review(
        redis,
        session.chat_id,
        accepted_change_ids={"chg-1"},
        rejected_change_ids=set(),
    )
    assert result.changes[0].status == UpdateModeChangeStatus.ACCEPTED


# ---------------------------------------------------------------------------
# API: PATCH /review with state_patch_decisions
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.state.redis = SimpleNamespace()

    fake_db = SimpleNamespace(get=AsyncMock(return_value=None))

    async def fake_get_db():
        yield fake_db

    from app.db.session import get_db
    app.dependency_overrides[get_db] = fake_get_db

    def configure_db(campaign=None):
        fake_db.get = AsyncMock(return_value=campaign)

    app.state.configure_db = configure_db
    return TestClient(app)


def _make_fake_campaign(config_version: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        config_version=config_version,
    )


def _build_session_with_state_ops() -> UpdateModeSession:
    now = datetime.now(timezone.utc)
    entries = [
        _state_op_entry(0, "current_focus", "replace_single", text="new focus"),
        _state_op_entry(1, "current_focus", "clear_single"),
        _state_op_entry(2, "agreements", "add_list_item", text="item 1"),
    ]
    return UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id="chat-1",
        campaign_id=str(uuid.uuid4()),
        domain_id="dnd",
        vault_ids=["vault-main"],
        default_vault_id="vault-main",
        candidate_document_ids=[str(uuid.uuid4())],
        note="n",
        changes=[],
        state_patch_operations=entries,
        created_at=now,
        expires_at=now + timedelta(hours=3),
    )


def test_patch_review_accepts_state_patch_decisions(client, monkeypatch) -> None:
    sess = _build_session_with_state_ops()
    accepted_session = sess.model_copy(deep=True)
    accepted_session.state_patch_operations[0].status = "accepted"
    accepted_session.state_patch_operations[1].status = "rejected"

    captured_kwargs: dict = {}

    async def fake_update_review(
        redis, chat_id, accepted_change_ids, rejected_change_ids,
        **kwargs,
    ):
        captured_kwargs["accepted_state_op_indexes"] = kwargs.get(
            "accepted_state_op_indexes"
        )
        captured_kwargs["rejected_state_op_indexes"] = kwargs.get(
            "rejected_state_op_indexes"
        )
        captured_kwargs["edited_state_ops"] = kwargs.get("edited_state_ops")
        return accepted_session

    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(update_review=fake_update_review),
    )

    resp = client.patch(
        "/api/chats/chat-1/update-mode/review",
        json={
            "accepted_change_ids": [],
            "rejected_change_ids": [],
            "state_patch_decisions": {
                "accepted_op_indexes": [0],
                "rejected_op_indexes": [1],
                "edited": [],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert captured_kwargs["accepted_state_op_indexes"] == {0}
    assert captured_kwargs["rejected_state_op_indexes"] == {1}
    assert captured_kwargs["edited_state_ops"] == {}
    # response echoes state-patch operations with new statuses
    statuses = [e["status"] for e in body["state_patch_operations"]]
    assert statuses[0] == "accepted"
    assert statuses[1] == "rejected"


def test_patch_review_edited_text_forwarded(client, monkeypatch) -> None:
    sess = _build_session_with_state_ops()
    accepted_session = sess.model_copy(deep=True)
    accepted_session.state_patch_operations[0].status = "accepted"
    accepted_session.state_patch_operations[0].edited_text = "manually edited"

    captured: dict = {}

    async def fake_update_review(
        redis, chat_id, accepted_change_ids, rejected_change_ids,
        **kwargs,
    ):
        captured["edited_state_ops"] = kwargs.get("edited_state_ops")
        return accepted_session

    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(update_review=fake_update_review),
    )

    resp = client.patch(
        "/api/chats/chat-1/update-mode/review",
        json={
            "accepted_change_ids": [],
            "rejected_change_ids": [],
            "state_patch_decisions": {
                "accepted_op_indexes": [0],
                "edited": [{"op_index": 0, "text": "manually edited"}],
            },
        },
    )
    assert resp.status_code == 200
    assert captured["edited_state_ops"] == {0: "manually edited"}


def test_patch_review_state_only_no_file_changes(client, monkeypatch) -> None:
    sess = _build_session_with_state_ops()
    accepted_session = sess.model_copy(deep=True)
    accepted_session.state_patch_operations[2].status = "accepted"

    captured: dict = {}

    async def fake_update_review(
        redis, chat_id, accepted_change_ids, rejected_change_ids,
        **kwargs,
    ):
        captured["accepted_state_op_indexes"] = kwargs.get(
            "accepted_state_op_indexes"
        )
        return accepted_session

    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(update_review=fake_update_review),
    )

    resp = client.patch(
        "/api/chats/chat-1/update-mode/review",
        json={
            "accepted_change_ids": [],
            "rejected_change_ids": [],
            "state_patch_decisions": {"accepted_op_indexes": [2]},
        },
    )
    assert resp.status_code == 200
    assert captured["accepted_state_op_indexes"] == {2}


def test_patch_review_propagates_unknown_state_op_422(client, monkeypatch) -> None:
    async def fake_update_review(
        redis, chat_id, accepted_change_ids, rejected_change_ids,
        **kwargs,
    ):
        raise UnknownStateOpIndexError(99)

    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(update_review=fake_update_review),
    )

    resp = client.patch(
        "/api/chats/chat-1/update-mode/review",
        json={
            "accepted_change_ids": [],
            "rejected_change_ids": [],
            "state_patch_decisions": {"accepted_op_indexes": [99]},
        },
    )
    assert resp.status_code == 422


def test_patch_review_propagates_state_op_conflict_409(client, monkeypatch) -> None:
    async def fake_update_review(
        redis, chat_id, accepted_change_ids, rejected_change_ids,
        **kwargs,
    ):
        raise StateOpReviewConflictError(7)

    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(update_review=fake_update_review),
    )

    resp = client.patch(
        "/api/chats/chat-1/update-mode/review",
        json={
            "accepted_change_ids": [],
            "rejected_change_ids": [],
            "state_patch_decisions": {"accepted_op_indexes": [7]},
        },
    )
    assert resp.status_code == 409


def test_session_response_includes_state_patch_fields(client, monkeypatch) -> None:
    sess = _build_session_with_state_ops()
    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(get=AsyncMock(return_value=sess)),
    )
    resp = client.get("/api/chats/chat-1/update-mode/session")
    assert resp.status_code == 200
    body = resp.json()
    assert "state_field_snapshot" in body
    assert "state_patch_operations" in body
    assert len(body["state_patch_operations"]) == 3


# ---------------------------------------------------------------------------
# API: POST /apply — state_patch_result + audit
# ---------------------------------------------------------------------------


def _build_session_for_apply() -> UpdateModeSession:
    now = datetime.now(timezone.utc)
    file_change = ResolvedUpdateModeChange(
        change_id="chg-1",
        vault_id="vault-main",
        document_id="doc-1",
        file_path="notes/session.md",
        action=UpdateModeAction.UPDATE,
        description="append",
        proposed_content="body",
        unified_diff="diff",
        status=UpdateModeChangeStatus.ACCEPTED,
    )
    entries = [
        _state_op_entry(0, "current_focus", "replace_single", text="new focus"),
        _state_op_entry(1, "agreements", "add_list_item", text="item 1"),
        _state_op_entry(2, "agreements", "remove_list_item", item_key="agreement-99"),
    ]
    entries[0].status = "accepted"
    entries[1].status = "accepted"
    entries[2].status = "rejected"

    return UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id="chat-1",
        campaign_id=str(uuid.uuid4()),
        domain_id="dnd",
        vault_ids=["vault-main"],
        default_vault_id="vault-main",
        candidate_document_ids=[str(uuid.uuid4())],
        note="n",
        changes=[file_change],
        state_patch_operations=entries,
        created_at=now,
        expires_at=now + timedelta(hours=3),
        apply_id=str(uuid.uuid4()),
        apply_started_at=now,
        apply_state="in_progress",
    )


def test_post_apply_state_patch_only(client, monkeypatch) -> None:
    """Apply succeeds when only state patch is accepted (no file changes)."""
    datetime.now(timezone.utc)
    entries = [
        _state_op_entry(0, "current_focus", "replace_single", text="new focus"),
    ]
    entries[0].status = "accepted"
    sess = _make_session_with_state_ops(state_ops=entries)

    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(
            begin_apply=AsyncMock(return_value=sess),
            complete_apply=AsyncMock(),
        ),
    )

    applied_response = CampaignStatePatchResponse(
        applied_state_version=2,
        config_version=1,
        applied_operations=["replace_single"],
        failed_operations=[],
    )

    async def fake_apply_patch(db, campaign_id, request, created_by=None):
        return applied_response

    monkeypatch.setattr(
        "app.services.campaign_state_value_service.campaign_state_value_service",
        SimpleNamespace(
            get_active_state=AsyncMock(return_value=None),
            apply_patch=fake_apply_patch,
        ),
    )

    client.app.state.configure_db(campaign=_make_fake_campaign(config_version=1))

    captured_audit: list = []

    async def fake_audit(*, db, action, entity_type, entity_id, actor, payload):
        captured_audit.append({"action": action, "payload": payload})

    monkeypatch.setattr("app.api.update_mode._write_audit_log", fake_audit)

    resp = client.post("/api/chats/chat-1/update-mode/apply", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state_patch_result"] is not None
    assert body["state_patch_result"]["applied_state_version"] == 2
    assert body["state_patch_result"]["applied_op_indexes"] == [0]
    assert body["results"] == []

    actions = [a["action"] for a in captured_audit]
    assert "update_mode.apply" in actions


def test_post_apply_audit_log_includes_rejected_state_ops(client, monkeypatch) -> None:
    sess = _build_session_for_apply()
    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(
            begin_apply=AsyncMock(return_value=sess),
            complete_apply=AsyncMock(),
        ),
    )

    applied_response = CampaignStatePatchResponse(
        applied_state_version=2,
        config_version=1,
        applied_operations=["replace_single", "add_list_item"],
        failed_operations=[],
    )

    async def fake_apply_patch(db, campaign_id, request, created_by=None):
        return applied_response

    monkeypatch.setattr(
        "app.services.campaign_state_value_service.campaign_state_value_service",
        SimpleNamespace(
            get_active_state=AsyncMock(return_value=None),
            apply_patch=fake_apply_patch,
        ),
    )

    client.app.state.configure_db(campaign=_make_fake_campaign(config_version=1))

    # mock indexer client to avoid HTTP errors
    indexer_apply_result = SimpleNamespace(
        apply_id=sess.apply_id,
        results=[],
    )
    monkeypatch.setattr(
        "app.api.update_mode.indexer_client",
        SimpleNamespace(apply=AsyncMock(return_value=indexer_apply_result)),
    )

    captured_audit: list = []

    async def fake_audit(*, db, action, entity_type, entity_id, actor, payload):
        captured_audit.append({"action": action, "payload": payload})

    monkeypatch.setattr("app.api.update_mode._write_audit_log", fake_audit)

    resp = client.post("/api/chats/chat-1/update-mode/apply", json={})
    assert resp.status_code == 200

    actions = [a["action"] for a in captured_audit]
    assert "update_mode.apply" in actions
    assert "update_mode.reject_state_patch" in actions

    apply_payload = next(a for a in captured_audit if a["action"] == "update_mode.apply")["payload"]
    sp = apply_payload["state_patch"]
    assert sp["accepted_op_indexes"] == [0, 1]
    assert sp["rejected_op_indexes"] == [2]

    reject_payload = next(a for a in captured_audit if a["action"] == "update_mode.reject_state_patch")["payload"]
    assert reject_payload["rejected_op_indexes"] == [2]
    assert len(reject_payload["ops"]) == 1


def test_post_apply_state_patch_conflict_does_not_break_apply(client, monkeypatch) -> None:
    entries = [
        _state_op_entry(0, "current_focus", "replace_single", text="new"),
    ]
    entries[0].status = "accepted"
    sess = _make_session_with_state_ops(state_ops=entries)

    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(
            begin_apply=AsyncMock(return_value=sess),
            complete_apply=AsyncMock(),
        ),
    )

    # Simulate ConfigVersionConflictError on state patch apply
    from app.services.campaign_state_value_service import ConfigVersionConflictError

    async def fake_apply_patch(db, campaign_id, request, created_by=None):
        raise ConfigVersionConflictError("mismatch")

    monkeypatch.setattr(
        "app.services.campaign_state_value_service.campaign_state_value_service",
        SimpleNamespace(
            get_active_state=AsyncMock(return_value=None),
            apply_patch=fake_apply_patch,
        ),
    )

    client.app.state.configure_db(campaign=_make_fake_campaign(config_version=1))

    captured_audit: list = []

    async def fake_audit(*, db, action, entity_type, entity_id, actor, payload):
        captured_audit.append({"action": action, "payload": payload})

    monkeypatch.setattr("app.api.update_mode._write_audit_log", fake_audit)

    resp = client.post("/api/chats/chat-1/update-mode/apply", json={})
    # 200 — file changes also not accepted here, but no exception raised.
    assert resp.status_code == 200
    body = resp.json()
    assert body["state_patch_result"] is not None
    assert body["state_patch_result"]["applied_op_indexes"] == []
    assert body["state_patch_result"]["failed_op_indexes"] == [0]


def test_post_apply_rejects_when_nothing_accepted(client, monkeypatch) -> None:
    sess = _make_session_with_state_ops()
    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(
            begin_apply=AsyncMock(return_value=sess),
            complete_apply=AsyncMock(),
        ),
    )

    resp = client.post("/api/chats/chat-1/update-mode/apply", json={})
    assert resp.status_code == 422
    assert "No accepted changes" in resp.json()["detail"]


def test_post_apply_uses_edited_text_in_state_patch(client, monkeypatch) -> None:
    sess = _build_session_for_apply()
    # edit text on op_index=0 (replace_single)
    sess.state_patch_operations[0].edited_text = "edited by user"

    monkeypatch.setattr(
        "app.api.update_mode.update_mode_store",
        SimpleNamespace(
            begin_apply=AsyncMock(return_value=sess),
            complete_apply=AsyncMock(),
        ),
    )

    captured_request: dict = {}

    async def fake_apply_patch(db, campaign_id, request, created_by=None):
        captured_request["request"] = request
        return CampaignStatePatchResponse(
            applied_state_version=2,
            config_version=1,
            applied_operations=["replace_single", "add_list_item"],
            failed_operations=[],
        )

    monkeypatch.setattr(
        "app.services.campaign_state_value_service.campaign_state_value_service",
        SimpleNamespace(
            get_active_state=AsyncMock(return_value=None),
            apply_patch=fake_apply_patch,
        ),
    )

    client.app.state.configure_db(campaign=_make_fake_campaign(config_version=1))

    monkeypatch.setattr(
        "app.api.update_mode.indexer_client",
        SimpleNamespace(
            apply=AsyncMock(
                return_value=SimpleNamespace(
                    apply_id=sess.apply_id, results=[]
                )
            )
        ),
    )

    async def fake_audit(*, db, action, entity_type, entity_id, actor, payload):
        return None

    monkeypatch.setattr("app.api.update_mode._write_audit_log", fake_audit)

    resp = client.post("/api/chats/chat-1/update-mode/apply", json={})
    assert resp.status_code == 200

    request = captured_request["request"]
    # replace_single op (op_index 0) should have text="edited by user"
    replace_op = next(op for op in request.operations if op.field_key == "current_focus")
    assert replace_op.text == "edited by user"


# ---------------------------------------------------------------------------
# UpdateModeGenerationResult DTO
# ---------------------------------------------------------------------------


def test_generation_result_default_state_patch_empty() -> None:
    intent = UpdateModeIntent(
        change_id="chg-1",
        action=UpdateModeAction.UPDATE,
        description="x",
        document_id="doc-1",
        operation=UpdateModeOperation.APPEND_AFTER_SECTION,
        anchor={"kind": "markdown_heading", "value": "h"},
        content="body",
    )
    result = UpdateModeGenerationResult(intents=[intent], no_change_reason=None)
    assert result.state_patch == []
    assert result.state_patch_questions == []


def test_generation_result_with_state_patch() -> None:
    intent = UpdateModeIntent(
        change_id="chg-1",
        action=UpdateModeAction.UPDATE,
        description="x",
        document_id="doc-1",
        operation=UpdateModeOperation.APPEND_AFTER_SECTION,
        anchor={"kind": "markdown_heading", "value": "h"},
        content="body",
    )
    sp = _make_replace_single(field_key="current_focus", text="new")
    result = UpdateModeGenerationResult(
        intents=[intent],
        no_change_reason=None,
        state_patch=[sp],
        state_patch_questions=["Need to confirm"],
    )
    assert len(result.state_patch) == 1
    assert result.state_patch_questions == ["Need to confirm"]


def test_generation_result_no_change_with_state_patch_only() -> None:
    sp = _make_replace_single(field_key="current_focus", text="new")
    result = UpdateModeGenerationResult(
        intents=[],
        no_change_reason="no file changes",
        state_patch=[sp],
    )
    assert result.state_patch == [sp]