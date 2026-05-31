"""add_campaign_id_to_chats

Revision ID: 0003_add_campaign_id_to_chats
Revises: 0002_refactor_tags_documents_remove_worlds
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_add_campaign_id_to_chats"
down_revision = "0002_refactor_tags_documents_remove_worlds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_chats_campaign", "chats", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("idx_chats_campaign", table_name="chats")
    op.drop_column("chats", "campaign_id")
