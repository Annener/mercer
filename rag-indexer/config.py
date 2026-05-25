from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class VaultConfig(BaseModel):
    vault_id: str
    domain_id: str
    path: str
    enabled: bool = True


class EmbeddingModelConfig(BaseModel):
    model_id: str
    provider: Literal["ollama", "openai_compatible"]
    model_name: str
    base_url: str
    dimensions: int = Field(gt=0)
    enabled: bool = True
    timeout_seconds: int = 30
    max_retries: int = 3


class GenerationModelConfig(BaseModel):
    model_id: str
    provider: Literal["openai_compatible"]
    base_url: str
    api_key_env: str
    enabled: bool = True
    timeout_seconds: int = 60


class RerankerConfig(BaseModel):
    enabled: bool = False
    provider: str | None = None
    base_url: str | None = None
    model_name: str | None = None


class ChatConfig(BaseModel):
    max_clarification_turns: int = Field(default=3, ge=1, le=10)
    stream_answers: bool = True
    auto_title: bool = True


class RetrievalConfig(BaseModel):
    top_k: int = Field(default=10, ge=1, le=100)
    reranker_enabled: bool = False


class ChunkingConfig(BaseModel):
    entity_aware_mode: bool = False
    chunk_size: int = Field(default=512, ge=64, description="Максимальное количество слов в чанке")
    overlap: int = Field(default=64, ge=0, description="Перекрытие соседних чанков в словах")


class ValidationRuleRange(BaseModel):
    min: float
    max: float


class AppConfig(BaseModel):
    vaults: dict[str, VaultConfig]
    embedding_models: dict[str, EmbeddingModelConfig]
    generation_models: dict[str, GenerationModelConfig]
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    validation_rules: dict[str, ValidationRuleRange] = Field(default_factory=dict)