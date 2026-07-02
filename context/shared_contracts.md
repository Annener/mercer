# Shared Contracts — Общие Pydantic-схемы

Файл: `shared_contracts/models.py`  
Используется: rag-backend, rag-indexer (общие типы для межсервисного взаимодействия)

## Базовые классы

### ORMModel
Базовый класс для схем, читаемых из SQLAlchemy ORM-объектов.
- `from_attributes=True`
- `_coerce_uuid_fields`: автоматически конвертирует `uuid.UUID` в `str`
- **ВАЖНО**: намеренно пропускает list-поля (relationships), чтобы избежать
  `MissingGreenlet` в async-контексте. List-поля заполняются вручную в роутах.

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
  status: unbound|indexing|bound|error
  chunk_count: int
```

## Операции с LanceDB (db-api-server API)

```python
UpsertChunk:
  chunk_id: str
  document_id: str
  vault_id: str
  text: str
  vector: list[float]
  metadata: dict

SearchRequest:
  vault_id: str
  query_vector: list[float]
  top_k: int = 10
  filter: dict | None

SearchResponse:
  results: list[ChunkRecord]
  scores: list[float]
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
                     binding_status, chunk_count, created_at, updated_at
  # binding_status: unbound|indexing|bound|error
VaultCreate: vault_id, domain_id, display_name?, embedding_model_id?, ...
VaultUpdate: все поля optional
```

### Tag
```python
TagRead(ORMModel): id, name, domain_id, campaign_id?, color?, created_at
# TagCreate / TagUpdate определены в api/settings/schemas.py
```

### Document
```python
DocumentRead(ORMModel): id, vault_id, source_path, title, md5, mtime, status,
                        indexed_at, created_at
  # status: pending|parsing|chunking|indexing|done|error|cancelled|empty
```

### Campaign
```python
CampaignRead(ORMModel): id, domain_id, name, description, system_prompt,
                        last_session_at, created_at
CampaignCreate: domain_id, name, description?, system_prompt?
CampaignUpdate: name?, description?, system_prompt?
```

### Pipeline
```python
PipelineStep:
  step_id: str
  type: Literal["retrieval", "validation"]
  depends_on: list[str] = []
  params: dict = {}

FinalComposition:
  template: str
  sources: list[str] = []

PipelineRead(ORMModel): id, pipeline_id, domain_id, campaign_id?, version, name, description,
                        steps: list[PipelineStep], final_composition: FinalComposition,
                        is_active, created_at
PipelineCreate: pipeline_id, domain_id, campaign_id?, version, name, description?,
                steps, final_composition
PipelineUpdate: name?, description?, steps?, final_composition?, is_active?
```

### Chat
```python
ChatRecord(ORMModel): id, title, domain_id, campaign_id?, vault_id?,
                      locked_pipeline_id?, pipeline_versions?,
                      pipeline_pause_state?, pending_pipeline_confirm?,
                      created_at, updated_at
CreateChatRequest: domain_id, campaign_id?
CreateChatResponse: chat_id: str
SendMessageRequest: text: str
```

### Message
```python
ChatMessage(ORMModel): id, chat_id, role, content, pipeline_id?, created_at
  # role: user | assistant | system
```

### ClarificationState
```python
ClarificationState(ORMModel): chat_id, stage, missing_fields, collected, turn, next_question
  # stage: idle | collecting | ready
ClarificationResponse:
  needs_clarification: bool
  question: str | None
ClarificationAnswer: answer: str
```

### PipelineDecision
```python
PipelineDecision(ORMModel): id, chat_id, message_id, selected_pipeline_id,
                            confidence, reasoning, mode, created_at
```

### AuditLog
```python
AuditLogRead(ORMModel): id, action, entity_type, entity_id, details, created_at
```

## Важные замечания

1. `has_api_key` в Read-схемах моделей — это `bool`, не сам ключ. Ключи хранятся
   зашифрованными в `encrypted_api_key` и никогда не возвращаются в API.

2. `domain_id` в Domain — это строка-идентификатор (`"dnd"`, `"work"`), не UUID.
   Все FK на домены — тоже строки.

3. `vault_id` в Vault — строка-идентификатор (`"dnd-vault"`), не UUID.
   UUID хранится во внутреннем поле `id`, но во внешнем API используется `vault_id`.

4. `VaultBinding.status` — используется значение `indexing` (не `binding`).

5. `js/api/sidecar.js` — фронтенд-клиент для управления pdf-sidecar через host-agent
   (запуск, остановка, установка, статус). Соответствует `api/settings/sidecar.py` в бэкенде.
