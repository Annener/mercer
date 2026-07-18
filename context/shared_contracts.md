# Shared Contracts — Общие Pydantic-схемы

Файл: `shared_contracts/models.py`  
Используется: rag-backend, rag-indexer (общие типы для межсервисного взаимодействия)

## Базовые классы

### ORMModel
Базовый класс для схем, читаемых из SQLAlchemy ORM-объектов.
- `from_attributes=True`
- `_coerce_uuid_fields`: автоматически конвертирует `uuid.UUID` в `str`
- **ВАЖНО**: намеренно пропускает list-поля (relationships), чтобы избежать
  `MissingGreenlet` в async-контексте. List-поля заполняются вручную в роутах/хелперах.

## Состояние индексатора (Redis)

```python
FileIndexState:
  checksum_md5: str
  status: pending|parsing|chunking|indexing|done|error|cancelled|empty|indexed
  chunks_total: int = 0
  chunks_processed: int = 0
  progress_pct: int = 0          # deprecated, back-compat
  last_modified: datetime
  error: str | None

IndexState:
  version: str = "1.0"
  task_id: str
  vault_id: str
  status: running|done|error|cancelled
  last_updated: datetime
  files: dict[str, FileIndexState]  # key = source_path
  error: str | None
```

## Записи хранилища (LanceDB через db-api-server)

```python
DocumentRecord:
  document_id: str
  vault_id: str
  source_path: str
  checksum: str
  metadata: dict
  chunk_count: int

ChunkRecord:
  chunk_id: str
  document_id: str
  vault_id: str
  text: str
  vector: list[float] | None
  metadata: dict
  summary: str | None

EntityRecord:
  entity_id: str
  kind: str
  name: str
  metadata: dict
  source_chunk_ids: list[str]

VaultBinding:
  vault_id: str
  embedding_model_id: str
  expected_dimensions: int  # > 0
  locked: bool = False
  status: unbound|binding|bound|error
  chunk_count: int
```

## Операции с LanceDB (db-api-server API)

```python
UpsertChunk:
  document_id: str
  chunk_index: int
  text: str
  vector: list[float]
  metadata: dict

UpsertRequest:
  vault_id: str
  chunks: list[UpsertChunk]

UpsertResponse:
  status: "ok" | "partial"
  upserted_count: int
  failed_indices: list[int]
  error_details: list[str]

SearchHit:
  chunk_id: str
  document_id: str
  text: str
  metadata: dict  # содержит vault_id, source_path, chunk_index и др.
  score: float

SearchRequest:
  vault_id: str
  vector: list[float]
  top_k: int = 10  # ge=1, le=200
  score_threshold: float | None
  filter: dict | None

SearchResponse:
  results: list[SearchHit]
```

## Read/Create/Update схемы (API-контракты)

### Domain
```python
DomainRead(ORMModel): domain_id, display_name, description, is_system, enabled, created_at, updated_at
DomainCreate: domain_id, display_name, description, enabled
DomainUpdate: display_name?, description?, enabled?
```

### DomainPrompt
```python
DomainPromptRead(ORMModel): id, domain_id, prompt_type, content, updated_at
  # prompt_type: system | clarification | planner | pipeline_router
DomainPromptUpdate: content
```

### DomainClarificationField
```python
DomainClarificationFieldRead(ORMModel): id, domain_id, field_name, label, hint, required, display_order
DomainClarificationFieldCreate: field_name, label, hint?, required, display_order
```

### PlatformSetting
```python
PlatformSettingRead(ORMModel): key, value, value_type, group_name, label, hint, updated_at
PlatformSettingUpdate: value  # только value изменяется
```

### GenerationModel
```python
GenerationModelRead(ORMModel): model_id, provider, display_name, base_url, timeout_seconds,
                               is_active, enabled, has_api_key, created_at, updated_at
GenerationModelCreate: model_id, provider, display_name?, base_url, api_key?, timeout_seconds, enabled
GenerationModelUpdate: provider?, display_name?, base_url?, api_key?, timeout_seconds?, enabled?
```

### EmbeddingModel
```python
EmbeddingModelRead(ORMModel): model_id, provider, display_name, model_name, base_url,
                              dimensions, timeout_seconds, max_retries, enabled, has_api_key, ...
EmbeddingModelCreate: model_id, provider (ollama|openai_compatible), model_name, base_url,
                      api_key?, dimensions (>0), timeout_seconds, max_retries, enabled
EmbeddingModelUpdate: все поля optional
```

### RerankModel
```python
RerankModelRead(ORMModel): model_id, provider, display_name, base_url, timeout_seconds,
                           is_active, enabled, has_api_key, created_at, updated_at
RerankModelCreate: model_id, provider, display_name?, base_url, api_key?, timeout_seconds, enabled
RerankModelUpdate: все поля optional
```

### Vault
```python
VaultRead(ORMModel): vault_id, domain_id, display_name, enabled, embedding_model_id,
                     expected_dimensions, chunk_size, overlap, entity_aware_mode,
                     semantic_threshold, binding_status, chunk_count,
                     git_author_name, git_author_email,   # Campaign Update Mode git identity
                     created_at, updated_at
VaultCreate: vault_id, domain_id, display_name?, embedding_model_id?, expected_dimensions?,
             chunk_size?, overlap?, entity_aware_mode?, semantic_threshold,
             git_author_name?, git_author_email?
VaultUpdate: все поля optional (включая binding_status, chunk_count,
             git_author_name, git_author_email)
```

### Document
```python
DocumentRead(ORMModel): id, vault_id, source_path, title, md5, mtime, indexed_at,
                        status, char_count, chunk_count, estimated_tokens, tags, created_at
  # status: pending | indexed | error
  # char_count, estimated_tokens — None если документ (ещё) не индексирован
  # tags: list[TagRead] — M2M, заполняется вручную в роуте
```

### DocumentCandidate
```python
DocumentCandidate(BaseModel):  # НЕ ORMModel, чистый DTO
  document_id: str
  title: str          # заполняется из Document.title ?? Document.source_path
  source_path: str
  char_count: int | None
  chunk_count: int | None
  estimated_tokens: int | None
  already_sent: bool  # True если document_id уже в Chat.sent_full_document_ids
```

Используется в `full_document_service.py` и `pipeline_executor.py` для Full Document Mode паузы.

### Tag / Campaign
```python
TagRead(ORMModel): id, name, domain_id, campaign_id, color, created_at
TagCreate: name, domain_id, campaign_id?, color?
TagUpdate: name?, color?
TagsGrouped: global_tags, by_campaign: dict[campaign_id, list[TagRead]]

CampaignRead(ORMModel): id, domain_id, name, description, system_prompt, last_session_at, created_at, tags
CampaignCreate: domain_id, name, description?, system_prompt?
CampaignUpdate: name?, description?, system_prompt?
```

### Chat
```python
ChatRecord(ORMModel):
  id: str
  title: str
  vault_id: str | None      # deprecated back-compat
  domain_id: str | None
  campaign_id: str | None
  locked_pipeline_id: str | None
  full_document_mode_enabled: bool = False  # режим отправки полных документов
  sent_full_document_ids: list[str] = []   # история уже отправленных документов
  created_at: datetime
  updated_at: datetime

CreateChatRequest:
  domain_id: str | None     # основной ID
  vault_id: str | None      # deprecated back-compat
  campaign_id: str | None

CreateChatResponse: chat_id, title
SendMessageRequest: content, stream=True
```

### Pipeline
```python
PipelineStep:
  step_id: str               # user-defined slug, e.g. "analyze"
  type: "retrieval" | "validation"
  name: str
  system_prompt: str         # {query}, {STEP_ID.result}, {STEP_ID.key}
  after_step_ids: list[str]  # [] = стартовый шаг
  # только retrieval:
  top_k, tag_ids, role, output_format: "text"|"json"
  # только validation:
  validation_prompt, options: list[str]?

FinalComposition:
  system_prompt: str  # {STEP_ID.result}, {query}

PipelineRead(ORMModel): id, pipeline_id, domain_id, campaign_id, version, name, description,
                        steps, final_composition, is_active, created_at
PipelineCreate: pipeline_id, domain_id, campaign_id?, name, description?, steps, final_composition
PipelineUpdate: name?, description?, steps?, final_composition?, is_active?
```

### PipelineExecutionContext

```python
PipelineExecutionContext(BaseModel):
  chat_id: str
  message_id: str
  query: str                 # после QueryRewriter
  original_query: str | None # запрос до переформулировки
  domain_id, campaign_id
  vault_ids: list[str]       # все enabled-Vault домена
  vault_id: str | None       # deprecated back-compat
  pipeline_id, pipeline_version, steps, final_composition  # None до router.select()
  history: list[ChatMessage]
  metadata: dict
  retrieval_strategy: str | None
  confidence, reasoning, mode  # заполняются после pipeline_router.select()
  step_results: dict[str, Any]  # накапливается в DAG
    # step_id           → текст/dict для output retrieval-шагов
    # _hits_{step_id}   → list[SearchHit] для full_document_service
```

`context.resolve(template)` — подставляет `{query}`, `{STEP_ID.result}`, `{STEP_ID.key}` (делегирует в `prompt_pack.resolve_step_vars`).

## Indexer task API

```python
StartIndexTaskRequest: vault_id, force_reindex=False
StartIndexTaskResponse: task_id, vault_id, status
TaskStateResponse: task_id, vault_id, status, state: IndexState | None
IndexStatusResponse: vault_id, task_id, status, progress_pct, chunks_total, chunks_processed, error, files
```

## WebSocket сообщения прогресса (rag-indexer → frontend)

```python
WSFileChunkProgressMessage: type="file_chunk_progress", task_id, file_path,
                            stage, chunks_total, chunks_processed, error
WSFileStatusMessage:        type="file_status", task_id, file_path, status, chunk_count, error
WSTaskCancelledMessage:     type="task_cancelled", task_id
WSTaskCompleteMessage:      type="task_complete", task_id, files_total, files_indexed
```

## Planner-контракты

```python
PipelineInvocation: pipeline_id, domain, priority
PlannerDecision: retrieval_strategy, clarification_needed, pipeline_invocations, reasoning
```

## ClarificationState

```python
ClarificationState(BaseModel):  # НЕ ORMModel — DTO между FSM и chat-роутом
  stage: idle | collecting | complete | fallback
  missing_fields: list[str]
  collected: dict[str, str]
  turn: int
  next_question: str | None
```

## Ретривал-схемы (deprecated/internal)

```python
RetrievalContext:  query, vault_ids, vault_id (deprecated), domain_id, campaign_id,
                   tag_ids, top_k, metadata_filter
RetrievalResult:  chunk_id, document_id, vault_id, text, score, metadata
PipelineStepResult: step_id, step_name, retrieval_results, llm_output, error
PipelineResult: pipeline_id, pipeline_version, steps, final_answer, error
```

---

## Campaign Update Mode контракты

Обмен между rag-backend и rag-indexer через `indexer_client.py`.

### EditIntent — LLM output

LLM возвращает намерения правок, не готовые перезаписанные файлы.

```python
class EditAnchor(BaseModel):
    kind: Literal["markdown_heading", "text_fragment"]
    value: str

class EditIntent(BaseModel):                   # action = "update"
    change_id: str                             # uuid4
    action: Literal["update"]
    document_id: str                           # из переданного бэкендом контекста
    description: str
    anchor: EditAnchor | None
    operation: Literal["append_after_section", "append_to_file", "replace_unique_text"]
    content: str

class CreateIntent(BaseModel):                 # action = "create"
    change_id: str
    action: Literal["create"]
    parent_document_id: str | None
    suggested_filename: str
    description: str
    content: str

AnyIntent = EditIntent | CreateIntent
```

### ResolvedChange — indexer output (Redis)

Indexer возвращает resolved change; backend хранит в Redis, не raw intent.

```python
class ResolvedChange(BaseModel):
    change_id: str
    vault_id: str
    document_id: str | None
    file_path: str
    action: Literal["update", "create"]
    description: str
    original_content: str       # из оригинального файла, не из indexed text
    proposed_content: str       # из оригинального файла
    unified_diff: str
    expected_sha256: str | None # None для create
    status: Literal["pending", "accepted", "rejected", "resolution_failed"] = "pending"
    error_code: str | None = None
    error_message: str | None = None
```

### UpdateModeSession — Redis key `update_mode:{chat_id}`

```python
class UpdateModeSession(BaseModel):
    session_id: str             # uuid4
    chat_id: str
    campaign_id: str
    created_at: datetime
    expires_at: datetime        # created_at + 3h
    changes: list[ResolvedChange]
    warnings: list[str]         # например, док превысил per-doc limit
```

### Resolve — internal API запрос/ответ

```python
class ResolveUpdateModeRequest(BaseModel):
    session_id: str
    vault_id: str
    intents: list[AnyIntent]

class ResolveUpdateModeResponse(BaseModel):
    resolved_changes: list[ResolvedChange]
```

### Apply — public API запрос/ответ

```python
class ApplyUpdateModeRequest(BaseModel):
    apply_id: str               # UUID, idempotency key

class VaultApplyResult(BaseModel):
    vault_id: str
    status: Literal["applied", "skipped", "conflict", "error"]
    applied_count: int
    snapshot_commit_sha: str | None
    commit_sha: str | None
    commit_message: str | None
    reindex_task_id: str | None
    reindex_error: str | None
    error_code: str | None
    error_message: str | None

class ApplyUpdateModeResponse(BaseModel):
    apply_id: str
    results: list[VaultApplyResult]
```

### Internal apply — indexer request

```python
class InternalApplyRequest(BaseModel):
    apply_id: str
    vault_id: str
    accepted_changes: list[ResolvedChange]  # только status="accepted"
    commit_message: str | None              # LLM-generated, max 72 символа
```
