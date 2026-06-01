"""fix documents.id, tags.id, document_labels FK columns: VARCHAR(36) -> UUID

Revision ID: 0013_fix_documents_tags_uuid
Revises: 0012_fix_tags_campaign_id_type
Create Date: 2026-06-01

Problem:
  Migrations 0010–0011 created the following columns as VARCHAR(36):
    - tags.id              (M04)
    - documents.id         (M01)
    - document_labels.document_id  (M02)
    - document_labels.tag_id       (M03)

  The SQLAlchemy ORM model declares all of them as UUID(as_uuid=True).
  PostgreSQL refuses to compare VARCHAR = UUID without an explicit cast,
  causing: "operator does not exist: character varying = uuid"
  on any ORM query touching these tables.

  Migration 0012 fixed tags.campaign_id but did NOT touch tags.id.

Note on campaign_tags:
  The campaign_tags association table is NOT created by any migration —
  it exists only in the ORM (created via create_all or a separate mechanism).
  Therefore all campaign_tags FK operations are guarded by _table_exists().

Fix strategy:
  1. Nullify any non-UUID values (defensive).
  2. Drop document_labels (has FK to both documents.id and tags.id).
  3. Drop all FK constraints referencing tags.id (from any table that exists).
  4. Cast tags.id VARCHAR -> UUID.
  5. Re-add FK from campaign_tags.tag_id -> tags.id (only if campaign_tags exists).
  6. Cast documents.id VARCHAR -> UUID.
  7. Re-create document_labels with proper UUID column types.
  8. Re-add tags UniqueConstraint (uq_tag_name_domain) if absent.

All steps are idempotent — safe to re-run.
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


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # Step 1: drop document_labels — depends on both tags.id & documents.id
    # ------------------------------------------------------------------
    if _table_exists(conn, "document_labels"):
        op.drop_table("document_labels")

    # ------------------------------------------------------------------
    # Step 2: fix tags.id  VARCHAR(36) -> UUID
    # ------------------------------------------------------------------
    if _col_type(conn, "tags", "id") in ("character varying", "varchar", "character", "text"):
        # Nullify any rows with non-UUID values (defensive)
        conn.execute(sa.text(
            f"UPDATE tags SET id = NULL WHERE id IS NOT NULL AND id !~ '{_UUID_RE}'"
        ))

        # Drop all FK constraints on tags.id from referencing tables.
        # We use a PL/pgSQL loop to handle auto-generated constraint names.
        # Each EXECUTE is guarded internally by checking if the table exists
        # before attempting the DROP — this avoids errors when campaign_tags
        # or other referencing tables haven't been created yet.
        conn.execute(sa.text("""
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN
                    SELECT c.conname, c.conrelid::regclass::text AS tbl
                    FROM pg_constraint c
                    JOIN pg_class rc ON rc.oid = c.confrelid
                    JOIN pg_namespace n ON n.oid = rc.relnamespace
                    WHERE rc.relname = 'tags'
                      AND n.nspname = 'public'
                      AND c.contype = 'f'
                LOOP
                    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', r.tbl, r.conname);
                END LOOP;
            END;
            $$;
        """))

        conn.execute(sa.text(
            "ALTER TABLE tags ALTER COLUMN id TYPE UUID USING id::uuid"
        ))

        # Re-add FK from campaign_tags.tag_id -> tags.id
        # ONLY if campaign_tags table exists (it is not created by any migration;
        # it may be absent on a fresh DB that hasn't run create_all yet).
        if _table_exists(conn, "campaign_tags"):
            conn.execute(sa.text(
                "ALTER TABLE campaign_tags "
                "ADD CONSTRAINT fk_campaign_tags_tag_id "
                "FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE"
            ))

    # ------------------------------------------------------------------
    # Step 3: fix documents.id  VARCHAR(36) -> UUID
    # ------------------------------------------------------------------
    if _col_type(conn, "documents", "id") in ("character varying", "varchar", "character", "text"):
        # Nullify invalid UUIDs (defensive)
        conn.execute(sa.text(
            f"UPDATE documents SET id = NULL WHERE id IS NOT NULL AND id !~ '{_UUID_RE}'"
        ))

        # Drop any remaining FK constraints pointing to documents.id
        conn.execute(sa.text("""
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN
                    SELECT c.conname, c.conrelid::regclass::text AS tbl
                    FROM pg_constraint c
                    JOIN pg_class rc ON rc.oid = c.confrelid
                    JOIN pg_namespace n ON n.oid = rc.relnamespace
                    WHERE rc.relname = 'documents'
                      AND n.nspname = 'public'
                      AND c.contype = 'f'
                LOOP
                    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', r.tbl, r.conname);
                END LOOP;
            END;
            $$;
        """))

        conn.execute(sa.text(
            "ALTER TABLE documents ALTER COLUMN id TYPE UUID USING id::uuid"
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
    # Step 5: ensure uq_tag_name_domain exists (may have been lost)
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
            "ALTER TABLE documents ALTER COLUMN id TYPE VARCHAR(36) USING id::text"
        ))

    # Revert tags.id UUID -> VARCHAR(36)
    if _col_type(conn, "tags", "id") == "uuid":
        # Drop FKs pointing at tags.id (including campaign_tags if it exists)
        conn.execute(sa.text("""
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN
                    SELECT c.conname, c.conrelid::regclass::text AS tbl
                    FROM pg_constraint c
                    JOIN pg_class rc ON rc.oid = c.confrelid
                    JOIN pg_namespace n ON n.oid = rc.relnamespace
                    WHERE rc.relname = 'tags'
                      AND n.nspname = 'public'
                      AND c.contype = 'f'
                LOOP
                    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', r.tbl, r.conname);
                END LOOP;
            END;
            $$;
        """))

        conn.execute(sa.text(
            "ALTER TABLE tags ALTER COLUMN id TYPE VARCHAR(36) USING id::text"
        ))

        # Restore FK from campaign_tags.tag_id -> tags.id only if it exists
        if _table_exists(conn, "campaign_tags"):
            conn.execute(sa.text(
                "ALTER TABLE campaign_tags "
                "ADD CONSTRAINT fk_campaign_tags_tag_id "
                "FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE"
            ))

    # Re-create document_labels with VARCHAR types (0011 state)
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
