"""iter1_domain_schema

Migration: Iteration 1 — Domain Schema

Revision ID: 0005_iter1_domain_schema
Revises: 0004_add_pipeline_id_to_messages
Create Date: 2026-05-31

Changes:
  - tags: vault_id -> domain_id (FK -> domains), update UNIQUE + index
  - campaigns: vault_id -> domain_id (FK -> domains)
  - pipelines: add campaign_id (FK nullable -> campaigns), update index
  - pipeline_labels: DROP TABLE

Downgrade restores previous state.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision = "0005_iter1_domain_schema"
down_revision = "0004_add_pipeline_id_to_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. tags: vault_id -> domain_id
    # ------------------------------------------------------------------
    # Check whether the tags table exists at all (may be missing on a
    # fresh DB that never ran 0002 cleanly).
    tags_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'tags'"
        )
    ).fetchone()

    if tags_exists:
        # Drop old constraints / indexes using raw SQL so we can use IF EXISTS
        conn.execute(sa.text(
            "ALTER TABLE tags DROP CONSTRAINT IF EXISTS uq_tags_name_vault_campaign"
        ))
        conn.execute(sa.text(
            "DROP INDEX IF EXISTS idx_tags_vault"
        ))

        # Drop FK constraint on vault_id (Postgres names it automatically)
        conn.execute(sa.text(
            """
            DO $$
            DECLARE r RECORD;
            BEGIN
                FOR r IN
                    SELECT tc.constraint_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.table_name = 'tags'
                      AND tc.constraint_type = 'FOREIGN KEY'
                      AND kcu.column_name = 'vault_id'
                LOOP
                    EXECUTE 'ALTER TABLE tags DROP CONSTRAINT IF EXISTS ' || quote_ident(r.constraint_name);
                END LOOP;
            END $$;
            """
        ))

        # Drop vault_id column if it still exists
        conn.execute(sa.text(
            "ALTER TABLE tags DROP COLUMN IF EXISTS vault_id"
        ))

        # Add domain_id only if it is not there yet
        col_exists = conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='tags' AND column_name='domain_id'"
            )
        ).fetchone()
        if not col_exists:
            op.add_column(
                "tags",
                sa.Column(
                    "domain_id",
                    sa.String(32),
                    sa.ForeignKey("domains.domain_id", ondelete="CASCADE"),
                    nullable=False,
                    server_default="default",
                ),
            )
            op.alter_column("tags", "domain_id", server_default=None)

        # New UNIQUE constraint and index (idempotent)
        conn.execute(sa.text(
            "ALTER TABLE tags DROP CONSTRAINT IF EXISTS uq_tags_name_domain_campaign"
        ))
        op.create_unique_constraint(
            "uq_tags_name_domain_campaign",
            "tags",
            ["name", "domain_id", "campaign_id"],
        )
        conn.execute(sa.text("DROP INDEX IF EXISTS idx_tags_domain"))
        op.create_index("idx_tags_domain", "tags", ["domain_id"])

    # ------------------------------------------------------------------
    # 2. campaigns: vault_id -> domain_id
    # ------------------------------------------------------------------
    campaigns_vault = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='campaigns' AND column_name='vault_id'"
        )
    ).fetchone()
    if campaigns_vault:
        op.drop_column("campaigns", "vault_id")

    campaigns_domain = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='campaigns' AND column_name='domain_id'"
        )
    ).fetchone()
    if not campaigns_domain:
        op.add_column(
            "campaigns",
            sa.Column(
                "domain_id",
                sa.String(32),
                sa.ForeignKey("domains.domain_id", ondelete="CASCADE"),
                nullable=False,
                server_default="default",
            ),
        )
        op.alter_column("campaigns", "domain_id", server_default=None)

    # ------------------------------------------------------------------
    # 3. pipelines: add campaign_id, update index
    # ------------------------------------------------------------------
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_pipelines_domain"))

    pipelines_campaign = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='pipelines' AND column_name='campaign_id'"
        )
    ).fetchone()
    if not pipelines_campaign:
        op.add_column(
            "pipelines",
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )

    conn.execute(sa.text("DROP INDEX IF EXISTS idx_pipelines_domain_campaign"))
    op.create_index(
        "idx_pipelines_domain_campaign",
        "pipelines",
        ["domain_id", "campaign_id", "is_active"],
    )

    # ------------------------------------------------------------------
    # 4. pipeline_labels: DROP TABLE IF EXISTS
    # ------------------------------------------------------------------
    conn.execute(sa.text("DROP TABLE IF EXISTS pipeline_labels"))


def downgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 4. Restore pipeline_labels
    # ------------------------------------------------------------------
    op.create_table(
        "pipeline_labels",
        sa.Column(
            "pipeline_uuid",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipelines.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # ------------------------------------------------------------------
    # 3. pipelines: remove campaign_id, restore old index
    # ------------------------------------------------------------------
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_pipelines_domain_campaign"))
    op.drop_column("pipelines", "campaign_id")
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_pipelines_domain"))
    op.create_index("idx_pipelines_domain", "pipelines", ["domain_id", "is_active"])

    # ------------------------------------------------------------------
    # 2. campaigns: domain_id -> vault_id
    # ------------------------------------------------------------------
    conn.execute(sa.text(
        "ALTER TABLE campaigns DROP COLUMN IF EXISTS domain_id"
    ))
    op.add_column(
        "campaigns",
        sa.Column(
            "vault_id",
            sa.String(64),
            sa.ForeignKey("vaults.vault_id"),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("campaigns", "vault_id", server_default=None)

    # ------------------------------------------------------------------
    # 1. tags: domain_id -> vault_id
    # ------------------------------------------------------------------
    conn.execute(sa.text(
        "ALTER TABLE tags DROP CONSTRAINT IF EXISTS uq_tags_name_domain_campaign"
    ))
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_tags_domain"))
    conn.execute(sa.text(
        "ALTER TABLE tags DROP COLUMN IF EXISTS domain_id"
    ))
    op.add_column(
        "tags",
        sa.Column(
            "vault_id",
            sa.String(64),
            sa.ForeignKey("vaults.vault_id", ondelete="CASCADE"),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("tags", "vault_id", server_default=None)
    conn.execute(sa.text(
        "ALTER TABLE tags DROP CONSTRAINT IF EXISTS uq_tags_name_vault_campaign"
    ))
    op.create_unique_constraint(
        "uq_tags_name_vault_campaign",
        "tags",
        ["name", "vault_id", "campaign_id"],
    )
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_tags_vault"))
    op.create_index("idx_tags_vault", "tags", ["vault_id"])
