# API Routes — rag-backend

Базовый URL: `http://localhost:8000`  
Основной файл: `rag-backend/app/main.py`

Все маршруты монтируются через `app.include_router(...)` в `main.py`. Префиксы отдельных роутеров:

| Роутер | Prefix | Файл | Назначение |
|---|---|---|---|
| `chat_router` | `/chat` | `api/chat.py` | Чаты, сообщения, стриминг, clarification |
| `pipeline_resume_router` | `/chat` | `api/pipeline_resume.py` | Подтверждение/resume пайплайнов |
| `fulldoc_confirm_router` | `/chat` | `api/fulldoc_confirm.py` | Подтверждение выбора документов в Full Document Mode |
| `config_router` | `/config` | `api/config_api.py` | Системные read-only справочники (domains/vaults) |
| `settings_router` | `/api/settings` (задаётся в `main.py`) | `api/settings/__init__.py` | Настройки платформы — агрегирует 12 sub-роутеров |
| `db_management_router` | (абсолютные пути) | `api/db_management.py` | Управление БД, миграции, прямой read-only storage API |
| `indexer_state_router` | `/api/v1` (задаётся в `main.py`) | `api/indexer_state.py` | Статус индексатора, задачи переиндексации |
| `watchdog_router` | `/api/v1` | `api/watchdog_settings.py` | Настройки watchdog, pending-files |
| `update_mode_router` | `/api/chats/{chat_id}/update-mode` | `api/update_mode.py` | Campaign Update Mode (review, apply) |

`settings_router` (`/api/settings`) включает следующие sub-роутеры:

| Sub-роутер | Собственный prefix | Файл |
|---|---|---|
| `status_router` | — | `settings/status.py` |
| `params_router` | — | `settings/params.py` |
| `domains_router` | — | `settings/domains.py` |
| `gen_models_router` | — | `settings/gen_models.py` |
| `emb_models_router` | — | `settings/emb_models.py` |
| `rerank_models_router` | — | `settings/rerank_models.py` |
| `vaults_router` | — | `settings/vaults.py` |
| `pipelines_router` | — | `settings/pipelines.py` |
| `tags_router` | `/tags` | `settings/tags.py` |
| `documents_router` | `/documents` | `settings/documents.py` |
| `campaigns_router` | — | `settings/campaigns.py` |
| `sidecar_router` | `/sidecar` | `settings/sidecar.py` |

> Вспомогательные файлы без роутеров: `settings/helpers.py` (общие хелперы), `settings/schemas.py` (Pydantic-схемы для этого пакета).

---

## Chat API (`api/chat.py`)

Префикс `/chat` (см. `router = APIRouter(prefix="/chat")`).

```
POST   /chat/create                                — создать чат
GET    /chat/list                                  — список чатов
PATCH  /chat/{chat_id}                             — обновить чат (title, locked_pipeline_id)
DELETE /chat/{chat_id}                             — удалить чат

GET    /chat/{chat_id}/history                     — история сообщений
POST   /chat/{chat_id}/send                        — отправить сообщение (non-stream)
POST   /chat/{chat_id}/send_stream                 — отправить сообщение (SSE stream)
POST   /chat/{chat_id}/rename                      — переименовать чат
POST   /chat/{chat_id}/lock_pipeline               — зафиксировать пайплайн для чата

POST   /chat/{chat_id}/clarify                     — отправить ответ на clarification-вопрос
POST   /chat/{chat_id}/pipeline_confirm            — подтвердить запуск pending-пайплайна
POST   /chat/{chat_id}/pipeline_resume             — продолжить DAG после validation/resume
POST   /chat/{chat_id}/full_document_confirm       — подтвердить выбор документов Full Document Mode
```

> `POST /chat/create` (а не `POST /api/chat/`); пути используют `/send_stream` для SSE-стрима. Раньше в документе фигурировали `/api/chat/`, `/messages`, `/clarification`, `/clarification/reset` — все эти эндпоинты удалены.

---

## Campaign Update Mode API (`api/update_mode.py`)

Префикс `/api/chats/{chat_id}/update-mode`. Доступен только для campaign-чатов.

```
POST   /api/chats/{chat_id}/update-mode/start
    — Старт update mode: retrieval → LLM edit intents + state_patch → resolve в indexer
    — Body: {"note": str (max 20000 chars)}
    — Response: StartUpdateModeResponse (session + warnings + state_field_snapshot + state_patch_operations)
    — 409 если сессия уже активна; 422 если нет tags / vault / indexed md

GET    /api/chats/{chat_id}/update-mode/session
    — Получить текущее состояние review-сессии из Redis
    — Response: UpdateModeSessionResponse (changes + warnings + state_field_snapshot + state_patch_operations)
    — 410 + Cache-Control: no-store если сессия истекла

PATCH  /api/chats/{chat_id}/update-mode/review
    — Обновить accepted/rejected статус правок в Redis
    — Body: UpdateModeReviewRequest
        {
          "accepted_change_ids":   [string],
          "rejected_change_ids":  [string],
          "state_patch_decisions": {                       // опционально
            "accepted_op_indexes": [int],
            "rejected_op_indexes": [int],
            "edited":               [{"op_index": int, "text": string}]
          }
        }
    — 422 при `unknown_state_op_index`; 409 при `state_op_review_conflict`

POST   /api/chats/{chat_id}/update-mode/apply
    — Применить accepted changes: checksum verify → snapshot → write → commit → reindex
    — Также применяет принятый state_patch через `campaign_state_value_service.apply_patch`
    — Body: {"apply_id": UUID (idempotency key)}
    — Response: ApplyUpdateModeResponse (per-vault results, commit SHA, reindex_task_id, state_patch_result)
    — 409 при `file_modified`, `vault_lock_timeout`, `apply_already_started`
    — state patch failure (config_version mismatch, source stale) → state_patch_result.failed_op_indexes, file apply продолжается

DELETE /api/chats/{chat_id}/update-mode/session
    — Отменить сессию, удалить из Redis
```

### Коды ошибок (application-level)

| Код | HTTP | Смысл |
|---|---|---|
| `campaign_required` | 422 | Чат не связан с campaign |
| `campaign_tags_required` | 422 | Нет tags у campaign |
| `no_enabled_vaults` | 422 | Нет enabled vault в domain |
| `campaign_has_no_indexed_markdown` | 422 | Нет tagged indexed `.md` |
| `no_relevant_campaign_context` | 422 | Retrieval не нашёл релевантный context |
| `no_usable_indexed_context` | 422 | Context reconstruction/limits не дали usable docs |
| `generation_provider_unavailable` | 503 | Нет active LLM provider |
| `indexer_unavailable` | 503/502 | Indexer недоступен |
| `session_already_active` | 409 | Review session уже есть |
| `session_expired` | 410 | Redis TTL истёк |
| `file_modified` | 409 | Файл изменился после review |
| `target_exists` | 409 | Create target уже существует |
| `vault_root_missing` | 409 | Нет vault directory |
| `vault_lock_timeout` | 409 | Vault занят другой операцией |
| `git_unavailable` | 503 | Git отсутствует/недоступен |
| `git_identity_missing` | 503 | Нет git identity (ни DB, ни env fallback) |
| `git_ignored_target` | 409 | Git игнорирует target `.md` |
| `apply_already_started` | 409 | Другой apply ID уже выполняется |
| `apply_id_payload_mismatch` | 409 | Тот же apply ID, другой payload |
| `apply_in_progress` | 409 | Apply с тем же ID ещё выполняется |
| `state_op_review_conflict` | 409 | state-patch op_index пересекается accepted и rejected |
| `unknown_state_op_index` | 422 | state-patch op_index отсутствует в сессии |
| `state_patch_conflict` | 409 | config_version mismatch / source snapshot stale |

### Internal Indexer API (внутри Docker-сети, не публичный)

```
POST   /internal/update-mode/resolve
    — LLM intent → original-file diff, SHA-256, unified_diff
    — Вызывается через `indexer_client.py` из rag-backend

POST   /internal/update-mode/apply
    — Checksum verify → snapshot → atomic write → git commit → targeted reindex
    — Apply idempotency: apply_id хранится в Redis/shared state; повтор с тем же apply_id возвращает тот же результат
```

---

## Settings API (`api/settings/`)

Все эндпоинты монтируются под `/api/settings` (задаётся в `main.py`). Внутри sub-роутеры добавляют свой собственный путь.

### Статус платформы (`settings/status.py`)

```
GET    /api/settings/status    — агрегированный статус готовности платформы
```

Возвращает:
```json
{
  "has_active_generation_model": true,
  "has_active_embedding_model": true,
  "pdf_sidecar_available": false,
  "has_vaults": true
}
```

Используется фронтендом для отображения предупреждений о незавершённой конфигурации.

### Домены (`settings/domains.py`)

```
GET    /api/settings/domains
POST   /api/settings/domains
GET    /api/settings/domains/{domain_id}
PUT    /api/settings/domains/{domain_id}                        — частичный update
GET    /api/settings/domains/{domain_id}/prompts
PUT    /api/settings/domains/{domain_id}/prompts/{prompt_type}
GET    /api/settings/domains/{domain_id}/fields                 — clarification fields
PUT    /api/settings/domains/{domain_id}/fields                 — замена clarification fields
DELETE /api/settings/domains/{domain_id}
```

### Вольты (`settings/vaults.py`)

```
GET    /api/settings/vaults
POST   /api/settings/vaults
PUT    /api/settings/vaults/{vault_id}                          — update
DELETE /api/settings/vaults/{vault_id}
POST   /api/settings/vaults/{vault_id}/toggle                   — bind/unbound toggle
```

> Старые эндпоинты `POST .../bind` и `POST .../unbind` удалены; переключение через единый `/toggle`.

### Документы (`settings/documents.py`)

Префикс `/documents` (внутри settings).

```
GET    /api/settings/documents
GET    /api/settings/documents/{document_id}
PUT    /api/settings/documents/{document_id}/labels             — полная замена тегов документа
POST   /api/settings/documents/labels/batch                     — batch-замена тегов
DELETE /api/settings/documents/{document_id}
```

> Раньше `reindex` объявлялся здесь; фактически он находится в `db_management.py` (см. ниже).

### Generation Models (`settings/gen_models.py`)

```
GET    /api/settings/models/generation
POST   /api/settings/models/generation
PUT    /api/settings/models/generation/{model_id:path}           — update
DELETE /api/settings/models/generation/{model_id:path}
POST   /api/settings/models/generation/{model_id:path}/activate
POST   /api/settings/models/generation/{model_id:path}/deactivate
POST   /api/settings/models/generation/{model_id:path}/toggle   — flip is_active
POST   /api/settings/models/generation/{model_id:path}/check    — health-check
```

### Embedding Models (`settings/emb_models.py`)

```
GET    /api/settings/models/embedding
POST   /api/settings/models/embedding
PUT    /api/settings/models/embedding/{model_id:path}
DELETE /api/settings/models/embedding/{model_id:path}
POST   /api/settings/models/embedding/{model_id:path}/check
POST   /api/settings/models/embedding/{model_id:path}/toggle
```

> У embedding-моделей нет `activate`/`deactivate`: активная выбирается через `Vault.embedding_model_id`.

### Rerank Models (`settings/rerank_models.py`)

```
GET    /api/settings/models/rerank
POST   /api/settings/models/rerank
PUT    /api/settings/models/rerank/{model_id:path}
DELETE /api/settings/models/rerank/{model_id:path}
POST   /api/settings/models/rerank/{model_id:path}/activate
POST   /api/settings/models/rerank/{model_id:path}/deactivate
POST   /api/settings/models/rerank/{model_id:path}/check
```

### Кампании (`settings/campaigns.py`)

```
GET    /api/settings/campaigns
POST   /api/settings/campaigns
GET    /api/settings/campaigns/{campaign_id}
PUT    /api/settings/campaigns/{campaign_id}
DELETE /api/settings/campaigns/{campaign_id}

GET    /api/settings/campaigns/{campaign_id}/tags
POST   /api/settings/campaigns/{campaign_id}/tags
GET    /api/settings/campaigns/{campaign_id}/global-tags
POST   /api/settings/campaigns/{campaign_id}/global-tags/{tag_id}
DELETE /api/settings/campaigns/{campaign_id}/global-tags/{tag_id}
```

#### Campaign State — Field Configuration (Stage 1)

```
GET    /api/settings/campaigns/{campaign_id}/state-fields
POST   /api/settings/campaigns/{campaign_id}/state-fields
PUT    /api/settings/campaigns/{campaign_id}/state-fields/{field_id}
DELETE /api/settings/campaigns/{campaign_id}/state-fields/{field_id}
POST   /api/settings/campaigns/{campaign_id}/state-fields/reorder
```

`PUT` и `DELETE` обязаны сохранять инвариант cascade-purge: при удалении поля все значения в активной версии state очищаются, создаётся новая `state_version` (`source_kind='patch'`, `base_state_version` = предыдущая), AuditLog пишет `campaign_state_field_cascade_purged`.

#### Campaign State — Versioned State (Stage 2)

```
GET    /api/settings/campaigns/{campaign_id}/state
GET    /api/settings/campaigns/{campaign_id}/state/versions
GET    /api/settings/campaigns/{campaign_id}/state/versions/{state_version}
POST   /api/settings/campaigns/{campaign_id}/state/patch
```

`POST .../state/patch` принимает `CampaignStatePatchRequest` (`base_state_version`, `config_version`, `operations: [...]`). При несовпадении версий — 409 без silent overwrite.

#### Campaign State — Initial State (Stage 3)

```
POST   /api/settings/campaigns/{campaign_id}/state/initial/preview
GET    /api/settings/campaigns/{campaign_id}/state/initial
POST   /api/settings/campaigns/{campaign_id}/state/initial/apply
```

- `POST .../state/initial/preview` принимает `{document_ids: string[]}` (1..50, только Markdown-индекс-документы кампании). Возвращает `CampaignStateInitialProposalRead` с `proposal_id`, `source_snapshot`, `proposal.fields`, `warnings`. Proposal сохраняется в Redis с TTL 3 часа.
- `GET .../state/initial` возвращает текущий proposal или `null`.
- `POST .../state/initial/apply` принимает `{proposal_id, config_version}`. Создаёт первую `CampaignStateVersion` (`source_kind="initial"`, `state_version=1`, `base_state_version=null`). Возвращает `CampaignStateVersionRead`.

Коды ошибок preview: `404 campaign_not_found`, `422 no_markdown_documents / document_not_markdown / document_not_indexed`, `503 generation_provider_unavailable / invalid_generation_output`.

Коды ошибок apply: `404 proposal_not_found / campaign_not_found`, `409 initial_already_applied / config_version_conflict / source_snapshot_stale` (с `stale_documents: string[]`), `410 proposal_expired`.

#### Campaign State — Effective Context (Stage 6)

```
GET    /api/settings/campaigns/{campaign_id}/effective-context?chat_id=...
```

Возвращает `EffectiveContextRead` с блоками `system_prompt`, `campaign_state`, `rag_context` (опц.), `history`/`user_message` (опц.), полями `total_tokens`, `budget`, `truncated_fields`, `state_version`. Не выполняет retrieval и не вызывает LLM. Возвращает 200 даже если active state отсутствует.

#### Campaign State — Stale Status (Stage 7)

```
GET    /api/settings/campaigns/{campaign_id}/state/stale-status
```

Возвращает `CampaignStateStaleStatus` (`potentially_stale`, `stale_documents`, `active_state_version`, `checked_at`). Вычисляется на лету из Redis vault-cache + `Document.md5`; не персистится в БД (AuditLog пишется только на переходе `false → true`).

### Теги (`settings/tags.py`)

Префикс `/tags` (внутри settings).

```
GET    /api/settings/tags
POST   /api/settings/tags
PUT    /api/settings/tags/{tag_id}                              — update
DELETE /api/settings/tags/{tag_id}
```

`GET /api/settings/tags` возвращает `TagsGrouped` (`global_tags`, `by_campaign`).

### Пайплайны (`settings/pipelines.py`)

```
GET    /api/settings/pipelines
POST   /api/settings/pipelines
PUT    /api/settings/pipelines/{pipeline_uuid}
DELETE /api/settings/pipelines/{pipeline_uuid}
POST   /api/settings/pipelines/{pipeline_uuid}/activate
POST   /api/settings/pipelines/{pipeline_uuid}/deactivate
```

### Платформенные параметры (`settings/params.py`)

```
GET    /api/settings/params                                  — все параметры (сгруппированы)
PUT    /api/settings/params/{key:path}                        — обновить параметр
POST   /api/settings/reset                                   — сброс к дефолтам
```

### Sidecar (`settings/sidecar.py`)

Префикс `/sidecar` (внутри settings). Прокси-роутер к **host-agent** (`HOST_AGENT_URL`, порт 9090). Позволяет UI управлять процессом `pdf-sidecar` на хосте. При недоступности host-agent возвращает `503` (или `200` с `agent_unavailable: true` для `/status` — чтобы UI не считал это ошибкой).

```
GET    /api/settings/sidecar/status
POST   /api/settings/sidecar/start
POST   /api/settings/sidecar/stop
POST   /api/settings/sidecar/restart
GET    /api/settings/sidecar/install/stream                  — SSE-поток вывода install.sh (установка)
```

---

## DB Management API (`api/db_management.py`)

Префикс не задан — маршруты используют абсолютные пути. Эндпоинты предназначены для внутреннего использования и UI «DB Browser».

```
GET    /api/db/documents                                    — список документов (фильтры)
DELETE /api/db/documents/{document_id}                       — удалить документ и его чанки
GET    /api/db/chunks                                        — список чанков
POST   /api/db/search/text                                   — full-text поиск
POST   /api/db/search/domain                                 — поиск в рамках домена
POST   /vaults/{vault_id}/reindex                            — запустить переиндексацию
DELETE /index-tasks/{task_id}                                — удалить задачу индексации
POST   /vaults/{vault_id}/detach                             — отвязать vault
GET    /db/ui                                                — HTML-страница DB Browser
```

---

## Indexer State API (`api/indexer_state.py`)

Префикс `/api/v1` (задаётся в `main.py`).

```
GET    /api/v1/index-tasks/{task_id}/state                   — IndexState из Redis
GET    /api/v1/vaults/{vault_id}/index-state                 — состояние индексации vault
GET    /api/v1/indexer/tasks                                 — список index-задач
POST   /api/v1/indexer/tasks/{task_id}/cancel                — отменить задачу
```

---

## Watchdog API (`api/watchdog_settings.py`)

Префикс `/api/v1` (задаётся в `main.py`).

```
GET    /api/v1/settings/watchdog                             — настройки watchdog
PATCH  /api/v1/settings/watchdog                             — изменить интервал и т.д.
GET    /api/v1/vaults/{vault_id}/pending-files               — файлы, ожидающие индексации
GET    /api/v1/domains/{domain_id}/pending-files             — то же в масштабе домена
POST   /api/v1/domains/{domain_id}/index                     — запуск индексации домена
```

---

## Config API (`api/config_api.py`)

Префикс `/config`. Read-only справочники для UI.

```
GET    /config/domains                                       — список доменов
GET    /config/vaults                                        — список vaults
```

---

## Статика и SPA

```
GET    /                                                     — возвращает index.html (ванильный JS SPA)
GET    /static/*                                             — статические файлы фронтенда
GET    /health                                               — {"status": "ok", "service": "rag-backend"}
```