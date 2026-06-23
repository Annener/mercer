"""add_semantic_threshold

Adds semantic_threshold column to vaults table.
Existing rows receive the default value 0.3.

Revision ID: 0022_add_semantic_threshold
Revises: 0021_remove_dead_platform_settings
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0022_add_semantic_threshold"
down_revision = "0021_remove_dead_platform_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: add nullable column (safe for existing rows)
    op.add_column("vaults", sa.Column("semantic_threshold", sa.Float(), nullable=True))
    # Step 2: backfill existing rows with the default value
    op.execute("UPDATE vaults SET semantic_threshold = 0.3 WHERE semantic_threshold IS NULL")
    # Step 3: make NOT NULL with server default
    op.alter_column(
        "vaults",
        "semantic_threshold",
        nullable=False,
        server_default="0.3",
    )


def downgrade() -> None:
    op.drop_column("vaults", "semantic_threshold")
