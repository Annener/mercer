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
    # ------------------------------------------------------------------
    # 1. tags: vault_id -> domain_id
    # ------------------------------------------------------------------
    # Drop old constraints/indexes
    op.drop_constraint("uq_tags_name_vault_campaign", "tags", type_="unique")
    op.drop_index("idx_tags_vault", table_name="tags")

    # Drop FK on vault_id before dropping column
    # (Alembic on PostgreSQL names it automatically; use batch if needed)
    op.drop_column("tags", "vault_id")

    # Add new column domain_id
    op.add_column(
        "tags",
        sa.Column(
            "domain_id",
            sa.String(32),
            sa.ForeignKey("domains.domain_id", ondelete="CASCADE"),
            nullable=False,
            server_default="default",  # temporary default for existing rows
        ),
    )
    # Remove the temporary server_default so new rows must supply a value
    op.alter_column("tags", "domain_id", server_default=None)

    # New UNIQUE constraint and index
    op.create_unique_constraint(
        "uq_tags_name_domain_campaign",
        "tags",
        ["name", "domain_id", "campaign_id"],
    )
    op.create_index("idx_tags_domain", "tags", ["domain_id"])

    # ------------------------------------------------------------------
    # 2. campaigns: vault_id -> domain_id
    # ------------------------------------------------------------------
    op.drop_column("campaigns", "vault_id")
    op.add_column(
        "campaigns",
        sa.Column(
            "domain_id",
            sa.String(32),
            sa.ForeignKey("domains.domain_id", ondelete="CASCADE"),
            nullable=False,
            server_default="default",  # temporary default for existing rows
        ),
    )
    op.alter_column("campaigns", "domain_id", server_default=None)

    # ------------------------------------------------------------------
    # 3. pipelines: add campaign_id, update index
    # ------------------------------------------------------------------
    op.drop_index("idx_pipelines_domain", table_name="pipelines")
    op.add_column(
        "pipelines",
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_pipelines_domain_campaign",
        "pipelines",
        ["domain_id", "campaign_id", "is_active"],
    )

    # ------------------------------------------------------------------
    # 4. pipeline_labels: DROP TABLE
    # ------------------------------------------------------------------
    op.drop_table("pipeline_labels")


def downgrade() -> None:
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
    op.drop_index("idx_pipelines_domain_campaign", table_name="pipelines")
    op.drop_column("pipelines", "campaign_id")
    op.create_index("idx_pipelines_domain", "pipelines", ["domain_id", "is_active"])

    # ------------------------------------------------------------------
    # 2. campaigns: domain_id -> vault_id
    # ------------------------------------------------------------------
    op.drop_column("campaigns", "domain_id")
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
    op.drop_constraint("uq_tags_name_domain_campaign", "tags", type_="unique")
    op.drop_index("idx_tags_domain", table_name="tags")
    op.drop_column("tags", "domain_id")
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
    op.create_unique_constraint(
        "uq_tags_name_vault_campaign",
        "tags",
        ["name", "vault_id", "campaign_id"],
    )
    op.create_index("idx_tags_vault", "tags", ["vault_id"])
