"""fix tags.campaign_id column type VARCHAR -> UUID

Revision ID: 0012_fix_tags_campaign_id_type
Revises: 0011_fix_documents_vault_id
Create Date: 2026-06-01

Problem:
  Migration 0010 created tags.campaign_id as VARCHAR(36).
  The SQLAlchemy ORM model declares it as UUID(as_uuid=True).
  PostgreSQL refuses to compare VARCHAR = UUID without an explicit cast,
  causing: "operator does not exist: character varying = uuid".

Fix:
  Convert tags.campaign_id to native UUID type.
  All existing values are valid UUID strings (or NULL), so ::uuid cast is safe.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision = "0012_fix_tags_campaign_id_type"
down_revision = "0011_fix_documents_vault_id"
branch_labels = None
depends_on = None


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
    col_type = _col_type(conn, "tags", "campaign_id")
    # Only run if the column is still character varying (safe to re-run)
    if col_type and col_type.lower() in ("character varying", "varchar", "text", "character"):
        # Drop FK constraint if it exists (created by 0010 without explicit name)
        conn.execute(sa.text("""
            DO $$
            DECLARE
                _constraint TEXT;
            BEGIN
                SELECT conname INTO _constraint
                FROM pg_constraint
                WHERE conrelid = 'tags'::regclass
                  AND contype = 'f'
                  AND conkey = ARRAY[
                      (SELECT attnum FROM pg_attribute
                       WHERE attrelid = 'tags'::regclass AND attname = 'campaign_id')
                  ]::smallint[];
                IF _constraint IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE tags DROP CONSTRAINT ' || quote_ident(_constraint);
                END IF;
            END;
            $$;
        """))

        # Nullify any values that are not valid UUIDs (defensive)
        conn.execute(sa.text("""
            UPDATE tags
            SET campaign_id = NULL
            WHERE campaign_id IS NOT NULL
              AND campaign_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        """))

        # Cast column to native UUID
        conn.execute(sa.text(
            "ALTER TABLE tags "
            "ALTER COLUMN campaign_id TYPE UUID USING campaign_id::uuid"
        ))

        # Re-add FK to campaigns.id
        conn.execute(sa.text(
            "ALTER TABLE tags "
            "ADD CONSTRAINT fk_tags_campaign_id "
            "FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    col_type = _col_type(conn, "tags", "campaign_id")
    if col_type and col_type.lower() == "uuid":
        # Drop FK
        conn.execute(sa.text(
            "ALTER TABLE tags DROP CONSTRAINT IF EXISTS fk_tags_campaign_id"
        ))
        # Cast back to VARCHAR
        conn.execute(sa.text(
            "ALTER TABLE tags "
            "ALTER COLUMN campaign_id TYPE VARCHAR(36) USING campaign_id::text"
        ))
