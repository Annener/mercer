"""add_pipeline_id_to_messages

Revision ID: 0004_add_pipeline_id_to_messages
Revises: 0003_add_campaign_id_to_chats
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_add_pipeline_id_to_messages"
down_revision = "0003_add_campaign_id_to_chats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "pipeline_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "pipeline_id")
