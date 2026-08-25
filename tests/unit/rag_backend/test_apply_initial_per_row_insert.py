"""Tests for per-row INSERT behavior in apply_initial / apply_patch.

Background:
    campaign_state_values table in production has PK on version_id alone
    (single column), not composite (version_id, field_id). Multi-row
    INSERT with the same version_id and different field_ids fails on the
    2nd row with `Key (version_id) already exists`. The fix is to insert
    one row at a time (per-row INSERT).

We test by:
    1. Static analysis: verify the source uses per-row INSERT (no
       multi-row insert with values_rows).
    2. Build-level: verify _build_initial_state_rows produces multi-row
       values_rows (regression test for the upstream).
    3. SQL compilation: verify the actual SQL emitted for a single-row
       INSERT is correct.
"""
from __future__ import annotations

import re
import uuid
from unittest.mock import MagicMock

from app.db.models import CampaignStateValue
from app.services.campaign_state_value_service import (
    _build_initial_state_rows,
)
from sqlalchemy import insert

from shared_contracts.models import (
    CampaignStateInitialFieldStatus,
    CampaignStateInitialProposal,
    CampaignStateInitialProposalField,
    CampaignStateInitialSingleValue,
)


def _make_field_row(key: str) -> MagicMock:
    """MagicMock с нужными атрибутами для _build_initial_state_rows."""
    f = MagicMock()
    f.id = uuid.uuid4()
    f.key = key
    f.mode = "single"
    f.enabled = True
    return f


def _make_proposal_two_singles() -> CampaignStateInitialProposal:
    return CampaignStateInitialProposal(
        fields=[
            CampaignStateInitialProposalField(
                field_key="field_a",
                mode="single",
                status=CampaignStateInitialFieldStatus(status="proposed"),
                single_value=CampaignStateInitialSingleValue(text="value A"),
            ),
            CampaignStateInitialProposalField(
                field_key="field_b",
                mode="single",
                status=CampaignStateInitialFieldStatus(status="proposed"),
                single_value=CampaignStateInitialSingleValue(text="value B"),
            ),
        ],
        questions=[],
    )


def test_build_initial_state_rows_two_singles_have_distinct_field_ids() -> None:
    """Regression: values_rows для 2 single-полей имеет 2 строки
    с разными field_id и одним version_id.

    Это и есть условие, при котором multi-row INSERT ломался бы.
    """
    vid = uuid.uuid4()
    field_a = _make_field_row("field_a")
    field_b = _make_field_row("field_b")
    fields_by_key = {"field_a": field_a, "field_b": field_b}

    proposal = _make_proposal_two_singles()
    values_rows, items_rows = _build_initial_state_rows(
        proposal, fields_by_key, vid
    )

    assert items_rows == []
    assert len(values_rows) == 2
    assert all(r["version_id"] == vid for r in values_rows)
    field_ids = {r["field_id"] for r in values_rows}
    assert field_ids == {field_a.id, field_b.id}, (
        f"Both rows should have distinct field_ids, got {field_ids}"
    )
    texts = {r["text"] for r in values_rows}
    assert texts == {"value A", "value B"}


def test_single_row_insert_sql_compiles_to_one_value_tuple() -> None:
    """Per-row INSERT даёт SQL с одной строкой в VALUES.

    Это контраст с multi-row INSERT, который компилируется в
    `VALUES (...), (...), ...`.
    """
    version_id = uuid.uuid4()
    field_id = uuid.uuid4()
    row = {
        "version_id": version_id,
        "field_id": field_id,
        "text": "hello",
        "source_refs": [],
    }
    # Имитируем per-row: передаём list с одним dict.
    stmt = insert(CampaignStateValue).values([row])
    compiled = str(stmt.compile())
    # Считаем tuples по уникальному marker'у ":text_m" — каждое tuple
    # в multi-row VALUES получает индекс _m0, _m1, ...
    tuple_count = compiled.count(":text_m")
    assert tuple_count == 1, (
        f"Expected 1 tuple in VALUES (per-row INSERT), got {tuple_count} "
        f"in: {compiled}"
    )


def test_multi_row_insert_sql_compiles_to_multiple_value_tuples() -> None:
    """Multi-row INSERT даёт SQL с несколькими tuples в VALUES (regression test).

    Это то, что было ДО фикса и ломалось в production.
    """
    version_id = uuid.uuid4()
    field_a = uuid.uuid4()
    field_b = uuid.uuid4()
    rows = [
        {
            "version_id": version_id,
            "field_id": field_a,
            "text": "hello A",
            "source_refs": [],
        },
        {
            "version_id": version_id,
            "field_id": field_b,
            "text": "hello B",
            "source_refs": [],
        },
    ]
    stmt = insert(CampaignStateValue).values(rows)
    compiled = str(stmt.compile())
    tuple_count = compiled.count(":text_m")
    assert tuple_count == 2, (
        f"Expected 2 tuples in multi-row INSERT, got {tuple_count}: "
        f"{compiled}"
    )


def test_apply_initial_source_uses_per_row_insert() -> None:
    """Static analysis: apply_initial НЕ использует multi-row INSERT
    для campaign_state_values (защита от regression).
    """
    from pathlib import Path

    src_path = (
        Path(__file__).parent.parent.parent.parent
        / "rag-backend"
        / "app"
        / "services"
        / "campaign_state_value_service.py"
    )
    src = src_path.read_text()

    # Ищем блок apply_initial — от "async def apply_initial" до
    # следующего "async def " или конца класса.
    m = re.search(
        r"async def apply_initial\((.*?)(?=\n    async def |\nclass |\Z)",
        src,
        re.DOTALL,
    )
    assert m, "Couldn't find apply_initial in source"
    body = m.group(1)

    # Внутри apply_initial не должно быть multi-row INSERT.
    has_per_row = re.search(
        r"for\s+\w+\s+in\s+values_rows_final\s*:.*?insert\(CampaignStateValue\)\.values\(\[",
        body,
        re.DOTALL,
    )
    assert has_per_row, (
        "apply_initial must use per-row INSERT for campaign_state_values."
    )

    # Anti-regression: НЕ должно быть multi-row insert.
    has_multi_row = re.search(
        r"insert\(CampaignStateValue\)\.values\(values_rows_final\)",
        body,
    )
    assert not has_multi_row, (
        "apply_initial must NOT use multi-row INSERT. "
        "Found: insert(CampaignStateValue).values(values_rows_final)"
    )


def test_apply_patch_source_uses_per_row_insert_for_values() -> None:
    """Static analysis: apply_patch тоже использует per-row INSERT
    для values (для будущей совместимости с composite PK миграцией).
    """
    from pathlib import Path

    src_path = (
        Path(__file__).parent.parent.parent.parent
        / "rag-backend"
        / "app"
        / "services"
        / "campaign_state_value_service.py"
    )
    src = src_path.read_text()

    # Ищем блок apply_patch.
    m = re.search(
        r"async def apply_patch\((.*?)(?=\n    async def |\nclass |\Z)",
        src,
        re.DOTALL,
    )
    assert m, "Couldn't find apply_patch in source"
    body = m.group(1)

    # В apply_patch не должно быть multi-row insert в values.
    has_per_row_values = re.search(
        r"for\s+\w+\s+in\s+value_rows\s*:.*?insert\(CampaignStateValue\)\.values\(\[",
        body,
        re.DOTALL,
    )
    assert has_per_row_values, (
        "apply_patch must use per-row INSERT for campaign_state_values."
    )
