"""Unit-тесты для Stage 6: campaign_state_compiler.

Чистая логика, без БД/HTTP. Покрывает:
  - порядок полей (display_order ASC, key ASC);
  - режимы single/list;
  - empty-поля (single=None или list пуст) — не считаются truncated;
  - soft-stop при превышении budget;
  - детерминизм (никаких LLM);
  - корректное форматирование resolved-элементов;
  - отсутствие state → пустой блок.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.services.campaign_state_compiler import (
    DEFAULT_TOKEN_BUDGET,
    compile_campaign_state,
    default_token_counter,
    get_campaign_state_token_budget,
)

from shared_contracts.models import (
    CampaignStateFieldConfigRead,
    CampaignStateFieldValuesRead,
    CampaignStateListItemRead,
    CampaignStateSingleValueRead,
    CampaignStateVersionRead,
    CampaignStateVersionSummary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cfg(
    key: str,
    label: str,
    mode: str = "single",
    *,
    enabled: bool = True,
    display_order: int = 0,
    description: str = "",
) -> CampaignStateFieldConfigRead:
    return CampaignStateFieldConfigRead(
        id=f"f-{key}",
        field_id=f"f-{key}",
        campaign_id="00000000-0000-0000-0000-000000000001",
        key=key,
        label=label,
        description=description,
        mode=mode,  # type: ignore[arg-type]
        enabled=enabled,
        display_order=display_order,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _version(
    fields: list[CampaignStateFieldValuesRead],
    state_version: int = 1,
    config_version: int = 1,
) -> CampaignStateVersionRead:
    return CampaignStateVersionRead(
        summary=CampaignStateVersionSummary(
            id="00000000-0000-0000-0000-000000000010",
            campaign_id="00000000-0000-0000-0000-000000000001",
            state_version=state_version,
            config_version=config_version,
            source_kind="initial",
            base_state_version=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_by=None,
        ),
        fields=fields,
    )


def _fv_single(
    field_key: str,
    field_id: str,
    text: str | None,
    display_order: int = 0,
) -> CampaignStateFieldValuesRead:
    single = None
    if text is not None:
        single = CampaignStateSingleValueRead(
            field_key=field_key,
            text=text,
            source_refs=[],
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    return CampaignStateFieldValuesRead(
        field_key=field_key,
        field_id=field_id,
        mode="single",
        enabled=True,
        display_order=display_order,
        single_value=single,
        items=[],
    )


def _fv_list(
    field_key: str,
    field_id: str,
    items: list[tuple[str, bool]],
    display_order: int = 0,
) -> CampaignStateFieldValuesRead:
    return CampaignStateFieldValuesRead(
        field_key=field_key,
        field_id=field_id,
        mode="list",
        enabled=True,
        display_order=display_order,
        single_value=None,
        items=[
            CampaignStateListItemRead(
                field_key=field_key,
                item_key=f"{field_key}-{i + 1:02d}",
                text=text,
                resolved=resolved,
                source_refs=[],
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for i, (text, resolved) in enumerate(items)
        ],
    )


# ---------------------------------------------------------------------------
# Базовые кейсы
# ---------------------------------------------------------------------------


class TestCompileEmptyInputs:
    def test_no_version_returns_empty_block(self):
        result = compile_campaign_state(
            version=None,
            fields=[_cfg("focus", "Текущий фокус")],
        )
        assert result.text == ""
        assert result.used_tokens == 0
        assert result.state_version is None
        assert result.truncated_fields == []

    def test_no_fields_returns_empty_block(self):
        result = compile_campaign_state(
            version=_version([]),
            fields=[],
        )
        assert result.text == ""
        assert result.used_tokens == 0
        assert result.fields == []

    def test_disabled_fields_are_skipped(self):
        cfg_disabled = _cfg("old", "Устаревшее", enabled=False)
        cfg_enabled = _cfg("focus", "Фокус")
        ver = _version([
            _fv_single("focus", "f-focus", "Дизайн"),
        ])
        result = compile_campaign_state(ver, [cfg_disabled, cfg_enabled])
        assert "Фокус" in result.text
        assert "Устаревшее" not in result.text
        assert "old" not in result.fields[0].field_key or result.fields[0].included


# ---------------------------------------------------------------------------
# Порядок полей
# ---------------------------------------------------------------------------


class TestCompileFieldOrdering:
    def test_order_by_display_order_then_key(self):
        # Конфиг с явным перепутанным порядком подачи.
        cfgs = [
            _cfg("zeta", "Зета", display_order=2),
            _cfg("alpha", "Альфа", display_order=0),
            _cfg("mu", "Мю", display_order=1),
        ]
        ver = _version([
            _fv_single("zeta", "f-zeta", "Z", display_order=2),
            _fv_single("alpha", "f-alpha", "A", display_order=0),
            _fv_single("mu", "f-mu", "M", display_order=1),
        ])
        result = compile_campaign_state(ver, cfgs)
        # Выходной текст должен идти в порядке alpha → mu → zeta.
        assert result.text.index("Альфа") < result.text.index("Мю") < result.text.index("Зета")

    def test_tie_break_by_key_asc(self):
        cfgs = [
            _cfg("zeta", "Зета", display_order=0),
            _cfg("alpha", "Альфа", display_order=0),
            _cfg("mu", "Мю", display_order=0),
        ]
        ver = _version([
            _fv_single("alpha", "f-alpha", "A", display_order=0),
            _fv_single("mu", "f-mu", "M", display_order=0),
            _fv_single("zeta", "f-zeta", "Z", display_order=0),
        ])
        result = compile_campaign_state(ver, cfgs)
        # ASCII tie-break: alpha < mu < zeta.
        assert result.text.index("Альфа") < result.text.index("Мю")
        assert result.text.index("Мю") < result.text.index("Зета")


# ---------------------------------------------------------------------------
# Режимы
# ---------------------------------------------------------------------------


class TestCompileModes:
    def test_single_field_renders_label_and_text(self):
        cfg = _cfg("focus", "Текущий фокус", mode="single")
        ver = _version([_fv_single("focus", "f-focus", "Дизайн MVP")])
        result = compile_campaign_state(ver, [cfg])
        assert "Текущий фокус (key=focus, mode=single):" in result.text
        assert "Дизайн MVP" in result.text
        assert result.fields[0].included is True
        assert result.fields[0].items_included == 1

    def test_list_field_renders_with_bullets(self):
        cfg = _cfg("agreements", "Договорённости", mode="list")
        ver = _version([
            _fv_list("agreements", "f-agr", [("A1", False), ("A2", False)]),
        ])
        result = compile_campaign_state(ver, [cfg])
        assert "Договорённости (key=agreements, mode=list):" in result.text
        assert "- A1" in result.text
        assert "- A2" in result.text

    def test_resolved_items_have_checkmark_prefix(self):
        cfg = _cfg("open_questions", "Открытые вопросы", mode="list")
        ver = _version([
            _fv_list("open_questions", "f-oq", [("Q1", True), ("Q2", False)]),
        ])
        result = compile_campaign_state(ver, [cfg])
        assert "[x] Q1" in result.text
        assert "- Q2" in result.text


# ---------------------------------------------------------------------------
# Empty / soft-stop
# ---------------------------------------------------------------------------


class TestCompileEmptyFields:
    def test_single_none_is_empty_not_truncated(self):
        cfg = _cfg("focus", "Фокус")
        ver = _version([_fv_single("focus", "f-focus", None)])
        result = compile_campaign_state(ver, [cfg])
        assert result.text == ""
        assert result.empty_fields == ["focus"]
        assert result.truncated_fields == []
        assert result.fields[0].included is False
        assert result.fields[0].truncated is False

    def test_list_empty_is_empty_not_truncated(self):
        cfg = _cfg("agreements", "Договорённости", mode="list")
        ver = _version([_fv_list("agreements", "f-agr", [])])
        result = compile_campaign_state(ver, [cfg])
        assert result.text == ""
        assert result.empty_fields == ["agreements"]
        assert result.truncated_fields == []


class TestCompileSoftStop:
    def test_field_excluded_when_exceeds_budget(self):
        # Поле "big" занимает больше оставшегося бюджета.
        budget = 10
        big_text = "x" * 200  # 200 chars → 50 токенов по ceil(len/4); больше budget.
        cfgs = [
            _cfg("first", "Первое", display_order=0),
            _cfg("big", "Большое", display_order=1),
        ]
        ver = _version([
            _fv_single("first", "f-first", "A", display_order=0),
            _fv_single("big", "f-big", big_text, display_order=1),
        ])
        result = compile_campaign_state(ver, cfgs, budget_tokens=budget)
        # Первое поле должно попасть, второе — быть исключено.
        assert result.truncated_fields == ["big"]
        assert result.fields[0].included is True
        assert result.fields[1].included is False
        assert result.fields[1].truncated is True

    def test_field_never_split_in_middle(self):
        # Поле размером больше бюджета — должно быть исключено целиком.
        budget = 5
        cfgs = [_cfg("alpha", "Альфа")]
        ver = _version([_fv_single("alpha", "f-alpha", "ABCDEFGHIJKLMNOP")])
        result = compile_campaign_state(ver, cfgs, budget_tokens=budget)
        assert result.text == ""
        assert result.truncated_fields == ["alpha"]
        assert result.fields[0].included is False
        assert result.fields[0].truncated is True

    def test_custom_token_counter_is_used(self):
        # Кастомный счётчик: 1 символ = 1 токен. "Альфа (key=alpha, mode=single): ABCDE" = 37 chars.
        # budget=50 → поле должно попасть.
        budget = 50
        cfgs = [_cfg("alpha", "Альфа")]
        ver = _version([_fv_single("alpha", "f-alpha", "ABCDE")])
        result = compile_campaign_state(
            ver, cfgs, budget_tokens=budget, token_counter=lambda s: len(s),
        )
        assert "ABCDE" in result.text
        assert result.fields[0].included is True


# ---------------------------------------------------------------------------
# Бюджет / дефолты
# ---------------------------------------------------------------------------


class TestBudgetDefaults:
    def test_default_budget_is_800(self):
        assert DEFAULT_TOKEN_BUDGET == 800

    def test_default_token_counter_is_ceil_div4(self):
        # 4 символа → 1 токен по ceil(4/4).
        assert default_token_counter("abcd") == 1
        # 5 символов → 2 токена.
        assert default_token_counter("abcde") == 2
        # 0 символов → 0 токенов.
        assert default_token_counter("") == 0


# ---------------------------------------------------------------------------
# Async: budget loader
# ---------------------------------------------------------------------------


class TestBudgetLoader:
    @pytest.mark.asyncio
    async def test_falls_back_when_db_none(self):
        budget = await get_campaign_state_token_budget(db=None)
        assert budget == DEFAULT_TOKEN_BUDGET
