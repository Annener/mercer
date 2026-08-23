"""Tests for Campaign State — Stage 3 contract validation.

Covers Pydantic validation of:
  - DocumentSnapshot (content_sha 32 hex chars)
  - CampaignStateInitialFieldStatus (clarification_question required when needs_clarification)
  - CampaignStateInitialProposalField
  - CampaignStateInitialProposal (fields + questions)
  - CampaignStateInitialProposalRead (proposal_id, campaign_id, config_version, snapshot, warnings, expires_at)
  - CampaignStateInitialPreviewRequest (document_ids min/max)
  - CampaignStateInitialApplyRequest (proposal_id, config_version >= 1)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared_contracts.models import (
    CampaignStateInitialApplyRequest,
    CampaignStateInitialFieldStatus,
    CampaignStateInitialListItem,
    CampaignStateInitialListValue,
    CampaignStateInitialPreviewRequest,
    CampaignStateInitialProposal,
    CampaignStateInitialProposalField,
    CampaignStateInitialProposalRead,
    CampaignStateInitialSingleValue,
    DocumentSnapshot,
)


# ---------------------------------------------------------------------------
# DocumentSnapshot
# ---------------------------------------------------------------------------


def test_document_snapshot_accepts_32_hex_sha() -> None:
    snap = DocumentSnapshot(
        document_id="11111111-1111-1111-1111-111111111111",
        vault_id="dnd-vault",
        source_path="session-14.md",
        title="Session 14",
        content_sha="a" * 32,
        estimated_tokens=1234,
    )
    assert snap.content_sha == "a" * 32
    assert snap.estimated_tokens == 1234


def test_document_snapshot_rejects_short_sha() -> None:
    with pytest.raises(ValidationError):
        DocumentSnapshot(
            document_id="11111111-1111-1111-1111-111111111111",
            vault_id="dnd-vault",
            source_path="session-14.md",
            content_sha="a" * 31,  # один символ короткий
            estimated_tokens=1234,
        )


def test_document_snapshot_rejects_long_sha() -> None:
    with pytest.raises(ValidationError):
        DocumentSnapshot(
            document_id="11111111-1111-1111-1111-111111111111",
            vault_id="dnd-vault",
            source_path="session-14.md",
            content_sha="a" * 33,
            estimated_tokens=1234,
        )


# ---------------------------------------------------------------------------
# CampaignStateInitialFieldStatus
# ---------------------------------------------------------------------------


def test_field_status_proposed_no_question_required() -> None:
    s = CampaignStateInitialFieldStatus(status="proposed")
    assert s.clarification_question is None


def test_field_status_empty_no_question_required() -> None:
    s = CampaignStateInitialFieldStatus(status="empty")
    assert s.clarification_question is None


def test_field_status_needs_clarification_requires_question() -> None:
    s = CampaignStateInitialFieldStatus(
        status="needs_clarification",
        clarification_question="Какой именно NPC?",
    )
    assert s.clarification_question == "Какой именно NPC?"


def test_field_status_needs_clarification_without_question_raises() -> None:
    with pytest.raises(ValidationError) as exc:
        CampaignStateInitialFieldStatus(status="needs_clarification")
    assert "clarification_question" in str(exc.value)


def test_field_status_needs_clarification_empty_question_raises() -> None:
    with pytest.raises(ValidationError):
        CampaignStateInitialFieldStatus(
            status="needs_clarification",
            clarification_question="   ",
        )


def test_field_status_invalid_value_raises() -> None:
    with pytest.raises(ValidationError):
        CampaignStateInitialFieldStatus(status="unknown")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CampaignStateInitialProposal / ProposalField
# ---------------------------------------------------------------------------


def test_proposal_field_single_proposed() -> None:
    pf = CampaignStateInitialProposalField(
        field_key="current_focus",
        mode="single",
        status=CampaignStateInitialFieldStatus(status="proposed"),
        single_value=CampaignStateInitialSingleValue(
            text="Спроектировать Campaign State MVP",
            source_refs=["file:11111111-1111-1111-1111-111111111111:sha:" + "a" * 32],
        ),
    )
    assert pf.mode == "single"
    assert pf.single_value is not None
    assert pf.list_value is None


def test_proposal_field_list_proposed() -> None:
    pf = CampaignStateInitialProposalField(
        field_key="agreements",
        mode="list",
        status=CampaignStateInitialFieldStatus(status="proposed"),
        list_value=CampaignStateInitialListValue(
            items=[
                CampaignStateInitialListItem(
                    text="Campaign State изменяется через review.",
                ),
                CampaignStateInitialListItem(
                    text="PDF не участвует в initial state.",
                ),
            ],
        ),
    )
    assert pf.mode == "list"
    assert pf.single_value is None
    assert pf.list_value is not None
    assert len(pf.list_value.items) == 2


def test_proposal_default_questions_empty() -> None:
    p = CampaignStateInitialProposal(fields=[])
    assert p.fields == []
    assert p.questions == []


def test_proposal_questions_preserved() -> None:
    p = CampaignStateInitialProposal(
        fields=[],
        questions=["Какая система правил?", "Где происходят события?"],
    )
    assert len(p.questions) == 2


# ---------------------------------------------------------------------------
# CampaignStateInitialProposalRead
# ---------------------------------------------------------------------------


def test_proposal_read_round_trip_serialization() -> None:
    import datetime as _dt

    snap = DocumentSnapshot(
        document_id="11111111-1111-1111-1111-111111111111",
        vault_id="dnd-vault",
        source_path="session-14.md",
        content_sha="b" * 32,
        estimated_tokens=500,
    )
    pf = CampaignStateInitialProposalField(
        field_key="current_focus",
        mode="single",
        status=CampaignStateInitialFieldStatus(status="empty"),
    )
    proposal = CampaignStateInitialProposal(fields=[pf], questions=["Q?"])
    now = _dt.datetime(2026, 8, 22, 12, 0, 0, tzinfo=_dt.timezone.utc)
    read = CampaignStateInitialProposalRead(
        proposal_id="abc-123",
        campaign_id="22222222-2222-2222-2222-222222222222",
        config_version=3,
        source_snapshot=[snap],
        proposal=proposal,
        warnings=["warn1"],
        created_at=now,
        expires_at=now + _dt.timedelta(hours=3),
    )
    j = read.model_dump_json()
    read2 = CampaignStateInitialProposalRead.model_validate_json(j)
    assert read2.proposal_id == read.proposal_id
    assert read2.config_version == 3
    assert len(read2.source_snapshot) == 1
    assert read2.source_snapshot[0].document_id == snap.document_id
    assert read2.warnings == ["warn1"]


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------


def test_preview_request_empty_list_raises() -> None:
    with pytest.raises(ValidationError):
        CampaignStateInitialPreviewRequest(document_ids=[])


def test_preview_request_max_50_ids_ok() -> None:
    ids = [f"11111111-1111-1111-1111-{i:012d}" for i in range(50)]
    req = CampaignStateInitialPreviewRequest(document_ids=ids)
    assert len(req.document_ids) == 50


def test_preview_request_more_than_50_ids_raises() -> None:
    ids = [f"11111111-1111-1111-1111-{i:012d}" for i in range(51)]
    with pytest.raises(ValidationError):
        CampaignStateInitialPreviewRequest(document_ids=ids)


def test_apply_request_requires_positive_config_version() -> None:
    with pytest.raises(ValidationError):
        CampaignStateInitialApplyRequest(proposal_id="x", config_version=0)


def test_apply_request_minimal_valid() -> None:
    req = CampaignStateInitialApplyRequest(proposal_id="abc", config_version=1)
    assert req.proposal_id == "abc"
    assert req.config_version == 1


def test_apply_request_proposal_id_required() -> None:
    with pytest.raises(ValidationError):
        CampaignStateInitialApplyRequest(proposal_id="", config_version=1)
