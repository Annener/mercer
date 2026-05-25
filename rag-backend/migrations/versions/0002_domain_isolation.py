from __future__ import annotations

from alembic import op

revision = "0002_domain_isolation"
down_revision = "0001_chat_pg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DROP всех чатов (пользователь согласился удалить legacy данные)
    op.execute("DELETE FROM chats")


def downgrade() -> None:
    # Nothing to rollback
    pass