"""Add drift_models table — Phase 2a of context-engine refactor.

Context-engine (Phase 2a) introduces a dedicated, lightweight LLM
("drift model") that compares recent chat messages against the current
campaign state and emits "drift hints" (contradictions / additions).

This migration creates the ``drift_models`` table — modelled after
``rerank_models`` — and seeds one default host-sidecar row so that the
new infra is usable out of the box.

The active model is enforced via a partial unique index
``uq_drift_models_active`` (Postgres ``WHERE is_active = true``) so
that at most one row has ``is_active=true`` at any time.

Revision ID: 0015_drift_models
Revises: 0014_chat_rag_prefill_enabled
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_drift_models"
down_revision = "0014_chat_rag_prefill_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drift_models",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("model_id", sa.String(128), nullable=False, unique=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("model_name", sa.String(256), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_drift_models_active",
        "drift_models",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.execute(
        """
        INSERT INTO drift_models (
            id, model_id, provider, model_name,
            is_active, enabled, display_name
        )
        VALUES (
            gen_random_uuid(),
            'drift-local-default',
            'host_sidecar',
            'qvikhr-3-1.7b-instruct-noreasoning-q4_k_m',
            true,
            true,
            'QVikhr-3-1.7B (local)'
        )
        """
    )


def downgrade() -> None:
    op.drop_index("uq_drift_models_active", table_name="drift_models")
    op.drop_table("drift_models")
