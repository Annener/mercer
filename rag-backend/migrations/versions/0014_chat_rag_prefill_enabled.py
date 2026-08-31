"""Add Chat.rag_prefill_enabled flag for per-chat RAG prefetch toggle.

When True (legacy grounded behaviour): a single retrieval is performed
up-front per chat turn and its evidence is injected into system_prompt,
AND round 0 of the agent loop forces a tool call.

When False (default; model-decides behaviour): no prefill; the model only
sees the conversation and decides itself whether to invoke search_knowledge.

Defaults to False so freshly migrated chats opt into the new model-decides
workflow, mirroring the default of the legacy `context_update_mode` flag.

Revision ID: 0014_chat_rag_prefill_enabled
Revises: 0013_state_values_composite_pkey
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_chat_rag_prefill_enabled"
down_revision = "0013_state_values_composite_pkey"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "rag_prefill_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chats", "rag_prefill_enabled")
