from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ParamUpdateRequest(BaseModel):
    value: Any = None


class DomainCreateRequest(BaseModel):
    domain_id: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    enabled: bool = True


class DomainUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    enabled: bool | None = None


class PromptUpdateRequest(BaseModel):
    content: str


class ClarificationFieldRequest(BaseModel):
    field_name: str
    label: str
    hint: str | None = None
    required: bool = True
    display_order: int = 0


class GenerationModelCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    provider: str = "openai_compatible"
    display_name: str | None = None
    base_url: str = ""
    api_key: str | None = None
    timeout_seconds: int = 60
    enabled: bool = True


class GenerationModelUpdateRequest(BaseModel):
    provider: str | None = None
    display_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None


class EmbeddingModelCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    provider: str
    display_name: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    dimensions: int = Field(gt=0)
    timeout_seconds: int = 30
    max_retries: int = 3
    enabled: bool = True


class EmbeddingModelUpdateRequest(BaseModel):
    provider: str | None = None
    display_name: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    timeout_seconds: int | None = None
    max_retries: int | None = None
    enabled: bool | None = None


class VaultCreateRequest(BaseModel):
    vault_id: str
    domain_id: str
    display_name: str | None = None
    embedding_model_id: str | None = None
    create_folder: bool = False


class VaultUpdateRequest(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    embedding_model_id: str | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None


# S48-2 fix: removed stale CampaignCreateRequest and CampaignUpdateRequest (old schema:
# campaign_id str, path_prefix, is_active). Campaigns route uses shared_contracts.models
# CampaignCreate / CampaignUpdate since migration 0009 (domain-based, not vault-based).
# WorldCreateRequest / WorldUpdateRequest also left as-is (no active route references found).

# D04 fix: добавлена строгая Pydantic-схема для POST /{campaign_id}/tags.
# Было: payload: dict — KeyError → 500 при отсутствии поля name.
class CampaignTagCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    color: str | None = None


class PipelineCreateRequest(BaseModel):
    pipeline_id: str
    domain_id: str
    name: str
    description: str | None = None
    steps: list[dict[str, Any]]
    final_composition: dict[str, Any]
    is_active: bool = True


class PipelineUpdateRequest(BaseModel):
    domain_id: str | None = None
    name: str | None = None
    description: str | None = None
    steps: list[dict[str, Any]] | None = None
    final_composition: dict[str, Any] | None = None
    is_active: bool | None = None
