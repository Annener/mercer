"""Switch default drift model from Qwen2.5-3B-Instruct to QVikhr-3-1.7B-Instruct-noreasoning.

Phase 2a context-engine originally shipped with Qwen2.5-3B-Instruct (Q4_K_M)
as the local drift-detector model. We replace it with QVikhr-3-1.7B-Instruct-
noreasoning — a Qwen3-1.7B-based model SFT-tuned on GrandMaster2 (RU/EN).
The new model is half the size (~1.1 GB vs ~2 GB), faster on Metal GPU,
and produces higher-quality Russian-language JSON output.

Only the seeded ``drift-local-default`` row is updated; user-created drift
models in the UI are untouched. The WHERE clause on ``model_name`` makes
this migration idempotent.

Revision ID: 0016_drift_model_qvikhr
Revises: 0015_drift_models
Create Date: 2026-09-03
"""
from __future__ import annotations

from alembic import op

revision = "0016_drift_model_qvikhr"
down_revision = "0015_drift_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE drift_models
           SET model_name = 'qvikhr-3-1.7b-instruct-noreasoning-q4_k_m',
               display_name = 'QVikhr-3-1.7B (local)',
               updated_at = NOW()
         WHERE model_id = 'drift-local-default'
           AND model_name = 'qwen2.5-3b-instruct-q4_k_m'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE drift_models
           SET model_name = 'qwen2.5-3b-instruct-q4_k_m',
               display_name = 'Qwen2.5-3B (local)',
               updated_at = NOW()
         WHERE model_id = 'drift-local-default'
           AND model_name = 'qvikhr-3-1.7b-instruct-noreasoning-q4_k_m'
        """
    )
