from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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
        "indexed",  # back-compat с V2.1
    ]
    progress_pct: int = Field(default=0, ge=0, le=100)  # deprecated, для back-compat
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


class CampaignRead(ORMModel):
    id: str
    campaign_id: str
    world_id: str
    vault_id: str
    name: str
    description: str | None = None
    path_prefix: str
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CampaignCreate(BaseModel):
    campaign_id: str
    world_id: str | None = None
    vault_id: str | None = None
    name: str
    description: str | None = None
    path_prefix: str
    is_active: bool = True


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    path_prefix: str | None = None
    is_active: bool | None = None


class PipelineStep(BaseModel):
    order: int
    type: Literal["book", "world", "campaign"]
    name: str
    role: Literal["methodology", "lore", "campaign_context", "character_sheet", "session_log", "rules"]
    system_prompt: str
    top_k: int | None = None
    document_ids: list[str] | None = None
    world_id: str | None = None
    categories: list[str] | None = None
    campaign_id: str | None = None


class FinalComposition(BaseModel):
    system_prompt: str


class PipelineRead(ORMModel):
    id: str
    pipeline_id: str
    domain_id: str
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
    name: str
    description: str | None = None
    steps: list[PipelineStep]
    final_composition: FinalComposition
    is_active: bool = True


class PipelineUpdate(PipelineCreate):
    pass


class ClarificationState(BaseModel):
    stage: Literal["idle", "collecting", "complete", "fallback"] = "idle"
    missing_fields: list[str] = Field(default_factory=list)
    collected: dict[str, Any] = Field(default_factory=dict)
    turn: int = 0
    next_question: str | None = None


class ChatMessage(BaseModel):
    message_id: str
    chat_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRecord(BaseModel):
    chat_id: str
    title: str = "New Chat"
    vault_id: str | None = None
    domain_id: str | None = None
    world_id: str | None = None
    locked_pipeline_id: str | None = None
    created_at: datetime
    updated_at: datetime
    pipeline_versions: dict[str, Any] = Field(default_factory=dict)


class PipelineContext(BaseModel):
    query: str
    vault_id: str
    domain_id: str | None = None
    context_chunks: list[ChunkRecord] = Field(default_factory=list)
    clarification_collected: dict[str, Any] = Field(default_factory=dict)
    chat_history: list[ChatMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    content: str
    confidence: float | None = None
    sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineInvocation(BaseModel):
    pipeline_id: str
    domain: str
    priority: int = 0


class PlannerDecision(BaseModel):
    retrieval_strategy: Literal["semantic", "keyword", "hybrid", "none"] = "semantic"
    clarification_needed: bool = False
    pipeline_invocations: list[PipelineInvocation] = Field(default_factory=list)
    reasoning: str | None = None


class StartIndexTaskRequest(BaseModel):
    vault_id: str
    force_reindex: bool = False


class StartIndexTaskResponse(BaseModel):
    task_id: str
    vault_id: str
    status: Literal["queued", "running"]


class TaskStateResponse(BaseModel):
    task_id: str
    vault_id: str
    status: Literal["running", "done", "error", "cancelled"]
    state: IndexState


class CreateChatRequest(BaseModel):
    vault_id: str | None = None
    domain_id: str | None = None
    world_id: str | None = None


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
    state: ClarificationState


class UpsertChunk(BaseModel):
    document_id: str
    chunk_index: int
    text: str  # ← text_for_bm25: чистый текст (для BM25 и UI)
    vector: list[float]  # ← embedding от text_for_embedding (обогащённый)
    metadata: dict[str, Any] = Field(default_factory=dict)  # ← включает embedding_text для отладки


class UpsertRequest(BaseModel):
    vault_id: str
    chunks: list[UpsertChunk]


class UpsertResponse(BaseModel):
    status: Literal["ok", "partial"]
    upserted_count: int
    failed_indices: list[int] = Field(default_factory=list)
    error_details: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    vault_id: str
    vector: list[float]
    top_k: int = 10
    filter: dict[str, Any] | None = None
    score_threshold: float | None = None


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float


class SearchResponse(BaseModel):
    results: list[SearchHit] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    trace_id: str | None = None


class WSFileStatusMessage(BaseModel):
    """
    Deprecated (V2.1): оставлено для back-compat.
    Используйте WSFileChunkProgressMessage для нового UI.
    """
    type: Literal["file_status"] = "file_status"
    task_id: str
    file_path: str
    status: Literal["parsing", "chunking", "embedding", "indexed", "error", "done", "cancelled", "pending", "indexing", "empty"]
    progress_pct: int = Field(default=0, ge=0, le=100)
    error: str | None = None


class WSFileChunkProgressMessage(BaseModel):
    """
    V3.0: прогресс индексации файла по чанкам (chunks_processed / chunks_total).
    Стадии: parsing → chunking → indexing → done | error
    """
    type: Literal["file_chunk_progress"] = "file_chunk_progress"
    task_id: str
    file_path: str
    stage: Literal["parsing", "chunking", "indexing", "done", "error", "pending", "cancelled", "empty"]
    chunks_total: int = 0
    chunks_processed: int = 0
    error: str | None = None


class WSTaskCompleteMessage(BaseModel):
    type: Literal["task_complete"] = "task_complete"
    task_id: str
    status: Literal["done"] = "done"
    files_total: int
    files_indexed: int


class WSTaskCancelledMessage(BaseModel):
    type: Literal["task_cancelled"] = "task_cancelled"
    task_id: str
    status: Literal["cancelled"] = "cancelled"


type TaskStreamEvent = (
    WSFileStatusMessage
    | WSFileChunkProgressMessage
    | WSTaskCompleteMessage
    | WSTaskCancelledMessage
)


__all__ = [
    "CampaignCreate",
    "CampaignRead",
    "CampaignUpdate",
    "ChatMessage",
    "ChatRecord",
    "ChunkRecord",
    "ClarificationResponse",
    "ClarificationState",
    "CreateChatRequest",
    "CreateChatResponse",
    "DocumentRecord",
    "DomainClarificationFieldCreate",
    "DomainClarificationFieldRead",
    "DomainCreate",
    "DomainPromptRead",
    "DomainPromptUpdate",
    "DomainRead",
    "DomainUpdate",
    "EmbeddingModelCreate",
    "EmbeddingModelRead",
    "EmbeddingModelUpdate",
    "EntityRecord",
    "ErrorResponse",
    "FileIndexState",
    "FinalComposition",
    "GenerationModelCreate",
    "GenerationModelRead",
    "GenerationModelUpdate",
    "IndexState",
    "PipelineCreate",
    "PipelineContext",
    "PipelineInvocation",
    "PipelineRead",
    "PipelineResult",
    "PipelineStep",
    "PipelineUpdate",
    "PlatformSettingRead",
    "PlatformSettingUpdate",
    "PlannerDecision",
    "SearchHit",
    "SearchRequest",
    "SearchResponse",
    "SendMessageRequest",
    "StartIndexTaskRequest",
    "StartIndexTaskResponse",
    "TaskStateResponse",
    "TaskStreamEvent",
    "UpsertChunk",
    "UpsertRequest",
    "UpsertResponse",
    "VaultBinding",
    "VaultCreate",
    "VaultRead",
    "VaultUpdate",
    "WSFileStatusMessage",
    "WSFileChunkProgressMessage",
    "WSTaskCancelledMessage",
    "WSTaskCompleteMessage",
]
