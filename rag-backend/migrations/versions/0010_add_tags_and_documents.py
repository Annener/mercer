"""add tags and documents tables

Revision ID: 0010_add_tags_and_documents
Revises: 0009_campaigns_schema_sync
Create Date: 2026-06-01

Changes:
  - CREATE TABLE tags
  - CREATE TABLE documents
  - ALTER TABLE platform_settings: value TEXT -> JSONB (USING value::jsonb)
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0010_add_tags_and_documents"
down_revision = "0009_campaigns_schema_sync"
branch_labels = None
depends_on = None


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t AND table_schema = 'public'"
        ),
        {"t": table},
    ).fetchone())


def _col_type(conn, table: str, column: str) -> str | None:
    row = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c AND table_schema = 'public'"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row[0] if row else None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Таблица tags
    if not _table_exists(conn, "tags"):
        op.create_table(
            "tags",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("domain_id", sa.String(64), nullable=False),
            sa.Column("campaign_id", sa.String(36), nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    # 2. Таблица documents
    if not _table_exists(conn, "documents"):
        op.create_table(
            "documents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("domain_id", sa.String(64), nullable=False),
            sa.Column("campaign_id", sa.String(36), nullable=True),
            sa.Column("file_path", sa.String(1000), nullable=True),
            sa.Column("file_type", sa.String(50), nullable=True),
            sa.Column("file_size", sa.BigInteger(), nullable=True),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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

    # 3. Конвертация platform_settings.value: TEXT -> JSONB
    # Используем явный USING, т.к. PostgreSQL не кастует TEXT->JSONB автоматически
    col_type = _col_type(conn, "platform_settings", "value")
    if col_type and col_type.lower() == "text":
        conn.execute(sa.text(
            "ALTER TABLE platform_settings "
            "ALTER COLUMN value TYPE JSONB USING value::jsonb"
        ))


def downgrade() -> None:
    conn = op.get_bind()

    # 3. Откат: JSONB -> TEXT
    col_type = _col_type(conn, "platform_settings", "value")
    if col_type and col_type.lower() == "jsonb":
        conn.execute(sa.text(
            "ALTER TABLE platform_settings "
            "ALTER COLUMN value TYPE TEXT USING value::text"
        ))

    # 2. Удаляем documents
    if _table_exists(conn, "documents"):
        op.drop_table("documents")

    # 1. Удаляем tags
    if _table_exists(conn, "tags"):
        op.drop_table("tags")
