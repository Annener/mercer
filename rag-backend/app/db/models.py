from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Domain(Base):
    __tablename__ = "domains"

    # domain_id — реальный PK таблицы (строка, не UUID).
    # Колонки id в БД нет — см. 0001_initial.py.
    domain_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    prompts: Mapped[list[DomainPrompt]] = relationship(back_populates="domain", cascade="all, delete-orphan")
    clarification_fields: Mapped[list[DomainClarificationField]] = relationship(
        back_populates="domain", cascade="all, delete-orphan", order_by="DomainClarificationField.display_order"
    )


class DomainPrompt(Base):
    __tablename__ = "domain_prompts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False)
    prompt_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    domain: Mapped[Domain] = relationship(back_populates="prompts")


class DomainClarificationField(Base):
    __tablename__ = "domain_clarification_fields"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    domain: Mapped[Domain] = relationship(back_populates="clarification_fields")


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    # value хранится как plain TEXT.
    # Десериализацию в нативный Python-тип выполняет SettingsService.deserialize_value().
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    group_name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class GenerationModel(Base):
    __tablename__ = "generation_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible")
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Vault(Base):
    __tablename__ = "vaults"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vault_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.domain_id", ondelete="SET NULL"), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    embedding_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expected_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overlap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entity_aware_mode: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    semantic_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.3, server_default="0.3")
    binding_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unbound", server_default="unbound")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Campaign Update Mode: per-vault git author identity override (nullable)
    git_author_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    git_author_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    documents: Mapped[list[Document]] = relationship(back_populates="vault", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("name", "domain_id", name="uq_tag_name_domain"),)

    document_labels: Mapped[list[DocumentLabel]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vault_id: Mapped[str] = mapped_column(String(128), ForeignKey("vaults.vault_id", ondelete="CASCADE"), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    mtime: Mapped[int] = mapped_column(Integer, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # --- full document mode: size metadata (Stage 1) ---
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    vault: Mapped[Vault] = relationship(back_populates="documents")
    labels: Mapped[list[DocumentLabel]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentLabel(Base):
    __tablename__ = "document_labels"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

    document: Mapped[Document] = relationship(back_populates="labels")
    tag: Mapped[Tag] = relationship(back_populates="document_labels")


class Campaign(Base):
    __tablename__ = "campaigns"

    # Реальная схема после 0009_campaigns_schema_sync:
    # id, domain_id, name, description, system_prompt, last_session_at, created_at
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_session_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chats: Mapped[list[Chat]] = relationship(back_populates="campaign")
    tags: Mapped[list[Tag]] = relationship(
        secondary="campaign_tags",
        primaryjoin="Campaign.id == campaign_tags.c.campaign_id",
        secondaryjoin="Tag.id == campaign_tags.c.tag_id",
        viewonly=True,
    )


from sqlalchemy import Table, Column  # noqa: E402

campaign_tags = Table(
    "campaign_tags",
    Base.metadata,
    Column("campaign_id", UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="New Chat")
    vault_id: Mapped[str | None] = mapped_column(String(128), nullable=True)  # deprecated back-compat
    # A01 fix: domain_id NOT NULL + CASCADE (инвариант arch.md §2.6, §8)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    # A02: pipeline_versions — JSONB dict
    pipeline_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    # A03: locked_pipeline_id
    locked_pipeline_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    # Stage 2: pipeline DAG state fields
    # pipeline_pause_state — snapshot DAG-контекста при паузе на validation-шаге.
    # Структура: {pipeline_id, step_id, resume_token, step_results, query, expires_at}
    # NULL = нет активной паузы.
    pipeline_pause_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    # pending_pipeline_confirm — данные ожидающего подтверждения запуска пайплайна.
    # Структура: {pipeline_id, pipeline_name, reasoning, confirm_token, query, expires_at}
    # NULL = нет ожидающего подтверждения.
    pending_pipeline_confirm: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    # --- full document mode (Stage 1) ---
    full_document_mode_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sent_full_document_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages: Mapped[list[Message]] = relationship(back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at")
    clarification_state: Mapped[ClarificationState | None] = relationship(back_populates="chat", cascade="all, delete-orphan", uselist=False)
    campaign: Mapped[Campaign | None] = relationship(back_populates="chats")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chat: Mapped[Chat] = relationship(back_populates="messages")


class ClarificationState(Base):
    __tablename__ = "clarification_states"

    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    missing_fields: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    collected: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    turn: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    chat: Mapped[Chat] = relationship(back_populates="clarification_state")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # actor and payload added by migration 0010_audit_log_actor_payload
    actor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(64), ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    final_composition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("pipeline_id", "domain_id", "version", name="uq_pipeline_domain_version"),)


class PipelineDecision(Base):
    __tablename__ = "pipeline_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    selected_pipeline_id: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RerankModel(Base):
    __tablename__ = "rerank_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai_compatible")
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# Alias for back-compat: chat.py imports ClarificationStateRow
ClarificationStateRow = ClarificationState
