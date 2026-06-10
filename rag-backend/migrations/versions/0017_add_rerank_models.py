"""add rerank_models table

Creates a new table rerank_models for managing reranker model configurations.
Does not modify any existing tables.

Revision ID: 0017_add_rerank_models
Revises: 0016_fix_platform_settings_value_type
Create Date: 2026-06-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_add_rerank_models"
down_revision = "0016_fix_platform_settings_value_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rerank_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, server_default="openai_compatible"),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("model_id", name="uq_rerank_models_model_id"),
    )


def downgrade() -> None:
    op.drop_table("rerank_models")
