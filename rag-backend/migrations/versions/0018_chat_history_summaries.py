"""Add chat_history_summaries table — Phase 3 rolling-summary compression.

Phase 3 of context-engine refactor: chat history compression.

Drift-detection сравнивает последние сообщения чата с Campaign State.
Со временем история растёт и перестаёт влезать в контекстное окно
локальной QVikhr (4096 токенов). Вместо того чтобы каждый раз резать
входные данные chunked-loop-ом, мы периодически (раз в 4 несжатых
сообщения) прогоняем старый блок сообщений через тот же QVikhr и
сохраняем «running summary» в Postgres. Drift-detector затем использует
этот summary + только последние 4 сообщения как контекст.

Одна строка на чат (``PRIMARY KEY chat_id``), перезаписывается при
следующем summarization. Никаких новых settings-ключей — поведение
включается автоматически когда в чате появляется drift-detector.

Revision ID: 0018_chat_history_summaries
Revises: 0017_drift_loop_enabled
Create Date: 2026-09-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0018_chat_history_summaries"
down_revision = "0017_drift_loop_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_history_summaries",
        sa.Column(
            "chat_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chats.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column(
            "summarized_messages_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "summarized_up_to_message_id",
            UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("chat_history_summaries")
