"""fix documents.id, tags.id, document_labels FK columns: VARCHAR(36) -> UUID

Revision ID: 0013_fix_documents_tags_uuid
Revises: 0012_fix_tags_campaign_id_type
Create Date: 2026-06-01

Problem:
  Migrations 0010-0011 created the following columns as VARCHAR(36):
    - tags.id              (M04) - no server_default
    - documents.id         (M01) - server_default=gen_random_uuid()::text  (STRING)
    - document_labels.document_id  (M02)
    - document_labels.tag_id       (M03)

  The ORM declares all of them as UUID(as_uuid=True).
  PostgreSQL refuses: "operator does not exist: character varying = uuid"

  IMPORTANT: documents.id has a STRING server_default (gen_random_uuid()::text).
  PostgreSQL cannot auto-cast a text DEFAULT to UUID type.
  Fix: DROP DEFAULT first, ALTER TYPE, then SET DEFAULT gen_random_uuid().

Note on campaign_tags:
  Not created by any migration - only in ORM via Table(...) / create_all.
  All campaign_tags FK ops are guarded by _table_exists().
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision = "0013_fix_documents_tags_uuid"
down_revision = "0012_fix_tags_campaign_id_type"
branch_labels = None
depends_on = None

_UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def _col_type(conn, table: str, column: str) -> str | None:
    row = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row[0].lower() if row else None


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    ).fetchone())


def _constraint_exists(conn, table: str, constraint: str) -> bool:
    return bool(conn.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint c "
            "JOIN pg_class r ON r.oid = c.conrelid "
            "WHERE r.relname = :t AND c.conname = :n "
            "AND r.relnamespace = 'public'::regnamespace"
        ),
        {"t": table, "n": constraint},
    ).fetchone())


def _drop_all_fk_to(conn, referenced_table: str) -> None:
    """Drop all FK constraints from any table that reference `referenced_table`.
    Uses a PL/pgSQL loop to avoid hardcoding auto-generated constraint names."""
    conn.execute(sa.text(f"""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN
                SELECT c.conname, c.conrelid::regclass::text AS tbl
                FROM pg_constraint c
                JOIN pg_class rc ON rc.oid = c.confrelid
                JOIN pg_namespace n ON n.oid = rc.relnamespace
                WHERE rc.relname = '{referenced_table}'
                  AND n.nspname = 'public'
                  AND c.contype = 'f'
            LOOP
                EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', r.tbl, r.conname);
            END LOOP;
        END;
        $$;
    """))


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # Step 1: drop document_labels first (FK deps on both tags.id & documents.id)
    # ------------------------------------------------------------------
    if _table_exists(conn, "document_labels"):
        op.drop_table("document_labels")

    # ------------------------------------------------------------------
    # Step 2: fix tags.id  VARCHAR(36) -> UUID
    # tags.id has NO server_default (created in 0010 without one),
    # so no DEFAULT handling needed here.
    # ------------------------------------------------------------------
    if _col_type(conn, "tags", "id") in ("character varying", "varchar", "character", "text"):
        # Nullify non-UUID values (defensive)
        conn.execute(sa.text(
            f"UPDATE tags SET id = NULL WHERE id IS NOT NULL AND id !~ '{_UUID_RE}'"
        ))

        # Drop all FK constraints referencing tags.id (auto-named, use loop)
        _drop_all_fk_to(conn, "tags")

        conn.execute(sa.text(
            "ALTER TABLE tags ALTER COLUMN id TYPE UUID USING id::uuid"
        ))

        # Restore FK from campaign_tags.tag_id only if the table exists
        if _table_exists(conn, "campaign_tags"):
            conn.execute(sa.text(
                "ALTER TABLE campaign_tags "
                "ADD CONSTRAINT fk_campaign_tags_tag_id "
                "FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE"
            ))

    # ------------------------------------------------------------------
    # Step 3: fix documents.id  VARCHAR(36) -> UUID
    #
    # IMPORTANT: documents.id was created in 0011 with
    #   server_default=sa.text("gen_random_uuid()::text")
    # PostgreSQL cannot cast a text/varchar DEFAULT to UUID automatically.
    # We must:
    #   1. DROP the existing DEFAULT
    #   2. ALTER COLUMN TYPE
    #   3. SET a proper UUID DEFAULT
    # ------------------------------------------------------------------
    if _col_type(conn, "documents", "id") in ("character varying", "varchar", "character", "text"):
        # Nullify invalid UUID values (defensive)
        conn.execute(sa.text(
            f"UPDATE documents SET id = NULL WHERE id IS NOT NULL AND id !~ '{_UUID_RE}'"
        ))

        # Drop FK constraints referencing documents.id
        _drop_all_fk_to(conn, "documents")

        # Step 3a: DROP the string server_default BEFORE altering the type
        conn.execute(sa.text(
            "ALTER TABLE documents ALTER COLUMN id DROP DEFAULT"
        ))

        # Step 3b: cast VARCHAR -> UUID
        conn.execute(sa.text(
            "ALTER TABLE documents ALTER COLUMN id TYPE UUID USING id::uuid"
        ))

        # Step 3c: restore a proper UUID default
        conn.execute(sa.text(
            "ALTER TABLE documents ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        ))

    # ------------------------------------------------------------------
    # Step 4: re-create document_labels with proper UUID FK types
    # ------------------------------------------------------------------
    if not _table_exists(conn, "document_labels"):
        op.create_table(
            "document_labels",
            sa.Column(
                "document_id",
                UUID(as_uuid=True),
                sa.ForeignKey("documents.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "tag_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tags.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )

    # ------------------------------------------------------------------
    # Step 5: ensure uq_tag_name_domain exists
    # ------------------------------------------------------------------
    if not _constraint_exists(conn, "tags", "uq_tag_name_domain"):
        conn.execute(sa.text(
            "ALTER TABLE tags "
            "ADD CONSTRAINT uq_tag_name_domain UNIQUE (name, domain_id)"
        ))


def downgrade() -> None:
    conn = op.get_bind()

    # Drop document_labels
    if _table_exists(conn, "document_labels"):
        op.drop_table("document_labels")

    # Revert documents.id UUID -> VARCHAR(36)
    if _col_type(conn, "documents", "id") == "uuid":
        conn.execute(sa.text(
            "ALTER TABLE documents ALTER COLUMN id DROP DEFAULT"
        ))
        conn.execute(sa.text(
            "ALTER TABLE documents ALTER COLUMN id TYPE VARCHAR(36) USING id::text"
        ))
        conn.execute(sa.text(
            "ALTER TABLE documents ALTER COLUMN id SET DEFAULT gen_random_uuid()::text"
        ))

    # Revert tags.id UUID -> VARCHAR(36)
    if _col_type(conn, "tags", "id") == "uuid":
        _drop_all_fk_to(conn, "tags")
        conn.execute(sa.text(
            "ALTER TABLE tags ALTER COLUMN id TYPE VARCHAR(36) USING id::text"
        ))
        if _table_exists(conn, "campaign_tags"):
            conn.execute(sa.text(
                "ALTER TABLE campaign_tags "
                "ADD CONSTRAINT fk_campaign_tags_tag_id "
                "FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE"
            ))

    # Re-create document_labels with VARCHAR(36) types (0011 state)
    if not _table_exists(conn, "document_labels"):
        op.create_table(
            "document_labels",
            sa.Column(
                "document_id",
                sa.String(36),
                sa.ForeignKey("documents.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "tag_id",
                sa.String(36),
                sa.ForeignKey("tags.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )
