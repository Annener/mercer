"""Tests for campaign_state_initial_service.py — orchestrator.

Стратегия: тестируем pure-logic хелперы (normalize_source_refs, normalize_proposal,
build_system_prompt, build_user_message) + LLM repair attempt без полноценной БД.

Тесты полного потока start_preview/apply (с SELECT FOR UPDATE, fetch,
audit-log) требуют интеграционного окружения и оставлены для отдельной
integration-стадии; contract + API покрытие достаточно для Stage 3.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.campaign_state_value_service import (
    _build_initial_state_rows,
)
from shared_contracts.models import (
    CampaignStateInitialFieldStatus,
    CampaignStateInitialListValue,
    CampaignStateInitialListItem,
    CampaignStateInitialProposal,
    CampaignStateInitialProposalField,
    CampaignStateInitialSingleValue,
    CampaignStateFieldMode,
)


# ---------------------------------------------------------------------------
# _build_initial_state_rows — публичный через apply_initial
# ---------------------------------------------------------------------------
# Мы не можем напрямую импортировать приватные функции, поэтому используем
# непрямой подход: apply_initial вызывает _build_initial_state_rows под капотом.
# Тесты _build_initial_state_rows проверяются через test_campaign_state_value_service_apply_initial
# (integration).


# ---------------------------------------------------------------------------
# Нормализация source_refs
# ---------------------------------------------------------------------------


def _norm(refs: list[str], snapshot: set[str]) -> tuple[list[str], list[str]]:
    """Обёртка для прямого вызова normalize из теста."""
    from app.services.campaign_state_initial_service import _normalize_source_refs

    warnings: list[str] = []
    out = _normalize_source_refs(refs, snapshot, warnings, field_key="f1")
    return out, warnings


def test_normalize_source_refs_keeps_only_valid_file_refs():
    snap = {"11111111-1111-1111-1111-111111111111"}
    refs = [
        f"file:11111111-1111-1111-1111-111111111111:sha:{'a'*32}",
        "chat:22222222-2222-2222-2222-222222222222",
        "vault:my-vault",
        f"file:99999999-9999-9999-9999-999999999999:sha:{'b'*32}",  # unknown doc
    ]
    out, warns = _norm(refs, snap)
    assert len(out) == 1
    assert out[0].startswith("file:11111111")
    assert any("unknown_document" in w for w in warns)


def test_normalize_source_refs_rejects_invalid_format():
    snap = {"11111111-1111-1111-1111-111111111111"}
    refs = [
        f"file:11111111-1111-1111-1111-111111111111:sha:{'a'*31}",  # short sha
        f"file:11111111-1111-1111-1111-111111111111:sha:{'b'*32}",  # valid
        "file:bad-uuid:sha:" + "a" * 32,  # bad uuid
        "garbage",
    ]
    out, warns = _norm(refs, snap)
    assert len(out) == 1
    # Все три невалидных должны породить warnings об invalid format.
    invalid_warns = [w for w in warns if "invalid_source_ref_format" in w]
    assert len(invalid_warns) == 3


def test_normalize_source_refs_truncates_at_max():
    snap = {f"11111111-1111-1111-1111-{i:012d}" for i in range(50)}
    refs = [f"file:{did}:sha:{'a'*32}" for did in snap]
    out, warns = _norm(refs, snap)
    # MAX = 32, плюс одно warning.
    assert len(out) == 32
    assert any("truncated" in w for w in warns)


def test_normalize_source_refs_drops_non_strings():
    snap = {"11111111-1111-1111-1111-111111111111"}
    refs = [
        None,  # type: ignore[list-item]
        42,  # type: ignore[list-item]
        f"file:11111111-1111-1111-1111-111111111111:sha:{'a'*32}",
    ]
    out, warns = _norm(refs, snap)  # type: ignore[arg-type]
    assert len(out) == 1
    assert any("non_string" in w for w in warns)


# ---------------------------------------------------------------------------
# _normalize_proposal — полная фильтрация
# ---------------------------------------------------------------------------


def _normalize(
    raw: dict[str, Any],
    fields_by_key: dict[str, Any],
    snapshot: set[str],
) -> tuple[Any, list[str]]:
    from app.services.campaign_state_initial_service import _normalize_proposal

    warnings: list[str] = []
    out = _normalize_proposal(raw, fields_by_key, snapshot, warnings)
    return out, warnings


class _FakeField:
    def __init__(self, key: str, mode: str, enabled: bool = True) -> None:
        self.key = key
        self.mode = mode
        self.enabled = enabled


def test_normalize_proposal_keeps_enabled_proposed_single():
    fields = {"focus": _FakeField("focus", "single")}
    snap = {"11111111-1111-1111-1111-111111111111"}
    raw = {
        "fields": [
            {
                "field_key": "focus",
                "mode": "single",
                "status": {"status": "proposed"},
                "single_value": {
                    "text": "value",
                    "source_refs": [f"file:11111111-1111-1111-1111-111111111111:sha:{'a'*32}"],
                },
            }
        ],
        "questions": ["Q1"],
    }
    out, warns = _normalize(raw, fields, snap)
    assert len(out.fields) == 1
    assert out.fields[0].single_value is not None
    assert out.fields[0].single_value.text == "value"
    assert out.questions == ["Q1"]


def test_normalize_proposal_skips_disabled_fields():
    fields = {
        "focus": _FakeField("focus", "single", enabled=False),
        "active": _FakeField("active", "list", enabled=True),
    }
    snap = {"11111111-1111-1111-1111-111111111111"}
    raw = {
        "fields": [
            {
                "field_key": "focus",
                "mode": "single",
                "status": {"status": "empty"},
            },
            {
                "field_key": "active",
                "mode": "list",
                "status": {"status": "proposed"},
                "list_value": {"items": [{"text": "x", "source_refs": []}]},
            },
        ]
    }
    out, warns = _normalize(raw, fields, snap)
    assert len(out.fields) == 1
    assert out.fields[0].field_key == "active"
    assert any("disabled_field_skipped:focus" in w for w in warns)


def test_normalize_proposal_drops_unknown_field_key():
    fields = {"focus": _FakeField("focus", "single")}
    raw = {
        "fields": [
            {
                "field_key": "focus",
                "mode": "single",
                "status": {"status": "empty"},
            },
            {
                "field_key": "mystery",
                "mode": "single",
                "status": {"status": "empty"},
            },
        ]
    }
    out, warns = _normalize(raw, fields, snapshot=set())
    assert len(out.fields) == 1
    assert out.fields[0].field_key == "focus"
    assert any("unknown_field_key:mystery" in w for w in warns)


def test_normalize_proposal_keeps_needs_clarification_with_question():
    fields = {"focus": _FakeField("focus", "single")}
    raw = {
        "fields": [
            {
                "field_key": "focus",
                "mode": "single",
                "status": {
                    "status": "needs_clarification",
                    "clarification_question": "Что именно?",
                },
            }
        ]
    }
    out, warns = _normalize(raw, fields, snapshot=set())
    assert len(out.fields) == 1
    assert out.fields[0].status.status == "needs_clarification"
    assert out.fields[0].status.clarification_question == "Что именно?"


def test_normalize_proposal_drops_needs_clarification_without_question():
    fields = {"focus": _FakeField("focus", "single")}
    raw = {
        "fields": [
            {
                "field_key": "focus",
                "mode": "single",
                "status": {"status": "needs_clarification"},
            }
        ]
    }
    out, warns = _normalize(raw, fields, snapshot=set())
    assert len(out.fields) == 0
    assert any("missing_clarification_question:focus" in w for w in warns)


def test_normalize_proposal_rejects_mode_mismatch():
    fields = {"focus": _FakeField("focus", "single")}
    raw = {
        "fields": [
            {
                "field_key": "focus",
                "mode": "list",  # ← mismatch
                "status": {"status": "empty"},
            }
        ]
    }
    out, warns = _normalize(raw, fields, snapshot=set())
    assert len(out.fields) == 0
    assert any("mode_mismatch" in w for w in warns)


# ---------------------------------------------------------------------------
# build_system_prompt / build_user_message
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_field_keys_and_descriptions():
    from app.services.campaign_state_initial_service import _build_system_prompt
    from app.db.models import CampaignStateFieldConfig

    fields = [
        CampaignStateFieldConfig(
            id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            key="focus",
            label="Фокус",
            description="Текущая цель сюжета",
            mode="single",
            enabled=True,
            display_order=0,
        ),
        CampaignStateFieldConfig(
            id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            key="npcs",
            label="NPC",
            description="Список активных NPC",
            mode="list",
            enabled=True,
            display_order=1,
        ),
        CampaignStateFieldConfig(
            id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            key="disabled_field",
            label="Disabled",
            description="Не должно попасть в промпт",
            mode="single",
            enabled=False,
            display_order=2,
        ),
    ]
    prompt = _build_system_prompt(fields)
    assert "focus" in prompt
    assert "npcs" in prompt
    assert "disabled_field" not in prompt
    assert "Текущая цель сюжета" in prompt
    assert "Список активных NPC" in prompt


def test_build_user_message_wraps_documents_with_id_and_sha():
    from app.services.campaign_state_initial_service import _build_user_message
    from shared_contracts.models import DocumentSnapshot

    snap1 = DocumentSnapshot(
        document_id="11111111-1111-1111-1111-111111111111",
        vault_id="dnd-vault",
        source_path="session-14.md",
        title="Session 14",
        content_sha="a" * 32,
        estimated_tokens=100,
    )
    snap2 = DocumentSnapshot(
        document_id="22222222-2222-2222-2222-222222222222",
        vault_id="dnd-vault",
        source_path="session-15.md",
        content_sha="b" * 32,
        estimated_tokens=200,
    )
    docs_text = {
        snap1.document_id: "content one",
        snap2.document_id: "content two",
    }
    msg = _build_user_message([snap1, snap2], docs_text)
    assert msg.startswith("<allowed_documents>")
    assert msg.endswith("</allowed_documents>")
    assert 'id="11111111-1111-1111-1111-111111111111"' in msg
    assert 'sha="' + "a" * 32 + '"' in msg
    assert 'id="22222222-2222-2222-2222-222222222222"' in msg
    assert "content one" in msg
    assert "content two" in msg


# ---------------------------------------------------------------------------
# LLM repair attempt: 1 fail → repair → ok; 2 fail → InvalidGenerationOutputError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_provider_with_repair_succeeds_on_second_attempt():
    from app.services.campaign_state_initial_service import (
        _call_provider_with_repair_raw,
        InvalidGenerationOutputError,
    )

    provider = MagicMock()
    # Первый вызов — невалидный dict (нет 'fields').
    # Второй вызов — валидный dict.
    provider.generate_json = AsyncMock(
        side_effect=[
            {"oops": "wrong"},
            {
                "fields": [
                    {
                        "field_key": "focus",
                        "mode": "single",
                        "status": {"status": "empty"},
                    }
                ],
                "questions": [],
            },
        ]
    )

    raw = await _call_provider_with_repair_raw(
        provider, system_prompt="sys", user_message="msg"
    )
    assert "fields" in raw
    assert provider.generate_json.call_count == 2


@pytest.mark.asyncio
async def test_call_provider_with_repair_raises_after_two_invalid_attempts():
    from app.services.campaign_state_initial_service import (
        _call_provider_with_repair_raw,
        InvalidGenerationOutputError,
    )

    provider = MagicMock()
    provider.generate_json = AsyncMock(
        side_effect=[
            {"oops": 1},
            {"still": "wrong"},
        ]
    )

    with pytest.raises(InvalidGenerationOutputError):
        await _call_provider_with_repair_raw(
            provider, system_prompt="sys", user_message="msg"
        )
    assert provider.generate_json.call_count == 2


@pytest.mark.asyncio
async def test_call_provider_with_repair_handles_non_dict_output():
    """Если LLM вернул не dict (например, list), repair должен сработать."""
    from app.services.campaign_state_initial_service import (
        _call_provider_with_repair_raw,
    )

    provider = MagicMock()
    provider.generate_json = AsyncMock(
        side_effect=[
            [1, 2, 3],  # не dict
            {
                "fields": [
                    {
                        "field_key": "focus",
                        "mode": "single",
                        "status": {"status": "empty"},
                    }
                ],
                "questions": [],
            },
        ]
    )

    raw = await _call_provider_with_repair_raw(
        provider, system_prompt="sys", user_message="msg"
    )
    assert isinstance(raw, dict)


# ---------------------------------------------------------------------------
# _build_initial_state_rows direct test (через импорт приватной функции)
# ---------------------------------------------------------------------------


def _make_field(key: str, mode: str, enabled: bool = True):
    from app.db.models import CampaignStateFieldConfig

    return CampaignStateFieldConfig(
        id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        key=key,
        label=key,
        description="",
        mode=mode,
        enabled=enabled,
        display_order=0,
    )


def test_build_initial_state_rows_creates_values_for_single_proposed():
    vid = uuid.uuid4()
    focus = _make_field("focus", "single")
    fields_by_key = {"focus": focus}
    proposal = CampaignStateInitialProposal(
        fields=[
            CampaignStateInitialProposalField(
                field_key="focus",
                mode="single",
                status=CampaignStateInitialFieldStatus(status="proposed"),
                single_value=CampaignStateInitialSingleValue(
                    text="initial focus text",
                    source_refs=[f"file:11111111-1111-1111-1111-111111111111:sha:{'a'*32}"],
                ),
            )
        ]
    )
    values_rows, items_rows = _build_initial_state_rows(proposal, fields_by_key, vid)
    assert len(values_rows) == 1
    assert items_rows == []
    assert values_rows[0]["text"] == "initial focus text"
    assert values_rows[0]["field_id"] == focus.id


def test_build_initial_state_rows_creates_items_for_list_proposed():
    vid = uuid.uuid4()
    npcs = _make_field("npcs", "list")
    fields_by_key = {"npcs": npcs}
    proposal = CampaignStateInitialProposal(
        fields=[
            CampaignStateInitialProposalField(
                field_key="npcs",
                mode="list",
                status=CampaignStateInitialFieldStatus(status="proposed"),
                list_value=CampaignStateInitialListValue(
                    items=[
                        CampaignStateInitialListItem(text="Ворон"),
                        CampaignStateInitialListItem(text="Изур"),
                    ],
                ),
            )
        ]
    )
    values_rows, items_rows = _build_initial_state_rows(proposal, fields_by_key, vid)
    assert values_rows == []
    assert len(items_rows) == 2
    assert items_rows[0]["item_key"] == "npcs-01"
    assert items_rows[1]["item_key"] == "npcs-02"


def test_build_initial_state_rows_skips_empty_and_clarification():
    vid = uuid.uuid4()
    focus = _make_field("focus", "single")
    npcs = _make_field("npcs", "list")
    fields_by_key = {"focus": focus, "npcs": npcs}
    proposal = CampaignStateInitialProposal(
        fields=[
            CampaignStateInitialProposalField(
                field_key="focus",
                mode="single",
                status=CampaignStateInitialFieldStatus(status="empty"),
            ),
            CampaignStateInitialProposalField(
                field_key="npcs",
                mode="list",
                status=CampaignStateInitialFieldStatus(
                    status="needs_clarification",
                    clarification_question="Сколько NPC?",
                ),
            ),
        ]
    )
    values_rows, items_rows = _build_initial_state_rows(proposal, fields_by_key, vid)
    assert values_rows == []
    assert items_rows == []


def test_build_initial_state_rows_skips_disabled_fields():
    vid = uuid.uuid4()
    focus = _make_field("focus", "single", enabled=False)
    fields_by_key = {"focus": focus}
    proposal = CampaignStateInitialProposal(
        fields=[
            CampaignStateInitialProposalField(
                field_key="focus",
                mode="single",
                status=CampaignStateInitialFieldStatus(status="proposed"),
                single_value=CampaignStateInitialSingleValue(text="x"),
            )
        ]
    )
    values_rows, items_rows = _build_initial_state_rows(proposal, fields_by_key, vid)
    assert values_rows == []
    assert items_rows == []
