from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    created_at: datetime
    updated_at: datetime
    pipeline_versions: dict[str, str] = Field(default_factory=dict)


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
    "ChatMessage",
    "ChatRecord",
    "ChunkRecord",
    "ClarificationResponse",
    "ClarificationState",
    "CreateChatRequest",
    "CreateChatResponse",
    "DocumentRecord",
    "EntityRecord",
    "ErrorResponse",
    "FileIndexState",
    "IndexState",
    "PipelineContext",
    "PipelineInvocation",
    "PipelineResult",
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
    "WSFileStatusMessage",
    "WSFileChunkProgressMessage",
    "WSTaskCancelledMessage",
    "WSTaskCompleteMessage",
]