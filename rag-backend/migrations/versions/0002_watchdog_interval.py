"""Add watchdog.interval_sec to platform_settings.

Revision ID: 0002_watchdog_interval
Revises: 0001_initial
Create Date: 2026-06-27
"""
from __future__ import annotations

from alembic import op

revision = "0002_watchdog_interval"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO platform_settings (key, value, value_type, group_name, label, hint)
        VALUES (
            'watchdog.interval_sec',
            '60',
            'int',
            'watchdog',
            'Интервал сканирования (сек)',
            'Как часто watchdog проверяет изменения в vault-директориях. Минимум 10 секунд.'
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM platform_settings WHERE key = 'watchdog.interval_sec'")
