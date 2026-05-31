"""add_uuid_pk_to_models_vaults

Revision ID: 0006_add_uuid_pk_to_models_vaults
Revises: 0005_iter1_domain_schema
Create Date: 2026-06-01

Problem:
  ORM models (GenerationModel, EmbeddingModel, Vault) declare `id` as UUID
  primary key, but the tables were created in 0001 with string PKs
  (model_id / vault_id).  SQLAlchemy generates SELECT ... generation_models.id ...
  which fails with UndefinedColumnError.

Fix:
  1. generation_models  — add `id` UUID PK, keep `model_id` as UNIQUE NOT NULL
  2. embedding_models   — same pattern
  3. vaults             — add `id` UUID PK, keep `vault_id` as UNIQUE NOT NULL

  All operations are idempotent (skip if column already exists).
  api_key_encrypted alias: 0001 created `encrypted_api_key`, ORM uses
  `api_key_encrypted` — we rename the column here.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision = "0006_add_uuid_pk_to_models_vaults"
down_revision = "0005_iter1_domain_schema"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def _constraint_exists(conn, table: str, constraint: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema='public' AND table_name=:t AND constraint_name=:c"
        ),
        {"t": table, "c": constraint},
    ).fetchone()
    return row is not None


def _add_uuid_pk(conn, table: str, old_pk_col: str) -> None:
    """
    Add a surrogate UUID primary key `id` to *table*, replacing the old
    string primary key *old_pk_col* (which becomes a UNIQUE NOT NULL column).
    Safe to call multiple times.
    """
    if _col_exists(conn, table, "id"):
        return  # already migrated

    # 1. Add id column with a temporary default so existing rows get a value
    conn.execute(sa.text(
        f"ALTER TABLE {table} ADD COLUMN id uuid DEFAULT gen_random_uuid() NOT NULL"
    ))

    # 2. Drop the old PK constraint
    conn.execute(sa.text(
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"
    ))

    # 3. Promote id to PK
    conn.execute(sa.text(
        f"ALTER TABLE {table} ADD PRIMARY KEY (id)"
    ))

    # 4. Ensure old string key stays UNIQUE NOT NULL (it already is, but be explicit)
    conn.execute(sa.text(
        f"ALTER TABLE {table} ALTER COLUMN {old_pk_col} SET NOT NULL"
    ))
    uq_name = f"uq_{table}_{old_pk_col}"
    if not _constraint_exists(conn, table, uq_name):
        conn.execute(sa.text(
            f"ALTER TABLE {table} ADD CONSTRAINT {uq_name} UNIQUE ({old_pk_col})"
        ))

    # 5. Remove the temporary default from id (ORM supplies it via Python)
    conn.execute(sa.text(
        f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT"
    ))


def _rename_col_if_needed(conn, table: str, old_name: str, new_name: str) -> None:
    if _col_exists(conn, table, old_name) and not _col_exists(conn, table, new_name):
        conn.execute(sa.text(
            f"ALTER TABLE {table} RENAME COLUMN {old_name} TO {new_name}"
        ))


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # generation_models
    # ------------------------------------------------------------------
    # 0001 named the column `encrypted_api_key`; ORM uses `api_key_encrypted`
    _rename_col_if_needed(conn, "generation_models", "encrypted_api_key", "api_key_encrypted")
    _add_uuid_pk(conn, "generation_models", "model_id")

    # ------------------------------------------------------------------
    # embedding_models
    # ------------------------------------------------------------------
    _rename_col_if_needed(conn, "embedding_models", "encrypted_api_key", "api_key_encrypted")
    _add_uuid_pk(conn, "embedding_models", "model_id")

    # ------------------------------------------------------------------
    # vaults
    # ------------------------------------------------------------------
    # 0001 created vaults with vault_id as PK (String).
    # ORM now expects id (UUID) as PK and vault_id as unique string.
    _add_uuid_pk(conn, "vaults", "vault_id")

    # vaults also gained several new columns in ORM that 0001 didn't have:
    for col_def in [
        ("display_name",       "VARCHAR(256)"),
        ("embedding_model_id", "VARCHAR(128)"),
        ("expected_dimensions","INTEGER"),
        ("chunk_size",         "INTEGER"),
        ("overlap",            "INTEGER"),
        ("entity_aware_mode",  "BOOLEAN"),
        ("binding_status",     "VARCHAR(32) NOT NULL DEFAULT 'unbound'"),
        ("chunk_count",        "INTEGER NOT NULL DEFAULT 0"),
    ]:
        col, definition = col_def
        if not _col_exists(conn, "vaults", col):
            conn.execute(sa.text(
                f"ALTER TABLE vaults ADD COLUMN {col} {definition}"
            ))


def downgrade() -> None:
    # Reversing a PK swap is destructive and rarely needed in practice.
    # Provide a minimal stub that removes the added id columns so Alembic
    # can track the revision graph.
    conn = op.get_bind()

    for table, old_pk in [
        ("vaults", "vault_id"),
        ("embedding_models", "model_id"),
        ("generation_models", "model_id"),
    ]:
        if _col_exists(conn, table, "id"):
            # Restore old PK
            conn.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"))
            conn.execute(sa.text(f"ALTER TABLE {table} ADD PRIMARY KEY ({old_pk})"))
            conn.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS id"))
