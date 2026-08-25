"""Test that CampaignStateValue model has composite PK.

Regression test for the schema bug: original migration 0008 declared
version_id as primary_key=True (single column). The model now declares
both version_id and field_id as primary_key=True (composite).
"""
from __future__ import annotations

from app.db.models import CampaignStateValue


def test_campaign_state_value_pk_is_composite() -> None:
    """PK должен быть (version_id, field_id), не только version_id."""
    pk_columns = list(CampaignStateValue.__table__.primary_key.columns)
    column_names = {col.name for col in pk_columns}
    assert "version_id" in column_names, (
        f"PK must include version_id, got: {column_names}"
    )
    assert "field_id" in column_names, (
        f"PK must include field_id (composite key), got: {column_names}. "
        "Single-column PK on version_id was the original bug — multi-row "
        "INSERT fails on the 2nd row with Key (version_id) already exists."
    )
    assert len(pk_columns) == 2, (
        f"Expected exactly 2 columns in composite PK, got {len(pk_columns)}: "
        f"{column_names}"
    )
