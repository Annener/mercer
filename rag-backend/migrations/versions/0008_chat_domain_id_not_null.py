"""chat.domain_id — set NOT NULL, truncate chats first

Revision ID: 0008_chat_domain_id_not_null
Revises: 0007_rename_api_key_encrypted
Create Date: 2026-06-01

Стратегия:
  1. DELETE все строки из chats (каскадно удалит messages и clarification_state
     через ondelete=CASCADE на FK).
  2. DROP старый FK на domain_id (имя авто-определяется динамически).
  3. ALTER COLUMN domain_id SET NOT NULL.
  4. CREATE FK с ondelete=CASCADE, ссылаясь на domains.domain_id (реальный PK).

Downgrade:
  Возвращает domain_id к nullable=True и FK с SET NULL. Данные не восстанавливаются.
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_chat_domain_id_not_null"
down_revision = "0007_rename_api_key_encrypted"
branch_labels = None
depends_on = None

_DROP_FK_SQL = """
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
        WHERE tc.table_name = 'chats'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = 'domain_id'
    LOOP
        EXECUTE 'ALTER TABLE chats DROP CONSTRAINT ' || quote_ident(r.constraint_name);
    END LOOP;
END $$;
"""


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Удаляем все чаты. messages/clarification_state удаляются каскадно.
    op.execute("DELETE FROM chats")

    # 2. Дропаем FK на domain_id (имя может быть любым).
    conn.execute(sa.text(_DROP_FK_SQL))

    # 3. NOT NULL.
    op.alter_column("chats", "domain_id", existing_type=sa.String(), nullable=False)

    # 4. Новый FK. domains.domain_id — реальный PK таблицы domains
    #    (см. 0005_iter1_domain_schema: ForeignKey("domains.domain_id"))
    op.create_foreign_key(
        "chats_domain_id_fkey",
        "chats",
        "domains",
        ["domain_id"],
        ["domain_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(_DROP_FK_SQL))
    op.alter_column("chats", "domain_id", existing_type=sa.String(), nullable=True)
    op.create_foreign_key(
        "chats_domain_id_fkey",
        "chats",
        "domains",
        ["domain_id"],
        ["domain_id"],
        ondelete="SET NULL",
    )
