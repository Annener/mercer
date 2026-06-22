"""remove_dead_platform_settings

Deletes platform_settings rows that are no longer used in code:
  - retrieval.reranker_enabled: never read; reranker is controlled via
    rerank_models table (is_active / enabled flags).
  - reranker.enabled / .provider / .base_url / .model_name: already removed
    from code in migration 0018, but rows may still exist in older DBs
    that were created before 0018 ran (or if 0018 INSERT-seeded them).

Revision ID: 0021_remove_dead_platform_settings
Revises: 0020_add_watchdog_setting
Create Date: 2026-06-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0021_remove_dead_platform_settings"
down_revision = "0020_add_watchdog_setting"
branch_labels = None
depends_on = None

_DEAD_KEYS = [
    "retrieval.reranker_enabled",
    "reranker.enabled",
    "reranker.provider",
    "reranker.base_url",
    "reranker.model_name",
]


def upgrade() -> None:
    platform_settings = sa.table(
        "platform_settings",
        sa.column("key", sa.String),
    )
    op.execute(
        platform_settings.delete().where(
            platform_settings.c.key.in_(_DEAD_KEYS)
        )
    )


def downgrade() -> None:
    """Re-insert removed rows with their original default values."""
    platform_settings = sa.table(
        "platform_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
        sa.column("group_name", sa.String),
        sa.column("label", sa.String),
        sa.column("hint", sa.Text),
    )
    op.bulk_insert(platform_settings, [
        {
            "key": "retrieval.reranker_enabled",
            "value": "false",
            "value_type": "bool",
            "group_name": "retrieval",
            "label": "Переранжирование",
            "hint": "Включает переранжирование результатов поиска для повышения релевантности.",
        },
        {
            "key": "reranker.enabled",
            "value": "false",
            "value_type": "bool",
            "group_name": "reranker",
            "label": "Включить reranker",
            "hint": "Требует настройки провайдера ниже.",
        },
        {
            "key": "reranker.provider",
            "value": "",
            "value_type": "str",
            "group_name": "reranker",
            "label": "Провайдер reranker",
            "hint": "Например: cohere, jina.",
        },
        {
            "key": "reranker.base_url",
            "value": "",
            "value_type": "str",
            "group_name": "reranker",
            "label": "URL reranker",
            "hint": "URL API reranker-провайдера.",
        },
        {
            "key": "reranker.model_name",
            "value": "",
            "value_type": "str",
            "group_name": "reranker",
            "label": "Модель reranker",
            "hint": "Название reranker-модели у провайдера.",
        },
    ])
