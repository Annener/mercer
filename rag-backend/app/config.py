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
    max_clarification_turns: int = Field(default=3, ge=0, le=10)
    stream_answers: bool = True
    auto_title: bool = True


class RetrievalConfig(BaseModel):
    enabled: bool = True
    top_k: int = Field(default=10, ge=1, le=100)
    reranker_enabled: bool = False


class PipelinesConfig(BaseModel):
    enabled: bool = True
    path: str = "/app/pipelines"
    reload_interval_seconds: float = Field(default=2.0, ge=0.5, le=60.0)
    debounce_seconds: float = Field(default=2.0, ge=0.0, le=30.0)


class UIConfig(BaseModel):
    db_management_enabled: bool = True


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
    pipelines: PipelinesConfig = Field(default_factory=PipelinesConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    validation_rules: dict[str, ValidationRuleRange] = Field(default_factory=dict)
