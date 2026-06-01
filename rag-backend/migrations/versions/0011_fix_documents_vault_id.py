"""fix documents table schema — align with ORM model

Revision ID: 0011_fix_documents_vault_id
Revises: 0010_add_tags_and_documents
Create Date: 2026-06-01

Проблема: миграция 0010 создала таблицу documents со старой схемой
(domain_id, content, file_path, file_type, file_size, metadata, updated_at),
тогда как ORM-модель (models.py) ожидает:
  id UUID, vault_id VARCHAR(128) FK→vaults.vault_id,
  source_path TEXT, title VARCHAR(512),
  md5 VARCHAR(32), mtime INTEGER,
  indexed_at TIMESTAMPTZ, status VARCHAR(32),
  created_at TIMESTAMPTZ

Решение: если таблица имеет старую схему (нет vault_id) — дропаем и пересоздаём.
Если vault_id уже существует — пропускаем (idempotent).
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0011_fix_documents_vault_id"
down_revision = "0010_add_tags_and_documents"
branch_labels = None
depends_on = None


def _col_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:t"
        ),
        {"t": table},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "documents"):
        # Таблицы нет вообще — создаём сразу правильную
        _create_documents()
        return

    if _col_exists(conn, "documents", "vault_id"):
        # Уже правильная схема — ничего не делаем
        return

    # Старая схема (domain_id вместо vault_id) — дропаем и пересоздаём.
    # Данных в старой схеме быть не должно (таблица создана в 0010 и никем не заполнялась).
    # document_labels ссылается на documents.id — дропаем её тоже и пересоздаём.
    if _table_exists(conn, "document_labels"):
        op.drop_table("document_labels")

    op.drop_table("documents")
    _create_documents()
    _create_document_labels()


def _create_documents() -> None:
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "vault_id",
            sa.String(128),
            sa.ForeignKey("vaults.vault_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("md5", sa.String(32), nullable=False),
        sa.Column("mtime", sa.Integer(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def _create_document_labels() -> None:
    op.create_table(
        "document_labels",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Откат: возвращаем старую схему из 0010
    if _table_exists(conn, "document_labels"):
        op.drop_table("document_labels")
    if _table_exists(conn, "documents"):
        op.drop_table("documents")

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
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
