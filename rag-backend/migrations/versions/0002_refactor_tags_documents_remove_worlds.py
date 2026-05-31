"""refactor_tags_documents_remove_worlds

Revision ID: 0002_refactor_tags_documents_remove_worlds
Revises: 0001_initial
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_refactor_tags_documents_remove_worlds"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Создать новые таблицы
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vault_id", sa.String(length=64), sa.ForeignKey("vaults.vault_id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "vault_id", "campaign_id", name="uq_tags_name_vault_campaign"),
    )
    op.create_index("idx_tags_vault", "tags", ["vault_id"])
    op.create_index("idx_tags_campaign", "tags", ["campaign_id"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vault_id", sa.String(length=64), sa.ForeignKey("vaults.vault_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("md5", sa.String(length=32), nullable=False),
        sa.Column("mtime", sa.BigInteger(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("vault_id", "source_path", name="uq_documents_vault_path"),
    )
    op.create_index("idx_documents_vault", "documents", ["vault_id"])
    op.create_index("idx_documents_status", "documents", ["vault_id", "status"])

    op.create_table(
        "document_labels",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("document_id", "tag_id"),
    )
    op.create_index("idx_document_labels_tag", "document_labels", ["tag_id"])

    op.create_table(
        "pipeline_labels",
        sa.Column("pipeline_uuid", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("pipeline_uuid", "tag_id"),
    )

    # 2. Изменить таблицу campaigns
    op.add_column("campaigns", sa.Column("system_prompt", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("last_session_at", sa.DateTime(timezone=True), nullable=True))

    op.drop_column("campaigns", "campaign_id")
    op.drop_column("campaigns", "world_id")
    op.drop_column("campaigns", "path_prefix")
    op.drop_column("campaigns", "is_active")
    # tag_id может отсутствовать — используем execute с IF EXISTS
    op.execute("ALTER TABLE campaigns DROP COLUMN IF EXISTS tag_id")

    # Убрать уникальный constraint который ссылался на удалённые колонки
    op.execute("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS uq_campaigns_campaign_world")

    # 3. Изменить таблицу chats
    op.drop_column("chats", "world_id")

    # 4. Изменить таблицу messages
    op.add_column(
        "messages",
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True),
    )

    # 5. Удалить таблицу worlds
    op.execute("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_world_id_fkey")
    op.execute("ALTER TABLE chats DROP CONSTRAINT IF EXISTS chats_world_id_fkey")
    op.execute("DROP INDEX IF EXISTS idx_worlds_vault")
    op.drop_table("worlds")


def downgrade() -> None:
    # Удалить pipeline_id из messages
    op.drop_column("messages", "pipeline_id")

    # Вернуть world_id в chats
    op.add_column("chats", sa.Column("world_id", sa.String(length=64), nullable=True, server_default=None))

    # Восстановить worlds
    op.create_table(
        "worlds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("world_id", sa.String(length=64), nullable=False),
        sa.Column("vault_id", sa.String(length=64), sa.ForeignKey("vaults.vault_id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path_prefix", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("world_id", "vault_id", name="uq_worlds_world_vault"),
    )
    op.create_index("idx_worlds_vault", "worlds", ["vault_id"])

    # Вернуть колонки campaigns
    op.add_column("campaigns", sa.Column("campaign_id", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("campaigns", sa.Column("world_id", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("campaigns", sa.Column("path_prefix", sa.String(length=512), nullable=False, server_default=""))
    op.add_column("campaigns", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.create_unique_constraint("uq_campaigns_campaign_world", "campaigns", ["campaign_id", "world_id"])

    op.drop_column("campaigns", "system_prompt")
    op.drop_column("campaigns", "last_session_at")

    # Удалить новые таблицы
    op.drop_table("pipeline_labels")
    op.drop_index("idx_document_labels_tag", table_name="document_labels")
    op.drop_table("document_labels")
    op.drop_index("idx_documents_status", table_name="documents")
    op.drop_index("idx_documents_vault", table_name="documents")
    op.drop_table("documents")
    op.drop_index("idx_tags_campaign", table_name="tags")
    op.drop_index("idx_tags_vault", table_name="tags")
    op.drop_table("tags")
