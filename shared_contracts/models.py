from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='before')
    @classmethod
    def _coerce_uuid_fields(cls, data: Any) -> Any:
        """Авто-конвертация uuid.UUID ORM-атрибутов в str для str-полей.

        ВАЖНО: намеренно пропускаем list-поля (релатионшипы типа tags, chats и т.п.).
        getattr на lazy SQLAlchemy relationship в async-контексте вызывает MissingGreenlet.
        List-поля заполняются явно снаружи (в роуте или хелпере) — не через from_attributes.
        """
        if not hasattr(data, '__dict__') and not hasattr(data, '__mapper__'):
            return data
        result: dict[str, Any] = {}
        for field_name, field_info in cls.model_fields.items():
            annotation = field_info.annotation
            origin = getattr(annotation, '__origin__', None)
            if origin is list:
                continue
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
    semantic_threshold: float = 0.3
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
    semantic_threshold: float = 0.3


class VaultUpdate(BaseModel):
    domain_id: str | None = None
    display_name: str | None = None
    enabled: bool | None = None
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    semantic_threshold: float | None = None
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
    char_count: int | None = None
    chunk_count: int | None = None
    estimated_tokens: int | None = None
    tags: list[TagRead] = []
    created_at: datetime | None = None


class DocumentCandidate(BaseModel):
    document_id: str
    title: str
    source_path: str
    char_count: int | None = None
    chunk_count: int | None = None
    estimated_tokens: int | None = None
    already_sent: bool


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


# ---------------------------------------------------------------------------
# Pipeline contracts — DAG-based execution model
# ---------------------------------------------------------------------------

class PipelineStep(BaseModel):
    """Шаг пайплайна в DAG-модели.

    Правила:
    - step_id уникален в рамках одного пайплайна (проверяется в Pipeline-валидаторе)
    - after_step_ids не может содержать собственный step_id (self-loop)
    - Поля top_k, tag_ids, role, output_format — только для type=retrieval
    - Поля validation_prompt, options — только для type=validation
    """
    step_id: str                                           # user-defined slug, e.g. "analyze"
    type: Literal["retrieval", "validation"]
    name: str                                              # отображаемое название
    system_prompt: str                                     # поддерживает {STEP_ID.result}, {STEP_ID.key}, {query}
    after_step_ids: list[str] = Field(default_factory=list)  # [] = стартовый шаг

    # --- только для type=retrieval ---
    top_k: int | None = None
    tag_ids: list[str] = Field(default_factory=list)
    role: str | None = None
    output_format: Literal["text", "json"] = "text"

    # --- только для type=validation ---
    validation_prompt: str | None = None                   # поддерживает {STEP_ID.result}
    options: list[str] | None = None                       # варианты выбора (опционально)

    @model_validator(mode='after')
    def _validate_step(self) -> 'PipelineStep':
        # self-loop
        if self.step_id in self.after_step_ids:
            raise ValueError(
                f"Step '{self.step_id}' cannot reference itself in after_step_ids"
            )
        # поля только для retrieval
        if self.type == "validation":
            if self.top_k is not None:
                raise ValueError("top_k is only valid for type=retrieval")
            if self.tag_ids:
                raise ValueError("tag_ids is only valid for type=retrieval")
            if self.role is not None:
                raise ValueError("role is only valid for type=retrieval")
            if self.output_format != "text":
                raise ValueError("output_format is only valid for type=retrieval")
        # поля только для validation
        if self.type == "retrieval":
            if self.validation_prompt is not None:
                raise ValueError("validation_prompt is only valid for type=validation")
            if self.options is not None:
                raise ValueError("options is only valid for type=validation")
        return self


class FinalComposition(BaseModel):
    """Финальная LLM-композиция после всех шагов пайплайна.

    Поддерживаемые переменные в system_prompt:
      {STEP_ID.result}   — полный текстовый результат шага
      {STEP_ID.key}      — ключ из JSON-результата шага (output_format=json)
      {query}            — запрос пользователя

    УДАЛЕНЫ (ломающее изменение, применяется миграционным скриптом в Этапе 2):
      {context}          — заменить на явные {STEP_ID.result}
      {collected_fields} — если нужны — передать через validation-шаг
    """
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
    campaign_id: str | None = None
    name: str
    description: str | None = None
    steps: list[PipelineStep]
    final_composition: FinalComposition

    @model_validator(mode='after')
    def _validate_unique_step_ids(self) -> 'PipelineCreate':
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            duplicates = [sid for sid in ids if ids.count(sid) > 1]
            raise ValueError(f"Duplicate step_ids in pipeline: {list(set(duplicates))}")
        return self


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[PipelineStep] | None = None
    final_composition: FinalComposition | None = None
    is_active: bool | None = None

    @model_validator(mode='after')
    def _validate_unique_step_ids(self) -> 'PipelineUpdate':
        if self.steps is not None:
            ids = [s.step_id for s in self.steps]
            if len(ids) != len(set(ids)):
                duplicates = [sid for sid in ids if ids.count(sid) > 1]
                raise ValueError(f"Duplicate step_ids in pipeline: {list(set(duplicates))}")
        return self


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
    locked_pipeline_id: str | None = None  # fix: поле отсутствовало — фронт не получал значение после lock
    full_document_mode_enabled: bool = False
    sent_full_document_ids: list[str] = Field(default_factory=list)
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
    """Read/cache contract for a single vault's configuration.

    Mirrors the `vaults` DB table columns used by the indexer for runtime
    decisions (embedding model, chunking, git identity).
    Additions here must stay in sync with migration 0005_campaign_update_git_identity.
    """
    vault_id: str
    domain_id: str
    enabled: bool = True
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    semantic_threshold: float = 0.3
    binding_status: str = "unbound"
    chunk_count: int = 0
    # Git identity fields — added by migration 0005_campaign_update_git_identity.
    # Used by indexer to sign commits; fallback to env GIT_AUTHOR_NAME/EMAIL when None.
    git_author_name: str | None = None
    git_author_email: str | None = None


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


# ---------------------------------------------------------------------------
# Clarification FSM state contract
# ---------------------------------------------------------------------------

class ClarificationState(BaseModel):
    """Пыдантик-DTO состояния машины уточняющих вопросов.

    Не является ORM-моделью — живёт только в памяти и передаётся
    между clarification_fsm и chat-роутом.
    Персистируется через ClarificationState ORM-строку в БД
    (app/db/models.py :: ClarificationState).
    """
    stage: Literal["idle", "collecting", "complete", "fallback"] = "idle"
    missing_fields: list[str] = Field(default_factory=list)
    collected: dict[str, str] = Field(default_factory=dict)
    turn: int = 0
    next_question: str | None = None


class PipelineExecutionContext(BaseModel):
    """Полный контекст для запуска пайплайна.

    pipeline_id, pipeline_version, steps, final_composition — Optional:
    объект создаётся до pipeline_router.select(), затем поля дописываются.
    PipelineExecutor обязан проверять что поля заполнены перед запуском.

    step_results — накапливается в процессе выполнения DAG:
      output_format=text  → step_results[step_id] = "строка"
      output_format=json  → step_results[step_id] = dict (при ошибке парсинга — строка)
      type=validation     → step_results[step_id] = ответ пользователя (строка)
    """
    chat_id: str
    message_id: str
    query: str
    original_query: str | None = None  # оригинал до переформулировки QueryRewriter-ом
    domain_id: str | None = None
    campaign_id: str | None = None
    vault_ids: list[str] = Field(default_factory=list)
    vault_id: str | None = None  # deprecated back-compat; используй vault_ids
    # C-STREAM02: заполняются после pipeline_router.select() — не при создании объекта
    pipeline_id: str | None = None
    pipeline_version: str | None = None
    steps: list[PipelineStep] | None = None
    final_composition: FinalComposition | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_strategy: str | None = None
    # Заполняются pipeline_router.select() после выбора пайплайна
    confidence: float | None = None
    reasoning: str | None = None
    mode: str | None = None
    # Накапливается в процессе DAG-выполнения
    step_results: dict[str, Any] = Field(default_factory=dict)

    def resolve(self, template: str) -> str:
        """Подставить {STEP_ID.result} и {STEP_ID.key} из накопленных step_results.

        Также поддерживает {query} — подставляется напрямую через format_map.
        Делегирует в resolve_step_vars() из prompt_pack.
        """
        # Импорт здесь во избежание циклических зависимостей:
        # shared_contracts не должен импортировать rag-backend напрямую.
        # В продакшне resolve_step_vars будет доступен как пакет в sys.path.
        try:
            from app.services.prompt_pack import resolve_step_vars  # type: ignore[import]
        except ImportError:
            # Fallback для контекстов где rag-backend не в sys.path (тесты shared_contracts)
            from prompt_pack import resolve_step_vars  # type: ignore[import]

        # Сначала разворачиваем {query} через простой .replace, чтобы не ломать
        # паттерн {STEP_ID.xxx} для resolve_step_vars
        resolved = template.replace("{query}", self.query)
        return resolve_step_vars(resolved, self.step_results)


class PipelineStepResult(BaseModel):
    step_id: str                                           # slug шага (новое поле)
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


# ---------------------------------------------------------------------------
# LanceDB / db-api-server contracts
# ---------------------------------------------------------------------------

class UpsertChunk(BaseModel):
    """Один чанк для записи в LanceDB."""
    document_id: str
    chunk_index: int
    text: str
    vector: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpsertRequest(BaseModel):
    vault_id: str
    chunks: list[UpsertChunk]


class UpsertResponse(BaseModel):
    status: Literal["ok", "partial"]
    upserted_count: int = 0
    failed_indices: list[int] = Field(default_factory=list)
    error_details: list[str] = Field(default_factory=str)


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float


class SearchRequest(BaseModel):
    vault_id: str
    vector: list[float]
    top_k: int = Field(default=10, ge=1, le=200)
    score_threshold: float | None = None
    filter: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Indexer task API contracts (rag-indexer/app/main.py)
# ---------------------------------------------------------------------------

class StartIndexTaskRequest(BaseModel):
    vault_id: str
    force_reindex: bool = False


class StartIndexTaskResponse(BaseModel):
    task_id: str
    vault_id: str
    status: str


class TaskStateResponse(BaseModel):
    task_id: str
    vault_id: str
    status: str
    state: IndexState | None = None


# ---------------------------------------------------------------------------
# WebSocket progress messages (rag-indexer → frontend)
# ---------------------------------------------------------------------------

class WSFileChunkProgressMessage(BaseModel):
    """Прогресс обработки файла: стадия + счётчики чанков."""
    type: Literal["file_chunk_progress"] = "file_chunk_progress"
    task_id: str
    file_path: str
    stage: Literal["parsing", "chunking", "indexing", "done", "error", "empty", "cancelled"]
    chunks_total: int = 0
    chunks_processed: int = 0
    error: str | None = None


class WSFileStatusMessage(BaseModel):
    """Финальный статус файла после индексации."""
    type: Literal["file_status"] = "file_status"
    task_id: str
    file_path: str
    status: Literal["done", "error", "empty", "cancelled"]
    chunk_count: int = 0
    error: str | None = None


class WSTaskCancelledMessage(BaseModel):
    """Задача индексации отменена."""
    type: Literal["task_cancelled"] = "task_cancelled"
    task_id: str


class WSTaskCompleteMessage(BaseModel):
    """Задача индексации завершена успешно."""
    type: Literal["task_complete"] = "task_complete"
    task_id: str
    files_total: int = 0
    files_indexed: int = 0


# ---------------------------------------------------------------------------
# Planner contracts
# ---------------------------------------------------------------------------

class PipelineInvocation(BaseModel):
    """Пайплайн, запланированный Planner-ом к выполнению."""
    pipeline_id: str
    domain: str | None = None
    priority: int = 0


class PlannerDecision(BaseModel):
    """Решение Planner.decide(): стратегия ретривала + нужна ли кларификация."""
    retrieval_strategy: str  # "none" | "semantic" | ...
    clarification_needed: bool = False
    pipeline_invocations: list[PipelineInvocation] = Field(default_factory=list)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Campaign Update Mode — Phase 2
# ---------------------------------------------------------------------------

class UpdateModeAction(str, Enum):
    UPDATE = "update"
    CREATE = "create"


class UpdateModeOperation(str, Enum):
    APPEND_AFTER_SECTION = "append_after_section"
    APPEND_TO_FILE = "append_to_file"
    REPLACE_UNIQUE_TEXT = "replace_unique_text"
    CREATE_FILE = "create_file"


class UpdateModeChangeStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLUTION_FAILED = "resolution_failed"


class UpdateModeVaultApplyStatus(str, Enum):
    APPLIED = "applied"
    CONFLICT = "conflict"
    FAILED = "failed"
    NO_CHANGES = "no_changes"


# --- LLM intent contracts ---

class UpdateModeAnchor(BaseModel):
    kind: Literal["markdown_heading", "exact_text"]
    value: str = Field(min_length=1, max_length=16_384)


class UpdateModeIntent(BaseModel):
    change_id: str
    action: UpdateModeAction
    description: str = Field(min_length=1, max_length=2_000)

    document_id: str | None = None
    parent_document_id: str | None = None

    operation: UpdateModeOperation
    anchor: UpdateModeAnchor | None = None

    suggested_filename: str | None = None
    content: str = Field(min_length=1, max_length=65_536)

    @model_validator(mode="after")
    def _validate_intent_invariants(self) -> "UpdateModeIntent":
        if self.action == UpdateModeAction.UPDATE:
            if self.document_id is None:
                raise ValueError("update action requires document_id")
            if self.parent_document_id is not None:
                raise ValueError("update action must not have parent_document_id")
            if self.suggested_filename is not None:
                raise ValueError("update action must not have suggested_filename")
            valid_ops = {
                UpdateModeOperation.APPEND_AFTER_SECTION,
                UpdateModeOperation.APPEND_TO_FILE,
                UpdateModeOperation.REPLACE_UNIQUE_TEXT,
            }
            if self.operation not in valid_ops:
                raise ValueError(f"update action requires operation in {[o.value for o in valid_ops]}")
            if self.operation == UpdateModeOperation.APPEND_AFTER_SECTION:
                if self.anchor is None or self.anchor.kind != "markdown_heading":
                    raise ValueError("append_after_section requires anchor.kind == markdown_heading")
            if self.operation == UpdateModeOperation.REPLACE_UNIQUE_TEXT:
                if self.anchor is None or self.anchor.kind != "exact_text":
                    raise ValueError("replace_unique_text requires anchor.kind == exact_text")
            if self.operation == UpdateModeOperation.APPEND_TO_FILE:
                if self.anchor is not None:
                    raise ValueError("append_to_file must not have anchor")

        if self.action == UpdateModeAction.CREATE:
            if self.document_id is not None:
                raise ValueError("create action must not have document_id")
            if self.operation != UpdateModeOperation.CREATE_FILE:
                raise ValueError("create action requires operation == create_file")
            if self.anchor is not None:
                raise ValueError("create action must not have anchor")
            if self.suggested_filename is None:
                raise ValueError("create action requires suggested_filename")

        if self.document_id is not None and self.parent_document_id is not None:
            raise ValueError("document_id and parent_document_id are mutually exclusive")

        return self


class UpdateModeIntentBatch(BaseModel):
    intents: list[UpdateModeIntent] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _validate_unique_change_ids(self) -> "UpdateModeIntentBatch":
        ids = [i.change_id for i in self.intents]
        if len(ids) != len(set(ids)):
            raise ValueError("change_id must be unique within batch")
        return self


# --- Phase 3: executor-level DTOs ---

class IndexedContextDocument(BaseModel):
    """In-memory DTO для документа, включённого в LLM-контекст.

    Используется только внутри UpdateModeExecutor — не персистируется.
    """
    document_id: str
    vault_id: str
    source_path: str
    title: str | None
    text: str
    estimated_tokens: int


class UpdateModeGenerationResult(BaseModel):
    """Outer wrapper результата генерации LLM.

    Отличается от UpdateModeIntentBatch тем, что допускает пустой список intents
    (когда note не содержит actionable изменений). В этом случае обязателен
    no_change_reason.

    Инварианты:
    - empty intents → non-empty no_change_reason
    - non-empty intents → no_change_reason must be None
    """
    intents: list[UpdateModeIntent] = Field(default_factory=list, max_length=10)
    no_change_reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def _validate_no_change_invariant(self) -> "UpdateModeGenerationResult":
        if not self.intents and not self.no_change_reason:
            raise ValueError(
                "no_change_reason is required when intents list is empty"
            )
        if self.intents and self.no_change_reason is not None:
            raise ValueError(
                "no_change_reason must be None when intents are present"
            )
        return self


# --- Internal indexer API contracts ---

class UpdateModeResolveRequest(BaseModel):
    chat_id: str
    campaign_id: str
    domain_id: str
    vault_ids: list[str] = Field(min_length=1)
    intents: list[UpdateModeIntent] = Field(min_length=1, max_length=10)
    default_vault_id: str
    candidate_document_ids: list[str] = Field(
        default_factory=list, min_length=0, max_length=15
    )

    @model_validator(mode="after")
    def _validate_default_vault(self) -> "UpdateModeResolveRequest":
        if self.default_vault_id not in self.vault_ids:
            raise ValueError("default_vault_id must be in vault_ids")
        return self


class ResolvedUpdateModeChange(BaseModel):
    change_id: str
    vault_id: str | None = None
    document_id: str | None = None
    file_path: str | None = None

    action: UpdateModeAction
    description: str

    original_content: str = ""
    proposed_content: str = ""
    unified_diff: str = ""
    expected_sha256: str | None = None

    status: UpdateModeChangeStatus = UpdateModeChangeStatus.PENDING
    error_code: str | None = None
    error_message: str | None = None


class UpdateModeResolveResponse(BaseModel):
    changes: list[ResolvedUpdateModeChange]


class UpdateModeApplyChange(BaseModel):
    change_id: str
    vault_id: str
    file_path: str
    action: UpdateModeAction
    proposed_content: str
    expected_sha256: str | None = None

    @model_validator(mode="after")
    def _validate_sha_policy(self) -> "UpdateModeApplyChange":
        if self.action == UpdateModeAction.UPDATE and self.expected_sha256 is None:
            raise ValueError("update action requires expected_sha256")
        if self.action == UpdateModeAction.CREATE and self.expected_sha256 is not None:
            raise ValueError("create action must not have expected_sha256")
        return self


class UpdateModeApplyRequest(BaseModel):
    apply_id: str
    chat_id: str
    campaign_id: str
    accepted_changes: list[UpdateModeApplyChange] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _validate_apply_request(self) -> "UpdateModeApplyRequest":
        change_ids = [c.change_id for c in self.accepted_changes]
        if len(change_ids) != len(set(change_ids)):
            raise ValueError("change_id must be unique in accepted_changes")
        path_pairs = [(c.vault_id, c.file_path) for c in self.accepted_changes]
        if len(path_pairs) != len(set(path_pairs)):
            raise ValueError("(vault_id, file_path) pairs must be unique in accepted_changes")
        return self


class UpdateModeVaultApplyResult(BaseModel):
    vault_id: str
    status: UpdateModeVaultApplyStatus
    applied_count: int = Field(ge=0)

    snapshot_commit_sha: str | None = None
    commit_sha: str | None = None
    commit_message: str | None = None

    reindex_task_id: str | None = None
    reindex_error: str | None = None

    error_code: str | None = None
    error_message: str | None = None


class UpdateModeApplyResponse(BaseModel):
    apply_id: str
    results: list[UpdateModeVaultApplyResult] = Field(min_length=1)


# --- Public backend API contracts ---

class StartUpdateModeRequest(BaseModel):
    note: str = Field(min_length=1, max_length=20_000)


class StartUpdateModeResponse(BaseModel):
    chat_id: str
    expires_at: datetime
    changes: list[ResolvedUpdateModeChange]
    warnings: list[str] = Field(default_factory=list)


class UpdateModeSessionResponse(BaseModel):
    chat_id: str
    campaign_id: str
    domain_id: str
    vault_ids: list[str]
    expires_at: datetime
    changes: list[ResolvedUpdateModeChange]
    warnings: list[str] = Field(default_factory=list)


class UpdateModeReviewRequest(BaseModel):
    accepted_change_ids: list[str] = Field(default_factory=list, max_length=10)
    rejected_change_ids: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _validate_no_overlap(self) -> "UpdateModeReviewRequest":
        accepted = set(self.accepted_change_ids)
        rejected = set(self.rejected_change_ids)
        overlap = accepted & rejected
        if overlap:
            raise ValueError(f"change_ids cannot be both accepted and rejected: {overlap}")
        if not accepted and not rejected:
            raise ValueError("review request must contain at least one accepted or rejected change_id")
        return self


class ApplyUpdateModeRequest(BaseModel):
    apply_id: str | None = None


class ApplyUpdateModeResponse(BaseModel):
    apply_id: str
    results: list[UpdateModeVaultApplyResult]


class CancelUpdateModeResponse(BaseModel):
    status: Literal["cancelled"]


# --- Redis session contract ---

class UpdateModeSession(BaseModel):
    session_id: str
    chat_id: str
    campaign_id: str
    domain_id: str

    vault_ids: list[str]
    default_vault_id: str
    candidate_document_ids: list[str]

    note: str
    warnings: list[str] = Field(default_factory=list)
    changes: list[ResolvedUpdateModeChange]

    created_at: datetime
    expires_at: datetime

    apply_id: str | None = None
    apply_started_at: datetime | None = None
