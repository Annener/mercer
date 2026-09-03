# База данных — схема PostgreSQL

Файл ORM-моделей: `rag-backend/app/db/models.py`  
Миграции: **Alembic** — `rag-backend/migrations/versions/`  
Запуск: `run_migrations()` в `rag-backend/app/db/migrations.py` — вызывает `alembic upgrade head` через `asyncio.to_thread` при старте сервиса.

Текущая цепочка миграций (revision → down_revision):

| Revision | down_revision | Назначение |
|---|---|---|
| `0001_initial` | — | Полная стартовая схема + seed доменов, промптов, clarification-fields и platform settings |
| `0002_watchdog_interval` | `0001_initial` | `platform_settings.watchdog.interval_sec`; заполнение `Document.char_count`, `chunk_count`, `estimated_tokens` |
| `0003_fulldoc_fields` | `0002_watchdog_interval` | `Chat.full_document_mode_enabled`, `Chat.sent_full_document_ids` (JSONB) |
| `0004_fulldoc_jsonb_fix` | `0003_fulldoc_fields` | Корректирующая миграция: фиксирует тип `sent_full_document_ids` под JSONB |
| `0005_campaign_git_identity` | `0004_fulldoc_jsonb_fix` | `Vault.git_author_name`, `Vault.git_author_email` (override для git identity в Update Mode) |
| `0006_audit_log_actor_payload` | `0005_campaign_git_identity` | `AuditLog.actor` (String 256, nullable), `AuditLog.payload` (JSONB, nullable) |
| `0007_campaign_state_field_config` | `0006_audit_log_actor_payload` | Таблица `campaign_state_field_configs` (Stage 1) + триггер `updated_at` |
| `0008_campaign_state_versions` | `0007_campaign_state_field_config` | `Campaign.config_version`; таблицы `campaign_state_versions`, `campaign_state_values`, `campaign_state_list_items` (Stage 2) |
| `0009_retrieval_tool_settings` | `0008_campaign_state_versions` | Сид `platform_settings.retrieval.*` — пять ключей для agent loop (Stage 8.2) |
| `0010_message_sources` | `0009_retrieval_tool_settings` | `Message.sources` (JSONB) — persistent source citations для assistant messages |
| `0011_chat_metadata` | `0010_message_sources` | `Chat.metadata` (JSONB) — inline scene-state; `Chat.context_update_mode` (BOOL) — флаг model-proposed context updates |
| `0012_grounded_knobs` | `0011_chat_metadata` | Bump `retrieval.top_k` (10 → 20) и `retrieval.evidence_token_budget` (4000 → 6000) для grounded agent-assistant |
| `0013_state_values_composite_pkey` | `0012_grounded_knobs` | Schema bug fix: PK `campaign_state_values` (был single-column `version_id`) → composite `(version_id, field_id)`. Семантика: одна строка на (version, field), корректно работает `apply_initial` с multi-row INSERT. |
| `0014_chat_rag_prefill_enabled` | `0013_state_values_composite_pkey` | `Chat.rag_prefill_enabled` (Bool, default false) — per-chat toggle для Sprint 2 prefill RAG. True = legacy grounded (retrieval ДО agent loop + tool_choice=required). False = model-decides workflow. |
| `0015_drift_models` | `0014_chat_rag_prefill_enabled` | Таблица `drift_models` (Phase 2a context-engine). UNIQUE `model_id`, partial UNIQUE `WHERE is_active = true` (`uq_drift_models_active`). Seed: `drift-local-default` (host_sidecar, QVikhr-3-1.7B-Instruct-noreasoning-q4_k_m, активна по умолчанию). |
| `0016_drift_model_qvikhr` | `0015_drift_models` | Переключение seed drift-модели с Qwen2.5-3B-Instruct на QVikhr-3-1.7B-Instruct-noreasoning (меньше размер, лучше RU, быстрее на Metal GPU). WHERE-clause на `model_name` гарантирует идемпотентность. |

> Имя файла миграции и `revision` могут расходиться (например, `0004_fix_sent_full_document_ids_jsonb.py` использует revision `0004_fulldoc_jsonb_fix`). Источник истины — `revision = "..."` внутри файла.

---

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
Campaign (1) ──► (N) CampaignStateFieldConfig   [CASCADE]
Campaign (1) ──► (N) CampaignStateVersion       [CASCADE]

CampaignStateVersion (1) ──► (N) CampaignStateValue     [CASCADE version]
CampaignStateVersion (1) ──► (N) CampaignStateListItem  [CASCADE version]
CampaignStateFieldConfig  (1) ──► (N) CampaignStateValue     [RESTRICT]
CampaignStateFieldConfig  (1) ──► (N) CampaignStateListItem  [RESTRICT]

Tag ──► campaign_id (nullable, прямой FK в таблице)
Tag (M) ──► (M) Campaign  [campaign_tags]

Vault (vault_id: String) ──► (N) Document  [vault_id FK = String, не UUID]
Document (M) ──► (M) Tag  [document_labels]

Chat (1) ──► (N) Message
Chat (1) ──► (1) ClarificationState
Chat (1) ──► (N) PipelineDecision
```

---

## Таблицы

### `domains`
- PK: `domain_id` (String(64), не UUID) — например `"dnd"`, `"work"`
- `display_name`, `description`, `is_system`, `enabled`
- Системные домены (`is_system=True`) нельзя удалять
- Зарегистрированные домены (сид): `dnd`, `default`

### `domain_prompts`
- Промпты домена по типу: `system`, `clarification`, `planner`, `pipeline_router`
- **UNIQUE** `(domain_id, prompt_type)`
- `content` (Text, дефолт пустая строка)

### `domain_clarification_fields`
- Поля уточняющих вопросов для конкретного домена
- `field_name`, `label`, `hint`, `required`, `display_order`
- **UNIQUE** `(domain_id, field_name)`
- Используются в `ClarificationFSM`

### `platform_settings`
- PK: `key` (String(128)) — например `"retrieval.top_k"`, `"pdf_sidecar.url"`
- `value` (Text, **всегда строка**), `value_type` (`int | float | bool | str`)
- `group_name`, `label`, `hint`
- Десериализация: `SettingsService.deserialize_value()`
- Загружаются в память при старте: `settings_service.load_settings()`

Сид-записи (добавляются при миграциях):

| key | group_name | value_type | Источник |
|---|---|---|---|
| `retrieval.enabled` | retrieval | bool | 0001 |
| `retrieval.top_k` | retrieval | int | 0001 |
| `chunking.chunk_size` | chunking | int | 0001 |
| `chunking.overlap` | chunking | int | 0001 |
| `chunking.entity_aware_mode` | chunking | bool | 0001 |
| `chat.max_clarification_turns` | chat | int | 0001 |
| `chat.stream_answers` | chat | bool | 0001 |
| `chat.auto_title` | chat | bool | 0001 |
| `pdf_sidecar.url` | sidecar | str | 0001 |
| `pdf_sidecar.timeout_seconds` | sidecar | int | 0001 |
| `pdf_sidecar.fallback_to_pdfminer` | sidecar | bool | 0001 |
| `watchdog_auto_index_extensions` | indexing | str | 0001 |
| `watchdog.interval_sec` | watchdog | int | 0002 |
| `retrieval.tool_enabled` | retrieval | bool | 0009 |
| `retrieval.policy` | retrieval | str | 0009 |
| `retrieval.max_rounds_chat` | retrieval | int | 0009 |
| `retrieval.max_rounds_assistive` | retrieval | int | 0009 |
| `retrieval.evidence_token_budget` | retrieval | int | 0009 (bumped 4000 → 6000 в 0012 для grounded agent-assistant) |
| `retrieval.top_k` | retrieval | int | 0001 (bumped 10 → 20 в 0012 для grounded agent-assistant) |
| `chat.campaign_state_token_budget` | chat | int | 0009 (Stage 6 — token budget для compiled Campaign State block; default 800) |

> `retrieval.policy` хранится как строка `"grounded" | "assistive"` и преобразуется в `RetrievalPolicy` enum в `app/services/retrieval_tool_settings.py`.

**Ключи, читаемые кодом, но без дефолта в сиде** (fallback в `app/services/context_engine/drift.py`):

| key | Тип | Default в коде | Где читается |
|---|---|---|---|
| `drift.confidence_threshold` | float | 0.5 | `context_engine/drift.py:65` — порог для отсечения drift hints |
| `drift.max_messages` | int | 10 | `context_engine/drift.py:66` — сколько последних сообщений читать |

Cooldown (30 сек) и TTL draft (3 часа) **захардкожены** в `context_engine/loop.py:32` (`_COOLDOWN_SECONDS`) и `context_engine/draft.py:47` (`_DRAFT_TTL_SECONDS`) — не вынесены в `platform_settings`. См. `context/open-questions.md` п.1 (глобальная настройка drift loop вкл/выкл).

### `generation_models`
- PK: `id` (UUID). `model_id` (String, UNIQUE) — идентификатор модели
- `provider` = `"openai_compatible"`
- `base_url`, `encrypted_api_key` (шифрование через `ENCRYPTION_KEY`)
- `is_active` (bool) — только одна активная (частичный UNIQUE-индекс `WHERE is_active = true`)
- `enabled` — модель доступна для выбора
- `display_name`, `timeout_seconds`, `created_at`, `updated_at`

### `embedding_models`
- `model_id` (UNIQUE), `provider` (`ollama | openai_compatible`)
- `model_name`, `base_url`, `dimensions`
- `max_retries`, `timeout_seconds`, `enabled`
- Нет `is_active` — связь с vault через `Vault.embedding_model_id`

### `rerank_models`
- Аналогична `generation_models`, но для реранкинга
- `is_active` — одна активная (UNIQUE-индекс `WHERE is_active = true`)

### `drift_models` (Context Engine Phase 2a, миграция `0015`)
- PK: `id` (UUID)
- `model_id` (String 128, UNIQUE) — например `"drift-local-default"`
- `provider` (String 64) — `"host_sidecar" | "openai_compatible"`
- `base_url` (String 512, nullable) — URL провайдера (для `host_sidecar` дефолт `http://host.docker.internal:8765`)
- `model_name` (String 256) — например `"qvikhr-3-1.7b-instruct-noreasoning-q4_k_m"`
- `encrypted_api_key` (Text, nullable) — для внешних провайдеров
- `is_active` (Bool) — одна активная (partial UNIQUE-индекс `uq_drift_models_active WHERE is_active = true`)
- `enabled` (Bool, default true) — доступна ли для выбора
- `display_name` (String 256, nullable) — `"QVikhr-3-1.7B (local)"` для UI
- `timeout_seconds` (Integer, default 60)
- `created_at`, `updated_at`
- Seed: `drift-local-default` (`host_sidecar`, `qvikhr-3-1.7b-instruct-noreasoning-q4_k_m`, активна по умолчанию)
- CRUD: встроен в `app/services/settings_service.py:395-470` (`list_drift_models`, `create_drift_model`, `update_drift_model`, `delete_drift_model`, `activate_drift_model`, `deactivate_drift_model`, `get_active_drift_model`). Не вынесен в отдельный `drift_model_service.py`.
- Settings UI: `frontend/src/components/settings/tabs/ModelsTab.tsx` → секция «Drift-модели».
- Миграция `0016_drift_model_qvikhr` переключила seed `Qwen2.5-3B → QVikhr-3-1.7B-Instruct-noreasoning` (идемпотентный UPDATE с WHERE-clause `model_name = 'qwen2.5-3b-instruct-q4_k_m'`, downgrade возвращает обратно).

### `vaults`
- PK: `id` (UUID). `vault_id` (String(128), UNIQUE) — например `"dnd-vault"`
- `domain_id` FK → `domains.domain_id` (`ON DELETE SET NULL`, nullable)
- `enabled` (Boolean, default True) — флаг доступности vault для Update Mode и retrieval
- `embedding_model_id` (String(128), не FK — хранит `model_id` строкой)
- `expected_dimensions` — фиксируется при bind
- `chunk_size`, `overlap`, `entity_aware_mode`
- `semantic_threshold` (Float, default 0.3)
- `binding_status`: `unbound | indexing | bound | error`
- `chunk_count` — счётчик, обновляется при индексации
- `git_author_name` (String(256), nullable) — git identity override (0005)
- `git_author_email` (String(320), nullable) — git identity override (0005)
- `created_at`, `updated_at`

> Физический `path` vault **не хранится** в БД. Root определяется deployment mount: `/data/vaults/{vault_id}`.

### `documents`
- PK: `id` (UUID)
- `vault_id` FK → `vaults.vault_id` (String, не UUID!) — `ON DELETE CASCADE`
- `source_path` (Text) — путь к файлу в vault
- `title` (String(512), nullable) — заголовок документа
- `md5` (32 hex), `mtime` — для определения изменений
- `status`: `pending | parsing | chunking | indexing | done | error | cancelled | empty`
- `indexed_at` — время успешной индексации
- `char_count` (Integer, nullable) — размер документа в символах (0002)
- `chunk_count` (Integer, nullable) — кол-во чанков (0002)
- `estimated_tokens` (Integer, nullable) — оценка токенов (0002)
- `created_at`
- **UNIQUE** `(vault_id, source_path)`

### `document_labels`
- PK: `(document_id, tag_id)` — составной
- Обе FK `ON DELETE CASCADE`

### `tags`
- PK: `id` (UUID)
- `domain_id` FK → `domains` (CASCADE)
- `campaign_id` FK → `campaigns` (SET NULL, nullable) — прямой FK, дополняет M2M `campaign_tags`
- `name`, `color` (nullable HEX/CSS), `created_at`
- **UNIQUE** `(name, domain_id)`

### `campaign_tags` (ассоциативная таблица)
- PK: `(campaign_id, tag_id)`
- Обе FK `ON DELETE CASCADE`
- Связывает `campaigns` ↔ `tags` (M2M), `viewonly=True` на стороне ORM

### `campaigns`
- PK: `id` (UUID)
- `domain_id` FK (CASCADE), `name` (String 256), `description` (Text, nullable)
- `system_prompt` — кастомный системный промпт для всей кампании
- `last_session_at` — для сортировки по активности
- `config_version` (Integer, default 1) — инкрементируется при любых изменениях конфигурации полей Campaign State (0008)
- `created_at`
- Связан с тегами через `campaign_tags` M2M; имеет `state_fields` и `state_versions` relationships

### `campaign_state_field_configs` (Campaign State Stage 1)
- PK: `id` (UUID)
- `campaign_id` FK (CASCADE), `key` (String 64), `label` (String 256)
- `description` (Text, дефолт "")
- `mode`: `"single" | "list"` (CHECK constraint `ck_state_fields_mode_valid`)
- `enabled` (Bool, default true)
- `display_order` (Integer, default 0, CHECK ≥ 0)
- `created_at`, `updated_at` (с триггером `trg_campaign_state_field_configs_updated_at`)
- **UNIQUE** `(campaign_id, key)`
- **CHECK** `length(key) >= 1 AND length(label) >= 1`
- Индекс `idx_state_fields_campaign_order` (`campaign_id`, `display_order`)

### `campaign_state_versions` (Campaign State Stage 2)
- PK: `id` (UUID)
- `campaign_id` FK (CASCADE)
- `state_version` (Integer, CHECK ≥ 1) — монотонный счётчик per campaign
- `config_version` (Integer, CHECK ≥ 1)
- `source_kind` (`"initial" | "patch"`, CHECK constraint, default `"patch"`)
- `base_state_version` (Integer, nullable) — на какой версии базировался этот снимок (NULL для первой)
- `created_at`, `created_by` (String 256, nullable)
- **UNIQUE** `(campaign_id, state_version)`
- Индекс `idx_state_versions_campaign_latest` (`campaign_id`, `state_version DESC`)
- Cascade values/list_items

### `campaign_state_values` (single-поля per version)
- PK: `version_id` (FK → `campaign_state_versions.id`, CASCADE)
- `field_id` FK → `campaign_state_field_configs.id` (RESTRICT)
- `text` (Text), `source_refs` (JSONB, default `[]`)
- `updated_at`
- Индекс `idx_state_values_field` (`field_id`)

### `campaign_state_list_items` (list-поля per version)
- PK: `id` (UUID)
- `version_id` FK (CASCADE)
- `field_id` FK → `campaign_state_field_configs.id` (RESTRICT)
- `item_key` (String 128, CHECK 1..128) — стабильный в пределах поля
- `text` (Text)
- `resolved` (Bool, default false)
- `source_refs` (JSONB, default `[]`)
- `created_at`, `updated_at`
- **UNIQUE** `(version_id, field_id, item_key)`
- Индексы: `idx_state_list_items_field_key` (`field_id`, `item_key`), `idx_state_list_items_version` (`version_id`)

### `chats`
- PK: `id` (UUID)
- `title` (String 512, default `"New Chat"`)
- `domain_id` NOT NULL + CASCADE (инвариант: чат всегда принадлежит домену)
- `campaign_id` nullable (SET NULL)
- `vault_id` (String, nullable, без FK — deprecated back-compat)
- `pipeline_versions` (JSONB, dict) — зафиксированные версии пайплайнов чата
- `locked_pipeline_id` — принудительно зафиксированный пайплайн
- `pipeline_pause_state` (JSONB, nullable) — состояние паузы на validation-шаге DAG
  - структура: `{pipeline_id, step_id, resume_token, step_results, query, expires_at}`
- `pending_pipeline_confirm` (JSONB, nullable) — ожидание подтверждения запуска пайплайна
  - структура: `{pipeline_id, pipeline_name, reasoning, confirm_token, query, expires_at}`
- `full_document_mode_enabled` (Bool, default false) — 0003
- `sent_full_document_ids` (JSONB list, default `[]`) — 0003 (тип JSONB закреплён 0004)
- `metadata` (JSONB, default `{}`) — 0011. Inline scene-state память чата, мутируется через `update_scene_state` tool. Структура:
  ```json
  {
    "scene_state": {
      "explicit": {"current_location": "...", "active_npcs": [...]},
      "drift": {
        "_hints": [{"fact": "...", "contradicts_field": null, "adds_field": "current_allies", "msg_ref": "1", "confidence": 0.85}],
        "_ts": "2026-09-01T18:00:00Z",
        "_chat_id": "<uuid>"
      }
    }
  }
  ```
  Под-пространство `explicit` пишется LLM через `update_scene_state` tool (host-controlled merge). Под-пространство `drift._hints` пишется `DriftDetector` (auto, low-confidence, max 8 hints в prompt). Доступ через `chat.metadata_json` в ORM (алиас для колонки `metadata`).
- `context_update_mode` (Bool, default false) — 0011. Master switch для `propose_context_update` tool. Когда true, agent loop может генерировать proposal-ы на обновление Campaign State / vault files, которые пользователь подтверждает в UI.
- `rag_prefill_enabled` (Bool, default false) — 0014. Per-chat toggle для Sprint 2 prefill RAG. True = legacy grounded (retrieval ДО agent loop + tool_choice=required в round 0). False = model-decides workflow (по умолчанию).
- `created_at`, `updated_at`

### `messages`
- `chat_id` FK (CASCADE), `role` (`user | assistant | system`), `content`
- `pipeline_id` — к какому пайплайну относится ответ
- `sources` (JSONB nullable, миграция `0010_message_sources`) — список `MessageSource`
  (path, page, vault_id, document_id, chunk_id, source_kind), использованных для генерации
  ответа. Заполняется во всех режимах: legacy single-shot, tool-based AgentLoop, pipeline
  (grouped → flattened), full document mode + resume flows. Используется для восстановления
  блока «Источники» при reload чата.
- `created_at`

### `clarification_states`
- PK = `chat_id` (1:1 к Chat)
- `stage`: FSM-состояние (`idle | collecting | complete | fallback`)
- `missing_fields` (JSONB list), `collected` (JSONB dict)
- `turn` — счётчик итераций уточнения
- `next_question` (Text, nullable) — сформулированный вопрос для пользователя
- `updated_at`

### `pipelines`
- `pipeline_id` (String) + `domain_id` + `version` — **UNIQUE**
- `steps` (JSONB array) — DAG шагов пайплайна
- `final_composition` (JSONB) — инструкция финальной сборки ответа
- `is_active` — активна ли данная версия
- `campaign_id` nullable — пайплайн может быть привязан к кампании
- `created_at`

### `pipeline_decisions`
- Лог решений роутера пайплайнов
- `chat_id` (FK CASCADE), `message_id` (UUID, без FK-констрейнта на `messages`)
- `selected_pipeline_id`, `confidence` (Float), `reasoning` (Text, nullable), `mode`
- `created_at`

### `audit_logs`
- PK: `id` (UUID)
- `action` (String 64), `entity_type` (String 32, nullable), `entity_id` (String 128, nullable)
- `actor` (String 256, nullable) — добавлено в `0006_audit_log_actor_payload`
- `payload` (JSONB, nullable) — заменил старое `details` в `0006_audit_log_actor_payload`
- `created_at`

Используется для логирования:

| action | Сценарий |
|---|---|
| `campaign_update_apply` | После apply Update Mode (`payload`: chat_id, campaign_id, apply_id, vault results, commit SHA, accepted change_ids, reindex task IDs) |
| `pipeline_router_failure` | Ошибка pipeline router |
| `chat.agent_loop` | Каждый чат-турн с tool-циклом: `payload` содержит `rounds`, `tool_calls_made`, `policy` (Stage 8.7) |
| `campaign_state_field_cascade_purged` | Каскадное удаление поля: `from_state_version`, `to_state_version`, `config_version`, `field_id`, `field_key`, `purged_values`, `purged_list_items` |
| `campaign_state_initial_propose_fields_applied` | Stage 3.v2 apply с accepted suggested_fields: `existing_fields_count`, `suggested_fields_total`, `suggested_fields_accepted`, `suggested_fields_rejected`, `total_fields_after_apply` |
| `update_mode.apply_schema` | Sprint 3 успех schema apply: `applied_op_indexes`, `failed_op_indexes`, `new_config_version`, `rolled_back` |
| `update_mode.apply_aborted_schema` | Sprint 3 abort с rollback: `failed_field_op_indexes`, `failed_reasons` |
| `context_draft_accepted` | ContextDraftCard Accept: `campaign_id`, `applied_state_version`, `operations_count` |
| `context_draft_rejected` | ContextDraftCard Reject: `campaign_id` |
| `context_draft_check_files` | ContextDraftCard Check-files: `session_id`, `campaign_id` (Phase 5) |

---

## Индексы

| Таблица | Индекс | Примечание |
|---|---|---|
| `generation_models` | `uq_generation_models_model_id`, partial `WHERE is_active` | гарантирует уникальность `model_id` и одну активную модель |
| `embedding_models` | `uq_embedding_models_model_id` | уникальность `model_id` |
| `rerank_models` | `uq_rerank_models_model_id`, partial `WHERE is_active` | аналогично generation |
| `drift_models` | `uq_drift_models_model_id`, partial `WHERE is_active` | аналогично generation, миграция 0015 |
| `vaults` | `uq_vaults_vault_id`, `idx_vaults_domain`, `idx_vaults_enabled` | по `domain_id`; по `enabled` |
| `documents` | `idx_documents_vault`, `idx_documents_status` | по `vault_id`; по `(vault_id, status)` |
| `tags` | `idx_tags_domain`, `idx_tags_campaign`, `uq_tag_name_domain` | по `domain_id`; по `campaign_id` |
| `document_labels` | `idx_document_labels_tag` | по `tag_id` |
| `chats` | `idx_chats_domain`, `idx_chats_campaign` | по `domain_id`; по `campaign_id` |
| `messages` | `idx_messages_chat` | по `chat_id` |
| `pipelines` | `uq_pipeline_domain_version`, `idx_pipelines_domain` | по `(pipeline_id, domain_id, version)`; по `(domain_id, is_active)` |
| `campaigns` | (PK) | на `id` |
| `campaign_state_field_configs` | `uq_state_fields_campaign_key`, `idx_state_fields_campaign_order` | уникальность `(campaign_id, key)`; сортировка |
| `campaign_state_versions` | `uq_state_versions_campaign_version`, `idx_state_versions_campaign_latest` | уникальность версии; быстрый lookup latest |
| `campaign_state_values` | `idx_state_values_field` | по `field_id` |
| `campaign_state_list_items` | `uq_state_list_items_version_field_key`, `idx_state_list_items_field_key`, `idx_state_list_items_version` | уникальность `item_key` внутри версии; быстрый lookup |