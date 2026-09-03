"""Add drift loop control flags to platform_settings.

Closes the gap where drift/draft loop ran unconditionally after every turn
for chats with ``campaign_id``. Three platform-level booleans now control
the behaviour:

- ``drift.enabled`` — master switch. If false, neither detect nor draft
  planning starts (and the idle scan is skipped too).
- ``drift.detect_enabled`` — only the detector. Useful to keep the
  ``scene_state.drift`` record fresh even when auto-drafting is off.
- ``drift.draft_enabled`` — only the drafter (reads detector hints and
  builds a state_patch).

Defaults are true so behaviour is unchanged for existing installations.

Revision ID: 0017_drift_loop_enabled
Revises: 0016_drift_model_qvikhr
Create Date: 2026-09-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_drift_loop_enabled"
down_revision = "0016_drift_model_qvikhr"
branch_labels = None
depends_on = None


_DRIFT_SETTINGS: list[dict[str, str]] = [
    {
        "key": "drift.enabled",
        "value": "true",
        "value_type": "bool",
        "group_name": "drift",
        "label": "Drift loop: главный переключатель",
        "hint": (
            "Если выключено — фоновое сравнение сообщений с Campaign State "
            "и планирование draft полностью остановлены. "
            "В этом режиме карточка «Возможные обновления» в чате не появится."
        ),
    },
    {
        "key": "drift.detect_enabled",
        "value": "true",
        "value_type": "bool",
        "group_name": "drift",
        "label": "Drift detection",
        "hint": (
            "Сравнивать последние сообщения чата с Campaign State и сохранять "
            "drift hints в scene_state. Если выключено — детектор не вызывается, "
            "но draft loop при этом тоже останавливается."
        ),
    },
    {
        "key": "drift.draft_enabled",
        "value": "true",
        "value_type": "bool",
        "group_name": "drift",
        "label": "Auto-draft на основе drift hints",
        "hint": (
            "Планировать state_patch на основе drift hints и сохранять в Redis "
            "(TTL 3 часа). Карточка «Возможные обновления» появляется только "
            "если этот флаг включён."
        ),
    },
]


def upgrade() -> None:
    for row in _DRIFT_SETTINGS:
        op.execute(
            sa.text(
                "INSERT INTO platform_settings "
                "(key, value, value_type, group_name, label, hint) "
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


def downgrade() -> None:
    keys = [row["key"] for row in _DRIFT_SETTINGS]
    op.execute(
        sa.text("DELETE FROM platform_settings WHERE key = ANY(:keys)").bindparams(
            keys=keys
        )
    )
