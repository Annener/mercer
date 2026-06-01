"""campaigns schema sync

Revision ID: 0009_campaigns_schema_sync
Revises: 0008_chat_domain_id_not_null
Create Date: 2026-06-01

Дрейф между models.py и реальной схемой campaigns:

Колонки, которые есть в БД, но отсутствуют в модели (лишние — оставляем,
просто убираем конфликтующие):
  - campaign_id  (str) — устаревший бизнес-ключ, DROP
  - world_id     (str) — устаревшее поле, DROP
  - path_prefix  (str) — устаревшее поле, DROP
  - is_active    (bool) — устаревшее поле, DROP
  - updated_at         — в модели нет, DROP

Колонки, которые есть в модели, но отсутствуют в БД (добавляем):
  - system_prompt  TEXT nullable
  - last_session_at TIMESTAMPTZ nullable

Downgrade: обратная операция.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0009_campaigns_schema_sync"
down_revision = "0008_chat_domain_id_not_null"
branch_labels = None
depends_on = None


def _col_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone())


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Добавляем отсутствующие колонки.
    if not _col_exists(conn, "campaigns", "system_prompt"):
        op.add_column("campaigns", sa.Column("system_prompt", sa.Text(), nullable=True))

    if not _col_exists(conn, "campaigns", "last_session_at"):
        op.add_column(
            "campaigns",
            sa.Column("last_session_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 2. Удаляем устаревшие колонки (idempotent через IF EXISTS).
    for col in ("campaign_id", "world_id", "path_prefix", "is_active", "updated_at"):
        if _col_exists(conn, "campaigns", col):
            # Сначала снимаем уникальные ограничения, которые могут ссылаться на эти колонки.
            if col == "campaign_id":
                conn.execute(sa.text(
                    "ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS uq_campaigns_campaign_world"
                ))
            op.drop_column("campaigns", col)


def downgrade() -> None:
    conn = op.get_bind()

    # Восстанавливаем удалённые колонки.
    if not _col_exists(conn, "campaigns", "updated_at"):
        op.add_column(
            "campaigns",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    for col, typ in [
        ("is_active", sa.Boolean()),
        ("path_prefix", sa.String(512)),
        ("world_id", sa.String(64)),
        ("campaign_id", sa.String(64)),
    ]:
        if not _col_exists(conn, "campaigns", col):
            op.add_column("campaigns", sa.Column(col, typ, nullable=True))

    # Удаляем добавленные колонки.
    for col in ("last_session_at", "system_prompt"):
        if _col_exists(conn, "campaigns", col):
            op.drop_column("campaigns", col)
