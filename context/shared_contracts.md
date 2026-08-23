# Shared Contracts — общие Pydantic-схемы

Файл: `shared_contracts/models.py`  
Используется: rag-backend, rag-indexer, db-api-server (общие типы для межсервисного взаимодействия и DAL).

---

## Базовые классы

### ORMModel
Базовый класс для схем, читаемых из SQLAlchemy ORM-объектов.
- `from_attributes=True`
- `_coerce_uuid_fields` (model_validator `mode='before'`): автоматически конвертирует `uuid.UUID` в `str` для str-полей.
- **ВАЖНО**: намеренно пропускает list-поля (relationships), чтобы избежать `MissingGreenlet` в async-контексте. List-поля (`tags`, `chats` и т.п.) заполняются вручную в роутах/хелперах.

---

## Состояние индексатора (Redis, shared между indexer и backend)

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
  files: dict[str, FileIndexState]   # key = source_path
  error: str | None
```

---

## Записи хранилища (LanceDB через db-api-server)

```python
DocumentRecord:
  document_id, vault_id, source_path, checksum, metadata, chunk_count

ChunkRecord:
  chunk_id, document_id, vault_id, text, vector, metadata, summary

EntityRecord:
  entity_id, kind, name, metadata, source_chunk_ids

VaultBinding:
  vault_id, embedding_model_id, expected_dimensions (>0),
  locked, status (unbound|binding|bound|error), chunk_count
```

---

## Операции с LanceDB (db-api-server API)

```python
UpsertChunk:       document_id, chunk_index, text, vector, metadata
UpsertRequest:     vault_id, chunks
UpsertResponse:    status ("ok"|"partial"), upserted_count, failed_indices, error_details

SearchHit:         chunk_id, document_id, text, metadata, score
SearchRequest:     vault_id, vector, top_k (1..200), score_threshold?, filter?
SearchResponse:    results: list[SearchHit]
```

## Source / SourceGroup / MessageSource (UI-источники чата)

Контракты для отображения и персистенции источников под сообщением ассистента.
Единая точка истины для всех сценариев (legacy single-shot, tool-based AgentLoop,
pipeline DAG, full document mode, resume flows).

```python
Source:           path, page?, vault_id?, document_id?, chunk_id?, score?, source_kind="chunk"|"full_document"
SourceGroup:      step_id, step_name, sources: list[Source]            # для grouped_by_step=true SSE event
MessageSource:    path, page?, vault_id?, document_id?, chunk_id?, source_kind   # lightweight DTO для Message.sources
```

- `source_kind="chunk"` — обычный retrieval chunk (SearchHit → Source).
- `source_kind="full_document"` — `send_full_document` шаг pipeline или
  документ, выбранный пользователем в full_document_selection.
  Всегда одна запись на `document_id` (без page).
- `page` присутствует только когда в `metadata` индексатора был `page_number`
  (сейчас — PDF). Для других типов файлов — `None`.

Helper-функции (`rag-backend/app/services/source_utils.py`):
- `hits_to_sources(hits, cap=None) → list[Source]` — дедуп по `(path, page, vault_id, chunk_id)`.
- `full_doc_hits_to_sources(hits) → list[Source]` — дедуп по `(path, vault_id, document_id)`,
  одна запись на документ.
- `dedup_sources(list[Source]) → list[Source]` — для multi-round agent loop.
- `sources_to_message_sources(list[Source]) → list[MessageSource]` — для персистенции.
- `merge_sources(*lists) → list[Source]` — объединение с дедупом.

Лимит `MAX_SOURCES_PER_TOOL_RESULT = 50` защищает SSE payload от раздувания при
больших выдачах `search_knowledge` (truncation по `evidence_token_budget` обычно
ограничивает строже).

---

## Read / Create / Update схемы (API-контракты)

### Домены и промпты

```python
DomainRead(ORMModel):    domain_id, display_name, description, is_system, enabled, created_at, updated_at
DomainCreate:            domain_id, display_name, description?, enabled
DomainUpdate:            display_name?, description?, enabled?

DomainPromptRead(ORMModel):  id, domain_id, prompt_type, content, updated_at
  # prompt_type: system | clarification | planner | pipeline_router
DomainPromptUpdate:         content

DomainClarificationFieldRead(ORMModel): id, domain_id, field_name, label, hint, required, display_order
DomainClarificationFieldCreate:         field_name, label, hint?, required, display_order
```

### Платформенные настройки

```python
PlatformSettingRead(ORMModel):  key, value, value_type (int|float|bool|str),
                                group_name, label, hint, updated_at
PlatformSettingUpdate:          value  # только value изменяется
```

### Модели генерации / эмбеддингов / реранкинга

```python
GenerationModelRead(ORMModel):  model_id, provider, display_name, base_url, timeout_seconds,
                                is_active, enabled, has_api_key, created_at, updated_at
GenerationModelCreate:          model_id, provider, display_name?, base_url, api_key?,
                                timeout_seconds, enabled
GenerationModelUpdate:          provider?, display_name?, base_url?, api_key?,
                                timeout_seconds?, enabled?

EmbeddingModelRead(ORMModel):   model_id, provider (ollama|openai_compatible), display_name,
                                model_name, base_url, dimensions, timeout_seconds, max_retries,
                                enabled, has_api_key, ...
EmbeddingModelCreate:           model_id, provider, display_name?, model_name, base_url, api_key?,
                                dimensions (>0), timeout_seconds, max_retries, enabled
EmbeddingModelUpdate:           все поля optional

RerankModelRead(ORMModel):      model_id, provider, display_name, base_url, timeout_seconds,
                                is_active, enabled, has_api_key, ...
RerankModelCreate:              model_id, provider, display_name?, base_url, api_key?,
                                timeout_seconds, enabled
RerankModelUpdate:              все поля optional
```

### Vault

```python
VaultRead(ORMModel):    vault_id, domain_id, display_name, enabled, embedding_model_id,
                        expected_dimensions, chunk_size, overlap, entity_aware_mode,
                        semantic_threshold, binding_status (unbound|indexing|bound|error),
                        chunk_count,
                        git_author_name, git_author_email,    # 0005_campaign_update_git_identity
                        created_at, updated_at
VaultCreate:            vault_id, domain_id, display_name?, embedding_model_id?,
                        expected_dimensions?, chunk_size?, overlap?, entity_aware_mode?,
                        semantic_threshold, git_author_name?, git_author_email?
VaultUpdate:            все поля optional (включая binding_status, chunk_count,
                        git_author_name, git_author_email)
```

### Документы

```python
DocumentRead(ORMModel): id, vault_id, source_path, title, md5, mtime, indexed_at,
                        status (pending|indexed|error),
                        char_count, chunk_count, estimated_tokens,
                        tags: list[TagRead], created_at
  # char_count, estimated_tokens — None, если документ (ещё) не индексирован
  # tags — M2M, заполняется вручную в роуте

DocumentCandidate (BaseModel, НЕ ORMModel):    # чистый DTO для Full Document Mode
  document_id, title, source_path, char_count, chunk_count, estimated_tokens, already_sent

DocumentLabelWrite:                            # полная замена тегов документа
  tag_ids: list[str]
```

### Теги и кампании

```python
TagRead(ORMModel):     id, name, domain_id, campaign_id, color, created_at
TagCreate:             name, domain_id, campaign_id?, color?
TagUpdate:             name?, color?
TagsGrouped:           global_tags: list[TagRead], by_campaign: dict[campaign_id, list[TagRead]]

CampaignRead(ORMModel):   id, domain_id, name, description, system_prompt, last_session_at,
                          created_at, tags: list[TagRead]
CampaignCreate:           domain_id, name, description?, system_prompt?
CampaignUpdate:           name?, description?, system_prompt?
```

### Чат

```python
ChatRecord(ORMModel):
  id, title,
  vault_id (deprecated back-compat), domain_id, campaign_id, locked_pipeline_id,
  full_document_mode_enabled, sent_full_document_ids,
  metadata (dict, JSONB — validation_alias="metadata_json"),     # 0011: inline scene-state
  context_update_mode (bool, default False),                     # 0011: master switch для propose_context_update tool
  created_at, updated_at

# 0011: Chat.metadata — JSONB колонка в БД названа `metadata`, в ORM атрибут — `metadata_json`
# (алиас через Pydantic validation_alias), чтобы избежать конфликта с `Base.metadata`.
# В коде используется `chat.metadata_json` напрямую или через property.
# Структура: {"scene_state": {<произвольный dict>}}

# 0011: Chat.context_update_mode — флаг, при True agent loop регистрирует
# PROPOSE_CONTEXT_UPDATE_TOOL. Управляется через UpdateChatRequest (PATCH /api/chats/{id}).

CreateChatRequest:    domain_id?, vault_id? (deprecated), campaign_id?
CreateChatResponse:   chat_id, title
UpdateChatRequest:    campaign_id?, full_document_mode_enabled?, context_update_mode?  # 0011
SendMessageRequest:   content, stream=True
ClarificationResponse:  message_id, role="assistant", content, clarification_id?, stage?
ClarificationAnswer:    clarification_id, answers: dict[str, str]
```

---

## Pipeline contracts — DAG-based execution model

```python
PipelineStep:
  step_id, type ("retrieval"|"validation"), name, system_prompt, after_step_ids
  # только для retrieval:
  top_k?, tag_ids, role?, output_format ("text"|"json"), send_full_document
  # только для validation:
  validation_prompt?, options?
  # Поддерживает {STEP_ID.result}, {STEP_ID.key}, {query}
  # Cross-field валидаторы запрещают несоответствующие комбинации полей

FinalComposition:
  system_prompt   # {STEP_ID.result}, {query}; {context} и {collected_fields} УДАЛЕНЫ

PipelineRead(ORMModel):    id, pipeline_id, domain_id, campaign_id?, version, name,
                           description?, steps, final_composition, is_active, created_at
PipelineCreate:            pipeline_id, domain_id, campaign_id?, name, description?,
                           steps, final_composition
  # _validate_unique_step_ids — нет повторяющихся step_id
PipelineUpdate:            name?, description?, steps?, final_composition?, is_active?

PipelineExecutionContext (BaseModel, runtime DTO):
  chat_id, message_id, query, original_query?, campaign_id?, domain_id?,
  vault_ids, vault_id? (deprecated),
  pipeline_id?, pipeline_version?, steps?, final_composition?,
  history: list[ChatMessage], metadata,
  retrieval_strategy?, confidence?, reasoning?, mode?,
  step_results: dict[str, Any]    # накапливается в DAG
    # output_format="text" → step_results[step_id] = "строка"
    # output_format="json" → step_results[step_id] = dict (при ошибке парсинга — строка)
    # type="validation"    → step_results[step_id] = ответ пользователя (строка)
    # ключи "_hits_{step_id}" — сырые SearchHit для full_document_service

  PipelineExecutionContext.resolve(template: str) -> str
    # Подставляет {query}, {STEP_ID.result}, {STEP_ID.key}
    # Делегирует в prompt_pack.resolve_step_vars

PipelineStepResult:   step_id, step_name, retrieval_results, llm_output?, error?
PipelineResult:       pipeline_id, pipeline_version, steps, final_answer, error?
```

---

## Planner contracts

```python
PipelineInvocation:    pipeline_id, domain?, priority=0
PlannerDecision:       retrieval_strategy, clarification_needed=False,
                       pipeline_invocations=[], reasoning=""
```

---

## ClarificationState

```python
ClarificationState (BaseModel, НЕ ORMModel — DTO между FSM и chat-роутом):
  stage: idle|collecting|complete|fallback
  missing_fields: list[str]
  collected: dict[str, str]
  turn: int = 0
  next_question: str | None
```

---

## Campaign Update Mode — Phase 2

```python
UpdateModeAction(str, Enum):       UPDATE = "update" | CREATE = "create"
UpdateModeOperation(str, Enum):    APPEND_AFTER_SECTION, APPEND_TO_FILE,
                                   REPLACE_UNIQUE_TEXT, CREATE_FILE,
                                   DELETE_SECTION, DELETE_UNIQUE_TEXT
UpdateModeChangeStatus(str, Enum): PENDING | ACCEPTED | REJECTED | RESOLUTION_FAILED
UpdateModeVaultApplyStatus(str, Enum): APPLIED | CONFLICT | FAILED | NO_CHANGES
```

### LLM intent contracts

```python
UpdateModeAnchor:
  kind: "markdown_heading" | "exact_text"
  value: str

UpdateModeIntent:
  change_id, action, description, document_id?, parent_document_id?,
  operation, anchor?, suggested_filename?, content
  # model_validator:
  #   DELETE_* операции → content == ""
  #   UPDATE action требует document_id; anchor по operation;
  #   CREATE action требует suggested_filename и CREATE_FILE

UpdateModeIntentBatch:    # 1..10 intents, уникальные change_id
  intents
```

### Executor-level DTOs

```python
IndexedContextDocument (in-memory, не персистируется):
  document_id, vault_id, source_path, title, text, estimated_tokens

UpdateModeGenerationResult:
  intents=[],            # пустой список допустим — обязателен no_change_reason
  no_change_reason?,     # required if intents пуст
  state_patch: list[CampaignStatePatchOperation] = [],   # Stage 5
  state_patch_questions: list[str] = []                  # Stage 5
```

### Internal indexer API

```python
UpdateModeResolveRequest:
  chat_id, campaign_id, domain_id, vault_ids (1+), intents (1..10),
  default_vault_id (∈ vault_ids), candidate_document_ids (0..15)

ResolvedUpdateModeChange:
  change_id, vault_id?, document_id?, file_path?, action, description,
  operation?, anchor?, op_content, resolve_order=-1,
  original_content, proposed_content, unified_diff, expected_sha256?,
  status=PENDING, error_code?, error_message?
  # resolve_order=-1 sentinel — legacy single-op session

UpdateModeResolveResponse:
  changes: list[ResolvedUpdateModeChange]
```

### Apply contracts (multi-op batch)

```python
UpdateModeApplyChange:           # deprecated single-change; legacy back-compat path
  change_id, vault_id, file_path, action, proposed_content, expected_sha256?,
  operation?, anchor?, op_content, description

UpdateModeFileOp:                # одна операция внутри batch
  change_id, operation, anchor_value?, content, expected_sha256?, description

UpdateModeFileChangeBatch:       # все операции на (vault_id, file_path)
  vault_id, file_path, action, ops (1..20)
  # CAS SHA-256: UPDATE batch → ops[0].expected_sha256 required, ops[1..] None
  #               CREATE batch → all ops[].expected_sha256 == None

UpdateModeApplyRequest:
  apply_id, chat_id, campaign_id,
  file_batches=[],               # primary
  accepted_changes=[]            # legacy back-compat, конвертируется в file_batches
  # model_validator нормализует accepted_changes → file_batches и валидирует
  # уникальность (vault_id, file_path)

UpdateModeVaultApplyResult:
  vault_id, status, applied_count,
  snapshot_commit_sha?, commit_sha?, commit_message?,
  reindex_task_id?, reindex_error?,
  error_code?, error_message?, manual_recovery_required=False

UpdateModeApplyResponse:
  apply_id, results=[UpdateModeVaultApplyResult]

IndexerApplyState:   # Redis: update_mode:apply:{apply_id} (TTL 3h)
  apply_id, request_fingerprint (SHA-256), status ("in_progress"|"completed"),
  response?, created_at
```

### Public backend API contracts

```python
StartUpdateModeRequest:    note (1..20000 chars)
StartUpdateModeResponse:   chat_id, expires_at, changes, warnings,
                           state_field_snapshot=[], state_patch_operations=[]

UpdateModeSessionResponse: chat_id, campaign_id, domain_id, vault_ids, expires_at,
                           changes, warnings,
                           state_field_snapshot=[], state_patch_operations=[]

UpdateModeReviewRequest:
  accepted_change_ids=[], rejected_change_ids=[],
  state_patch_decisions?: UpdateModeStatePatchDecisions
  field_change_decisions?: UpdateModeStateFieldChangeDecisions      # 0011 (Sprint 3)
  # model_validator: нет пересечений accepted/rejected;
  #                  не пустой (хотя бы одно поле — file, state или field)

ApplyUpdateModeRequest:    apply_id?
ApplyUpdateModeResponse:   apply_id, results,
                           state_patch_result?: UpdateModeStatePatchApplyResult,
                           field_changes_result?: UpdateModeStateFieldChangeApplyResult  # 0011 (Sprint 3)

CancelUpdateModeResponse:  status="cancelled"

UpdateModeSession (Redis contract):     # ключ update_mode:{chat_id}, TTL 3h
  session_id, chat_id, campaign_id, domain_id, vault_ids, default_vault_id,
  candidate_document_ids, note, warnings, changes,
  created_at, expires_at,
  apply_id?, apply_started_at?, apply_state ("review"|"in_progress"|"completed"),
  state_field_snapshot=[], state_patch_operations=[],
  state_field_change_operations=[UpdateModeStateFieldChangeEntry],    # 0011 (Sprint 3)
  apply_result?
```

---

## Campaign State — Stage 1: Field Configuration contracts

```python
CampaignStateFieldMode = Literal["single", "list"]

CampaignStateFieldConfigRead(ORMModel):
  id, campaign_id, key, label, description="", mode, enabled=True, display_order=0,
  created_at?, updated_at?

CampaignStateFieldConfigCreate:
  key (1..64), label (1..256), description="" (≤8K),
  mode, enabled=True, display_order=0 (≥0)
  # key — immutable после создания; mode — только при создании

CampaignStateFieldConfigUpdate:
  label?, description?, enabled?, display_order?
  # key и mode запрещены (immutable) — сервис вернёт 409 при попытке

CampaignStateFieldConfigReorderRequest:
  field_ids (≥1, уникальные в пределах кампании, len == current count)
```

---

## Campaign State — Stage 2: Versioned State contracts

```python
CampaignStateSourceKind = Literal["initial", "patch"]

CampaignStateSingleValueRead(ORMModel):
  field_key, text, source_refs=[], updated_at?
  # source_refs формат: "file:<document_id>:sha:<sha256>" | "chat:<message_id>" | "vault:<vault_id>"

CampaignStateListItemRead(ORMModel):
  field_key, item_key, text, resolved=False, source_refs=[], updated_at?

CampaignStateFieldValuesRead(ORMModel):
  field_key, field_id, mode, enabled, display_order,
  single_value?, items=[]

CampaignStateVersionSummary(ORMModel):
  id, campaign_id, state_version, config_version,
  source_kind, base_state_version?, created_at?, created_by?

CampaignStateVersionRead(ORMModel):
  summary, fields=[]

CampaignStatePatchOperationType = Literal[
  "replace_single", "clear_single",
  "add_list_item", "update_list_item", "resolve_list_item", "remove_list_item",
]

_CampaignStatePatchBase:        # reason (1..1024), source_refs=[]
CampaignStateReplaceSingle:     type="replace_single", field_key, text (1..8192)
CampaignStateClearSingle:       type="clear_single",   field_key
CampaignStateAddListItem:       type="add_list_item",  field_key, text
CampaignStateUpdateListItem:    type="update_list_item",  field_key, item_key, text
CampaignStateResolveListItem:   type="resolve_list_item", field_key, item_key
CampaignStateRemoveListItem:    type="remove_list_item",  field_key, item_key

CampaignStatePatchOperation =
  CampaignStateReplaceSingle | CampaignStateClearSingle
  | CampaignStateAddListItem | CampaignStateUpdateListItem
  | CampaignStateResolveListItem | CampaignStateRemoveListItem

CampaignStatePatchRequest:
  base_state_version? (≥1), config_version (≥1), operations (≥1)

CampaignStatePatchRejection:
  op_index, op_type,
  code (field_not_found|mode_mismatch|item_not_found|invalid_source_ref|invalid_payload),
  detail=""

CampaignStatePatchResponse:
  applied_state_version, config_version,
  applied_operations=[], failed_operations=[]
  # Stage 2: fail-fast — failed_operations содержит ровно одну запись
```

---

## Campaign State — Stage 3: Initial State contracts

```python
CampaignStateSourceType = Literal["file"]
CampaignStateInitialFieldStatusValue = Literal["proposed", "empty", "needs_clarification"]

DocumentSnapshot:
  document_id, vault_id, source_path, title?,
  content_sha (32 hex = md5), estimated_tokens (≥0)
  # используется для проверки неизменности источника между preview и apply

CampaignStateInitialSingleValue:    text (1..8192), source_refs=[]
CampaignStateInitialListItem:       text (1..8192), source_refs=[]
                                     # item_key НЕ задаётся LLM — генерируется сервером
CampaignStateInitialListValue:      items=[]
CampaignStateInitialFieldStatus:    status, clarification_question?
                                     # при "needs_clarification" → question обязателен

CampaignStateInitialProposalField:
  field_key, mode, status,
  single_value?, list_value?
  # при status="proposed" ожидается заполненный single_value или list_value

CampaignStateInitialProposal:       fields=[], questions=[]

CampaignStateInitialProposalRead:   # хранится в Redis, TTL 3h
  proposal_id, campaign_id, config_version,
  source_snapshot=[DocumentSnapshot],
  proposal: CampaignStateInitialProposal,
  warnings=[], created_at, expires_at

CampaignStateInitialPreviewRequest:   document_ids (1..50)
CampaignStateInitialApplyRequest:
  proposal_id (1..64), config_version (≥1),
  proposal_overrides: CampaignStateInitialProposal | None = None
  # Опциональный proposal с правками пользователя. Мерджится поверх
  # proposal из Redis по field_key. source_snapshot не затрагивается.
```

---

## Campaign State — Stage 5: state_patch in proposal

```python
CampaignStateFieldSnapshot:    # снимок метаданных enabled-поля в Redis-сессии Update Mode
  field_id, key, label, description, mode, display_order

UpdateModeStatePatchEntry:     # одна операция в proposal Update Mode
  op_index (≥0), field_key, field_label, mode, operation,
  previous_text?, proposed_text?, edited_text?,
  status ("pending"|"accepted"|"rejected")

UpdateModeStatePatchEdit:      # inline-правка текста на review-этапе
  op_index, text
  # допустимо только для replace_single / update_list_item / add_list_item

UpdateModeStatePatchDecisions:
  accepted_op_indexes=[], rejected_op_indexes=[], edited=[]
  # model_validator: нет пересечений accepted/rejected;
  #                  edited не должен быть rejected

UpdateModeStatePatchApplyResult:
  applied_state_version, config_version,
  applied_op_indexes=[], failed_op_indexes=[],
  failed_reasons: dict[str, str]
```

---

## Campaign State — Stage 6: Prompt Assembly contracts

```python
CampaignStateCompiledFieldRead:
  field_key, field_id, label, mode,
  included, truncated, rendered_text, estimated_tokens,
  items_included=0, items_total=0

CampaignStateCompiledBlock:    # детерминированно скомпилированный текст
  state_version?, config_version?,
  budget_tokens, used_tokens,
  truncated_fields=[], empty_fields=[], fields=[],
  text=""

EffectiveContextBlock:        # один блок effective-context (для debug)
  name, text, estimated_tokens
  # name: "system_prompt" | "campaign_state" | "rag_context" | "history" | "user_message"

EffectiveContextRead:
  campaign_id?, chat_id?, domain_id?,
  blocks=[], total_tokens=0, budget=0,
  truncated_fields=[], state_version?
```

---

## Campaign State — Stage 7: Stale Status contracts

```python
CampaignStateStaleStatus:      # вычисляется на лету, не персистится
  potentially_stale: bool,
  stale_documents: list[str],   # document_id в порядке обнаружения
  active_state_version: int | None,
  checked_at: datetime
```

---

## LLM tool-call contracts (Stage 8: conditional / cyclic RAG + Sprint 1/3)

```python
LLMToolCallFunction:   name, arguments    # raw JSON от модели
LLMToolCall:           id, type="function", function, index
LLMToolDefinitionFunction:  name, description, parameters (JSON Schema)
LLMToolDefinition:     type="function", function
LLMToolChoice:         mode="auto"|"none"|"required", function_name?
                       .to_openai() -> str | dict

LLMAssistantMessage:   role="assistant", content="", tool_calls=[]
LLMToolMessage:        role="tool", tool_call_id, content

RetrievalPolicy(str, Enum):     ASSISTIVE = "assistive" | GROUNDED = "grounded"

AgentRoundResult:      # snapshot одного раунда для streaming и audit
  round, queries, tool_name?, reason?,
  hits_count, evidence_tokens,
  scope ("campaign"|"domain"|"empty"|"no_vault"),
  skipped_reason?

SearchKnowledgeRequest:  queries (≥1), reason=""
SearchKnowledgeResult:   queries_used, hits, scope, evidence_tokens, note?

AgentLoopResult:         # финал agent loop
  content, rounds=[AgentRoundResult],
  tool_calls_made=0, policy=ASSISTIVE
```

### Tool definitions (Sprint 1 + Sprint 3)

`AgentLoop` регистрирует 2-3 tool definitions. Все три — `LLMToolDefinition(type="function", function=LLMToolDefinitionFunction(...))`.

| Tool | Когда активен | Параметры |
|---|---|---|
| `search_knowledge` (Stage 8.4) | всегда | `queries: list[str] ≥1`, `reason: str` |
| `update_scene_state` (Sprint 1) | всегда | `patch: dict`, `reason: str` |
| `propose_context_update` (Sprint 3) | только если `chat.context_update_mode=True` | `field_changes: list[ContextFieldChange]?`, `state_patch: list[CampaignStatePatchOperation]?`, `file_changes: list[UpdateModeIntent]?`, `confidence: float ∈ [0,1]` (обязателен), `reason: str` (обязателен), `source_message_ids: list[str]?`, `review_summary: str?` |

### Sprint 3 — Model-proposed context updates (новые DTO)

```python
ContextFieldChangeOperation(str, Enum):    CREATE_FIELD | UPDATE_FIELD
# delete_field намеренно отсутствует в Sprint 3 (пользователь удаляет руками через UI).

ContextFieldChange:        # одна schema-операция в proposal
  operation: ContextFieldChangeOperation,
  key: str                            # regex ^[a-z][a-z0-9_]*$, ≤64 chars
  label: str                          # 1..256 chars
  description: str = ""               # ≤8KB
  mode: CampaignStateFieldMode
  enabled: bool = True
  display_order: int = 1000           # по умолчанию новые поля в конце

ContextUpdateProposal:      # трёхсекционный proposal (model-driven)
  field_changes: list[ContextFieldChange] = []
  state_patch: list[CampaignStatePatchOperation] = []
  file_changes: list[UpdateModeIntent] = []
  confidence: float ∈ [0,1]
  reason: str
  source_message_ids: list[str] = []
  review_summary: str = ""
  # Cross-section: state_patch может ссылаться на field_key,
  # который создаётся в field_changes этого же proposal.
  # На стороне executor это валидируется через
  # _filter_state_patch_by_pending_field_changes.

# Минимальный confidence для принятия proposal: 0.5 (константа
# PROPOSAL_MIN_CONFIDENCE в agent_loop.py). Ниже — proposal отбрасывается
# host-side без UI review.
```

### Sprint 3 — Update Mode schema-change DTO

```python
UpdateModeStateFieldChangeEntry:     # per-op entry в session.state_field_change_operations
  op_index: int ≥0
  operation: ContextFieldChangeOperation
  key: str
  proposed_label, proposed_description, proposed_mode, proposed_enabled,
  proposed_display_order: ... | None
  previous_label, previous_description, previous_enabled,
  previous_display_order: ... | None
  edited_label, edited_description, edited_display_order: ... | None
  status: "pending" | "accepted" | "rejected"

UpdateModeStateFieldChangeDecisions:    # /review request body
  accepted_op_indexes: list[int] = []
  rejected_op_indexes: list[int] = []
  # Inline-edit НЕ поддерживается для schema в Sprint 3 (label/description
  # change можно отредактировать через UI перед apply).

UpdateModeStateFieldChangeApplyResult:    # /apply response (Stage A)
  applied_op_indexes: list[int] = []
  failed_op_indexes: list[int] = []
  failed_reasons: dict[str, str] = {}
  new_config_version: int = 0
  # had_failures: True если любая операция упала — apply отменяет
  # (audit log: update_mode.apply_aborted_schema, HTTP 422).
```

---

## Indexer task API contracts (rag-indexer/app/main.py)

```python
StartIndexTaskRequest:    vault_id, force_reindex=False, source_paths?  # targeted reindex
StartIndexTaskResponse:   task_id, vault_id, status
TaskStateResponse:        task_id, vault_id, status, state: IndexState?
IndexStatusResponse:      vault_id, task_id?, status, progress_pct, chunks_total,
                          chunks_processed, error?, files: dict[str, FileIndexState]
```

---

## WebSocket сообщения прогресса (rag-indexer → frontend)

```python
WSFileChunkProgressMessage:  type="file_chunk_progress", task_id, file_path,
                             stage, chunks_total, chunks_processed, error?
WSFileStatusMessage:         type="file_status", task_id, file_path, status,
                             chunk_count=0, error?
WSTaskCancelledMessage:      type="task_cancelled", task_id
WSTaskCompleteMessage:       type="task_complete", task_id, files_total, files_indexed
```

---

## Audit log contracts

```python
AuditLogRead(ORMModel):   id, action, entity_type?, entity_id?,
                         actor?, payload (JSONB)?, created_at
# actor + payload добавлены в миграции 0006_audit_log_actor_payload

# Известные `action` значения:
# - "chat.agent_loop"           — каждый tool-loop turn (Sprint 8.4)
# - "update_mode.apply"         — успешный apply (с file/state_patch результатами)
# - "update_mode.apply_schema"  — Sprint 3: schema-операции (Stage A) применены
# - "update_mode.apply_aborted_schema"  # Sprint 3: schema fail → apply отменён
# - "update_mode.reject_state_patch"    — отдельно логируются отклонённые state ops
# - "campaign_state_field_cascade_purged" — Stage 1: каскадная очистка при удалении поля
# - "campaign_state_patch_applied"       — Stage 2: применение state_patch
```

---

## Прочие (Vault config, Embedding, Index)

```python
VaultConfigEntry:        # read/cache контракт для одного vault в индексаторе
  vault_id, domain_id, enabled, embedding_model_id?,
  expected_dimensions?, chunk_size?, overlap?, entity_aware_mode?,
  semantic_threshold, binding_status, chunk_count,
  git_author_name?, git_author_email?

VaultConfig:             # map vault_id → VaultConfigEntry

EmbeddingRequest:        vault_id, texts, model_id?
EmbeddingResponse:       vault_id, embeddings, model_id

IndexRequest:            vault_id, force=False
IndexResponse:           vault_id, task_id, status
```