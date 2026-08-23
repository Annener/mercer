"""Stage 8.2: retrieval tool settings for conditional/cyclic RAG.

Adds platform settings that govern the agent loop behaviour in chat:
- retrieval.tool_enabled: master switch for the search_knowledge tool.
- retrieval.policy: 'grounded' (default; model must use evidence) or
  'assistive' (model may or may not call the tool).
- retrieval.max_rounds_chat: max number of tool-call rounds per chat turn
  in 'grounded' mode (per spec §12.2).
- retrieval.max_rounds_assistive: same but for 'assistive' mode.
- retrieval.evidence_token_budget: max tokens of evidence per round,
  enforced by the host before sending tool_result back to the model.

Revision ID: 0009_retrieval_tool_settings
Revises: 0008_campaign_state_versions
Create Date: 2026-08-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_retrieval_tool_settings"
down_revision = "0008_campaign_state_versions"
branch_labels = None
depends_on = None


_RETRIEVAL_TOOL_SETTINGS: list[dict[str, str]] = [
    {
        "key": "retrieval.tool_enabled",
        "value": "true",
        "value_type": "bool",
        "group_name": "retrieval",
        "label": "Tool: поиск в базе знаний",
        "hint": (
            "Главный переключатель tool-вызова search_knowledge в чате. "
            "Если выключено — модель не получает tool, и чат работает как раньше."
        ),
    },
    {
        "key": "retrieval.policy",
        "value": "grounded",
        "value_type": "str",
        "group_name": "retrieval",
        "label": "Retrieval policy",
        "hint": (
            "assistive — модель решает, нужен ли поиск. "
            "grounded — модель обязана искать evidence для фактов и лора."
        ),
    },
    {
        "key": "retrieval.max_rounds_chat",
        "value": "2",
        "value_type": "int",
        "group_name": "retrieval",
        "label": "Макс. раундов поиска (grounded)",
        "hint": "Сколько раз модель может вызвать search_knowledge за один turn в grounded-режиме.",
    },
    {
        "key": "retrieval.max_rounds_assistive",
        "value": "1",
        "value_type": "int",
        "group_name": "retrieval",
        "label": "Макс. раундов поиска (assistive)",
        "hint": "Сколько раз модель может вызвать search_knowledge за один turn в assistive-режиме.",
    },
    {
        "key": "retrieval.evidence_token_budget",
        "value": "4000",
        "value_type": "int",
        "group_name": "retrieval",
        "label": "Бюджет токенов evidence",
        "hint": (
            "Максимальный размер evidence, который хост отдаёт модели за один tool_call. "
            "Защищает prompt от раздувания."
        ),
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    settings_table = sa.table(
        "platform_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
        sa.column("group_name", sa.String),
        sa.column("label", sa.String),
        sa.column("hint", sa.Text),
    )
    # Идемпотентный insert: ON CONFLICT DO NOTHING по ключу.
    for row in _RETRIEVAL_TOOL_SETTINGS:
        op.execute(
            sa.text(
                "INSERT INTO platform_settings (key, value, value_type, group_name, label, hint) "
                "VALUES (:key, :value, :value_type, :group_name, :label, :hint) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(
                key=row["key"],
                value=row["value"],
                value_type=row["value_type"],
                group_name=row["group_name"],
                label=row["label"],
                hint=row["hint"],
            )
        )
    # bulk_insert оставлен для документации; фактически используем ON CONFLICT.
    del settings_table, bind


def downgrade() -> None:
    keys = [row["key"] for row in _RETRIEVAL_TOOL_SETTINGS]
    op.execute(
        sa.text("DELETE FROM platform_settings WHERE key = ANY(:keys)").bindparams(keys=keys)
    )
