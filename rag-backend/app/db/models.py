from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

import uuid as _uuid


class Base(DeclarativeBase):
    pass


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    vaults: Mapped[list[Vault]] = relationship(back_populates="domain")
    chats: Mapped[list[Chat]] = relationship(back_populates="domain")
    clarification_fields: Mapped[list[DomainClarificationField]] = relationship(
        back_populates="domain"
    )
    campaigns: Mapped[list[Campaign]] = relationship(back_populates="domain")
    tags: Mapped[list[Tag]] = relationship(back_populates="domain")
    prompts: Mapped[list[DomainPrompt]] = relationship(back_populates="domain")
    pipelines: Mapped[list[Pipeline]] = relationship(back_populates="domain")


class DomainPrompt(Base):
    __tablename__ = "domain_prompts"
    __table_args__ = (
        UniqueConstraint("domain_id", "prompt_type", name="uq_domain_prompts_domain_type"),
    )

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    domain_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    prompt_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    domain: Mapped[Domain] = relationship(back_populates="prompts")


class Vault(Base):
    __tablename__ = "vaults"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    vault_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    domain_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True
    )
    embedding_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    binding_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unbound"
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overlap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entity_aware_mode: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    domain: Mapped[Domain | None] = relationship(back_populates="vaults")


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GenerationModel(Base):
    __tablename__ = "generation_models"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    # TEXT instead of JSONB: values are plain scalars (str/int/bool).
    # Storing as TEXT avoids JSON-wrapping quirks when read via asyncpg directly.
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="str")


class Pipeline(Base):
    __tablename__ = "pipelines"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "version", name="uq_pipelines_id_version"),
    )

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    pipeline_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id"), nullable=False
    )
    campaign_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True
    )
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[Any] = mapped_column(JSONB, nullable=False)
    final_composition: Mapped[Any] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    domain: Mapped[Domain] = relationship(back_populates="pipelines")


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    domain_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    domain: Mapped[Domain] = relationship(back_populates="chats")
    messages: Mapped[list[Message]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )
    campaign: Mapped[Campaign | None] = relationship(back_populates="chats")
    clarification_state: Mapped[ClarificationState | None] = relationship(
        back_populates="chat", uselist=False, cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    chat_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # JSONB: stores list of source dicts [{chunk_id, score, text, ...}]
    sources: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chat: Mapped[Chat] = relationship(back_populates="messages")


class ClarificationState(Base):
    __tablename__ = "clarification_states"

    chat_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    missing_fields: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    collected: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chat: Mapped[Chat] = relationship(back_populates="clarification_state")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DomainClarificationField(Base):
    __tablename__ = "domain_clarification_fields"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    domain_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    field_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    options: Mapped[str | None] = mapped_column(Text, nullable=True)
    placeholder: Mapped[str | None] = mapped_column(String(256), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    domain: Mapped[Domain] = relationship(back_populates="clarification_fields")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    domain: Mapped[Domain] = relationship(back_populates="campaigns")
    chats: Mapped[list[Chat]] = relationship(back_populates="campaign")
    tags: Mapped[list[Tag]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    domain: Mapped[Domain] = relationship(back_populates="tags")
    campaign: Mapped[Campaign | None] = relationship(back_populates="tags")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    vault_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    md5: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mtime: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PipelineDecision(Base):
    __tablename__ = "pipeline_decisions"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    message_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # JSONB: stores list of executed step dicts [{name, status, duration_ms, ...}]
    steps: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    final_composition: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
