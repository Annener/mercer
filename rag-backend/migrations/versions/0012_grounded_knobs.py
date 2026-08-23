"""Bump retrieval knobs for grounded agent-assistant mode.

- retrieval.top_k: 10 → 20 (more recall per round)
- retrieval.evidence_token_budget: 4000 → 6000 (richer evidence blocks)

The values live in platform_settings and are read at runtime by
settings_service.get("retrieval.top_k", db) and
settings_service.get("retrieval.evidence_token_budget", db).

This migration is idempotent: it only updates rows that already exist
with the OLD values, so re-running it on a fresh DB (which uses the
DEFAULTS in settings_service) is a no-op.

Revision ID: 0012_grounded_knobs
Revises: 0011_chat_metadata
Create Date: 2026-08-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_grounded_knobs"
down_revision = "0011_chat_metadata"
branch_labels = None
depends_on = None


_OLD_TOP_K = "10"
_NEW_TOP_K = "20"

_OLD_BUDGET = "4000"
_NEW_BUDGET = "6000"


def upgrade() -> None:
    # top_k: bump only if still at the legacy default.
    op.execute(
        sa.text(
            "UPDATE platform_settings SET value = :new "
            "WHERE key = 'retrieval.top_k' AND value = :old"
        ).bindparams(new=_NEW_TOP_K, old=_OLD_TOP_K)
    )
    # evidence_token_budget: same idea.
    op.execute(
        sa.text(
            "UPDATE platform_settings SET value = :new "
            "WHERE key = 'retrieval.evidence_token_budget' AND value = :old"
        ).bindparams(new=_NEW_BUDGET, old=_OLD_BUDGET)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE platform_settings SET value = :old "
            "WHERE key = 'retrieval.top_k' AND value = :new"
        ).bindparams(new=_NEW_TOP_K, old=_OLD_TOP_K)
    )
    op.execute(
        sa.text(
            "UPDATE platform_settings SET value = :old "
            "WHERE key = 'retrieval.evidence_token_budget' AND value = :new"
        ).bindparams(new=_NEW_BUDGET, old=_OLD_BUDGET)
    )