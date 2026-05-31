"""add_uuid_pk_to_models_vaults

Revision ID: 0006_add_uuid_pk_to_models_vaults
Revises: 0005_iter1_domain_schema
Create Date: 2026-06-01

Problem:
  ORM models (GenerationModel, EmbeddingModel, Vault) declare `id` as UUID
  primary key, but the tables were created in 0001 with string PKs
  (model_id / vault_id).  SQLAlchemy generates SELECT ... id ... which
  fails with UndefinedColumnError.

  Additionally, 0001 named the API-key column `encrypted_api_key` while
  the ORM uses `api_key_encrypted`.

Fix:
  1. generation_models  -- add id UUID PK, model_id -> UNIQUE NOT NULL
  2. embedding_models   -- same (drop/restore vault FK first)
  3. vaults             -- same (drop/restore downstream FKs first)
     + add new ORM columns that were not in 0001
  All operations are idempotent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_add_uuid_pk_to_models_vaults"
down_revision = "0005_iter1_domain_schema"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col_exists(conn, table: str, column: str) -> bool:
    return conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).fetchone() is not None


def _constraint_exists(conn, table: str, constraint: str) -> bool:
    return conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema='public' AND table_name=:t AND constraint_name=:c"
        ),
        {"t": table, "c": constraint},
    ).fetchone() is not None


def _get_fk_constraints(conn, table: str, column: str) -> list[tuple[str, str]]:
    """
    Return [(fk_table, fk_constraint_name), ...] for all FK constraints on
    *other* tables whose column references *table*.*column*.
    """
    rows = conn.execute(
        sa.text(
            """
            SELECT tc.table_name, tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
            JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_name  = :ref_table
              AND ccu.column_name = :ref_col
              AND tc.table_name  != :ref_table
            """
        ),
        {"ref_table": table, "ref_col": column},
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _add_uuid_pk(conn, table: str, old_pk_col: str) -> None:
    """
    Add a surrogate UUID primary key `id` to *table* (replaces the old
    string PK *old_pk_col*, which becomes UNIQUE NOT NULL).
    Drops and restores dependent FK constraints automatically.
    Safe to call multiple times.
    """
    if _col_exists(conn, table, "id"):
        return  # already migrated

    # 1. Collect dependent FKs (other tables referencing old PK column)
    dep_fks = _get_fk_constraints(conn, table, old_pk_col)

    # 2. Collect the column types for those FK columns so we can restore them
    fk_col_types: dict[tuple[str, str], str] = {}
    for fk_table, _ in dep_fks:
        rows = conn.execute(
            sa.text(
                "SELECT kcu.column_name, c.data_type, c.character_maximum_length "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON kcu.constraint_name = tc.constraint_name "
                "JOIN information_schema.columns c "
                "  ON c.table_name = kcu.table_name AND c.column_name = kcu.column_name "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON ccu.constraint_name = tc.constraint_name "
                "WHERE tc.constraint_type = 'FOREIGN KEY' "
                "  AND tc.table_name = :t "
                "  AND ccu.table_name = :ref "
                "  AND ccu.column_name = :ref_col"
            ),
            {"t": fk_table, "ref": table, "ref_col": old_pk_col},
        ).fetchall()
        for r in rows:
            col_name = r[0]
            data_type = r[1]
            char_len = r[2]
            if char_len:
                col_type = f"{data_type}({char_len})"
            else:
                col_type = data_type
            fk_col_types[(fk_table, col_name)] = col_type

    # 3. Drop dependent FK constraints
    for fk_table, fk_name in dep_fks:
        conn.execute(sa.text(
            f"ALTER TABLE {fk_table} DROP CONSTRAINT IF EXISTS {fk_name}"
        ))

    # 4. Drop the old PK constraint
    conn.execute(sa.text(
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"
    ))

    # 5. Add id column with gen_random_uuid() for existing rows
    conn.execute(sa.text(
        f"ALTER TABLE {table} ADD COLUMN id uuid DEFAULT gen_random_uuid() NOT NULL"
    ))

    # 6. Promote id to PK
    conn.execute(sa.text(
        f"ALTER TABLE {table} ADD PRIMARY KEY (id)"
    ))

    # 7. Ensure old string key stays UNIQUE NOT NULL
    uq_name = f"uq_{table}_{old_pk_col}"
    if not _constraint_exists(conn, table, uq_name):
        conn.execute(sa.text(
            f"ALTER TABLE {table} ADD CONSTRAINT {uq_name} UNIQUE ({old_pk_col})"
        ))

    # 8. Remove the temporary default from id
    conn.execute(sa.text(
        f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT"
    ))

    # 9. Restore dropped FK constraints (they still reference the same string column)
    for fk_table, fk_name in dep_fks:
        col_info = [(k[1], v) for k, v in fk_col_types.items() if k[0] == fk_table]
        for col_name, _col_type in col_info:
            conn.execute(sa.text(
                f"ALTER TABLE {fk_table} ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY ({col_name}) REFERENCES {table} ({old_pk_col})"
            ))


def _rename_col_if_needed(conn, table: str, old_name: str, new_name: str) -> None:
    if _col_exists(conn, table, old_name) and not _col_exists(conn, table, new_name):
        conn.execute(sa.text(
            f"ALTER TABLE {table} RENAME COLUMN {old_name} TO {new_name}"
        ))


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. generation_models  (no dependents on model_id outside of itself)
    # ------------------------------------------------------------------
    _rename_col_if_needed(conn, "generation_models", "encrypted_api_key", "api_key_encrypted")
    _add_uuid_pk(conn, "generation_models", "model_id")

    # ------------------------------------------------------------------
    # 2. embedding_models  (vaults.embedding_model_id -> embedding_models.model_id)
    # ------------------------------------------------------------------
    _rename_col_if_needed(conn, "embedding_models", "encrypted_api_key", "api_key_encrypted")
    _add_uuid_pk(conn, "embedding_models", "model_id")

    # ------------------------------------------------------------------
    # 3. vaults  (chats.vault_id, documents.vault_id, campaigns.vault_id -> vaults.vault_id)
    # ------------------------------------------------------------------
    _add_uuid_pk(conn, "vaults", "vault_id")

    # Extra ORM columns on vaults not present in 0001
    for col, definition in [
        ("display_name",        "VARCHAR(256)"),
        ("embedding_model_id",  "VARCHAR(128)"),
        ("expected_dimensions", "INTEGER"),
        ("chunk_size",          "INTEGER"),
        ("overlap",             "INTEGER"),
        ("entity_aware_mode",   "BOOLEAN"),
        ("binding_status",      "VARCHAR(32) NOT NULL DEFAULT 'unbound'"),
        ("chunk_count",         "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if not _col_exists(conn, "vaults", col):
            conn.execute(sa.text(f"ALTER TABLE vaults ADD COLUMN {col} {definition}"))


# ---------------------------------------------------------------------------
# Downgrade  (minimal — removes added id columns, restores old PKs)
# ---------------------------------------------------------------------------

def downgrade() -> None:
    conn = op.get_bind()

    for table, old_pk in [
        ("vaults", "vault_id"),
        ("embedding_models", "model_id"),
        ("generation_models", "model_id"),
    ]:
        if not _col_exists(conn, table, "id"):
            continue
        dep_fks = _get_fk_constraints(conn, table, "id")
        for fk_table, fk_name in dep_fks:
            conn.execute(sa.text(
                f"ALTER TABLE {fk_table} DROP CONSTRAINT IF EXISTS {fk_name}"
            ))
        conn.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"))
        conn.execute(sa.text(f"ALTER TABLE {table} ADD PRIMARY KEY ({old_pk})"))
        conn.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS id"))
