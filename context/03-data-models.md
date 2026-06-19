# 03 — Модели данных

## PostgreSQL (SQLAlchemy ORM)

### Иерархия сущностей

```
Domain
├── DomainPrompt (system/clarification/planner/pipeline_router)
├── DomainClarificationField
├── Vault ──▶ Document ──▶ DocumentLabel ──▶ Tag
├── Tag (name, domain_id, campaign_id, color)
├── Campaign ──▶ Chat ──▶ Message
│             └── Tags (campaign_tags m2m)
└── Pipeline (DAG: steps JSONB + final_composition JSONB)

PlatformSetting (key-value, группированные)
GenerationModel (зашифрованный api_key, is_active)
EmbeddingModel (provider, dimensions, зашифрованный api_key)
RerankModel (is_active, зашифрованный api_key)
AuditLog
PipelineDecision
ClarificationState (FSM для уточнений)
```

### Ключевые особенности схемы
- `Domain.domain_id` — строковый PK (не UUID), например `"dnd"`, `"work"`
- `Chat.domain_id` — NOT NULL + CASCADE (arch-инвариант)
- `Chat.pipeline_pause_state` — JSONB-снапшот DAG-контекста при паузе на validation
- `Chat.pending_pipeline_confirm` — JSONB ожидающего подтверждения пайплайна
- `Chat.locked_pipeline_id` — зафиксированный пайплайн для чата
- `Chat.vault_id` — **deprecated**, оставлен для back-compat
- `GenerationModel.encrypted_api_key` — зашифровано Fernet (`ENCRYPTION_KEY`)
- Все UUID в PostgreSQL хранятся через `UUID(as_uuid=True)`, конвертация в str — через `ORMModel._coerce_uuid_fields()`

### Миграции
Alembic, `rag-backend/migrations/`, 0001..0019.
Запускаются автоматически при старте `rag-backend`.

---

## Pydantic-контракты (`shared_contracts/models.py`)

Общие модели, используемые всеми сервисами:

### Vault / документы
```python
VaultRead, VaultCreate, VaultUpdate
DocumentRead, DocumentLabelWrite
FileIndexState  # статус файла: pending/parsing/chunking/indexing/done/error
IndexState      # статус задачи индексации
```

### Домены
```python
DomainRead, DomainCreate, DomainUpdate
DomainPromptRead, DomainPromptUpdate
DomainClarificationFieldRead, DomainClarificationFieldCreate
```

### Чаты
```python
ChatRecord, ChatMessage
CreateChatRequest  # domain_id (основной) + vault_id (deprecated back-compat)
SendMessageRequest
ClarificationResponse, ClarificationAnswer
```

### Пайплайны (DAG)
```python
PipelineStep        # step_id, type: retrieval|validation, after_step_ids
FinalComposition    # system_prompt с {STEP_ID.result}, {query}
PipelineRead, PipelineCreate, PipelineUpdate
PipelineExecutionContext  # полный контекст выполнения DAG
PipelineStepResult, PipelineResult
```

### Поиск / LanceDB
```python
RetrievalContext, RetrievalResult
SearchRequest, SearchResponse, SearchHit
UpsertRequest, UpsertChunk, UpsertResponse
```

### Индексатор
```python
StartIndexTaskRequest/Response
TaskStateResponse
IndexRequest, IndexResponse, IndexStatusResponse
```

### WebSocket-сообщения (прогресс индексации)
```python
WSFileChunkProgressMessage  # type: "file_chunk_progress"
WSFileStatusMessage         # type: "file_status"
WSTaskCompleteMessage       # type: "task_complete"
WSTaskCancelledMessage      # type: "task_cancelled"
```

### Настройки
```python
PlatformSettingRead, PlatformSettingUpdate
GenerationModelRead, GenerationModelCreate, GenerationModelUpdate
EmbeddingModelRead, EmbeddingModelCreate, EmbeddingModelUpdate
```

### Теги и кампании
```python
TagRead, TagCreate, TagUpdate
TagsGrouped  # global_tags + by_campaign для UI
CampaignRead, CampaignCreate, CampaignUpdate
```

### Важные детали
- `ORMModel` — базовый класс с `from_attributes=True` + авто-конвертация UUID → str
- Lazy-relationship поля в `ORMModel._coerce_uuid_fields()` **намеренно пропускаются** (List-поля)
- `PipelineExecutionContext.resolve(template)` — разворачивает `{STEP_ID.result}`, `{STEP_ID.key}`, `{query}`
- `VaultConfigEntry.binding_status`: `unbound|binding|bound|error`

---

## LanceDB (векторное хранилище)

- Данные: `./data/lancedb/`
- Управление через `db-api-server` REST API
- Таблица на vault_id
- Поля чанка: `chunk_id`, `document_id`, `text`, `vector[2560]`, `metadata JSONB`
