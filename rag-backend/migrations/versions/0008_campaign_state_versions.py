"""Add versioned Campaign State tables.

Revision ID: 0008_campaign_state_versions
Revises: 0007_campaign_state_field_config
Create Date: 2026-08-22

Campaign State — Stage 2: Versioned State.

Adds:
  - campaigns.config_version (config-change counter)
  - campaign_state_versions (snapshot per applied patch)
  - campaign_state_values (per-version single-field values, JSONB source_refs)
  - campaign_state_list_items (per-version list items, stable item_key)

Patch is applied as a new snapshot row in campaign_state_versions; the previous
version and its values/list_items remain immutable for audit/history.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_campaign_state_versions"
down_revision = "0007_campaign_state_field_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Config version counter on Campaign.
    op.add_column(
        "campaigns",
        sa.Column(
            "config_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    # 2) Per-campaign state version rows.
    op.create_table(
        "campaign_state_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False, server_default="patch"),
        sa.Column("base_state_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(length=256), nullable=True),
        sa.UniqueConstraint(
            "campaign_id", "state_version", name="uq_state_versions_campaign_version"
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_state_versions_state_version_positive",
        ),
        sa.CheckConstraint(
            "config_version >= 1",
            name="ck_state_versions_config_version_positive",
        ),
        sa.CheckConstraint(
            "source_kind IN ('initial', 'patch')",
            name="ck_state_versions_source_kind_valid",
        ),
    )
    op.create_index(
        "idx_state_versions_campaign_latest",
        "campaign_state_versions",
        ["campaign_id", sa.text("state_version DESC")],
    )

    # 3) Per-version single-field values (one row per single-mode field per version).
    op.create_table(
        "campaign_state_values",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaign_state_versions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign_state_field_configs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_state_values_field",
        "campaign_state_values",
        ["field_id"],
    )

    # 4) Per-version list items (item_key is stable within a field across versions).
    op.create_table(
        "campaign_state_list_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaign_state_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "field_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign_state_field_configs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("item_key", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "version_id", "field_id", "item_key",
            name="uq_state_list_items_version_field_key",
        ),
        sa.CheckConstraint(
            "length(item_key) >= 1 AND length(item_key) <= 128",
            name="ck_state_list_items_item_key_length",
        ),
    )
    op.create_index(
        "idx_state_list_items_field_key",
        "campaign_state_list_items",
        ["field_id", "item_key"],
    )
    op.create_index(
        "idx_state_list_items_version",
        "campaign_state_list_items",
        ["version_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_state_list_items_version", table_name="campaign_state_list_items")
    op.drop_index("idx_state_list_items_field_key", table_name="campaign_state_list_items")
    op.drop_table("campaign_state_list_items")

    op.drop_index("idx_state_values_field", table_name="campaign_state_values")
    op.drop_table("campaign_state_values")

    op.drop_index("idx_state_versions_campaign_latest", table_name="campaign_state_versions")
    op.drop_table("campaign_state_versions")

    op.drop_column("campaigns", "config_version")