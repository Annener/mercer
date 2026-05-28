"""initial

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "domains",
        sa.Column("domain_id", sa.String(length=32), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "domain_prompts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", sa.String(length=32), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("domain_id", "prompt_type", name="uq_domain_prompts_domain_type"),
    )
    op.create_table(
        "domain_clarification_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain_id", sa.String(length=32), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("hint", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("domain_id", "field_name", name="uq_domain_fields_domain_name"),
    )
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("group_name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("hint", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "generation_models",
        sa.Column("model_id", sa.String(length=128), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="openai_compatible"),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_generation_models_active",
        "generation_models",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_table(
        "embedding_models",
        sa.Column("model_id", sa.String(length=128), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "vaults",
        sa.Column("vault_id", sa.String(length=64), primary_key=True),
        sa.Column("domain_id", sa.String(length=32), sa.ForeignKey("domains.domain_id"), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("embedding_model_id", sa.String(length=128), sa.ForeignKey("embedding_models.model_id"), nullable=True),
        sa.Column("expected_dimensions", sa.Integer(), nullable=True),
        sa.Column("chunk_size", sa.Integer(), nullable=True),
        sa.Column("overlap", sa.Integer(), nullable=True),
        sa.Column("entity_aware_mode", sa.Boolean(), nullable=True),
        sa.Column("binding_status", sa.String(length=16), nullable=False, server_default="unbound"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_vaults_domain", "vaults", ["domain_id"])
    op.create_index("idx_vaults_enabled", "vaults", ["enabled"])
    op.create_table(
        "chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("vault_id", sa.String(length=64), sa.ForeignKey("vaults.vault_id"), nullable=True),
        sa.Column("domain_id", sa.String(length=32), sa.ForeignKey("domains.domain_id"), nullable=True),
        sa.Column("world_id", sa.String(length=64), nullable=True, server_default=None),
        sa.Column("locked_pipeline_id", sa.String(length=64), nullable=True, server_default=None),
        sa.Column("pipeline_versions", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "clarification_states",
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("missing_fields", postgresql.JSONB(), nullable=True),
        sa.Column("collected", postgresql.JSONB(), nullable=True),
        sa.Column("turn", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_question", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
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
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("world_id", sa.String(length=64), nullable=False),
        sa.Column("vault_id", sa.String(length=64), sa.ForeignKey("vaults.vault_id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("path_prefix", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "world_id", name="uq_campaigns_campaign_world"),
    )
    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pipeline_id", sa.String(length=64), nullable=False),
        sa.Column("domain_id", sa.String(length=32), sa.ForeignKey("domains.domain_id"), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("final_composition", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("pipeline_id", "version", name="uq_pipelines_id_version"),
    )
    op.create_index("idx_pipelines_domain", "pipelines", ["domain_id", "is_active"])
    op.create_table(
        "pipeline_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("selected_pipeline_id", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    _seed()


def downgrade() -> None:
    op.drop_table("pipeline_decisions")
    op.drop_index("idx_pipelines_domain", table_name="pipelines")
    op.drop_table("pipelines")
    op.drop_table("campaigns")
    op.drop_index("idx_worlds_vault", table_name="worlds")
    op.drop_table("worlds")
    op.drop_table("audit_logs")
    op.drop_table("clarification_states")
    op.drop_table("messages")
    op.drop_table("chats")
    op.drop_index("idx_vaults_enabled", table_name="vaults")
    op.drop_index("idx_vaults_domain", table_name="vaults")
    op.drop_table("vaults")
    op.drop_table("embedding_models")
    op.drop_index("idx_generation_models_active", table_name="generation_models")
    op.drop_table("generation_models")
    op.drop_table("platform_settings")
    op.drop_table("domain_clarification_fields")
    op.drop_table("domain_prompts")
    op.drop_table("domains")


def _seed() -> None:
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

    prompt_table = sa.table(
        "domain_prompts",
        sa.column("domain_id", sa.String),
        sa.column("prompt_type", sa.String),
        sa.column("content", sa.Text),
    )
    op.bulk_insert(prompt_table, _domain_prompts())

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
            {
                "domain_id": "dnd",
                "field_name": "topic",
                "label": "тему или объект вопроса",
                "hint": "Уточняет короткие или неоднозначные запросы.",
                "required": True,
                "display_order": 0,
            },
            {
                "domain_id": "dnd",
                "field_name": "subject",
                "label": "конкретный класс, расу, заклинание или предмет",
                "hint": "Уточняет неоднозначные D&D-сущности.",
                "required": True,
                "display_order": 1,
            },
        ],
    )

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
            "system": """You are a helpful assistant. Answer directly and use the retrieved context only when it is relevant.
When citing context blocks (numbered as [1], [2], ...), reference them inline in your answer.
Do NOT add a "Sources" or "References" section at the end of your response — the UI renders them automatically.

Context:
{context}

Collected clarification fields:
{collected_fields}
""",
            "clarification": "Уточните, пожалуйста: {missing_fields}\n",
            "planner": "Decide if the user query needs clarification: {query}\n",
        },
        "dnd": {
            "system": """Ты — ИИ-ассистент и соавтор мастера (DM) для Dungeons & Dragons. Твоя задача — помогать строить сюжеты, сражения и лор, строго опираясь на предоставленный локальный контекст.

ПРАВИЛА ОТВЕТА:
1. ОСНОВА НА КОНТЕКСТЕ: Все факты, имена, локации и механики должны браться из пронумерованных блоков контекста (обозначены как [1], [2], ... в разделе КОНТЕКСТ). Ссылайся на них в тексте ответа в квадратных скобках: например «согласно правилам [2]». Если данных не хватает, честно скажи об этом, предложи уточнить запрос или используй общие правила D&D 5e, явно пометив это как `[Общее знание]`. НЕ добавляй раздел «Источники» или список ссылок в конце ответа — интерфейс отображает их автоматически.
2. ФОРМАТ: Всегда отвечай в формате Markdown. Используй заголовки `#`, списки, таблицы для характеристик/монстров и цитаты `>` для правил. Структурируй ответ: Лор → Сюжет/Зацепки → Сражение/Механика → Рекомендации DM.
3. УТОЧНЕНИЯ: Если в запросе отсутствуют критические данные (уровень/состав партии, желаемая сложность, конкретная локация из лора), задай 1-3 чётких уточняющих вопроса ПЕРЕД генерацией основного контента.
4. РОЛЬ: Ты не просто справочник, а активный соавтор. Предлагай варианты, рассчитывай баланс encounter, адаптируй лор под нужды стола, сохраняй атмосферу мира.

КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ:
{context}

СОБРАННЫЕ ПОЛЯ УТОЧНЕНИЯ:
{collected_fields}
""",
            "clarification": "Чтобы подготовить точный и атмосферный контент, уточните: {missing_fields}\n",
            "planner": "Decide whether this D&D query needs clarification before answering: {query}\n",
        },
        "work": {
            "system": """You are a concise work knowledge-base assistant. Prioritize actionable answers and cite retrieved context blocks inline using [1], [2], ... notation when referencing them.
Do NOT add a "Sources" or "References" section at the end of your response — the UI renders them automatically.

Context:
{context}

Collected clarification fields:
{collected_fields}
""",
            "clarification": "Уточните рабочий контекст: {missing_fields}\n",
            "planner": "Decide whether this work query needs clarification before answering: {query}\n",
        },
    }

    rows: list[dict[str, str]] = []
    for domain_id, domain_prompts in prompts.items():
        for prompt_type in ("system", "clarification", "planner"):
            rows.append({"domain_id": domain_id, "prompt_type": prompt_type, "content": domain_prompts[prompt_type]})
        rows.append({"domain_id": domain_id, "prompt_type": "pipeline_router", "content": ""})
    return rows


def _platform_settings() -> list[dict[str, str]]:
    return [
        {"key": "retrieval.enabled", "value": "true", "value_type": "bool", "group_name": "retrieval", "label": "Поиск по базе знаний", "hint": "Включает поиск по базе знаний при ответах. Если выключено — модель отвечает только из своих знаний."},
        {"key": "retrieval.top_k", "value": "10", "value_type": "int", "group_name": "retrieval", "label": "Глубина поиска", "hint": "Сколько фрагментов текста передавать модели. Больше — полнее контекст, но медленнее."},
        {"key": "retrieval.reranker_enabled", "value": "false", "value_type": "bool", "group_name": "retrieval", "label": "Переранжирование", "hint": "Включает переранжирование результатов поиска для повышения релевантности."},
        {"key": "chunking.chunk_size", "value": "2000", "value_type": "int", "group_name": "chunking", "label": "Размер фрагмента", "hint": "Максимальный размер одного фрагмента текста при индексации (в словах)."},
        {"key": "chunking.overlap", "value": "64", "value_type": "int", "group_name": "chunking", "label": "Перекрытие", "hint": "Количество слов, повторяющихся между соседними фрагментами."},
        {"key": "chunking.entity_aware_mode", "value": "true", "value_type": "bool", "group_name": "chunking", "label": "Умный чанкинг", "hint": "Распознаёт именованные сущности и старается не разрывать связанные описания."},
        {"key": "chat.max_clarification_turns", "value": "3", "value_type": "int", "group_name": "chat", "label": "Лимит уточнений", "hint": "Максимальное количество уточняющих вопросов перед ответом. 0 — без уточнений."},
        {"key": "chat.stream_answers", "value": "true", "value_type": "bool", "group_name": "chat", "label": "Стриминг ответов", "hint": "Показывает ответ по мере генерации. Если выключено — ответ появится целиком."},
        {"key": "chat.auto_title", "value": "true", "value_type": "bool", "group_name": "chat", "label": "Автозаголовок", "hint": "Автоматически придумывает название для нового чата."},
        {"key": "reranker.enabled", "value": "false", "value_type": "bool", "group_name": "reranker", "label": "Включить reranker", "hint": "Требует настройки провайдера ниже."},
        {"key": "reranker.provider", "value": "", "value_type": "str", "group_name": "reranker", "label": "Провайдер reranker", "hint": "Например: cohere, jina."},
        {"key": "reranker.base_url", "value": "", "value_type": "str", "group_name": "reranker", "label": "URL reranker", "hint": "URL API reranker-провайдера."},
        {"key": "reranker.model_name", "value": "", "value_type": "str", "group_name": "reranker", "label": "Модель reranker", "hint": "Название reranker-модели у провайдера."},
        {"key": "pdf_sidecar.url", "value": "http://host.docker.internal:8765", "value_type": "str", "group_name": "sidecar", "label": "URL PDF-сайдкара", "hint": "Сервис для парсинга PDF. host.docker.internal — стандартный адрес хоста из Docker."},
        {"key": "pdf_sidecar.timeout_seconds", "value": "180", "value_type": "int", "group_name": "sidecar", "label": "Таймаут сайдкара", "hint": "Максимальное время ожидания ответа от сайдкара на один файл."},
        {"key": "pdf_sidecar.fallback_to_pdfminer", "value": "true", "value_type": "bool", "group_name": "sidecar", "label": "Фоллбэк на pdfminer", "hint": "Если сайдкар недоступен — использовать быстрый парсер pdfminer вместо него."},
    ]
