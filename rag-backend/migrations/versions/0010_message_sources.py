"""Add sources column to messages for persistent source citations.

Stores a deduplicated list of sources (path/page/vault_id/document_id/chunk_id/source_kind)
that contributed to an assistant message. Used to restore the sources block on
chat reload and across `pipeline_confirm` / `full_document_confirm` resumes.

Revision ID: 0010_message_sources
Revises: 0009_retrieval_tool_settings
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_message_sources"
down_revision = "0009_retrieval_tool_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("sources", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "sources")
