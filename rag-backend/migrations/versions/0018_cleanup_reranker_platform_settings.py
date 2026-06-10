"""cleanup: delete legacy reranker.* keys from platform_settings

Revision ID: 0018_cleanup_reranker_platform_settings
Revises: 0017_add_rerank_models
Create Date: 2026-06-10

Почему: плоские ключи reranker.enabled / reranker.provider /
reranker.base_url / reranker.model_name больше не используются:
конфигурация reranker-моделей перенесена в таблицу rerank_models
(шаг 1, миграция 0017). Ключ retrieval.reranker_enabled не трогаем.

Downgrade: восстанавливаем записи с дефолтными значениями.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_cleanup_reranker_platform_settings"
down_revision = "0017_add_rerank_models"
branch_labels = None
depends_on = None


_LEGACY_KEYS = (
    "reranker.enabled",
    "reranker.provider",
    "reranker.base_url",
    "reranker.model_name",
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM platform_settings WHERE key LIKE 'reranker.%'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    defaults = [
        {"key": "reranker.enabled",    "value": "false", "value_type": "bool", "group_name": "reranker", "label": "Включить reranker",       "hint": "Требует настройки провайдера ниже."},
        {"key": "reranker.provider",   "value": "",      "value_type": "str",  "group_name": "reranker", "label": "Провайдер reranker",     "hint": "Например: cohere, jina."},
        {"key": "reranker.base_url",   "value": "",      "value_type": "str",  "group_name": "reranker", "label": "URL reranker",             "hint": "URL API reranker-провайдера."},
        {"key": "reranker.model_name", "value": "",      "value_type": "str",  "group_name": "reranker", "label": "Модель reranker",          "hint": "Название reranker-модели у провайдера."},
    ]
    for row in defaults:
        conn.execute(
            sa.text(
                "INSERT INTO platform_settings (key, value, value_type, group_name, label, hint) "
                "VALUES (:key, :value, :value_type, :group_name, :label, :hint) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            row,
        )
