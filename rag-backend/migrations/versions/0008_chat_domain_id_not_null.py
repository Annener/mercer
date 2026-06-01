"""chat.domain_id — set NOT NULL, truncate chats first

Revision ID: 0008_chat_domain_id_not_null
Revises: 0007_rename_api_key_encrypted
Create Date: 2026-06-01

Стратегия:
  1. DELETE все строки из chats (каскадно удалит messages и clarification_state
     через ondelete=CASCADE на FK).
  2. ALTER COLUMN domain_id SET NOT NULL.
  3. ALTER COLUMN domain_id DROP DEFAULT (если вдруг есть server_default=NULL).

Downgrade:
  Возвращает domain_id к nullable=True. Данные не восстанавливаются.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_chat_domain_id_not_null"
down_revision = "0007_rename_api_key_encrypted"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Удаляем все чаты до применения NOT NULL-ограничения.
    #    messages и clarification_state удалятся каскадно (FK ondelete=CASCADE).
    op.execute("DELETE FROM chats")

    # 2. Применяем NOT NULL.
    op.alter_column(
        "chats",
        "domain_id",
        existing_type=sa.String(),
        nullable=False,
    )

    # 3. Пересоздаём FK с ondelete=CASCADE вместо SET NULL.
    #    Имя constraint берём из 0005_iter1_domain_schema (chats_domain_id_fkey).
    op.drop_constraint("chats_domain_id_fkey", "chats", type_="foreignkey")
    op.create_foreign_key(
        "chats_domain_id_fkey",
        "chats",
        "domains",
        ["domain_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("chats_domain_id_fkey", "chats", type_="foreignkey")
    op.create_foreign_key(
        "chats_domain_id_fkey",
        "chats",
        "domains",
        ["domain_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column(
        "chats",
        "domain_id",
        existing_type=sa.String(),
        nullable=True,
    )
