"""initial

Чистая стартовая миграция — единственная точка входа для свежей установки.
Создаёт полную схему БД в том состоянии, которое соответствует текущим
ORM-моделям (app/db/models.py) после применения всех 22 исторических миграций.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # domains
    # ------------------------------------------------------------------
    op.create_table(
        "domains",
        sa.Column("domain_id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # domain_prompts
    # ------------------------------------------------------------------
    op.create_table(
        "domain_prompts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", sa.String(64), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("domain_id", "prompt_type", name="uq_domain_prompts_domain_type"),
    )

    # ------------------------------------------------------------------
    # domain_clarification_fields
    # ------------------------------------------------------------------
    op.create_table(
        "domain_clarification_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", sa.String(64), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("domain_id", "field_name", name="uq_domain_fields_domain_name"),
    )

    # ------------------------------------------------------------------
    # platform_settings  (value = TEXT, не JSONB — итог 0016)
    # ------------------------------------------------------------------
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(16), nullable=False),
        sa.Column("group_name", sa.String(64), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("hint", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # generation_models  (UUID PK + model_id UNIQUE — итог 0006/0007)
    # ------------------------------------------------------------------
    op.create_table(
        "generation_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, server_default="openai_compatible"),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("model_id", name="uq_generation_models_model_id"),
    )
    op.create_index(
        "idx_generation_models_active",
        "generation_models",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    # ------------------------------------------------------------------
    # embedding_models  (UUID PK + model_id UNIQUE — итог 0006/0007)
    # ------------------------------------------------------------------
    op.create_table(
        "embedding_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("model_id", name="uq_embedding_models_model_id"),
    )

    # ------------------------------------------------------------------
    # rerank_models  (0017)
    # ------------------------------------------------------------------
    op.create_table(
        "rerank_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, server_default="openai_compatible"),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("model_id", name="uq_rerank_models_model_id"),
    )

    # ------------------------------------------------------------------
    # vaults  (UUID PK + vault_id UNIQUE — итог 0006/0014/0022)
    # ------------------------------------------------------------------
    op.create_table(
        "vaults",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vault_id", sa.String(128), nullable=False),
        sa.Column("domain_id", sa.String(64), sa.ForeignKey("domains.domain_id", ondelete="SET NULL"), nullable=True),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("embedding_model_id", sa.String(128), nullable=True),
        sa.Column("expected_dimensions", sa.Integer(), nullable=True),
        sa.Column("chunk_size", sa.Integer(), nullable=True),
        sa.Column("overlap", sa.Integer(), nullable=True),
        sa.Column("entity_aware_mode", sa.Boolean(), nullable=True),
        sa.Column("semantic_threshold", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("binding_status", sa.String(32), nullable=False, server_default="unbound"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vault_id", name="uq_vaults_vault_id"),
    )
    op.create_index("idx_vaults_domain", "vaults", ["domain_id"])
    op.create_index("idx_vaults_enabled", "vaults", ["enabled"])

    # ------------------------------------------------------------------
    # campaigns  (итог 0005/0009/0014)
    # ------------------------------------------------------------------
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", sa.String(64), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("last_session_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # tags  (итог 0005/0012/0013/0014)
    # ------------------------------------------------------------------
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("domain_id", sa.String(64), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("color", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "domain_id", name="uq_tag_name_domain"),
    )
    op.create_index("idx_tags_domain", "tags", ["domain_id"])
    op.create_index("idx_tags_campaign", "tags", ["campaign_id"])

    # ------------------------------------------------------------------
    # campaign_tags  (итог 0014)
    # ------------------------------------------------------------------
    op.create_table(
        "campaign_tags",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )

    # ------------------------------------------------------------------
    # pipelines  (итог 0001/0005/0014)
    # ------------------------------------------------------------------
    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pipeline_id", sa.String(64), nullable=False),
        sa.Column("domain_id", sa.String(64), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("final_composition", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("pipeline_id", "domain_id", "version", name="uq_pipeline_domain_version"),
    )
    op.create_index("idx_pipelines_domain", "pipelines", ["domain_id", "is_active"])

    # ------------------------------------------------------------------
    # chats  (итог 0003/0008/0011/0014/0019)
    # ------------------------------------------------------------------
    op.create_table(
        "chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(512), nullable=False, server_default="New Chat"),
        sa.Column("vault_id", sa.String(128), nullable=True),
        sa.Column("domain_id", sa.String(64), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("locked_pipeline_id", sa.String(64), nullable=True),
        sa.Column("pipeline_versions", postgresql.JSONB(), nullable=True),
        sa.Column("pipeline_pause_state", postgresql.JSONB(), nullable=True),
        sa.Column("pending_pipeline_confirm", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_chats_domain", "chats", ["domain_id"])
    op.create_index("idx_chats_campaign", "chats", ["campaign_id"])

    # ------------------------------------------------------------------
    # messages  (итог 0002/0015)
    # ------------------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("pipeline_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_messages_chat", "messages", ["chat_id"])

    # ------------------------------------------------------------------
    # clarification_states
    # ------------------------------------------------------------------
    op.create_table(
        "clarification_states",
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("missing_fields", postgresql.JSONB(), nullable=True),
        sa.Column("collected", postgresql.JSONB(), nullable=True),
        sa.Column("turn", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_question", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # pipeline_decisions  (message_id без FK — в ORM нет FK-constraint)
    # ------------------------------------------------------------------
    op.create_table(
        "pipeline_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selected_pipeline_id", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # audit_logs
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=True),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------------
    # documents  (итог 0011/0013/0014)
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vault_id", sa.String(128), sa.ForeignKey("vaults.vault_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("md5", sa.String(32), nullable=False),
        sa.Column("mtime", sa.Integer(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vault_id", "source_path", name="uq_documents_vault_path"),
    )
    op.create_index("idx_documents_vault", "documents", ["vault_id"])
    op.create_index("idx_documents_status", "documents", ["vault_id", "status"])

    # ------------------------------------------------------------------
    # document_labels  (итог 0013)
    # ------------------------------------------------------------------
    op.create_table(
        "document_labels",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("idx_document_labels_tag", "document_labels", ["tag_id"])

    # ------------------------------------------------------------------
    # Seed data
    # ------------------------------------------------------------------
    _seed()


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_index("idx_document_labels_tag", table_name="document_labels")
    op.drop_table("document_labels")
    op.drop_index("idx_documents_status", table_name="documents")
    op.drop_index("idx_documents_vault", table_name="documents")
    op.drop_table("documents")
    op.drop_table("audit_logs")
    op.drop_table("pipeline_decisions")
    op.drop_table("clarification_states")
    op.drop_index("idx_messages_chat", table_name="messages")
    op.drop_table("messages")
    op.drop_index("idx_chats_campaign", table_name="chats")
    op.drop_index("idx_chats_domain", table_name="chats")
    op.drop_table("chats")
    op.drop_index("idx_pipelines_domain", table_name="pipelines")
    op.drop_table("pipelines")
    op.drop_table("campaign_tags")
    op.drop_index("idx_tags_campaign", table_name="tags")
    op.drop_index("idx_tags_domain", table_name="tags")
    op.drop_table("tags")
    op.drop_table("campaigns")
    op.drop_index("idx_vaults_enabled", table_name="vaults")
    op.drop_index("idx_vaults_domain", table_name="vaults")
    op.drop_table("vaults")
    op.drop_table("rerank_models")
    op.drop_table("embedding_models")
    op.drop_index("idx_generation_models_active", table_name="generation_models")
    op.drop_table("generation_models")
    op.drop_table("platform_settings")
    op.drop_table("domain_clarification_fields")
    op.drop_table("domain_prompts")
    op.drop_table("domains")


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed() -> None:
    _seed_domains()
    _seed_domain_prompts()
    _seed_clarification_fields()
    _seed_platform_settings()


def _seed_domains() -> None:
    domains = sa.table(
        "domains",
        sa.column("domain_id", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        domains,
        [
            {"domain_id": "default", "display_name": "Default", "description": "General assistant", "is_system": True, "enabled": True},
            {"domain_id": "dnd", "display_name": "Dungeons & Dragons", "description": "Dungeons & Dragons rules, lore and session co-authoring", "is_system": False, "enabled": True},
            {"domain_id": "work", "display_name": "Work", "description": "Work knowledge base", "is_system": False, "enabled": True},
        ],
    )


def _seed_domain_prompts() -> None:
    prompt_table = sa.table(
        "domain_prompts",
        sa.column("domain_id", sa.String),
        sa.column("prompt_type", sa.String),
        sa.column("content", sa.Text),
    )
    op.bulk_insert(prompt_table, _domain_prompts())


def _seed_clarification_fields() -> None:
    field_table = sa.table(
        "domain_clarification_fields",
        sa.column("domain_id", sa.String),
        sa.column("field_name", sa.String),
        sa.column("label", sa.String),
        sa.column("hint", sa.Text),
        sa.column("required", sa.Boolean),
        sa.column("display_order", sa.Integer),
    )
    op.bulk_insert(
        field_table,
        [
            {"domain_id": "dnd", "field_name": "topic", "label": "тему или объект вопроса", "hint": "Уточняет короткие или неоднозначные запросы.", "required": True, "display_order": 0},
            {"domain_id": "dnd", "field_name": "subject", "label": "конкретный класс, расу, заклинание или предмет", "hint": "Уточняет неоднозначные D&D-сущности.", "required": True, "display_order": 1},
        ],
    )


def _seed_platform_settings() -> None:
    settings = sa.table(
        "platform_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
        sa.column("value_type", sa.String),
        sa.column("group_name", sa.String),
        sa.column("label", sa.String),
        sa.column("hint", sa.Text),
    )
    op.bulk_insert(settings, _platform_settings())


def _domain_prompts() -> list[dict[str, str]]:
    prompts = {
        "default": {
            "system": (
                'You are a helpful assistant. Answer directly and use the retrieved context only when it is relevant.\n'
                'When citing context blocks (numbered as [1], [2], ...), reference them inline in your answer.\n'
                'Do NOT add a "Sources" or "References" section at the end of your response — the UI renders them automatically.\n\n'
                'Context:\n{context}\n\n'
                'Collected clarification fields:\n{collected_fields}\n'
            ),
            "clarification": "Уточните, пожалуйста: {missing_fields}\n",
            "planner": "Decide if the user query needs clarification: {query}\n",
            "pipeline_router": "",
        },
        "dnd": {
            "system": (
                'Ты — ИИ-ассистент и соавтор мастера (DM) для Dungeons & Dragons. Твоя задача — помогать строить сюжеты, сражения и лор, строго опираясь на предоставленный локальный контекст.\n\n'
                'ПРАВИЛА ОТВЕТА:\n'
                '1. ОСНОВА НА КОНТЕКСТЕ: Все факты, имена, локации и механики должны браться из пронумерованных блоков контекста (обозначены как [1], [2], ... в разделе КОНТЕКСТ). Ссылайся на них в тексте ответа в квадратных скобках: например «согласно правилам [2]». Если данных не хватает, честно скажи об этом, предложи уточнить запрос или используй общие правила D&D 5e, явно пометив это как `[Общее знание]`. НЕ добавляй раздел «Источники» или список ссылок в конце ответа — интерфейс отображает их автоматически.\n'
                '2. ФОРМАТ: Всегда отвечай в формате Markdown. Используй заголовки `#`, списки, таблицы для характеристик/монстров и цитаты `>` для правил. Структурируй ответ: Лор → Сюжет/Зацепки → Сражение/Механика → Рекомендации DM.\n'
                '3. УТОЧНЕНИЯ: Если в запросе отсутствуют критические данные (уровень/состав партии, желаемая сложность, конкретная локация из лора), задай 1-3 чётких уточняющих вопроса ПЕРЕД генерацией основного контента.\n'
                '4. РОЛЬ: Ты не просто справочник, а активный соавтор. Предлагай варианты, рассчитывай баланс encounter, адаптируй лор под нужды стола, сохраняй атмосферу мира.\n\n'
                'КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ:\n{context}\n\n'
                'СОБРАННЫЕ ПОЛЯ УТОЧНЕНИЯ:\n{collected_fields}\n'
            ),
            "clarification": "Чтобы подготовить точный и атмосферный контент, уточните: {missing_fields}\n",
            "planner": "Decide whether this D&D query needs clarification before answering: {query}\n",
            "pipeline_router": "",
        },
        "work": {
            "system": (
                'You are a concise work knowledge-base assistant. Prioritize actionable answers and cite retrieved context blocks inline using [1], [2], ... notation when referencing them.\n'
                'Do NOT add a "Sources" or "References" section at the end of your response — the UI renders them automatically.\n\n'
                'Context:\n{context}\n\n'
                'Collected clarification fields:\n{collected_fields}\n'
            ),
            "clarification": "Уточните рабочий контекст: {missing_fields}\n",
            "planner": "Decide whether this work query needs clarification before answering: {query}\n",
            "pipeline_router": "",
        },
    }

    rows: list[dict[str, str]] = []
    for domain_id, domain_prompts in prompts.items():
        for prompt_type in ("system", "clarification", "planner", "pipeline_router"):
            rows.append({"domain_id": domain_id, "prompt_type": prompt_type, "content": domain_prompts[prompt_type]})
    return rows


def _platform_settings() -> list[dict[str, str]]:
    return [
        {"key": "retrieval.enabled", "value": "true", "value_type": "bool", "group_name": "retrieval", "label": "Поиск по базе знаний", "hint": "Включает поиск по базе знаний при ответах. Если выключено — модель отвечает только из своих знаний."},
        {"key": "retrieval.top_k", "value": "10", "value_type": "int", "group_name": "retrieval", "label": "Глубина поиска", "hint": "Сколько фрагментов текста передавать модели. Больше — полнее контекст, но медленнее."},
        {"key": "chunking.chunk_size", "value": "2000", "value_type": "int", "group_name": "chunking", "label": "Размер фрагмента", "hint": "Максимальный размер одного фрагмента текста при индексации (в словах)."},
        {"key": "chunking.overlap", "value": "64", "value_type": "int", "group_name": "chunking", "label": "Перекрытие", "hint": "Количество слов, повторяющихся между соседними фрагментами."},
        {"key": "chunking.entity_aware_mode", "value": "true", "value_type": "bool", "group_name": "chunking", "label": "Умный чанкинг", "hint": "Распознаёт именованные сущности и старается не разрывать связанные описания."},
        {"key": "chat.max_clarification_turns", "value": "3", "value_type": "int", "group_name": "chat", "label": "Лимит уточнений", "hint": "Максимальное количество уточняющих вопросов перед ответом. 0 — без уточнений."},
        {"key": "chat.stream_answers", "value": "true", "value_type": "bool", "group_name": "chat", "label": "Стриминг ответов", "hint": "Показывает ответ по мере генерации. Если выключено — ответ появится целиком."},
        {"key": "chat.auto_title", "value": "true", "value_type": "bool", "group_name": "chat", "label": "Автозаголовок", "hint": "Автоматически придумывает название для нового чата."},
        {"key": "pdf_sidecar.url", "value": "http://host.docker.internal:8765", "value_type": "str", "group_name": "sidecar", "label": "URL PDF-сайдкара", "hint": "Сервис для парсинга PDF. host.docker.internal — стандартный адрес хоста из Docker."},
        {"key": "pdf_sidecar.timeout_seconds", "value": "180", "value_type": "int", "group_name": "sidecar", "label": "Таймаут сайдкара", "hint": "Максимальное время ожидания ответа от сайдкара на один файл."},
        {"key": "pdf_sidecar.fallback_to_pdfminer", "value": "true", "value_type": "bool", "group_name": "sidecar", "label": "Фоллбэк на pdfminer", "hint": "Если сайдкар недоступен — использовать быстрый парсер pdfminer вместо него."},
        {"key": "watchdog_auto_index_extensions", "value": ".md,.pdf", "value_type": "str", "group_name": "indexing", "label": "Авто-индексация расширений", "hint": "Расширения файлов через запятую (.md,.pdf). Пусто — только ручная индексация."},
    ]
