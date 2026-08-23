"""Sprint 3 — ContextUpdateProposal DTO contract tests.

Covers:
  - ContextFieldChange (operation enum, key regex, lengths)
  - ContextUpdateProposal (cross-section validation)
  - UpdateModeStateFieldChangeEntry + Decisions
  - UpdateModeSession serialises new state_field_change_operations field
  - UpdateModeReviewRequest accepts optional field_change_decisions
"""
from __future__ import annotations

import pytest

from shared_contracts.models import (
    ContextFieldChange,
    ContextFieldChangeOperation,
    ContextUpdateProposal,
    UpdateModeReviewRequest,
    UpdateModeSession,
    UpdateModeStateFieldChangeDecisions,
    UpdateModeStateFieldChangeEntry,
)


# ---------------------------------------------------------------------------
# ContextFieldChange
# ---------------------------------------------------------------------------


def test_context_field_change_create_minimal():
    fc = ContextFieldChange(
        operation=ContextFieldChangeOperation.CREATE_FIELD,
        key="main_villains",
        label="Главные злодеи",
        mode="list",
    )
    assert fc.key == "main_villains"
    assert fc.label == "Главные злодеи"
    assert fc.mode == "list"
    assert fc.enabled is True
    assert fc.display_order == 1000
    assert fc.description == ""


def test_context_field_change_key_must_be_snake_case():
    """key must match ^[a-z][a-z0-9_]*$ — uppercase and starting digit are rejected."""
    with pytest.raises(Exception):
        ContextFieldChange(
            operation=ContextFieldChangeOperation.CREATE_FIELD,
            key="MainVillains",
            label="x",
            mode="single",
        )
    with pytest.raises(Exception):
        ContextFieldChange(
            operation=ContextFieldChangeOperation.CREATE_FIELD,
            key="1main",
            label="x",
            mode="single",
        )


def test_context_field_change_key_accepts_snake_and_digits():
    fc = ContextFieldChange(
        operation=ContextFieldChangeOperation.CREATE_FIELD,
        key="npc_42",
        label="x",
        mode="list",
    )
    assert fc.key == "npc_42"


def test_context_field_change_label_length_bounds():
    with pytest.raises(Exception):
        ContextFieldChange(
            operation=ContextFieldChangeOperation.CREATE_FIELD,
            key="x",
            label="",  # min_length=1
            mode="single",
        )
    with pytest.raises(Exception):
        ContextFieldChange(
            operation=ContextFieldChangeOperation.CREATE_FIELD,
            key="x",
            label="a" * 257,  # max_length=256
            mode="single",
        )


# ---------------------------------------------------------------------------
# ContextUpdateProposal
# ---------------------------------------------------------------------------


def test_proposal_defaults_to_empty():
    p = ContextUpdateProposal(confidence=0.7, reason="x")
    assert p.field_changes == []
    assert p.state_patch == []
    assert p.file_changes == []
    assert p.source_message_ids == []
    assert p.review_summary == ""


def test_proposal_serialises_to_json():
    p = ContextUpdateProposal(
        field_changes=[
            ContextFieldChange(
                operation=ContextFieldChangeOperation.CREATE_FIELD,
                key="k",
                label="K",
                mode="single",
            )
        ],
        confidence=0.5,
        reason="test",
    )
    data = p.model_dump_json()
    assert '"operation":"create_field"' in data
    assert '"key":"k"' in data


def test_proposal_rejects_duplicate_create_keys():
    """Two create_field ops with the same key is a logic error."""
    with pytest.raises(Exception):
        ContextUpdateProposal(
            field_changes=[
                ContextFieldChange(
                    operation=ContextFieldChangeOperation.CREATE_FIELD,
                    key="dup",
                    label="a",
                    mode="single",
                ),
                ContextFieldChange(
                    operation=ContextFieldChangeOperation.CREATE_FIELD,
                    key="dup",
                    label="b",
                    mode="list",
                ),
            ],
            confidence=0.5,
            reason="x",
        )


def test_proposal_confidence_bounds():
    with pytest.raises(Exception):
        ContextUpdateProposal(confidence=-0.1, reason="x")
    with pytest.raises(Exception):
        ContextUpdateProposal(confidence=1.1, reason="x")
    # Boundaries accepted
    ContextUpdateProposal(confidence=0.0, reason="x")
    ContextUpdateProposal(confidence=1.0, reason="x")


def test_proposal_no_delete_in_sprint_3():
    """delete_field is intentionally absent in Sprint 3. Verify by trying
    to construct one — pydantic will reject unknown enum values."""
    with pytest.raises(Exception):
        ContextFieldChange(
            operation="delete_field",  # type: ignore[arg-type]
            key="x",
            label="x",
            mode="single",
        )


# ---------------------------------------------------------------------------
# UpdateModeStateFieldChangeEntry
# ---------------------------------------------------------------------------


def test_state_field_change_entry_defaults():
    e = UpdateModeStateFieldChangeEntry(
        op_index=0,
        operation=ContextFieldChangeOperation.CREATE_FIELD,
        key="k",
    )
    assert e.status == "pending"
    assert e.proposed_label is None
    assert e.previous_label is None


# ---------------------------------------------------------------------------
# UpdateModeStateFieldChangeDecisions
# ---------------------------------------------------------------------------


def test_field_change_decisions_empty_lists_ok():
    d = UpdateModeStateFieldChangeDecisions(
        accepted_op_indexes=[], rejected_op_indexes=[]
    )
    assert d.accepted_op_indexes == []


def test_field_change_decisions_no_overlap():
    with pytest.raises(Exception):
        UpdateModeStateFieldChangeDecisions(
            accepted_op_indexes=[0, 1],
            rejected_op_indexes=[1, 2],
        )


def test_field_change_decisions_distinct_indexes_ok():
    UpdateModeStateFieldChangeDecisions(
        accepted_op_indexes=[0, 1],
        rejected_op_indexes=[2, 3],
    )


# ---------------------------------------------------------------------------
# UpdateModeSession round-trips new field
# ---------------------------------------------------------------------------


def test_session_round_trips_field_change_operations():
    from datetime import datetime, timedelta, timezone

    from shared_contracts.models import ResolvedUpdateModeChange

    now = datetime.now(timezone.utc)
    s = UpdateModeSession(
        session_id="sid",
        chat_id="cid",
        campaign_id="camp",
        domain_id="dnd",
        vault_ids=["v1"],
        default_vault_id="v1",
        candidate_document_ids=[],
        note="x",
        created_at=now,
        expires_at=now + timedelta(hours=3),
        changes=[],
        state_field_change_operations=[
            UpdateModeStateFieldChangeEntry(
                op_index=0,
                operation=ContextFieldChangeOperation.CREATE_FIELD,
                key="k",
                proposed_label="K",
                proposed_mode="list",
            )
        ],
    )
    data = s.model_dump(mode="json")
    assert len(data["state_field_change_operations"]) == 1
    assert data["state_field_change_operations"][0]["key"] == "k"


def test_session_defaults_field_change_operations_to_empty_list():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    s = UpdateModeSession(
        session_id="sid",
        chat_id="cid",
        campaign_id="camp",
        domain_id="dnd",
        vault_ids=["v1"],
        default_vault_id="v1",
        candidate_document_ids=[],
        note="x",
        created_at=now,
        expires_at=now + timedelta(hours=3),
        changes=[],
    )
    assert s.state_field_change_operations == []


# ---------------------------------------------------------------------------
# UpdateModeReviewRequest — accepts new optional field
# ---------------------------------------------------------------------------


def test_review_request_without_field_change_decisions_still_works():
    """Backwards-compat: старые клиенты не передают field_change_decisions."""
    req = UpdateModeReviewRequest(
        accepted_change_ids=["chg-1"],
        rejected_change_ids=[],
    )
    assert req.field_change_decisions is None
    assert req.state_patch_decisions is None


def test_review_request_with_field_change_decisions():
    req = UpdateModeReviewRequest(
        accepted_change_ids=[],
        rejected_change_ids=[],
        field_change_decisions=UpdateModeStateFieldChangeDecisions(
            accepted_op_indexes=[0],
            rejected_op_indexes=[],
        ),
    )
    assert req.field_change_decisions is not None
    assert req.field_change_decisions.accepted_op_indexes == [0]


def test_review_request_empty_without_anything_raises():
    """Validator: must have at least one accept/reject somewhere."""
    with pytest.raises(Exception):
        UpdateModeReviewRequest()


def test_review_request_field_change_only_is_enough():
    """field_change_decisions alone is sufficient (file/state могут быть пустыми)."""
    req = UpdateModeReviewRequest(
        accepted_change_ids=[],
        rejected_change_ids=[],
        field_change_decisions=UpdateModeStateFieldChangeDecisions(
            accepted_op_indexes=[0],
        ),
    )
    assert req.field_change_decisions is not None