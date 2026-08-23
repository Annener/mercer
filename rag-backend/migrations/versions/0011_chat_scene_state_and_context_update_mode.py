"""Add chat.metadata JSONB and context_update_mode flag.

- chat.metadata: arbitrary JSON for inline scene-state memory managed by the
  agent loop via the `update_scene_state` tool. Initial value is `{}` so
  callers can safely read keys that may be absent.
- chat.context_update_mode: master switch for the model-proposed context
  update flow. When True, the agent loop gains the `propose_context_update`
  tool and may emit proposal cards for user review. Defaults to False to
  preserve existing behaviour.

Revision ID: 0011_chat_scene_state_and_context_update_mode
Revises: 0010_message_sources
Create Date: 2026-08-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_chat_scene_state_and_context_update_mode"
down_revision = "0010_message_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "chats",
        sa.Column(
            "context_update_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chats", "context_update_mode")
    op.drop_column("chats", "metadata")