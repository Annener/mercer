"""Add actor and payload columns to audit_logs table.

Revision ID: 0006_audit_log_actor_payload
Revises: 0005_campaign_git_identity
Create Date: 2026-07-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_audit_log_actor_payload"
down_revision = "0005_campaign_git_identity"
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
