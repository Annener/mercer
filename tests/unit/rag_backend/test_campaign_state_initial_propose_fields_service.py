"""Tests for Stage 3.v2 service logic (propose_fields).

Covers pure-logic helpers:
  - _normalize_proposal_v2: фильтрация suggested_fields (existing/snapshot dedup,
    cap, валидации); режимы propose_fields=true / false.
  - _build_system_prompt: ветка propose_fields=true добавляет блок инструкций.
  - _unify_proposal_for_apply: existing + accepted suggested → V1 формат.
  - _next_display_order: стабильное следующее значение.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.db.models import CampaignStateFieldConfig

from shared_contracts.models import (
    CampaignStateInitialFieldStatus,
    CampaignStateInitialListItem,
    CampaignStateInitialListValue,
    CampaignStateInitialProposalField,
    CampaignStateInitialProposalV2,
    CampaignStateInitialSingleValue,
    CampaignStateSuggestedFieldConfig,
)

# ---------------------------------------------------------------------------
# _build_system_prompt — ветка propose_fields
# ---------------------------------------------------------------------------


def _field(key: str, label: str, mode: str) -> CampaignStateFieldConfig:
    return CampaignStateFieldConfig(
        id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        key=key,
        label=label,
        description="",
        mode=mode,  # type: ignore[arg-type]
        enabled=True,
        display_order=0,
    )


def test_build_system_prompt_propose_fields_adds_suggested_section():
    from app.services.campaign_state_initial_service import _build_system_prompt

    fields = [_field("focus", "Фокус", "single")]
    prompt = _build_system_prompt(fields, propose_fields=False, max_suggested_fields=15)
    assert "SUGGESTED FIELDS" not in prompt
    assert "suggested_fields" not in prompt

    prompt2 = _build_system_prompt(fields, propose_fields=True, max_suggested_fields=10)
    assert "SUGGESTED FIELDS" in prompt2
    assert "max_suggested_fields=10" in prompt2
    assert '"suggested_fields"' in prompt2
    # Ключ из fields должен быть в обоих prompt'ах.
    assert "focus" in prompt2


def test_build_system_prompt_propose_fields_no_existing_fields_ok():
    """При 0 enabled-полей и propose_fields=True — промпт всё равно валиден."""
    from app.services.campaign_state_initial_service import _build_system_prompt

    prompt = _build_system_prompt([], propose_fields=True, max_suggested_fields=15)
    assert "FIELD CONFIGURATION (ordered" in prompt
    assert "SUGGESTED FIELDS" in prompt


# ---------------------------------------------------------------------------
# _normalize_proposal_v2 — фильтрация suggested_fields
# ---------------------------------------------------------------------------


class _FakeField:
    def __init__(self, key: str, mode: str, enabled: bool = True) -> None:
        self.key = key
        self.mode = mode
        self.enabled = enabled


def _normalize(
    raw: dict[str, Any],
    fields_by_key: dict[str, Any],
    snapshot: set[str],
    *,
    propose_fields: bool,
    max_suggested_fields: int = 15,
) -> tuple[Any, list[str]]:
    from app.services.campaign_state_initial_service import _normalize_proposal_v2

    warnings: list[str] = []
    out = _normalize_proposal_v2(
        raw,
        fields_by_key,
        snapshot,
        warnings,
        propose_fields=propose_fields,
        max_suggested_fields=max_suggested_fields,
    )
    return out, warnings


SNAPSHOT_DOC = "11111111-1111-1111-1111-111111111111"
SHA_REF = f"file:{SNAPSHOT_DOC}:sha:{'a' * 32}"


def test_normalize_v2_keeps_suggested_when_propose_fields_true():
    fields = {"focus": _FakeField("focus", "single")}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": "character_goals",
                "label": "Цели",
                "description": "",
                "mode": "single",
                "initial_status": {
                    "status": "proposed",
                },
                "single_value": {"text": "Найти артефакт", "source_refs": []},
            }
        ],
        "questions": [],
    }
    out, warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.suggested_fields) == 1
    assert out.suggested_fields[0].key == "character_goals"
    assert out.suggested_fields[0].single_value.text == "Найти артефакт"
    assert not any("ignored" in w for w in warns)


def test_normalize_v2_ignores_suggested_when_propose_fields_false():
    fields = {"focus": _FakeField("focus", "single")}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": "character_goals",
                "label": "Цели",
                "mode": "single",
                "initial_status": {"status": "empty"},
            }
        ],
        "questions": [],
    }
    out, warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=False)
    assert len(out.suggested_fields) == 0
    assert any("suggested_fields_ignored:propose_fields_false" in w for w in warns)


def test_normalize_v2_drops_suggested_with_existing_key():
    fields = {"focus": _FakeField("focus", "single")}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": "focus",  # ← дубликат existing
                "label": "Дубль",
                "mode": "single",
                "initial_status": {"status": "empty"},
            }
        ],
        "questions": [],
    }
    out, warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.suggested_fields) == 0
    assert any("suggested_field_duplicate_existing_key:focus" in w for w in warns)


def test_normalize_v2_drops_suggested_with_duplicate_key_in_batch():
    fields = {}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": "x",
                "label": "X1",
                "mode": "single",
                "initial_status": {"status": "empty"},
            },
            {
                "key": "x",  # ← дубликат внутри suggested
                "label": "X2",
                "mode": "single",
                "initial_status": {"status": "empty"},
            },
        ],
        "questions": [],
    }
    out, warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.suggested_fields) == 1
    assert any("suggested_field_duplicate_key" in w for w in warns)


def test_normalize_v2_respects_max_suggested_fields():
    fields = {}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": f"key_{i}",
                "label": f"L{i}",
                "mode": "single",
                "initial_status": {"status": "empty"},
            }
            for i in range(20)
        ],
        "questions": [],
    }
    out, warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True, max_suggested_fields=5)
    assert len(out.suggested_fields) == 5
    assert any("suggested_fields_limit_reached:5" in w for w in warns)


def test_normalize_v2_filters_invalid_suggested_field():
    fields = {}
    raw = {
        "fields": [],
        "suggested_fields": [
            {"key": "Bad-Key!", "label": "X", "mode": "single",
             "initial_status": {"status": "empty"}},
            {"key": "ok_key", "label": "", "mode": "single",
             "initial_status": {"status": "empty"}},  # empty label
            "not-a-dict",
            {"key": "ok2", "label": "OK", "mode": "unknown",  # bad mode
             "initial_status": {"status": "empty"}},
        ],
        "questions": [],
    }
    out, warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.suggested_fields) == 0
    # Все 4 должны породить warnings.
    assert len(warns) >= 4


def test_normalize_v2_keeps_suggested_with_invalid_source_ref():
    """Invalid source_ref в suggested_field отбрасывается с warning, но
    предложение сохраняется (как и в V1 _normalize_proposal)."""
    fields = {}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": "x",
                "label": "X",
                "mode": "single",
                "initial_status": {"status": "proposed"},
                "single_value": {
                    "text": "value",
                    "source_refs": [
                        "garbage",
                        f"file:22222222-2222-2222-2222-222222222222:sha:{'b' * 32}",
                    ],
                },
            }
        ],
        "questions": [],
    }
    out, warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.suggested_fields) == 1
    assert out.suggested_fields[0].single_value.source_refs == []
    assert any("invalid_source_ref_format" in w for w in warns)


def test_normalize_v2_suggested_needs_clarification_without_question_dropped():
    fields = {}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": "x",
                "label": "X",
                "mode": "single",
                "initial_status": {"status": "needs_clarification"},
            }
        ],
        "questions": [],
    }
    out, warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.suggested_fields) == 0
    assert any("missing_clarification_question" in w for w in warns)


def test_normalize_v2_suggested_list_mode():
    fields = {}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": "npcs",
                "label": "NPC",
                "description": "Список",
                "mode": "list",
                "initial_status": {"status": "proposed"},
                "list_value": {"items": [{"text": "Ворон"}, {"text": "Изур"}]},
            }
        ],
        "questions": [],
    }
    out, _warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.suggested_fields) == 1
    assert out.suggested_fields[0].list_value is not None
    assert len(out.suggested_fields[0].list_value.items) == 2


def test_normalize_v2_existing_and_suggested():
    """Existing fields + suggested_fields вместе."""
    fields = {"focus": _FakeField("focus", "single")}
    raw = {
        "fields": [
            {
                "field_key": "focus",
                "mode": "single",
                "status": {"status": "proposed"},
                "single_value": {"text": "текст", "source_refs": []},
            }
        ],
        "suggested_fields": [
            {
                "key": "npcs",
                "label": "NPC",
                "mode": "list",
                "initial_status": {"status": "proposed"},
                "list_value": {"items": [{"text": "A"}, {"text": "B"}]},
            }
        ],
        "questions": ["q1"],
    }
    out, _warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.fields) == 1
    assert len(out.suggested_fields) == 1
    assert out.questions == ["q1"]


def test_normalize_v2_works_with_no_existing_fields_and_propose_fields_true():
    fields = {}
    raw = {
        "fields": [],
        "suggested_fields": [
            {
                "key": "x",
                "label": "X",
                "mode": "single",
                "initial_status": {"status": "proposed"},
                "single_value": {"text": "v", "source_refs": []},
            }
        ],
        "questions": [],
    }
    out, _warns = _normalize(raw, fields, {SNAPSHOT_DOC}, propose_fields=True)
    assert len(out.fields) == 0
    assert len(out.suggested_fields) == 1


# ---------------------------------------------------------------------------
# _unify_proposal_for_apply
# ---------------------------------------------------------------------------


def _make_field_row(key: str) -> CampaignStateFieldConfig:
    return CampaignStateFieldConfig(
        id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        key=key,
        label=key,
        description="",
        mode="single",
        enabled=True,
        display_order=0,
    )


def test_unify_proposal_for_apply_keeps_existing():
    from app.services.campaign_state_initial_service import _unify_proposal_for_apply

    p_v2 = CampaignStateInitialProposalV2(
        fields=[
            CampaignStateInitialProposalField(
                field_key="focus",
                mode="single",
                status=CampaignStateInitialFieldStatus(status="proposed"),
                single_value=CampaignStateInitialSingleValue(text="existing"),
            )
        ],
        suggested_fields=[],
        questions=[],
    )
    out = _unify_proposal_for_apply(p_v2, {}, [])
    assert len(out.fields) == 1
    assert out.fields[0].field_key == "focus"
    assert out.fields[0].single_value.text == "existing"


def test_unify_proposal_for_apply_adds_suggested():
    from app.services.campaign_state_initial_service import _unify_proposal_for_apply

    sf = CampaignStateSuggestedFieldConfig(
        key="new_field",
        label="New Field",
        mode="single",
        initial_status="proposed",
        single_value=CampaignStateInitialSingleValue(text="new value"),
    )
    field_row = _make_field_row("new_field")
    p_v2 = CampaignStateInitialProposalV2(
        fields=[],
        suggested_fields=[sf],
        questions=[],
    )
    out = _unify_proposal_for_apply(p_v2, {"new_field": field_row}, [sf])
    assert len(out.fields) == 1
    assert out.fields[0].field_key == "new_field"
    assert out.fields[0].single_value.text == "new value"


def test_unify_proposal_for_apply_existing_and_suggested():
    from app.services.campaign_state_initial_service import _unify_proposal_for_apply

    existing_pf = CampaignStateInitialProposalField(
        field_key="focus",
        mode="single",
        status=CampaignStateInitialFieldStatus(status="proposed"),
        single_value=CampaignStateInitialSingleValue(text="existing"),
    )
    sf = CampaignStateSuggestedFieldConfig(
        key="npcs",
        label="NPC",
        mode="list",
        initial_status="proposed",
        list_value=CampaignStateInitialListValue(
            items=[CampaignStateInitialListItem(text="A")]
        ),
    )
    field_row = _make_field_row("npcs")
    p_v2 = CampaignStateInitialProposalV2(
        fields=[existing_pf],
        suggested_fields=[sf],
        questions=["q1"],
    )
    out = _unify_proposal_for_apply(
        p_v2,
        {"npcs": field_row},
        [sf],
    )
    assert len(out.fields) == 2
    assert {f.field_key for f in out.fields} == {"focus", "npcs"}
    npcs = next(f for f in out.fields if f.field_key == "npcs")
    assert npcs.mode == "list"
    assert npcs.list_value.items[0].text == "A"


def test_unify_proposal_for_apply_preserves_questions():
    from app.services.campaign_state_initial_service import _unify_proposal_for_apply

    p_v2 = CampaignStateInitialProposalV2(
        fields=[],
        suggested_fields=[],
        questions=["q1", "q2"],
    )
    out = _unify_proposal_for_apply(p_v2, {}, [])
    assert out.questions == ["q1", "q2"]


def test_unify_proposal_for_apply_skips_suggested_not_in_accepted():
    """Если accepted_sf не содержит suggested — поле пропускается.

    (Defensive: на практике сервис фильтрует rejected до этого. Но если клиент
    прислал inconsistent payload, не должно упасть.)
    """
    from app.services.campaign_state_initial_service import _unify_proposal_for_apply

    sf = CampaignStateSuggestedFieldConfig(
        key="lonely",
        label="Lonely",
        mode="single",
        initial_status="proposed",
        single_value=CampaignStateInitialSingleValue(text="x"),
    )
    p_v2 = CampaignStateInitialProposalV2(
        fields=[],
        suggested_fields=[sf],
        questions=[],
    )
    field_row = _make_field_row("lonely")
    out = _unify_proposal_for_apply(
        p_v2,
        {"lonely": field_row},  # поле создано
        [],  # но НЕ принято
    )
    assert len(out.fields) == 0


# ---------------------------------------------------------------------------
# _next_display_order
# ---------------------------------------------------------------------------


def test_next_display_order_no_existing():
    from app.services.campaign_state_initial_service import _next_display_order

    assert _next_display_order([], start=-1) == 0
    assert _next_display_order([5], start=-1) == 6
    assert _next_display_order([], start=10) == 11
