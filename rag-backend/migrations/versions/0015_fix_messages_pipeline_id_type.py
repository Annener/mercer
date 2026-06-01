"""fix messages.pipeline_id: UUID -> VARCHAR(64)

Migration 0004 created messages.pipeline_id as UUID.
ORM declares it as String(64) (string slug, e.g. "default", "dnd").
PostgreSQL rejects INSERT with DatatypeMismatchError.

Fix: ALTER COLUMN TYPE to VARCHAR(64) (idempotent).
Existing values are NULL — no data loss.

Revision ID: 0015_fix_messages_pipeline_id_type
Revises: 0014_sync_orm_schema
Create Date: 2026-06-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_fix_messages_pipeline_id_type"
down_revision = "0014_sync_orm_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'messages' AND column_name = 'pipeline_id'"
        )
    ).fetchone()
    if row and row[0].lower() == "uuid":
        conn.execute(
            sa.text(
                "ALTER TABLE messages "
                "ALTER COLUMN pipeline_id TYPE VARCHAR(64) "
                "USING pipeline_id::text"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'messages' AND column_name = 'pipeline_id'"
        )
    ).fetchone()
    if row and row[0].lower() in ("character varying", "varchar"):
        conn.execute(
            sa.text(
                "ALTER TABLE messages "
                "ALTER COLUMN pipeline_id TYPE UUID "
                "USING pipeline_id::uuid"
            )
        )
