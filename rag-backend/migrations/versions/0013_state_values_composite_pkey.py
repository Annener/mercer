"""Make campaign_state_values PK composite (version_id, field_id).

Schema bug fix: original migration 0008 declared version_id as
primary_key=True, creating single-column PK. This is wrong because
apply_initial inserts multiple rows with the same version_id and
different field_ids, which violates single-column PK on the 2nd
row of a multi-row INSERT (Key (version_id) already exists).

Fix: PK should be (version_id, field_id) — one row per (version, field).
This matches the semantic: a state version is a snapshot of values
across multiple fields, so each (version, field) pair needs its own row.

Bug repro (before fix):
    apply_initial creates CampaignStateVersion X.
    values_rows = [
        {"version_id": X, "field_id": A, "text": ...},
        {"version_id": X, "field_id": B, "text": ...},
    ]
    INSERT INTO campaign_state_values VALUES (X, A, ...), (X, B, ...)
    → 1st row OK, 2nd row fails with Key (version_id)=(X) already exists.

After this migration, the PK enforces uniqueness on (version_id, field_id)
and the multi-row INSERT works correctly.

Revision ID: 0013_state_values_composite_pkey
Revises: 0012_grounded_knobs
Create Date: 2026-08-25
"""
from __future__ import annotations

from alembic import op

revision = "0013_state_values_composite_pkey"
down_revision = "0012_grounded_knobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE campaign_state_values "
        "DROP CONSTRAINT campaign_state_values_pkey"
    )
    op.execute(
        "ALTER TABLE campaign_state_values "
        "ADD PRIMARY KEY (version_id, field_id)"
    )


def downgrade() -> None:
    # WARNING: downgrade restores broken single-column PK. After downgrade,
    # any insert with multiple rows sharing the same version_id will fail.
    op.execute(
        "ALTER TABLE campaign_state_values "
        "DROP CONSTRAINT campaign_state_values_pkey"
    )
    op.execute(
        "ALTER TABLE campaign_state_values "
        "ADD PRIMARY KEY (version_id)"
    )
