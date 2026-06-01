"""sync ORM schema: varchar sizes, pipelines.campaign_id, chats.title NOT NULL, campaign_tags

Revision ID: 0014_sync_orm_schema
Revises: 0013_fix_documents_tags_uuid
Create Date: 2026-06-01

Исправляет расхождения между ORM (models.py) и реальной схемой БД:
  M05  domains.domain_id         VARCHAR(32) → VARCHAR(64)
  M06  vaults.vault_id           VARCHAR(64) → VARCHAR(128)
  M07  vaults.domain_id          VARCHAR(32) → VARCHAR(64)
  M08  vaults.binding_status     VARCHAR(16) → VARCHAR(32)
  M09  chats.domain_id           VARCHAR(32) → VARCHAR(64)
  M10  chats.vault_id            VARCHAR(64) → VARCHAR(128)
  M11  chats.title               nullable → NOT NULL DEFAULT 'New Chat'
  M12  pipelines.domain_id       VARCHAR(32) → VARCHAR(64)
  M13  pipelines.version         VARCHAR(16) → VARCHAR(32)
  M14  pipelines.campaign_id     добавить колонку UUID FK campaigns.id
  M15  display_name/name         VARCHAR(255) → VARCHAR(256) (domains, vaults, campaigns, pipelines)
  M16  tags.name                 VARCHAR(100) → VARCHAR(128)
  M17  tags.color                VARCHAR(20)  → VARCHAR(32)
  M18  campaign_tags             создать таблицу если не существует
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0014_sync_orm_schema"
down_revision = "0013_fix_documents_tags_uuid"
branch_labels = None
depends_on = None


def _col_type(conn: sa.engine.Connection, table: str, column: str) -> str:
    """Возвращает pg data_type колонки в нижнем регистре."""
    row = conn.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row[0].lower() if row else ""


def _col_char_length(conn: sa.engine.Connection, table: str, column: str) -> int:
    """Возвращает character_maximum_length колонки (0 если не применимо)."""
    row = conn.execute(
        sa.text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return int(row[0]) if row and row[0] else 0


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t AND table_schema = 'public'"
        ),
        {"t": table},
    ).fetchone()
    return row is not None


def _col_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row is not None


def _col_is_nullable(conn: sa.engine.Connection, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return row[0].lower() == "yes" if row else True


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # M05  domains.domain_id: VARCHAR(32) → VARCHAR(64)
    # Это PK — нужно сначала дропнуть все FK, расширить, восстановить
    # ------------------------------------------------------------------
    if _col_char_length(conn, "domains", "domain_id") < 64:
        # Дропаем FK от зависимых таблиц (имена могут быть автогенерированными)
        conn.execute(sa.text("""
            DO $$ DECLARE r RECORD;
            BEGIN
              FOR r IN
                SELECT tc.constraint_name, tc.table_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.referential_constraints rc
                  ON tc.constraint_name = rc.constraint_name
                JOIN information_schema.key_column_usage ccu
                  ON rc.unique_constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND ccu.table_name = 'domains'
                  AND ccu.column_name = 'domain_id'
              LOOP
                EXECUTE 'ALTER TABLE ' || quote_ident(r.table_name)
                     || ' DROP CONSTRAINT ' || quote_ident(r.constraint_name);
              END LOOP;
            END $$;
        """))
        # Расширяем сам PK и все FK-колонки
        for tbl, col in [
            ("domains",    "domain_id"),
            ("domain_prompts", "domain_id"),
            ("domain_clarification_fields", "domain_id"),
            ("vaults",     "domain_id"),
            ("chats",      "domain_id"),
            ("campaigns",  "domain_id"),
            ("pipelines",  "domain_id"),
            ("tags",       "domain_id"),
        ]:
            if _col_exists(conn, tbl, col) and _col_char_length(conn, tbl, col) < 64:
                conn.execute(sa.text(
                    f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE VARCHAR(64)"
                ))
        # Восстанавливаем FK
        fk_defs = [
            ("domain_prompts",              "domain_id", "domains", "domain_id", "CASCADE"),
            ("domain_clarification_fields", "domain_id", "domains", "domain_id", "CASCADE"),
            ("vaults",                      "domain_id", "domains", "domain_id", "SET NULL"),
            ("chats",                       "domain_id", "domains", "domain_id", "CASCADE"),
            ("campaigns",                   "domain_id", "domains", "domain_id", "CASCADE"),
            ("pipelines",                   "domain_id", "domains", "domain_id", "CASCADE"),
            ("tags",                        "domain_id", "domains", "domain_id", "CASCADE"),
        ]
        for tbl, col, ref_tbl, ref_col, on_delete in fk_defs:
            if _col_exists(conn, tbl, col):
                conn.execute(sa.text(
                    f"ALTER TABLE {tbl} ADD CONSTRAINT fk_{tbl}_{col} "
                    f"FOREIGN KEY ({col}) REFERENCES {ref_tbl}({ref_col}) ON DELETE {on_delete}"
                ))

    # ------------------------------------------------------------------
    # M06  vaults.vault_id: VARCHAR(64) → VARCHAR(128)
    # vault_id — уникальный ключ, на него ссылаются chats и documents
    # ------------------------------------------------------------------
    if _col_char_length(conn, "vaults", "vault_id") < 128:
        conn.execute(sa.text("""
            DO $$ DECLARE r RECORD;
            BEGIN
              FOR r IN
                SELECT tc.constraint_name, tc.table_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.referential_constraints rc
                  ON tc.constraint_name = rc.constraint_name
                JOIN information_schema.key_column_usage ccu
                  ON rc.unique_constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND ccu.table_name = 'vaults'
                  AND ccu.column_name = 'vault_id'
              LOOP
                EXECUTE 'ALTER TABLE ' || quote_ident(r.table_name)
                     || ' DROP CONSTRAINT ' || quote_ident(r.constraint_name);
              END LOOP;
            END $$;
        """))
        for tbl, col in [
            ("vaults",    "vault_id"),
            ("chats",     "vault_id"),
            ("documents", "vault_id"),
        ]:
            if _col_exists(conn, tbl, col) and _col_char_length(conn, tbl, col) < 128:
                conn.execute(sa.text(
                    f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE VARCHAR(128)"
                ))
        # Восстанавливаем FK
        if _col_exists(conn, "chats", "vault_id"):
            conn.execute(sa.text(
                "ALTER TABLE chats ADD CONSTRAINT fk_chats_vault_id "
                "FOREIGN KEY (vault_id) REFERENCES vaults(vault_id)"
            ))
        if _col_exists(conn, "documents", "vault_id"):
            conn.execute(sa.text(
                "ALTER TABLE documents ADD CONSTRAINT fk_documents_vault_id "
                "FOREIGN KEY (vault_id) REFERENCES vaults(vault_id) ON DELETE CASCADE"
            ))

    # ------------------------------------------------------------------
    # M08  vaults.binding_status: VARCHAR(16) → VARCHAR(32)
    # ------------------------------------------------------------------
    if _col_char_length(conn, "vaults", "binding_status") < 32:
        conn.execute(sa.text(
            "ALTER TABLE vaults ALTER COLUMN binding_status TYPE VARCHAR(32)"
        ))

    # ------------------------------------------------------------------
    # M11  chats.title: nullable → NOT NULL DEFAULT 'New Chat'
    # ------------------------------------------------------------------
    if _col_is_nullable(conn, "chats", "title"):
        conn.execute(sa.text("UPDATE chats SET title = 'New Chat' WHERE title IS NULL"))
        conn.execute(sa.text(
            "ALTER TABLE chats ALTER COLUMN title SET NOT NULL"
        ))
        conn.execute(sa.text(
            "ALTER TABLE chats ALTER COLUMN title SET DEFAULT 'New Chat'"
        ))

    # ------------------------------------------------------------------
    # M13  pipelines.version: VARCHAR(16) → VARCHAR(32)
    # ------------------------------------------------------------------
    if _col_char_length(conn, "pipelines", "version") < 32:
        conn.execute(sa.text(
            "ALTER TABLE pipelines ALTER COLUMN version TYPE VARCHAR(32)"
        ))

    # ------------------------------------------------------------------
    # M14  pipelines.campaign_id: добавить UUID FK → campaigns.id
    # ------------------------------------------------------------------
    if not _col_exists(conn, "pipelines", "campaign_id"):
        op.add_column(
            "pipelines",
            sa.Column(
                "campaign_id",
                UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # ------------------------------------------------------------------
    # M15  display_name / name: VARCHAR(255) → VARCHAR(256)
    # ------------------------------------------------------------------
    for tbl, col in [
        ("domains",   "display_name"),
        ("vaults",    "display_name"),
        ("campaigns", "name"),
        ("pipelines", "name"),
    ]:
        if _col_exists(conn, tbl, col) and _col_char_length(conn, tbl, col) == 255:
            conn.execute(sa.text(
                f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE VARCHAR(256)"
            ))

    # ------------------------------------------------------------------
    # M16  tags.name: VARCHAR(100) → VARCHAR(128)
    # ------------------------------------------------------------------
    if _col_char_length(conn, "tags", "name") < 128:
        conn.execute(sa.text(
            "ALTER TABLE tags ALTER COLUMN name TYPE VARCHAR(128)"
        ))

    # ------------------------------------------------------------------
    # M17  tags.color: VARCHAR(20) → VARCHAR(32)
    # ------------------------------------------------------------------
    if _col_char_length(conn, "tags", "color") < 32:
        conn.execute(sa.text(
            "ALTER TABLE tags ALTER COLUMN color TYPE VARCHAR(32)"
        ))

    # ------------------------------------------------------------------
    # M18  campaign_tags: создать таблицу если не существует
    # ------------------------------------------------------------------
    if not _table_exists(conn, "campaign_tags"):
        op.create_table(
            "campaign_tags",
            sa.Column(
                "campaign_id",
                UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "tag_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tags.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()

    # M18
    if _table_exists(conn, "campaign_tags"):
        op.drop_table("campaign_tags")

    # M14
    if _col_exists(conn, "pipelines", "campaign_id"):
        op.drop_column("pipelines", "campaign_id")

    # Остальные изменения типов не откатываем —
    # расширение VARCHAR не влияет на данные и безопасно оставить.
