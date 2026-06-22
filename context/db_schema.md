# База данных — схема PostgreSQL

Файл: `rag-backend/app/db/models.py`  
Migrations: `rag-backend/app/db/migrations.py` (кастомные SQL-скрипты, не Alembic)

## Ключевые сущности и связи

```
Domain (1) ──→ (N) DomainPrompt
Domain (1) ──→ (N) DomainClarificationField
Domain (1) ──→ (N) Vault
Domain (1) ──→ (N) Campaign
Domain (1) ──→ (N) Tag
Domain (1) ──→ (N) Chat
Domain (1) ──→ (N) Pipeline

Campaign (1) ──→ (N) Chat
Campaign (M) ──→ (M) Tag  [campaign_tags]

Vault (1) ──→ (N) Document
Document (M) ──→ (M) Tag  [document_labels]

Chat (1) ──→ (N) Message
Chat (1) ──→ (1) ClarificationState
Chat (1) ──→ (N) PipelineDecision
```

## Таблицы

### Domain
- PK: `domain_id` (String, не UUID!) — например `"dnd"`, `"work"`
- `display_name`, `description`, `is_system`, `enabled`
- Системные домены (`is_system=True`) нельзя удалять

### DomainPrompt
- Промпты домена по типу: `system`, `clarification`, `planner`, `pipeline_router`
- Уникален по `(domain_id, prompt_type)`
- Содержимое хранится в поле `content` (Text)

### DomainClarificationField
- Поля уточняющих вопросов для конкретного домена
- `field_name`, `label`, `hint`, `required`, `display_order`
- Используются в ClarificationFSM

### PlatformSetting
- PK: `key` (String) — например `"retrieval.top_k"`
- `value` (Text, всегда строка), `value_type` (int/float/bool/str)
- `group_name`, `label`, `hint`
- Десериализация: `SettingsService.deserialize_value()`
- Загружаются в память при старте: `settings_service.load_settings()`

### GenerationModel
- `model_id` (unique String) — идентификатор модели
- `provider` = `"openai_compatible"`
- `base_url`, `encrypted_api_key` (шифрование через ENCRYPTION_KEY)
- `is_active` (bool) — только одна активная модель одновременно
- `enabled` — модель доступна для выбора

### EmbeddingModel
- `model_id` (unique), `provider` (ollama | openai_compatible)
- `model_name`, `base_url`, `dimensions`
- `max_retries`, `timeout_seconds`

### RerankModel
- Аналогична GenerationModel, но для реранкинга
- `is_active` — одна активная

### Vault
- `vault_id` (unique String) — например `"dnd-vault"`
- `domain_id` FK → domains
- `embedding_model_id` (String, не FK — хранит model_id)
- `binding_status`: `unbound | indexing | bound | error`
- `chunk_size`, `overlap`, `entity_aware_mode`
- `chunk_count` — счётчик, обновляется при индексации

### Document
- `vault_id` FK → vaults
- `source_path` — путь к файлу в vault
- `md5`, `mtime` — для определения изменений
- `status`: `pending | parsing | chunking | indexing | done | error | cancelled | empty`
- `indexed_at` — время успешной индексации

### Tag
- Принадлежит домену (`domain_id`), может быть привязан к кампании
- Уникален по `(name, domain_id)`
- `color` (необязательный HEX/CSS цвет)

### Campaign
- Сессионный контейнер для чатов
- `domain_id`, `name`, `description`
- `system_prompt` — кастомный системный промпт для всей кампании
- `last_session_at` — для сортировки по активности
- Связан с тегами через `campaign_tags` M2M

### Chat
- `domain_id` NOT NULL + CASCADE (инвариант: чат всегда принадлежит домену)
- `campaign_id` nullable (чат может быть вне кампании)
- `pipeline_versions` (JSONB) — зафиксированные версии пайплайнов чата
- `locked_pipeline_id` — принудительно зафиксированный пайплайн
- `pipeline_pause_state` (JSONB) — состояние паузы на validation-шаге DAG
  - структура: `{pipeline_id, step_id, resume_token, step_results, query, expires_at}`
- `pending_pipeline_confirm` (JSONB) — ожидание подтверждения запуска пайплайна
  - структура: `{pipeline_id, pipeline_name, reasoning, confirm_token, query, expires_at}`

### Message
- `chat_id` FK, `role` (user/assistant/system), `content`
- `pipeline_id` — к какому пайплайну относится ответ

### ClarificationState
- PK = `chat_id` (1:1 к Chat)
- `stage`: FSM-состояние (`idle | collecting | ready`)
- `missing_fields` (JSONB list), `collected` (JSONB dict)
- `turn` — счётчик итераций уточнения
- `next_question` — сформулированный вопрос для пользователя

### Pipeline
- `pipeline_id` (String) + `domain_id` + `version` — уникальный ключ
- `steps` (JSONB array) — DAG шагов пайплайна
- `final_composition` (JSONB) — инструкция финальной сборки ответа
- `is_active` — активна ли данная версия
- `campaign_id` nullable — пайплайн может быть привязан к кампании

### PipelineDecision
- Лог решений роутера пайплайнов
- `chat_id`, `message_id`, `selected_pipeline_id`, `confidence`, `mode`

### AuditLog
- `action`, `entity_type`, `entity_id`, `details` (JSONB)
