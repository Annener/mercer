from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='before')
    @classmethod
    def _coerce_uuid_fields(cls, data: Any) -> Any:
        """Auto-coerce uuid.UUID ORM attributes to str for all str-typed fields."""
        if not hasattr(data, '__dict__') and not hasattr(data, '__mapper__'):
            return data
        result: dict[str, Any] = {}
        for field_name, field_info in cls.model_fields.items():
            val = getattr(data, field_name, None)
            if isinstance(val, _uuid.UUID):
                result[field_name] = str(val)
            elif val is not None:
                result[field_name] = val
            else:
                result[field_name] = val
        return result


class FileIndexState(BaseModel):
    checksum_md5: str
    chunk_ids: list[str] = Field(default_factory=list)
    status: Literal[
        "pending",
        "parsing",
        "chunking",
        "indexing",
        "done",
        "error",
        "cancelled",
        "empty",
        "indexed",  # back-compat V2.1
    ]
    progress_pct: int = Field(default=0, ge=0, le=100)  # deprecated, back-compat
    chunks_total: int = 0
    chunks_processed: int = 0
    last_modified: datetime
    error: str | None = None


class IndexState(BaseModel):
    version: str = "1.0"
    task_id: str
    vault_id: str
    status: Literal["running", "done", "error", "cancelled"]
    last_updated: datetime
    files: dict[str, FileIndexState] = Field(default_factory=dict)
    error: str | None = None


class DocumentRecord(BaseModel):
    document_id: str
    vault_id: str
    source_path: str
    checksum: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_count: int = 0


class ChunkRecord(BaseModel):
    chunk_id: str
    document_id: str
    vault_id: str
    text: str
    vector: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None


class EntityRecord(BaseModel):
    entity_id: str
    kind: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_chunk_ids: list[str] = Field(default_factory=list)


class VaultBinding(BaseModel):
    vault_id: str
    embedding_model_id: str
    expected_dimensions: int = Field(gt=0)
    locked: bool = False
    status: Literal["unbound", "binding", "bound", "error"] = "unbound"
    chunk_count: int = 0


class DomainRead(ORMModel):
    domain_id: str
    display_name: str
    description: str | None = None
    is_system: bool = False
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DomainCreate(BaseModel):
    domain_id: str
    display_name: str
    description: str | None = None
    enabled: bool = True


class DomainUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    enabled: bool | None = None


class DomainPromptRead(ORMModel):
    id: str | None = None
    domain_id: str
    prompt_type: Literal["system", "clarification", "planner", "pipeline_router"]
    content: str
    updated_at: datetime | None = None


class DomainPromptUpdate(BaseModel):
    content: str


class DomainClarificationFieldRead(ORMModel):
    id: str | None = None
    domain_id: str
    field_name: str
    label: str
    hint: str | None = None
    required: bool = True
    display_order: int = 0


class DomainClarificationFieldCreate(BaseModel):
    field_name: str
    label: str
    hint: str | None = None
    required: bool = True
    display_order: int = 0


class PlatformSettingRead(ORMModel):
    key: str
    value: Any
    value_type: Literal["int", "float", "bool", "str"]
    group_name: str
    label: str
    hint: str
    updated_at: datetime | None = None


class PlatformSettingUpdate(BaseModel):
    value: Any


class GenerationModelRead(ORMModel):
    model_id: str
    provider: str = "openai_compatible"
    display_name: str | None = None
    base_url: str
    timeout_seconds: int = 60
    is_active: bool = False
    enabled: bool = True
    has_api_key: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GenerationModelCreate(BaseModel):
    model_id: str
    provider: str = "openai_compatible"
    display_name: str | None = None
    base_url: str
    api_key: str | None = None
    timeout_seconds: int = 60
    enabled: bool = True


class GenerationModelUpdate(BaseModel):
    provider: str | None = None
    display_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None


class EmbeddingModelRead(ORMModel):
    model_id: str
    provider: Literal["ollama", "openai_compatible"]
    display_name: str | None = None
    model_name: str
    base_url: str
    dimensions: int
    timeout_seconds: int = 30
    max_retries: int = 3
    enabled: bool = True
    has_api_key: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EmbeddingModelCreate(BaseModel):
    model_id: str
    provider: Literal["ollama", "openai_compatible"]
    display_name: str | None = None
    model_name: str
    base_url: str
    api_key: str | None = None
    dimensions: int = Field(gt=0)
    timeout_seconds: int = 30
    max_retries: int = 3
    enabled: bool = True


class EmbeddingModelUpdate(BaseModel):
    provider: Literal["ollama", "openai_compatible"] | None = None
    display_name: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    timeout_seconds: int | None = None
    max_retries: int | None = None
    enabled: bool | None = None


class VaultRead(ORMModel):
    vault_id: str
    domain_id: str
    display_name: str | None = None
    enabled: bool = True
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    binding_status: Literal["unbound", "indexing", "bound", "error"] = "unbound"
    chunk_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VaultCreate(BaseModel):
    vault_id: str
    domain_id: str
    display_name: str | None = None
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None


class VaultUpdate(BaseModel):
    domain_id: str | None = None
    display_name: str | None = None
    enabled: bool | None = None
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    binding_status: Literal["unbound", "indexing", "bound", "error"] | None = None
    chunk_count: int | None = None


class TagRead(ORMModel):
    """Тег принадлежит домену (не Vault)."""
    id: str
    name: str
    domain_id: str
    campaign_id: str | None = None
    color: str | None = None
    created_at: datetime | None = None


class TagCreate(BaseModel):
    """Создание тега: привязка к домену, не к Vault."""
    name: str
    domain_id: str
    campaign_id: str | None = None
    color: str | None = None


class TagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class TagsGrouped(BaseModel):
    """Ответ GET /tags — теги сгруппированы для UI"""
    global_tags: list[TagRead] = []
    by_campaign: dict[str, list[TagRead]] = {}  # campaign_id → теги


class DocumentRead(ORMModel):
    id: str
    vault_id: str
    source_path: str
    title: str | None = None
    md5: str
    mtime: int
    indexed_at: datetime | None = None
    status: Literal["pending", "indexed", "error"]
    tags: list[TagRead] = []
    created_at: datetime | None = None


class DocumentLabelWrite(BaseModel):
    """Полная замена тегов документа"""
    tag_ids: list[str]


class CampaignRead(ORMModel):
    """Кампания принадлежит домену (не Vault)."""
    id: str
    domain_id: str
    name: str
    description: str | None = None
    system_prompt: str | None = None
    last_session_at: datetime | None = None
    created_at: datetime | None = None
    tags: list[TagRead] = []


class CampaignCreate(BaseModel):
    """Создание кампании: привязка к домену, не к Vault."""
    domain_id: str
    name: str
    description: str | None = None
    system_prompt: str | None = None


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None


class PipelineStep(BaseModel):
    order: int
    type: Literal["retrieval", "final"]
    name: str
    system_prompt: str
    top_k: int | None = None
    tag_ids: list[str] = []   # только для type="retrieval"; фильтруется бэкендом по domain_id
    is_final: bool = False    # ровно один True обязателен в пайплайне
    role: str | None = None   # опциональная метка для UI


class FinalComposition(BaseModel):
    system_prompt: str


class PipelineRead(ORMModel):
    id: str
    pipeline_id: str
    domain_id: str
    campaign_id: str | None = None  # None = общий пайплайн домена
    version: str
    name: str
    description: str | None = None
    steps: list[PipelineStep]
    final_composition: FinalComposition
    is_active: bool = True
    created_at: datetime | None = None


class PipelineCreate(BaseModel):
    pipeline_id: str
    domain_id: str
    campaign_id: str | None = None  # None = общий пайплайн домена
    name: str
    description: str | None = None
    steps: list[PipelineStep]
    final_composition: FinalComposition


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[PipelineStep] | None = None
    final_composition: FinalComposition | None = None
    is_active: bool | None = None


class RetrievalContext(BaseModel):
    """Контекст выполнения пайплайна. vault_id оставлен для back-compat (TODO: удалить в iter4-cleanup)."""
    query: str
    vault_ids: list[str] = Field(default_factory=list)  # все enabled-Vault домена
    vault_id: str | None = None  # deprecated back-compat; используй vault_ids
    domain_id: str | None = None
    campaign_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
    top_k: int = 5
    metadata_filter: dict[str, Any] | None = None


class RetrievalResult(BaseModel):
    chunk_id: str
    document_id: str
    vault_id: str | None = None
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime
    pipeline_id: str | None = None


class ChatRecord(ORMModel):
    id: str
    title: str
    vault_id: str | None = None   # TODO(iter4-cleanup): удалить после полного перехода фронта на domain_id
    domain_id: str | None = None
    campaign_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AuditLogRead(ORMModel):
    id: str
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    actor: str | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime


class VaultConfigEntry(BaseModel):
    vault_id: str
    domain_id: str
    enabled: bool = True
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    binding_status: str = "unbound"
    chunk_count: int = 0


class VaultConfig(BaseModel):
    vaults: dict[str, VaultConfigEntry] = Field(default_factory=dict)


class EmbeddingRequest(BaseModel):
    vault_id: str
    texts: list[str]
    model_id: str | None = None


class EmbeddingResponse(BaseModel):
    vault_id: str
    embeddings: list[list[float]]
    model_id: str


class IndexRequest(BaseModel):
    vault_id: str
    force: bool = False


class IndexResponse(BaseModel):
    vault_id: str
    task_id: str
    status: str


class IndexStatusResponse(BaseModel):
    vault_id: str
    task_id: str | None
    status: str
    progress_pct: int = 0
    chunks_total: int = 0
    chunks_processed: int = 0
    error: str | None = None
    files: dict[str, FileIndexState] = Field(default_factory=dict)


class CreateChatRequest(BaseModel):
    """
    domain_id — основной идентификатор контекста чата.
    vault_id оставлен nullable для back-compat (старые клиенты).
    campaign_id — опциональная привязка к кампании (iter2).
    TODO(iter4-cleanup): сделать domain_id обязательным, убрать vault_id.
    """
    domain_id: str | None = None
    vault_id: str | None = None  # deprecated back-compat
    campaign_id: str | None = None


class CreateChatResponse(BaseModel):
    chat_id: str
    title: str


class SendMessageRequest(BaseModel):
    content: str
    stream: bool = True


class ClarificationResponse(BaseModel):
    message_id: str
    role: Literal["assistant"] = "assistant"
    content: str
    clarification_id: str | None = None
    stage: str | None = None


class ClarificationAnswer(BaseModel):
    clarification_id: str
    answers: dict[str, str]


class PipelineExecutionContext(BaseModel):
    """Полный контекст для запуска пайплайна."""
    chat_id: str
    message_id: str
    query: str
    domain_id: str | None = None
    campaign_id: str | None = None
    vault_ids: list[str] = Field(default_factory=list)
    vault_id: str | None = None  # deprecated back-compat; используй vault_ids
    pipeline_id: str
    pipeline_version: str
    steps: list[PipelineStep]
    final_composition: FinalComposition
    history: list[ChatMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineStepResult(BaseModel):
    step_order: int
    step_name: str
    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    llm_output: str | None = None
    error: str | None = None


class PipelineResult(BaseModel):
    pipeline_id: str
    pipeline_version: str
    steps: list[PipelineStepResult] = Field(default_factory=list)
    final_answer: str
    error: str | None = None
