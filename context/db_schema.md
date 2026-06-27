# База данных — схема PostgreSQL

Файл ORM-моделей: `rag-backend/app/db/models.py`  
Миграции: **Alembic** — `rag-backend/migrations/versions/0001_initial.py`  
Запуск: `run_migrations()` в `rag-backend/app/db/migrations.py` — вызывает `alembic upgrade head` через `asyncio.to_thread` при старте сервиса.  
Текущая миграция: `0001_initial` — чистая стартовая, полная схема (содержит seed-данные).

## Ключевые сущности и связи

```
Domain (1) ──► (N) DomainPrompt
Domain (1) ──► (N) DomainClarificationField
Domain (1) ──► (N) Vault              [SET NULL при удалении домена]
Domain (1) ──► (N) Campaign
Domain (1) ──► (N) Tag
Domain (1) ──► (N) Chat               [CASCADE]
Domain (1) ──► (N) Pipeline

Campaign (1) ──► (N) Chat
Campaign (M) ──► (M) Tag  [campaign_tags]

Tag ──► campaign_id (nullable, direct FK в таблице)
Tag (M) ──► (M) Campaign  [campaign_tags]

Vault (vault_id: String) ──► (N) Document  [vault_id FK = String, не UUID]
Document (M) ──► (M) Tag  [document_labels]

Chat (1) ──► (N) Message
Chat (1) ──► (1) ClarificationState
Chat (1) ──► (N) PipelineDecision
```

## Таблицы

### Domain
- PK: `domain_id` (String(64), не UUID) — например `"dnd"`, `"work"`
- `display_name`, `description`, `is_system`, `enabled`
- Системные домены (`is_system=True`) нельзя удалять

### DomainPrompt
- Промпты домена по типу: `system`, `clarification`, `planner`, `pipeline_router`
- **UNIQUE** `(domain_id, prompt_type)`
- `content` (Text, сервер дефолт: пустая строка)

### DomainClarificationField
- Поля уточняющих вопросов для конкретного домена
- `field_name`, `label`, `hint`, `required`, `display_order`
- **UNIQUE** `(domain_id, field_name)`
- Используются в ClarificationFSM

### PlatformSetting
- PK: `key` (String(128)) — например `"retrieval.top_k"`, `"pdf_sidecar.url"`
- `value` (Text, **всегда строка**), `value_type` (int/float/bool/str)
- `group_name`, `label`, `hint`
- Десериализация: `SettingsService.deserialize_value()`
- Загружаются в память при старте: `settings_service.load_settings()`

### GenerationModel
- PK: `id` (UUID). `model_id` (String, UNIQUE) — идентификатор модели
- `provider` = `"openai_compatible"`
- `base_url`, `encrypted_api_key` (шифрование через `ENCRYPTION_KEY`)
- `is_active` (bool) — только одна активная (частичный UNIQUE-индекс `WHERE is_active = true`)
- `enabled` — модель доступна для выбора

### EmbeddingModel
- `model_id` (UNIQUE), `provider` (ollama | openai_compatible)
- `model_name`, `base_url`, `dimensions`
- `max_retries`, `timeout_seconds`
- Нет `is_active` — связь с vault через `Vault.embedding_model_id`

### RerankModel
- Аналогична GenerationModel, но для реранкинга
- `is_active` — одна активная (UNIQUE-индекс `WHERE is_active = true`)

### Vault
- PK: `id` (UUID). `vault_id` (String(128), UNIQUE) — например `"dnd-vault"`
- `domain_id` FK → domains — **без CASCADE** (`ON DELETE SET NULL`), nullable
- `embedding_model_id` (String(128), не FK — хранит `model_id` строкой)
- `expected_dimensions` — фиксируется при bind
- `chunk_size`, `overlap`, `entity_aware_mode`
- `semantic_threshold` (Float, default 0.3)
- `binding_status`: `unbound | indexing | bound | error`
- `chunk_count` — счётчик, обновляется при индексации

### Document
- PK: `id` (UUID)
- `vault_id` FK → vaults.**vault_id** (String, не UUID!) — `ON DELETE CASCADE`
- `source_path` (Text) — путь к файлу в vault
- `title` (String(512), nullable) — заголовок документа
- `md5`, `mtime` — для определения изменений
- `status`: `pending | parsing | chunking | indexing | done | error | cancelled | empty`
- `indexed_at` — время успешной индексации
- **UNIQUE** `(vault_id, source_path)`

### Tag
- PK: `id` (UUID)
- `domain_id` FK → domains (CASCADE)
- `campaign_id` FK → campaigns (SET NULL, nullable) — **прямой столбец в таблице**, дополняет M2M `campaign_tags`
- `name`, `color` (nullable HEX/CSS)
- **UNIQUE** `(name, domain_id)`

### Campaign
- Сессионный контейнер для чатов
- `domain_id`, `name`, `description`
- `system_prompt` — кастомный системный промпт для всей кампании
- `last_session_at` — для сортировки по активности
- Связан с тегами через `campaign_tags` M2M

### Chat
- `domain_id` NOT NULL + CASCADE (инвариант: чат всегда принадлежит домену)
- `campaign_id` nullable (SET NULL)
- `vault_id` (String, nullable, без FK — позволяет указать vault по-умолчанию)
- `pipeline_versions` (JSONB) — зафиксированные версии пайплайнов чата
- `locked_pipeline_id` — принудительно зафиксированный пайплайн
- `pipeline_pause_state` (JSONB) — состояние паузы на validation-шаге DAG
  - структура: `{pipeline_id, step_id, resume_token, step_results, query, expires_at}`
- `pending_pipeline_confirm` (JSONB) — ожидание подтверждения запуска пайплайна
  - структура: `{pipeline_id, pipeline_name, reasoning, confirm_token, query, expires_at}`

### Message
- `chat_id` FK (CASCADE), `role` (user/assistant/system), `content`
- `pipeline_id` — к какому пайплайну относится ответ

### ClarificationState
- PK = `chat_id` (1:1 к Chat)
- `stage`: FSM-состояние (`idle | collecting | ready`)
- `missing_fields` (JSONB list), `collected` (JSONB dict)
- `turn` — счётчик итераций уточнения
- `next_question` — сформулированный вопрос для пользователя

### Pipeline
- `pipeline_id` (String) + `domain_id` + `version` — **UNIQUE**
- `steps` (JSONB array) — DAG шагов пайплайна
- `final_composition` (JSONB) — инструкция финальной сборки ответа
- `is_active` — активна ли данная версия
- `campaign_id` nullable — пайплайн может быть привязан к кампании

### PipelineDecision
- Лог решений роутера пайплайнов
- `chat_id`, `message_id` (без FK-констрейнта на messages), `selected_pipeline_id`
- `confidence` (Float), `reasoning` (Text, nullable), `mode`

### AuditLog
- `action`, `entity_type`, `entity_id`, `details` (JSONB)

## Индексы

| Таблица | Индекс | Примечание |
|---|---|---|
| `generation_models` | `idx_generation_models_active` (partial `WHERE is_active`) | гарантирует одну активную модель |
| `rerank_models` | `idx_rerank_models_active` (partial) | аналогично |
| `vaults` | `idx_vaults_domain` | по domain_id |
| `documents` | `idx_documents_vault`, `idx_documents_status` | по vault_id; по (vault_id, status) |
| `tags` | `idx_tags_domain`, `idx_tags_campaign` | по domain_id; по campaign_id |
| `document_labels` | `idx_document_labels_tag` | по tag_id |
| `chats` | `idx_chats_domain`, `idx_chats_campaign` | по domain_id; по campaign_id |
| `messages` | `idx_messages_chat` | по chat_id |
| `pipelines` | `idx_pipelines_domain` | по (domain_id, is_active) |
