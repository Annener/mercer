"""platform_settings.value: JSONB -> TEXT

Migration 0010 converted value TEXT -> JSONB.
This caused asyncpg to return raw JSON strings (e.g. '"http://..."' instead
of 'http://...') when the indexer reads settings directly via asyncpg,
bypassing SQLAlchemy. The indexer's _cast_value does not JSON-decode,
so string values arrived with wrapping quotes, breaking URL construction.

Fix: revert to TEXT. Existing JSONB values are unwrapped via (value #>> '{}')
which strips the JSON string quotes: '"http://..."' -> 'http://...',
'"true"' -> 'true', '"180"' -> '180', null -> NULL.

Revision ID: 0016_platform_settings_value_jsonb_to_text
Revises: 0015_fix_messages_pipeline_id_type
Create Date: 2026-06-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_platform_settings_value_jsonb_to_text"
down_revision = "0015_fix_messages_pipeline_id_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Check current column type
    row = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'platform_settings' AND column_name = 'value'"
        )
    ).fetchone()
    if row and row[0].lower() == "jsonb":
        # Unwrap JSON strings: '"http://..."' -> 'http://...', '"true"' -> 'true'
        conn.execute(
            sa.text(
                "ALTER TABLE platform_settings "
                "ALTER COLUMN value TYPE TEXT "
                "USING (value #>> '{}')"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'platform_settings' AND column_name = 'value'"
        )
    ).fetchone()
    if row and row[0].lower() in ("text", "character varying"):
        conn.execute(
            sa.text(
                "ALTER TABLE platform_settings "
                "ALTER COLUMN value TYPE JSONB "
                "USING to_jsonb(value)"
            )
        )
