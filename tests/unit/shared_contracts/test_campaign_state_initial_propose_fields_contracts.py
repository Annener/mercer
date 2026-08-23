"""Tests for Stage 3.v2 (propose_fields) Pydantic contracts.

Covers:
  - CampaignStateSuggestedFieldConfig — Pydantic валидации (key regex, mode/value,
    needs_clarification).
  - CampaignStateInitialProposalV2 — fields + suggested_fields + questions.
  - CampaignStateInitialProposalReadV2 — round-trip JSON сериализация.
  - CampaignStateInitialPreviewRequestV2 — propose_fields/max_suggested_fields.
  - CampaignStateInitialApplyRequestV2 — accepted/rejected keys (backward-compat).
"""
from __future__ import annotations

import datetime as _dt

import pytest
from pydantic import ValidationError

from shared_contracts.models import (
    CampaignStateInitialApplyRequestV2,
    CampaignStateInitialFieldStatus,
    CampaignStateInitialListItem,
    CampaignStateInitialListValue,
    CampaignStateInitialPreviewRequestV2,
    CampaignStateInitialProposal,
    CampaignStateInitialProposalField,
    CampaignStateInitialProposalRead,
    CampaignStateInitialProposalReadV2,
    CampaignStateInitialProposalV2,
    CampaignStateInitialSingleValue,
    CampaignStateSuggestedFieldConfig,
    DocumentSnapshot,
)

# ---------------------------------------------------------------------------
# CampaignStateSuggestedFieldConfig
# ---------------------------------------------------------------------------


def test_suggested_field_single_proposed():
    sf = CampaignStateSuggestedFieldConfig(
        key="character_goals",
        label="Цели персонажа",
        description="Краткосрочные и долгосрочные цели.",
        mode="single",
        initial_status="proposed",
        single_value=CampaignStateInitialSingleValue(
            text="Найти артефакт",
        ),
    )
    assert sf.key == "character_goals"
    assert sf.mode == "single"
    assert sf.single_value.text == "Найти артефакт"
    assert sf.list_value is None


def test_suggested_field_list_proposed():
    sf = CampaignStateSuggestedFieldConfig(
        key="npcs",
        label="NPC",
        mode="list",
        initial_status="proposed",
        list_value=CampaignStateInitialListValue(
            items=[
                CampaignStateInitialListItem(text="Ворон"),
                CampaignStateInitialListItem(text="Изур"),
            ],
        ),
    )
    assert sf.list_value is not None
    assert len(sf.list_value.items) == 2
    assert sf.single_value is None


def test_suggested_field_needs_clarification():
    sf = CampaignStateSuggestedFieldConfig(
        key="unknown_thing",
        label="Что-то",
        mode="single",
        initial_status="needs_clarification",
        clarification_question="Какой именно аспект?",
    )
    assert sf.clarification_question is not None


def test_suggested_field_needs_clarification_missing_question_raises():
    with pytest.raises(ValidationError) as exc:
        CampaignStateSuggestedFieldConfig(
            key="x",
            label="X",
            mode="single",
            initial_status="needs_clarification",
        )
    assert "clarification_question" in str(exc.value)


def test_suggested_field_proposed_single_missing_value_raises():
    with pytest.raises(ValidationError) as exc:
        CampaignStateSuggestedFieldConfig(
            key="x",
            label="X",
            mode="single",
            initial_status="proposed",
        )
    assert "single_value" in str(exc.value)


def test_suggested_field_proposed_list_missing_value_raises():
    with pytest.raises(ValidationError) as exc:
        CampaignStateSuggestedFieldConfig(
            key="npcs",
            label="NPC",
            mode="list",
            initial_status="proposed",
        )
    assert "list_value" in str(exc.value)


def test_suggested_field_invalid_key_pattern_raises():
    with pytest.raises(ValidationError) as exc:
        CampaignStateSuggestedFieldConfig(
            key="Bad-Key!",
            label="X",
            mode="single",
            initial_status="empty",
        )
    # Либо "pattern", либо "String should match pattern"
    msg = str(exc.value).lower()
    assert "pattern" in msg


def test_suggested_field_key_too_long_raises():
    with pytest.raises(ValidationError):
        CampaignStateSuggestedFieldConfig(
            key="a" * 65,
            label="X",
            mode="single",
            initial_status="empty",
        )


def test_suggested_field_invalid_mode_raises():
    with pytest.raises(ValidationError):
        CampaignStateSuggestedFieldConfig(
            key="x",
            label="X",
            mode="unknown",  # type: ignore[arg-type]
            initial_status="empty",
        )


def test_suggested_field_invalid_initial_status_raises():
    with pytest.raises(ValidationError):
        CampaignStateSuggestedFieldConfig(
            key="x",
            label="X",
            mode="single",
            initial_status="unknown",  # type: ignore[arg-type]
        )


def test_suggested_field_label_too_long_raises():
    with pytest.raises(ValidationError):
        CampaignStateSuggestedFieldConfig(
            key="x",
            label="L" * 257,
            mode="single",
            initial_status="empty",
        )


def test_suggested_field_description_too_long_raises():
    with pytest.raises(ValidationError):
        CampaignStateSuggestedFieldConfig(
            key="x",
            label="X",
            description="d" * (8 * 1024 + 1),
            mode="single",
            initial_status="empty",
        )


# ---------------------------------------------------------------------------
# CampaignStateInitialProposalV2 / ReadV2
# ---------------------------------------------------------------------------


def test_proposal_v2_empty_lists_ok():
    p = CampaignStateInitialProposalV2()
    assert p.fields == []
    assert p.suggested_fields == []
    assert p.questions == []


def test_proposal_v2_round_trip_json():
    sf = CampaignStateSuggestedFieldConfig(
        key="primary_objective",
        label="Главная цель",
        mode="single",
        initial_status="proposed",
        single_value=CampaignStateInitialSingleValue(text="x"),
    )
    p = CampaignStateInitialProposalV2(
        fields=[],
        suggested_fields=[sf],
        questions=["q1"],
    )
    j = p.model_dump_json()
    p2 = CampaignStateInitialProposalV2.model_validate_json(j)
    assert p2.suggested_fields[0].key == "primary_objective"
    assert p2.questions == ["q1"]


def test_proposal_read_v2_round_trip_with_suggested_fields():
    snap = DocumentSnapshot(
        document_id="11111111-1111-1111-1111-111111111111",
        vault_id="dnd-vault",
        source_path="session-14.md",
        content_sha="a" * 32,
        estimated_tokens=500,
    )
    sf = CampaignStateSuggestedFieldConfig(
        key="arc",
        label="Арка",
        mode="single",
        initial_status="proposed",
        single_value=CampaignStateInitialSingleValue(text="..."),
    )
    pf = CampaignStateInitialProposalField(
        field_key="current_focus",
        mode="single",
        status=CampaignStateInitialFieldStatus(status="empty"),
    )
    now = _dt.datetime(2026, 8, 23, 12, 0, 0, tzinfo=_dt.timezone.utc)
    read = CampaignStateInitialProposalReadV2(
        proposal_id="abc",
        campaign_id="22222222-2222-2222-2222-222222222222",
        config_version=3,
        source_snapshot=[snap],
        proposal=CampaignStateInitialProposalV2(
            fields=[pf],
            suggested_fields=[sf],
            questions=[],
        ),
        warnings=[],
        created_at=now,
        expires_at=now + _dt.timedelta(hours=3),
    )
    j = read.model_dump_json()
    read2 = CampaignStateInitialProposalReadV2.model_validate_json(j)
    assert read2.proposal.suggested_fields[0].key == "arc"
    assert len(read2.proposal.fields) == 1


def test_proposal_read_v2_inherits_v1_fields():
    """V2 Read должна наследовать все V1-поля."""
    snap = DocumentSnapshot(
        document_id="11111111-1111-1111-1111-111111111111",
        vault_id="dnd-vault",
        source_path="session-14.md",
        content_sha="a" * 32,
        estimated_tokens=500,
    )
    pf = CampaignStateInitialProposalField(
        field_key="current_focus",
        mode="single",
        status=CampaignStateInitialFieldStatus(status="empty"),
    )
    now = _dt.datetime(2026, 8, 23, 12, 0, 0, tzinfo=_dt.timezone.utc)
    read = CampaignStateInitialProposalReadV2(
        proposal_id="abc",
        campaign_id="22222222-2222-2222-2222-222222222222",
        config_version=3,
        source_snapshot=[snap],
        proposal=CampaignStateInitialProposalV2(
            fields=[pf], suggested_fields=[], questions=[]
        ),
        warnings=["w1"],
        created_at=now,
        expires_at=now + _dt.timedelta(hours=3),
    )
    assert read.warnings == ["w1"]
    assert read.config_version == 3
    assert read.proposal_id == "abc"
    assert read.source_snapshot[0].content_sha == "a" * 32


def test_proposal_v2_validates_against_v1_proposal_subtype():
    """Proposal v2 внутри Read V2 принимает v1-поля без suggested_fields."""
    p = CampaignStateInitialProposalV2(
        fields=[
            CampaignStateInitialProposalField(
                field_key="x",
                mode="single",
                status=CampaignStateInitialFieldStatus(status="empty"),
            )
        ],
    )
    assert len(p.fields) == 1
    assert p.suggested_fields == []


# ---------------------------------------------------------------------------
# Preview Request V2
# ---------------------------------------------------------------------------


def test_preview_request_v2_propose_fields_default_false():
    req = CampaignStateInitialPreviewRequestV2(
        document_ids=["11111111-1111-1111-1111-111111111111"],
    )
    assert req.propose_fields is False
    assert req.max_suggested_fields == 15


def test_preview_request_v2_propose_fields_true():
    req = CampaignStateInitialPreviewRequestV2(
        document_ids=["11111111-1111-1111-1111-111111111111"],
        propose_fields=True,
        max_suggested_fields=10,
    )
    assert req.propose_fields is True
    assert req.max_suggested_fields == 10


def test_preview_request_v2_max_suggested_fields_above_50_raises():
    with pytest.raises(ValidationError):
        CampaignStateInitialPreviewRequestV2(
            document_ids=["11111111-1111-1111-1111-111111111111"],
            propose_fields=True,
            max_suggested_fields=51,
        )


def test_preview_request_v2_empty_docs_raises():
    with pytest.raises(ValidationError):
        CampaignStateInitialPreviewRequestV2(document_ids=[])


# ---------------------------------------------------------------------------
# Apply Request V2
# ---------------------------------------------------------------------------


def test_apply_request_v2_accepts_v1_payload_no_accepted_keys():
    """V1 payload (без accepted/rejected ключей) должен пройти валидацию."""
    req = CampaignStateInitialApplyRequestV2(
        proposal_id="abc",
        config_version=1,
    )
    assert req.accepted_suggested_field_keys == []
    assert req.rejected_suggested_field_keys == []
    assert req.proposal_id == "abc"


def test_apply_request_v2_with_accepted_keys():
    req = CampaignStateInitialApplyRequestV2(
        proposal_id="abc",
        config_version=1,
        accepted_suggested_field_keys=["a", "b"],
        rejected_suggested_field_keys=["c"],
    )
    assert req.accepted_suggested_field_keys == ["a", "b"]
    assert req.rejected_suggested_field_keys == ["c"]


def test_apply_request_v2_more_than_50_accepted_raises():
    with pytest.raises(ValidationError):
        CampaignStateInitialApplyRequestV2(
            proposal_id="abc",
            config_version=1,
            accepted_suggested_field_keys=["k" for _ in range(51)],
        )


def test_apply_request_v2_requires_positive_config_version():
    with pytest.raises(ValidationError):
        CampaignStateInitialApplyRequestV2(
            proposal_id="abc",
            config_version=0,
        )


def test_apply_request_v2_proposal_id_required():
    with pytest.raises(ValidationError):
        CampaignStateInitialApplyRequestV2(
            proposal_id="",
            config_version=1,
        )


# ---------------------------------------------------------------------------
# V1 backward compat: V1 Read is still valid as a V2 Read (without suggested_fields)
# ---------------------------------------------------------------------------


def test_v2_read_accepts_v1_proposal_payload():
    """Должна принимать dict, сериализованный из V1 Read (без suggested_fields)."""
    snap = DocumentSnapshot(
        document_id="11111111-1111-1111-1111-111111111111",
        vault_id="dnd-vault",
        source_path="session-14.md",
        content_sha="a" * 32,
        estimated_tokens=500,
    )
    pf = CampaignStateInitialProposalField(
        field_key="x",
        mode="single",
        status=CampaignStateInitialFieldStatus(status="empty"),
    )
    v1 = CampaignStateInitialProposalRead(
        proposal_id="abc",
        campaign_id="22222222-2222-2222-2222-222222222222",
        config_version=3,
        source_snapshot=[snap],
        proposal=CampaignStateInitialProposal(fields=[pf], questions=[]),
        warnings=[],
        created_at=_dt.datetime.now(_dt.timezone.utc),
        expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
    )
    j = v1.model_dump_json()
    # V2 Read ВАЛИДИРУЕТСЯ тем же JSON (suggested_fields default=[]).
    parsed = CampaignStateInitialProposalReadV2.model_validate_json(j)
    assert parsed.proposal.suggested_fields == []
