"""0010_audit_log_actor_payload

Adds actor (VARCHAR 256) and payload (JSONB) columns to audit_logs table.
The old 'details' column (JSONB) is left intact for backward-compat — data
already stored there will not be migrated automatically.

Revision ID: 0010
Revises: 0005
Create Date: 2026-07-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column("actor", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_logs", "payload")
    op.drop_column("audit_logs", "actor")
