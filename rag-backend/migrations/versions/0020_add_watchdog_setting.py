"""Add watchdog_auto_index_extensions to platform_settings.

Revision ID: 0020_add_watchdog_setting
Revises: 0019
Create Date: 2026-06-21

Добавляет глобальную настройку watchdog-а: список расширений файлов,
для которых индексация запускается автоматически при обнаружении изменений.
Значение по умолчанию — '.md,.pdf' (Сценарий 1: всё автоматически).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0020_add_watchdog_setting"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO platform_settings (key, value, value_type, group_name, label, hint)
            VALUES (
                'watchdog_auto_index_extensions',
                '.md,.pdf',
                'str',
                'indexing',
                'Авто-индексация расширений',
                'Расширения файлов через запятую (.md,.pdf). Пусто — только ручная индексация.'
            )
            ON CONFLICT (key) DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM platform_settings WHERE key = 'watchdog_auto_index_extensions';"
        )
    )
