"""Add pipeline_pause_state and pending_pipeline_confirm to chats.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-18

pipeline_pause_state  — персистентное состояние паузы при validation-шаге.
  Хранит snapshot контекста выполнения DAG:
  {
    "pipeline_id": str,
    "step_id": str,                 # id validation-шага, на котором остановились
    "resume_token": str,            # UUID-токен, передаётся во фронтенд
    "step_results": {               # результаты уже выполненных шагов
      "<step_id>": {"result": str, "output_format": "text"|"json"}
    },
    "query": str,                   # исходный запрос пользователя
    "expires_at": str               # ISO-8601, UTC, +1 час от момента паузы
  }
  NULL — нет активной паузы.

pending_pipeline_confirm — ожидание подтверждения запуска пайплайна.
  Хранит данные для inline-карточки подтверждения:
  {
    "pipeline_id": str,
    "pipeline_name": str,
    "reasoning": str,               # аргументация роутера
    "confirm_token": str,           # UUID-токен подтверждения
    "query": str,
    "expires_at": str               # ISO-8601, UTC, +10 минут
  }
  NULL — нет ожидающего подтверждения.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column(
            "pipeline_pause_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "DAG execution snapshot while waiting for validation step resume. "
                "Keys: pipeline_id, step_id, resume_token, step_results, query, expires_at. "
                "NULL when no pause is active."
            ),
        ),
    )
    op.add_column(
        "chats",
        sa.Column(
            "pending_pipeline_confirm",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Pending pipeline launch confirmation data for inline confirm card. "
                "Keys: pipeline_id, pipeline_name, reasoning, confirm_token, query, expires_at. "
                "NULL when no confirmation is pending."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("chats", "pending_pipeline_confirm")
    op.drop_column("chats", "pipeline_pause_state")
