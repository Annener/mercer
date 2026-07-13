"""Add full_document_mode fields to chats and size fields to documents.

Revision ID: 0003_fulldoc_fields
Revises: 0002_watchdog_interval
Create Date: 2026-07-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_fulldoc_fields"
down_revision = "0002_watchdog_interval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- chats: full document mode fields ---
    op.add_column(
        "chats",
        sa.Column(
            "full_document_mode_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "chats",
        sa.Column(
            "sent_full_document_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )

    # --- documents: size metadata fields ---
    op.add_column(
        "documents",
        sa.Column("char_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("chunk_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("estimated_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "estimated_tokens")
    op.drop_column("documents", "chunk_count")
    op.drop_column("documents", "char_count")
    op.drop_column("chats", "sent_full_document_ids")
    op.drop_column("chats", "full_document_mode_enabled")
