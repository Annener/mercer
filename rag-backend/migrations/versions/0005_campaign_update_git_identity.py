"""Add git author identity fields to vaults table.

Revision ID: 0005_campaign_git_identity
Revises: 0004_fulldoc_jsonb_fix
Create Date: 2026-07-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_campaign_git_identity"
down_revision = "0004_fulldoc_jsonb_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vaults",
        sa.Column("git_author_name", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "vaults",
        sa.Column("git_author_email", sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vaults", "git_author_email")
    op.drop_column("vaults", "git_author_name")
