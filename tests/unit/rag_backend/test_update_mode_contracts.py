"""Unit tests for Campaign Update Mode shared_contracts DTO validation.

No I/O required: pure Pydantic validation tests.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared_contracts.models import (
    ApplyUpdateModeResponse,
    ResolvedUpdateModeChange,
    StartUpdateModeRequest,
    UpdateModeAction,
    UpdateModeAnchor,
    UpdateModeApplyChange,
    UpdateModeApplyRequest,
    UpdateModeChangeStatus,
    UpdateModeIntent,
    UpdateModeIntentBatch,
    UpdateModeOperation,
    UpdateModeResolveRequest,
    UpdateModeReviewRequest,
    UpdateModeSession,
    UpdateModeVaultApplyResult,
    UpdateModeVaultApplyStatus,
)
from datetime import datetime, timedelta, timezone
import uuid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_update_intent(
    change_id: str = "ch-1",
    document_id: str = "doc-abc",
    operation: UpdateModeOperation = UpdateModeOperation.APPEND_TO_FILE,
    anchor: UpdateModeAnchor | None = None,
    content: str = "New paragraph.",
) -> UpdateModeIntent:
    return UpdateModeIntent(
        change_id=change_id,
        action=UpdateModeAction.UPDATE,
        description="Add new paragraph",
        document_id=document_id,
        operation=operation,
        anchor=anchor,
        content=content,
    )


def _make_create_intent(
    change_id: str = "ch-new",
    filename: str = "new_file.md",
    content: str = "# New document",
) -> UpdateModeIntent:
    return UpdateModeIntent(
        change_id=change_id,
        action=UpdateModeAction.CREATE,
        description="Create new document",
        operation=UpdateModeOperation.CREATE_FILE,
        suggested_filename=filename,
        content=content,
    )


# ---------------------------------------------------------------------------
# UpdateModeIntent — action=UPDATE
# ---------------------------------------------------------------------------


class TestUpdateModeIntentUpdate:
    def test_append_to_file_valid(self) -> None:
        intent = _make_update_intent(operation=UpdateModeOperation.APPEND_TO_FILE)
        assert intent.action == UpdateModeAction.UPDATE
        assert intent.anchor is None

    def test_append_after_section_requires_markdown_heading_anchor(self) -> None:
        anchor = UpdateModeAnchor(kind="markdown_heading", value="## Combat")
        intent = _make_update_intent(
            operation=UpdateModeOperation.APPEND_AFTER_SECTION,
            anchor=anchor,
        )
        assert intent.anchor is not None

    def test_append_after_section_wrong_anchor_kind_raises(self) -> None:
        anchor = UpdateModeAnchor(kind="exact_text", value="some text")
        with pytest.raises(ValidationError, match="markdown_heading"):
            _make_update_intent(
                operation=UpdateModeOperation.APPEND_AFTER_SECTION,
                anchor=anchor,
            )

    def test_replace_unique_text_requires_exact_text_anchor(self) -> None:
        anchor = UpdateModeAnchor(kind="exact_text", value="old paragraph")
        intent = _make_update_intent(
            operation=UpdateModeOperation.REPLACE_UNIQUE_TEXT,
            anchor=anchor,
        )
        assert intent.anchor.kind == "exact_text"

    def test_replace_unique_text_wrong_anchor_raises(self) -> None:
        anchor = UpdateModeAnchor(kind="markdown_heading", value="## Section")
        with pytest.raises(ValidationError, match="exact_text"):
            _make_update_intent(
                operation=UpdateModeOperation.REPLACE_UNIQUE_TEXT,
                anchor=anchor,
            )

    def test_append_to_file_with_anchor_raises(self) -> None:
        anchor = UpdateModeAnchor(kind="exact_text", value="something")
        with pytest.raises(ValidationError, match="must not have anchor"):
            _make_update_intent(
                operation=UpdateModeOperation.APPEND_TO_FILE,
                anchor=anchor,
            )

    def test_update_without_document_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="document_id"):
            UpdateModeIntent(
                change_id="ch-x",
                action=UpdateModeAction.UPDATE,
                description="missing doc_id",
                operation=UpdateModeOperation.APPEND_TO_FILE,
                content="text",
            )

    def test_update_with_create_file_operation_raises(self) -> None:
        with pytest.raises(ValidationError):
            UpdateModeIntent(
                change_id="ch-x",
                action=UpdateModeAction.UPDATE,
                description="wrong op",
                document_id="doc-1",
                operation=UpdateModeOperation.CREATE_FILE,
                content="text",
            )

    def test_update_with_suggested_filename_raises(self) -> None:
        with pytest.raises(ValidationError, match="suggested_filename"):
            UpdateModeIntent(
                change_id="ch-x",
                action=UpdateModeAction.UPDATE,
                description="wrong",
                document_id="doc-1",
                operation=UpdateModeOperation.APPEND_TO_FILE,
                suggested_filename="foo.md",
                content="text",
            )


# ---------------------------------------------------------------------------
# UpdateModeIntent — action=CREATE
# ---------------------------------------------------------------------------


class TestUpdateModeIntentCreate:
    def test_create_valid(self) -> None:
        intent = _make_create_intent()
        assert intent.action == UpdateModeAction.CREATE
        assert intent.document_id is None

    def test_create_without_suggested_filename_raises(self) -> None:
        with pytest.raises(ValidationError, match="suggested_filename"):
            UpdateModeIntent(
                change_id="ch-x",
                action=UpdateModeAction.CREATE,
                description="create",
                operation=UpdateModeOperation.CREATE_FILE,
                content="body",
            )

    def test_create_with_document_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="document_id"):
            UpdateModeIntent(
                change_id="ch-x",
                action=UpdateModeAction.CREATE,
                description="bad",
                document_id="doc-1",
                operation=UpdateModeOperation.CREATE_FILE,
                suggested_filename="f.md",
                content="body",
            )

    def test_create_with_non_create_operation_raises(self) -> None:
        with pytest.raises(ValidationError, match="create_file"):
            UpdateModeIntent(
                change_id="ch-x",
                action=UpdateModeAction.CREATE,
                description="bad op",
                operation=UpdateModeOperation.APPEND_TO_FILE,
                suggested_filename="f.md",
                content="body",
            )

    def test_create_with_anchor_raises(self) -> None:
        with pytest.raises(ValidationError, match="anchor"):
            UpdateModeIntent(
                change_id="ch-x",
                action=UpdateModeAction.CREATE,
                description="bad",
                operation=UpdateModeOperation.CREATE_FILE,
                anchor=UpdateModeAnchor(kind="exact_text", value="x"),
                suggested_filename="f.md",
                content="body",
            )


# ---------------------------------------------------------------------------
# UpdateModeIntentBatch
# ---------------------------------------------------------------------------


def test_intent_batch_valid() -> None:
    batch = UpdateModeIntentBatch(
        intents=[_make_create_intent("c1"), _make_update_intent("u1")]
    )
    assert len(batch.intents) == 2


def test_intent_batch_empty_raises() -> None:
    with pytest.raises(ValidationError):
        UpdateModeIntentBatch(intents=[])


def test_intent_batch_duplicate_change_ids_raises() -> None:
    with pytest.raises(ValidationError, match="unique"):
        UpdateModeIntentBatch(
            intents=[_make_update_intent("dup"), _make_update_intent("dup")]
        )


# ---------------------------------------------------------------------------
# UpdateModeResolveRequest
# ---------------------------------------------------------------------------


def test_resolve_request_default_vault_must_be_in_vault_ids() -> None:
    with pytest.raises(ValidationError, match="default_vault_id"):
        UpdateModeResolveRequest(
            chat_id="c",
            campaign_id="camp",
            domain_id="dom",
            vault_ids=["v1"],
            intents=[_make_create_intent()],
            default_vault_id="v-not-in-list",
        )


def test_resolve_request_valid() -> None:
    req = UpdateModeResolveRequest(
        chat_id="c",
        campaign_id="camp",
        domain_id="dom",
        vault_ids=["v1", "v2"],
        intents=[_make_create_intent()],
        default_vault_id="v1",
    )
    assert req.default_vault_id == "v1"


# ---------------------------------------------------------------------------
# UpdateModeApplyChange
# ---------------------------------------------------------------------------


def test_apply_change_update_requires_sha() -> None:
    with pytest.raises(ValidationError, match="expected_sha256"):
        UpdateModeApplyChange(
            change_id="ch-1",
            vault_id="v1",
            file_path="notes/session1.md",
            action=UpdateModeAction.UPDATE,
            proposed_content="text",
            expected_sha256=None,
        )


def test_apply_change_create_must_not_have_sha() -> None:
    with pytest.raises(ValidationError, match="expected_sha256"):
        UpdateModeApplyChange(
            change_id="ch-1",
            vault_id="v1",
            file_path="new_file.md",
            action=UpdateModeAction.CREATE,
            proposed_content="text",
            expected_sha256="abc123",
        )


def test_apply_change_create_valid() -> None:
    ch = UpdateModeApplyChange(
        change_id="ch-1",
        vault_id="v1",
        file_path="new.md",
        action=UpdateModeAction.CREATE,
        proposed_content="# New",
    )
    assert ch.expected_sha256 is None


# ---------------------------------------------------------------------------
# UpdateModeApplyRequest
# ---------------------------------------------------------------------------


def test_apply_request_duplicate_change_ids_raises() -> None:
    ch = UpdateModeApplyChange(
        change_id="dup",
        vault_id="v1",
        file_path="a.md",
        action=UpdateModeAction.CREATE,
        proposed_content="x",
    )
    ch2 = UpdateModeApplyChange(
        change_id="dup",
        vault_id="v1",
        file_path="b.md",
        action=UpdateModeAction.CREATE,
        proposed_content="y",
    )
    with pytest.raises(ValidationError, match="unique"):
        UpdateModeApplyRequest(
            apply_id="apply-1",
            chat_id="chat-1",
            campaign_id="camp-1",
            accepted_changes=[ch, ch2],
        )


def test_apply_request_duplicate_path_pairs_raises() -> None:
    ch1 = UpdateModeApplyChange(
        change_id="c1",
        vault_id="v1",
        file_path="same.md",
        action=UpdateModeAction.CREATE,
        proposed_content="a",
    )
    ch2 = UpdateModeApplyChange(
        change_id="c2",
        vault_id="v1",
        file_path="same.md",
        action=UpdateModeAction.CREATE,
        proposed_content="b",
    )
    with pytest.raises(ValidationError, match="unique"):
        UpdateModeApplyRequest(
            apply_id="apply-1",
            chat_id="chat-1",
            campaign_id="camp-1",
            accepted_changes=[ch1, ch2],
        )


# ---------------------------------------------------------------------------
# UpdateModeReviewRequest
# ---------------------------------------------------------------------------


def test_review_request_overlap_raises() -> None:
    with pytest.raises(ValidationError, match="both accepted and rejected"):
        UpdateModeReviewRequest(
            accepted_change_ids=["ch-1"],
            rejected_change_ids=["ch-1"],
        )


def test_review_request_empty_raises() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        UpdateModeReviewRequest(
            accepted_change_ids=[],
            rejected_change_ids=[],
        )


def test_review_request_valid() -> None:
    req = UpdateModeReviewRequest(
        accepted_change_ids=["ch-1"],
        rejected_change_ids=["ch-2"],
    )
    assert len(req.accepted_change_ids) == 1


# ---------------------------------------------------------------------------
# StartUpdateModeRequest
# ---------------------------------------------------------------------------


def test_start_request_empty_note_raises() -> None:
    with pytest.raises(ValidationError):
        StartUpdateModeRequest(note="")


def test_start_request_valid() -> None:
    req = StartUpdateModeRequest(note="Add loot table for Session 12.")
    assert req.note.startswith("Add loot")


# ---------------------------------------------------------------------------
# UpdateModeSession round-trip
# ---------------------------------------------------------------------------


def test_session_json_round_trip() -> None:
    now = _now()
    session = UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id="chat-rt",
        campaign_id="camp-rt",
        domain_id="dom-rt",
        vault_ids=["v1"],
        default_vault_id="v1",
        candidate_document_ids=[],
        note="Roundtrip note",
        changes=[
            ResolvedUpdateModeChange(
                change_id="c1",
                action=UpdateModeAction.CREATE,
                description="desc",
                vault_id="v1",
                file_path="new.md",
                proposed_content="# new",
                status=UpdateModeChangeStatus.PENDING,
            )
        ],
        created_at=now,
        expires_at=now + timedelta(hours=3),
    )
    restored = UpdateModeSession.model_validate_json(session.model_dump_json())
    assert restored.chat_id == session.chat_id
    assert restored.changes[0].status == UpdateModeChangeStatus.PENDING


# ---------------------------------------------------------------------------
# Enum completeness smoke tests
# ---------------------------------------------------------------------------


def test_all_action_values() -> None:
    assert set(UpdateModeAction) == {UpdateModeAction.UPDATE, UpdateModeAction.CREATE}


def test_all_operation_values() -> None:
    ops = set(UpdateModeOperation)
    assert UpdateModeOperation.CREATE_FILE in ops
    assert UpdateModeOperation.APPEND_AFTER_SECTION in ops
    assert UpdateModeOperation.REPLACE_UNIQUE_TEXT in ops
    assert UpdateModeOperation.APPEND_TO_FILE in ops


def test_all_change_status_values() -> None:
    statuses = set(UpdateModeChangeStatus)
    assert UpdateModeChangeStatus.PENDING in statuses
    assert UpdateModeChangeStatus.ACCEPTED in statuses
    assert UpdateModeChangeStatus.REJECTED in statuses
    assert UpdateModeChangeStatus.RESOLUTION_FAILED in statuses
