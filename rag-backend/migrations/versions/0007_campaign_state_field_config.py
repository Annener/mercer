"""Add campaign_state_field_configs table for Campaign State field configuration.

Revision ID: 0007_campaign_state_field_config
Revises: 0006_audit_log_actor_payload
Create Date: 2026-08-20

Campaign State — Stage 1: Field Configuration.
Хранит конфигурацию полей Campaign State для каждой кампании. Сами значения
state, версии и list-item IDs не относятся к этой миграции (Stage 2).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0007_campaign_state_field_config"
down_revision = "0006_audit_log_actor_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_state_field_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("campaign_id", "key", name="uq_state_fields_campaign_key"),
        sa.CheckConstraint(
            "mode IN ('single', 'list')",
            name="ck_state_fields_mode_valid",
        ),
        sa.CheckConstraint(
            "display_order >= 0",
            name="ck_state_fields_display_order_nonneg",
        ),
        sa.CheckConstraint(
            "length(key) >= 1 AND length(label) >= 1",
            name="ck_state_fields_min_lengths",
        ),
    )
    op.create_index(
        "idx_state_fields_campaign_order",
        "campaign_state_field_configs",
        ["campaign_id", "display_order"],
    )

    # Триггер для auto-update updated_at при UPDATE (onupdate=func.now() на стороне ORM
    # работает только в сессии, для raw SQL не вызывается — добавляем триггер).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION campaign_state_field_configs_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_campaign_state_field_configs_updated_at
            BEFORE UPDATE ON campaign_state_field_configs
            FOR EACH ROW
            EXECUTE FUNCTION campaign_state_field_configs_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_campaign_state_field_configs_updated_at ON campaign_state_field_configs")
    op.execute("DROP FUNCTION IF EXISTS campaign_state_field_configs_set_updated_at()")
    op.drop_index("idx_state_fields_campaign_order", table_name="campaign_state_field_configs")
    op.drop_table("campaign_state_field_configs")
