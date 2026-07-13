"""Cast sent_full_document_ids column from json to jsonb.

Revision ID: 0004_fulldoc_jsonb_fix
Revises: 0003_fulldoc_fields
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op

revision = "0004_fulldoc_jsonb_fix"
down_revision = "0003_fulldoc_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chats
            ALTER COLUMN sent_full_document_ids TYPE jsonb
            USING sent_full_document_ids::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE chats
            ALTER COLUMN sent_full_document_ids TYPE json
            USING sent_full_document_ids::text::json
        """
    )
