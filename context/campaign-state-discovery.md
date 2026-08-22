# Campaign State — этап 0: Discovery

Ниже зафиксирована карта текущей реализации Mercer, полученная на этапе Discovery. Она используется как вход для последующих этапов реализации Campaign State.

## Карта точек расширения

| Область | Путь | Символы / элементы | Роль для Campaign State | Читать дальше? |
|---|---|---|---|---|
| Campaign (БД) | `rag-backend/app/db/models.py` | `Campaign`, `campaign_tags`, `Tag.campaign_id`, `Chat.campaign_id` | Источник истины о существующих полях Campaign и её связях | Нет |
| Campaign (API) | `rag-backend/app/api/settings/campaigns.py` | `list_campaigns`, `get_campaign`, `create_campaign`, `update_campaign`, `delete_campaign`, `_campaign_with_tags`, `_campaign_read` | CRUD-роутер; шаблон partial PATCH и batch-операций с тегами | Нет |
| Campaign (API) | `rag-backend/app/api/settings/tags.py` | `list_tags`, `create_tag`, `update_tag`, `delete_tag` | Фильтрация тегов по домену/кампании, исключённый `vault_id` | Нет |
| Campaign (frontend) | `rag-backend/app/static/js/api.js` | `ChatAPI.getCampaigns`, `getCampaign`, `createCampaign`, `getCampaignTags`, `createCampaignTag`, `getCampaignGlobalTags`, `link`, `unlink` | Фронтенд-миксин для текущих Campaign endpoints | Нет |
| Update Mode (хранилище) | `rag-backend/app/services/update_mode_store.py` | `UpdateModeStore`, `update_mode_store`, `_REVIEW_LUA`, `_APPLY_BEGIN_LUA`, `_APPLY_COMPLETE_LUA`, `_normalize_session_lists`, `SESSION_TTL_SECONDS = 10800` | Контракт Redis-сессии и Lua-атомарность; вероятная точка расширения для state patch | Да — см. неизвестности |
| Update Mode (executor) | `rag-backend/app/services/update_mode_executor.py` | `UpdateModeExecutor.start`, `_get_campaign_tag_ids`, `get_campaign_markdown_document_ids`, `_build_context_documents`, `_generate_intents`, `_validate_intents_domain`, `_select_default_vault` | Оркестратор retrieval для Update Mode; ключевая точка для Markdown-only evidence и генерации state patch | Нет |
| Update Mode (API) | `rag-backend/app/api/update_mode.py` | `start_update_mode`, `get_update_mode_session`, `review_changes`, `apply_changes`, `cancel_update_mode`, `_build_file_batches`, `_write_audit_log` | Маршрутизация, маппинг ошибок, review/apply и audit | Да |
| Update Mode (internal client) | `rag-backend/app/services/indexer_client.py` | `IndexerClient`, `IndexerUnavailableError`, `IndexerConflictError` | HTTP-клиент к `rag-indexer`; прокси для resolve/apply | Нет |
| Full Documents | `rag-backend/app/services/full_document_context.py` | `FULL_DOC_TOKEN_LIMIT = 32_000`, `reconstruct_full_text`, `collect_document_candidates`, `assemble_hybrid_context`, `_get_http_client`, `aclose_http_client`, эвристика `math.ceil(len / 4)` | Текущая реализация Full Documents; token limit считает эвристически и не использует `Document.estimated_tokens` | Нет |
| Prompt assembly | `rag-backend/app/services/prompt_pack.py` | `PromptPack`, `resolve_step_vars`, `format_prompt`, `_stringify` | Сейчас обслуживает только DAG placeholders; Campaign State compiler отсутствует | Нет |
| Prompt assembly (runtime) | `rag-backend/app/api/chat.py` | `_resolve_system_prompt`, `plain_stream`, `_plain_llm_reply` | Точка сборки `system_prompt + rag_context`; место для инъекции compiled Campaign State | Да |
| Prompt assembly (pipeline) | `rag-backend/app/services/pipeline_executor.py` | `_resolve_prompt`, `_run_final_composition`, `_run_dag_step`, `_retrieve_full_documents_for_step_dag`, `_maybe_pause_for_full_doc`, `resume_from_full_doc_selection`, `PER_DOC_TOKEN_LIMIT = 16_000`, `TOTAL_TOKEN_BUDGET = 64_000` | Точка сборки prompt в pipeline/DAG; требует отдельного решения по инъекции state | Нет |
| Retrieval | `rag-backend/app/services/retrieval.py` | `retrieve`, `retrieve_multi_vault`, `rerank_hits`, `format_context`, `format_context_with_role`, `get_allowed_tag_ids`, `get_document_ids_by_tags`, `get_documents_by_tag` | Основной RAG-движок; база для conditional retrieval tool | Нет |
| Retrieval (scope) | `rag-backend/app/services/vault_config_service.py` | `VaultConfigService`, `vault_config_service`, `enabled_for_domain`, `VaultConfigEntry` | Фильтр enabled Vault домена для retrieval scope | Нет |
| Reindex (DB-клиент) | `rag-indexer/app/db_client.py` | `IndexerDBClient`, `get_document_by_path`, `create_document`, `update_document_status`, `update_document_size`, `delete_document`, `get_all_documents`, `get_platform_settings` | Реестр документов для indexer | Нет |
| Reindex (state Redis) | `rag-indexer/parser/state/redis_state_manager.py` | `RedisStateManager`, `create_task`, `update_file_stage`, `increment_*`, `get_task_state`, `rebuild_vault_cache`, `mark_file_indexed`, `mark_file_pending`, `get_vault_state`, `is_vault_indexing`, `request_cancel`, `is_cancelled`, `TASK_TTL = 86400`, `CANCEL_TTL = 3600` | Состояние index-задач; потенциальная точка передачи/фиксации события для `potentially_stale` | Нет |
| Reindex (lifecycle) | `rag-indexer/app/main.py` | `lifespan`, `start_index_task`, `list_index_tasks`, `cancel_index_task`, `get_task_state`, `get_vault_documents`, `IndexerService`, `_rebuild_one_vault`, `fs_git.git_init_if_needed`, `fs_git.ensure_vault_*` | Lifecycle indexer: Redis + DB + rebuild + watchdog | Нет |
| Миграции | `rag-backend/migrations/versions/0001_initial.py` | `upgrade`, `downgrade`, `_seed_domains`, `_seed_domain_prompts`, `_seed_clarification_fields`, `_seed_platform_settings` | Стартовая схема и seed доменных prompt/платформенных настроек | Нет |
| Миграции | `rag-backend/migrations/versions/0002_watchdog.py` | `upgrade` | Пример миграции данных: `watchdog.interval_sec`, `Document.char_count`, `chunk_count`, `estimated_*` | Нет |
| Миграции | `rag-backend/migrations/versions/0004_jsonb.py` | `upgrade`, `downgrade` | Пример корректирующей миграции `json → jsonb` | Нет |
| Миграции | `rag-backend/migrations/versions/0005_campaign_vault_git_author.py` | `Vault.git_author_name`, `Vault.git_author_email` | Пример migration, связанной с Campaign/Update Mode | Нет |
| Миграции | `rag-backend/migrations/versions/0006_audit_log.py` | `AuditLog.actor`, `AuditLog.payload (JSONB)` | Образец audit-полей; потребуется уточнить применение для state patch | Нет |
| Миграции (runner) | `rag-backend/app/db/migrations.py` | `run_migrations()`, `_upgrade_head()` | Точка запуска Alembic при старте | Нет |
| Контракты | `shared_contracts/models.py` | `ORMModel._coerce_uuid_fields`, `DocumentCandidate`, `DocumentRecord`, `ChunkRecord`, `ChatRecord`, `CreateChatRequest`, `PipelineExecutionContext.resolve`, `UpdateModeIntent`, `IntentBatch`, `Operation`, `ResolvedUpdateModeChange`, `UpdateModeResolveRequest`, `UpdateModeResolveResponse`, `UpdateModeFileOp`, `UpdateModeFileChangeBatch`, `UpdateModeApplyRequest`, `UpdateModeApplyResponse`, `UpdateModeVaultApplyResult`, `UpdaterState` *(отсутствует)*, `StartUpdateModeRequest`, `StartUpdateModeResponse`, `UpdateModeSessionResponse`, `UpdateModeReviewRequest`, `UpdateModeSession`, `UpdateModeGenerationResult`, `VaultConfigEntry`, `IndexedContextDocument` | Shared API/ORM contracts; ключевая точка расширения state patch DTO и proposal/session contract | Нет |
| Документация API | `context/api_routes.md` | Read-only | Источник истины для endpoint-имён | Нет |
| Документация DB | `context/db_schema.md` | Read-only | Источник истины для таблиц и FK | Нет |
| Документация Update Mode | `context/campaign-update-mode.md` | Read-only | Источник истины для текущей семантики Update Mode; требует дополнения state-patch семантикой | Нет |

## Подтверждённые выводы

- Campaign уже имеет БД-модель, CRUD API, frontend API-клиент и связи с тегами/чатами.
- В коде нет сущностей `CampaignState*`: ни в `db/models.py`, ни в `shared_contracts/models.py`, ни в API, ни во frontend-миксинах.
- В коде нет `CampaignStatePatchOperation`: Update Mode сейчас оперирует только файловыми изменениями через `UpdateModeFileOp` и связанные batch-контракты.
- Update Mode уже содержит отдельные storage, executor и API-слои, а также Redis-сессию с атомарными Lua-переходами review/apply.
- Update Mode уже выбирает Markdown-документы кампании через `get_campaign_markdown_document_ids`, что соответствует политике Markdown-only для Campaign State update.
- Full Documents mode уже имеет token limit `32_000` и подходит для явного выбора источников initial Campaign State. Текущий token count использует эвристику `ceil(len(text) / 4)`.
- В обычном runtime chat prompt собирается в `rag-backend/app/api/chat.py`; в pipeline есть отдельная сборка prompt в `rag-backend/app/services/pipeline_executor.py`.
- В коде пока нет bounded agent loop и tool-схемы `search_knowledge`: ни в `chat.py`, ни в `pipeline_executor.py`, ни в `update_mode_executor.py`.
- Retrieval уже имеет основные primitive-операции: scoped retrieval, reranking, форматирование context и фильтрацию документов по tags.
- В коде нет retrieval policy `assistive`/`grounded`: она отсутствует в `PlatformSetting`, `AppConfig` и `RetrievalConfig`.
- Для stale-state сценария indexer предоставляет lifecycle и Redis task state, но в текущих Redis-ключах/моделях нет `potentially_stale` и нет watcher → campaign trigger.
- PDF должен остаться в RAG, но быть исключён из state initial/update flows на серверной стороне.

## Неизвестности и расхождения

### 1. Update Mode Store и partial apply

Нужно прочитать/проверить `rag-backend/app/services/update_mode_store.py` подробнее перед этапом 4:

- полный формат payload Redis-сессии;
- допустимые статусы и переходы;
- как session versioning/идемпотентность реализованы сейчас;
- можно ли расширить session schema state-операциями без нарушения Lua-скриптов;
- как корректно маркировать частичный apply и исключать повторное применение отклонённых операций.

### 2. Update Mode API и audit

Нужно уточнить в `rag-backend/app/api/update_mode.py`:

- точную форму request/response review и apply;
- как выражается выбор отдельных file changes;
- где хранится результат частичного применения;
- можно ли переиспользовать `_write_audit_log` для state patch и каким должен быть `AuditLog.payload`;
- как API сообщает stale session или conflict.

Выявлено расхождение frontend ↔ backend для review:

- frontend-миксин отправляет `POST` с `{accepted, rejected}`;
- backend router ожидает `PATCH` с `{accepted_change_ids, rejected_change_ids}`.

Это существующий integration defect или устаревший клиентский контракт. Его нужно подтвердить и исправить отдельной небольшой задачей **до этапа 4**, но это не блокирует этап 1 Field Configuration.

### 3. Миграция Update Mode

Наличие отдельной migration `0004_campaign_update_mode.py` не подтверждено:

- в прочитанных файлах её нет;
- `context/db_schema.md` упоминает такую миграцию, но прямой исходный код не был прочитан;
- в discovery уже есть `0004_jsonb.py`, что требует сверки фактического списка `rag-backend/migrations/versions/` и Alembic revision history.

Это нужно закрыть **до создания первой новой миграции на этапе 1**, чтобы не выбрать неверный `down_revision` и не пропустить существующую историю схемы.

### 4. Подсчёт токенов

В текущем прочитанном коде нет единого точного token counter:

- `update_mode_executor.py`, `pipeline_executor.py` и Full Documents используют эвристику `math.ceil(len(text) / 4)`;
- `prompt_pack.py` и `retrieval.py` не выполняют оценку токенов;
- `Document.estimated_tokens` заполняется индексатором, но способ/место заполнения не подтверждены;
- `rag-indexer/app/db_client.py` содержит `update_document_size(...)`, но не подтверждено, где и как он вызывается.

Это не блокирует этап 1. Перед этапами 3 и 5 нужно отдельно подтвердить контракт token accounting и решить, где допустима текущая эвристика, а где нужен общий сервис подсчёта.

### 5. Potentially stale / watcher → campaign

В `RedisStateManager` используются ключи/состояния `task:*`, `vault:*`, `cancel:*`, `active_tasks`, `last_task_id`; полей или ключей state-уведомлений нет.

Это подтверждает, что `potentially_stale` следует проектировать как backend/DB-модель, а не как расширение временного Redis task state. Вопрос реализации watcher → campaign mapping относится к этапу 6 и не блокирует этап 1.

### 6. Pipeline sentinel

`PIPELINE_NONE_ID = "__none__"` применяется в `chat.py`, но в `UpdateChatRequest` не подтверждена отдельная валидация `Chat.locked_pipeline_id` для этого sentinel.

Это не относится к Campaign State напрямую. Зафиксировать как отдельный технический долг/проверку, не включать в этапы 1–7 без отдельного решения.

## Минимальный набор файлов для этапа 1: Field Configuration

Этап 1 реализует только конфигурацию полей Campaign State по спецификации: `key`, `label`, `description`, `mode`, `enabled`, порядок. В него не входят active state, версии state, LLM proposal, initial state, Update Mode patch, prompt assembly, stale status или RAG.

### Обязательно прочитать / добавить в контекст Aider

| Файл | Зачем |
|---|---|
| `rag-backend/app/db/models.py` | Точка добавления `CampaignStateFieldConfig` и связи с `Campaign` |
| `rag-backend/app/api/settings/campaigns.py` | CRUD-паттерны, batch tags и `exclude_unset` partial PATCH; вероятная точка добавления `/campaigns/{id}/state-fields` |
| `rag-backend/app/api/settings/tags.py` | Паттерны порядка/упорядоченных сущностей и фильтрация по домену |
| `rag-backend/migrations/versions/0001_initial.py` | Шаблоны `op.create_table`, уникальных ограничений и индексов |
| `rag-backend/migrations/versions/0006_audit_log.py` | Пример JSONB-поля и аудиторской структуры; читать как migration convention, а не как готовую state-модель |
| `rag-backend/app/db/migrations.py` | Точка запуска Alembic |
| `shared_contracts/models.py` | Точка добавления `CampaignStateFieldConfig`, `CampaignStateFieldMode` (`single`/`list`) и request/update DTO |
| `context/db_schema.md` | Источник истины по стилю таблиц, FK и текущей схеме |
| `context/api_routes.md` | Стиль объявления и документирования роутеров |
| `context/conventions.md` | Naming, style, Alembic и async conventions |
| `context/campaign-state-implementation-spec.md` | Зафиксированный scope и acceptance criteria этапа 1 |
| `context/campaign-state-discovery.md` | Discovery-карта, неизвестности и границы этапа |

### Желательно добавить до проектирования этапа 1

| Файл / действие | Зачем |
|---|---|
| Полный фактический список `rag-backend/migrations/versions/` | Закрыть расхождение по `0004_campaign_update_mode.py`, определить корректный Alembic `down_revision` |
| `rag-backend/app/services/settings_service.py` | Проверить, где по conventions располагается сервисная CRUD-логика для settings; если файла нет, зафиксировать это |
| `rag-backend/app/api/settings/__init__.py` *(если существует)* | Проверить подключение sub-routers |
| `rag-backend/app/static/js/api.js` | Подготовить точку для `getStateFields`, `createStateField` и других frontend API-вызовов, если UI включается в этап 1 |

### Не нужно читать для этапа 1

- `rag-backend/app/services/update_mode_executor.py` — понадобится на этапах 3–4.
- `rag-backend/app/services/pipeline_executor.py` — понадобится на этапе 5.
- `rag-indexer/app/main.py` — понадобится на этапе 6.
- Retrieval и reindex internals — понадобятся на этапе 7.

## Рекомендация по следующему действию

Перед переходом к проектированию этапа 1:

1. **Сначала сверить полный список migrations и revision graph.** Это быстрый, обязательный шаг перед любой новой migration. Нужно подтвердить, существует ли `0004_campaign_update_mode.py`, почему discovery видит `0004_jsonb.py`, и какой фактический Alembic head.
2. **Добавить `settings_service.py` и `app/api/settings/__init__.py`, если они существуют.** Это уменьшит риск поместить CRUD-логику не в тот слой.
3. **Не блокировать этап 1 из-за расхождения `updateModeReview`.** Оно относится к существующему Update Mode и должно быть исправлено отдельной задачей до этапа 4.
4. После пунктов 1–2 запустить `/ask` для короткого проектирования этапа 1 и только затем использовать `/architect` для реализации.

## Рекомендуемое чтение по этапам

| Этап | Обязательные документы | Editable code после `/ask` |
|---|---|---|
| 1. Field configuration | `campaign-state-implementation-spec.md`, этот discovery, `context/db_schema.md`, `context/conventions.md` | Migration, Campaign ORM, campaign schemas/DTO, service, router, tests |
| 2. Versioned State | Spec, discovery, `context/db_schema.md`, `context/shared_contracts.md` | Migration, state ORM/service/contracts/API, tests |
| 3. Initial State | Spec, discovery, `context/campaign-update-mode.md`, Full Documents code | Full Documents entry point, proposal/state service/API, tests |
| 4. Update Mode patch | Spec, discovery, `context/campaign-update-mode.md`, `update_mode_store.py`, `update_mode_executor.py`, `update_mode.py` | Update Mode store/executor/API/contracts/state service, tests; frontend отдельным подэтапом |
| 5. Prompt assembly | Spec, discovery, `context/architecture.md`, `context/rag-backend-services.md` | Context compiler, `chat.py`, prompt/pipeline files по подтверждённому scope, tests |
| 6. Potentially stale | Spec, discovery, indexer lifecycle/state/DB client, campaign source/tag code | Reindex integration, backend stale status/API/UI, tests |
| 7. Conditional/cyclic RAG | Spec, discovery, `context/rag_pipeline.md`, retrieval/chat orchestration code | Tool schema, chat orchestration, retrieval service, integration tests |
