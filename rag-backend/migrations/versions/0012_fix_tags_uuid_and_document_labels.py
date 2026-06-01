"""fix tags schema and document_labels FK type mismatch

Revision ID: 0012_fix_tags_uuid_and_document_labels
Revises: 0011_fix_documents_vault_id
Create Date: 2026-06-01

Проблема:
  Миграция 0010 создала таблицу tags с id VARCHAR(36).
  Миграция 0011 попыталась создать document_labels с tag_id UUID —
  FK не может ссылаться на VARCHAR-колонку: DatatypeMismatchError.

  Также tags.id не совпадает с ORM-моделью (UUID(as_uuid=True)).

Решение (idempotent):
  1. Дропаем document_labels если есть (мешает ALTER на tags).
  2. Приводим tags.id к UUID через ALTER COLUMN ... USING id::uuid.
  3. Добавляем недостающие столбцы tags.campaign_id (UUID), tags.color,
     UniqueConstraint uq_tag_name_domain — если их ещё нет.
  4. Пересоздаём document_labels с tag_id UUID FK → tags.id.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0012_fix_tags_uuid_and_document_labels"
down_revision = "0011_fix_documents_vault_id"
branch_labels = None
depends_on = None


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:t"
        ),
        {"t": table},
    ).fetchone())


def _col_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).fetchone())


def _col_type(conn, table: str, column: str) -> str | None:
    row = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row[0] if row else None


def _constraint_exists(conn, table: str, constraint: str) -> bool:
    return bool(conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema='public' AND table_name=:t AND constraint_name=:c"
        ),
        {"t": table, "c": constraint},
    ).fetchone())


def upgrade() -> None:
    conn = op.get_bind()

    # ── Шаг 1: дропаем document_labels — мешает ALTER TABLE tags ──────────────
    if _table_exists(conn, "document_labels"):
        op.drop_table("document_labels")

    # ── Шаг 2: приводим tags.id к UUID ────────────────────────────────────────
    if _table_exists(conn, "tags"):
        id_type = _col_type(conn, "tags", "id")
        if id_type and "char" in id_type.lower():
            # Дропаем FK из других таблиц, ссылающиеся на tags.id
            # (campaign_tags.tag_id создан в 0009, тоже VARCHAR — фиксируем)
            if _table_exists(conn, "campaign_tags"):
                op.drop_table("campaign_tags")

            # ALTER tags.id VARCHAR -> UUID
            conn.execute(sa.text(
                "ALTER TABLE tags ALTER COLUMN id TYPE UUID USING id::uuid"
            ))

        # campaign_id: VARCHAR -> UUID если нужно
        if _col_exists(conn, "tags", "campaign_id"):
            cid_type = _col_type(conn, "tags", "campaign_id")
            if cid_type and "char" in cid_type.lower():
                conn.execute(sa.text(
                    "ALTER TABLE tags "
                    "ALTER COLUMN campaign_id TYPE UUID USING campaign_id::uuid"
                ))
        else:
            # Добавляем campaign_id UUID FK -> campaigns.id если не существует
            op.add_column("tags", sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
                nullable=True,
            ))

        # UniqueConstraint(name, domain_id)
        if not _constraint_exists(conn, "tags", "uq_tag_name_domain"):
            op.create_unique_constraint(
                "uq_tag_name_domain", "tags", ["name", "domain_id"]
            )

        # domain_id FK -> domains.domain_id (если FKC ещё нет)
        # (0010 создал domain_id без FK — добавляем ограничение)
        if not _constraint_exists(conn, "tags", "tags_domain_id_fkey"):
            op.create_foreign_key(
                "tags_domain_id_fkey",
                "tags", "domains",
                ["domain_id"], ["domain_id"],
                ondelete="CASCADE",
            )

    # ── Шаг 3: пересоздаём campaign_tags ──────────────────────────────────────
    if not _table_exists(conn, "campaign_tags"):
        op.create_table(
            "campaign_tags",
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "tag_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tags.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )

    # ── Шаг 4: создаём document_labels с правильными UUID FK ─────────────────
    if not _table_exists(conn, "document_labels"):
        op.create_table(
            "document_labels",
            sa.Column(
                "document_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("documents.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "tag_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tags.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "document_labels"):
        op.drop_table("document_labels")
    if _table_exists(conn, "campaign_tags"):
        op.drop_table("campaign_tags")
    # Откат типов — не делаем: потеря данных невозможна (UUID ↔ VARCHAR round-trip)
    # Просто помечаем как no-op для downgrade
