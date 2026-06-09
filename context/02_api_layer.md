# Mercer — Шаг 2: API-слой (chat, settings, config, db_management)

> Файл описывает состояние **as is** на момент создания (июнь 2026).

---

## 1. `app/api/chat.py` — Чат-роутер

### Префикс и регистрация
```
router = APIRouter(prefix="/chat", tags=["chat"])
в main.py регистрируется без prefix -> фактические роуты: /chat/...
```

### Локальные Pydantic-схемы (re-declared в chat.py)

Virtual: `chat.py` переопределяет `CreateChatRequest` поверх импорта из shared_contracts:
```python
class CreateChatRequest(BaseModel):
    domain_id: str          # ОБЯЗАТЕЛЕН (NOT NULL, str, не Optional)
    vault_id: str | None    # deprecated back-compat
    campaign_id: str | None
```
На основании этой схемы работает POST /chat/create. Если domain_id = null — Pydantic вернёт 422.

```python
class RenameChatRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)

class PipelineLockRequest(BaseModel):
    pipeline_id: str | None = None
```

### Роуты

| Метод | Путь | Тело запроса | Ответ | Описание |
|---|---|---|---|---|
| POST | `/chat/create` | `CreateChatRequest` | `CreateChatResponse` | Создаёт Chat + ClarificationState |
| GET | `/chat/list` | `?domain_id=` | `ChatListResponse` | Список чатов, фильтр по domain |
| GET | `/chat/{chat_id}/history` | — | `ChatHistoryResponse` | История + vault_enabled |
| POST | `/chat/{chat_id}/rename` | `RenameChatRequest` | `CreateChatResponse` | Переименование |
| DELETE | `/chat/{chat_id}` | — | 204 | Удаление |
| POST | `/chat/{chat_id}/lock_pipeline` | `PipelineLockRequest` | `{status, locked_pipeline_id}` | Блокировка пайплайна |
| POST | `/chat/{chat_id}/send` | `SendMessageRequest` | `MessageResponse` | Не-стрим ответ |
| POST | `/chat/{chat_id}/send_stream` | `SendMessageRequest` | `StreamingResponse` | SSE-стрим |
| POST | `/chat/{chat_id}/clarify` | `ClarificationAnswer` | `ClarificationResponse` | Ответ на уточнение |

### `POST /chat/create` — деталь
```python
# domain_id обязателен; campaign_id -> uuid.UUID
chat = Chat(title="New Chat", vault_id=req.vault_id,
            domain_id=req.domain_id, campaign_id=campaign_uuid,
            pipeline_versions=await _pipeline_versions(request))
db.add(chat)
await db.flush()
db.add(ClarificationStateRow(chat_id=chat.id, stage="idle"))
await db.commit()
```

### `POST /chat/{chat_id}/send` — деталь
1. `_get_chat_or_404(chat_id)` — uuid parse + db.get
2. Создаёт Message(role=user)
3. `_domain_id_for_chat()` — chat.domain_id или campaign.domain_id
4. `vault_ids` — из `config_for_vault.vaults` фильтрация по domain_id
5. `retrieval_strategy` — `"semantic"` если vault_id + retrieval.enabled, иначе `"none"`
6. `PipelineExecutionContext` — без `final_composition` (None по умолчанию)
7. `PipelineRouter(db).select(context)` — если None → 503
8. `context.pipeline_id/version/steps/final_composition` — заполняются после select
9. `history` — последние 20 сообщений
10. `PipelineExecutor(db).run(context)` → `PipelineResult`
11. Сохраняет Message(role=assistant)
12. Auto-title если `chat.title == "New Chat"`

### `POST /chat/{chat_id}/send_stream` — деталь
Тот же порядок, что `/send`, но:
- возвращает `StreamingResponse(event_stream(), media_type="text/event-stream")`
- `executor.run_stream(context)` — async-генератор
- чанки `{type:"delta"}` переименованы в `{type:"token"}` (нормализация внутри event_stream)
- запись Message + auto-title после получения full_answer
- завершает стрим `data: [DONE]\n\n`

**SSE-чанки (бэк → фронтенд):**

| `type` | Содержимое | Назначение |
|---|---|---|
| `pipeline_selected` | `pipeline_id`, `pipeline_name`, `mode` | Выбран пайплайн |
| `progress` | `step`, `total`, `step_name` | Прогресс шага |
| `step_done` | `step` | Шаг завершён |
| `token` | `content` | Токен LLM |
| `sources` | `sources: [...]` | Источники (flat) |
| `sources` | `grouped_by_step: true`, `step_groups: [...]` | Источники по шагам |
| `clarification` | `question`, `clarification_id`, `content` | Нужно уточнение |
| `error` | `message` | Ошибка pipeline |
| `[DONE]` | — | Финальный сентинел |

### Вспомогательные функции

```python
_get_chat_or_404(chat_id, db)    # uuid.UUID parse + db.get(Chat, uuid) -> 404
_vault_enabled(db, vault_id)     # settings_service.get("retrieval.enabled")
_domain_id_for_chat(chat, db)    # chat.domain_id > campaign.domain_id
_audit(db, action, entity, id, payload)  # db.add(AuditLog(...))
_pipeline_versions(request)      # X-Pipeline-Version headers
_auto_title(query)               # первые 7 слов, макс 255 символов
```

**Важно:** `config_for_vault = VaultConfigService()` — синглтон на уровне модуля, не per-request.

---

## 2. `app/api/config_api.py` — Рантайм-конфиг

```
router = APIRouter(tags=["config"])
регистрируется без prefix -> /config/...
```

| Метод | Путь | Ответ | Описание |
|---|---|---|---|
| GET | `/config/domains` | `list[DomainRead]` | Список доменов (облегчённый, для UI) |
| GET | `/config/pipelines` | `list[PipelineRead]` | Пайплайны (фильтр: domain_id, campaign_id, is_active) |
| GET | `/config/vaults` | `list[VaultRead]` | Список vault-ов |

**Важно:** `GET /config/domains` — это публичный рид. `api.js.getDomains()` использует `/config/domains`, а `getSettingsDomains()` — `/api/settings/domains`.

---

## 3. `app/api/settings/` — Settings API

```
router = APIRouter(prefix="/api/settings", ...)
```

### 3.1 `__init__.py` — сборка sub-роутеров
Импортирует все sub-роутеры и подключает их к главному settings_router.

### 3.2 `status.py`

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/settings/status` | `{llm_ok, embedding_ok, indexer_ok, vaults_count, ...}` |

Совокупный статус платформы: наличие активной модели, индексер доступен, vaultы.

### 3.3 `params.py`

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/settings/params` | Список всех `platform_settings` |
| PUT | `/api/settings/params/{key}` | Обновление одного параметра |
| POST | `/api/settings/reset` | Сброс к значениям по умолчанию |

### 3.4 `domains.py`

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| GET | `/api/settings/domains` | — | `list[DomainRead]` |
| POST | `/api/settings/domains` | `DomainCreate` | `DomainRead` |
| PUT | `/api/settings/domains/{domain_id}` | `DomainUpdate` | `DomainRead` |
| DELETE | `/api/settings/domains/{domain_id}` | — | 204 |
| GET | `/api/settings/domains/{domain_id}/prompts` | — | `list[DomainPromptRead]` |
| PUT | `/api/settings/domains/{domain_id}/prompts/{prompt_type}` | `DomainPromptUpdate` | `DomainPromptRead` |
| GET | `/api/settings/domains/{domain_id}/fields` | — | `list[DomainClarificationFieldRead]` |
| PUT | `/api/settings/domains/{domain_id}/fields` | `list[DomainClarificationFieldCreate]` | `list[DomainClarificationFieldRead]` |

**Важно:** `prompt_type` ∈ `{"system", "clarification", "planner", "pipeline_router"}`. PUT /fields — full-replace семантика.

### 3.5 `gen_models.py`

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| GET | `/api/settings/models/generation` | — | `list[GenerationModelRead]` |
| POST | `/api/settings/models/generation` | `GenerationModelCreate` | `GenerationModelRead` |
| PUT | `/api/settings/models/generation/{model_id}` | `GenerationModelUpdate` | `GenerationModelRead` |
| DELETE | `/api/settings/models/generation/{model_id}` | — | 204 |
| POST | `/api/settings/models/generation/{model_id}/activate` | — | `{status, model_id}` |
| POST | `/api/settings/models/generation/{model_id}/toggle` | — | `GenerationModelRead` |
| POST | `/api/settings/models/generation/{model_id}/check` | — | `{ok: bool, latency_ms, error?}` |

**Важно:** `/activate` снимает `is_active` со всех остальных моделей в одной транзакции и перезагружает активный провайдер в `settings_service`. `/check` вызывает LLM-провайдер с тестовым промптом.

### 3.6 `emb_models.py`

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/settings/models/embedding` | `list[EmbeddingModelRead]` |
| POST | `/api/settings/models/embedding` | `EmbeddingModelRead` |
| PUT | `/api/settings/models/embedding/{model_id}` | `EmbeddingModelRead` |
| DELETE | `/api/settings/models/embedding/{model_id}` | 204 |
| POST | `/api/settings/models/embedding/{model_id}/check` | `{ok, latency_ms, error?}` |

**Важно:** роута `/activate` для embedding отсутствует — привязка модели идёт через `embedding_model_id` на Vault.

### 3.7 `vaults.py`

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/settings/vaults` | `list[VaultRead]` |
| POST | `/api/settings/vaults` | `VaultCreate` → `VaultRead` |
| PUT | `/api/settings/vaults/{vault_id}` | `VaultUpdate` → `VaultRead` |
| DELETE | `/api/settings/vaults/{vault_id}` | 204 |
| POST | `/api/settings/vaults/{vault_id}/toggle` | `VaultRead` |

**Важно:** `vault_id` в URL — business-key (строка типа `"my_vault"`), не UUID `id`. toggle переключает `vault.enabled`.

### 3.8 `tags.py`

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/settings/tags` | `?domain_id=&vault_id=&campaign_id=` → `TagsGrouped` |
| POST | `/api/settings/tags` | `TagCreate` → `TagRead` |
| PUT | `/api/settings/tags/{tag_id}` | `TagCreate` → `TagRead` |
| DELETE | `/api/settings/tags/{tag_id}` | 204 |

**Важно:** `GET /api/settings/tags` возвращает `TagsGrouped` (не простой список). `domain_id` обязателен.

### 3.9 `campaigns.py`

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/settings/campaigns` | `?domain_id=` → `list[CampaignRead]` |
| POST | `/api/settings/campaigns` | `CampaignCreate` → `CampaignRead` |
| GET | `/api/settings/campaigns/{id}` | `CampaignRead` |
| PUT | `/api/settings/campaigns/{id}` | `CampaignUpdate` → `CampaignRead` |
| DELETE | `/api/settings/campaigns/{id}` | 204 |
| GET | `/api/settings/campaigns/{id}/tags` | `TagsGrouped` |
| POST | `/api/settings/campaigns/{id}/tags` | `TagCreate` → `TagRead` |

### 3.10 `pipelines.py`

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/settings/pipelines` | `?domain_id=&campaign_id=` → `list[PipelineRead]` |
| POST | `/api/settings/pipelines` | `PipelineCreate` → `PipelineRead` |
| PUT | `/api/settings/pipelines/{pipeline_id}` | `PipelineUpdate` → `PipelineRead` |
| DELETE | `/api/settings/pipelines/{pipeline_id}` | 204 |
| POST | `/api/settings/pipelines/{pipeline_id}/activate` | `{status, pipeline_id}` |
| POST | `/api/settings/pipelines/{pipeline_id}/deactivate` | `{status, pipeline_id}` |

**Важно:** `{pipeline_id}` в URL — business-key (строка), не UUID. Unique constraint: (pipeline_id, domain_id, version). `activate` выставляет `is_active=True` только для этого pipeline; у остальных в этом домене `is_active` не сбрасывается.

### 3.11 `documents.py`

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/settings/documents` | `?vault_id=\|domain_id=&status=&tag_id=` → `list[DocumentRead]` |
| GET | `/api/settings/documents/{document_id}` | `DocumentRead` |
| PUT | `/api/settings/documents/{document_id}/labels` | `DocumentLabelWrite` → `DocumentRead` |
| POST | `/api/settings/documents/labels/batch` | `{document_ids, tag_ids}` → 204 |

**Важно:** `vault_id` ИЛИ `domain_id` обязателен (400 если ни одного). PUT /labels — full-replace (удаляет все старые метки). batch — additive.

### 3.12 `helpers.py`
Разделяемые вспомогательные функции для settings-роутеров (шифрование/дешифрование API-ключей, поиск Vault по vault_id, поиск Document с тегами).

### 3.13 `schemas.py`
Локальные Pydantic-схемы для settings-ответов (не входящие в shared_contracts):
- `SettingsStatus` — композитный статус
- `PlatformSettingRead` — CRUD-ответ для параметров
- `UpdateParamRequest` — `{value: Any}`

---

## 4. `app/api/db_management.py` — DB Management API

```
router = APIRouter(prefix="/api/db", tags=["db-management"])
регистрируется без prefix -> /api/db/...
```

**Важно:** роутер включается только если `AppConfig.ui.db_management_enabled = True`.

### Маршруты

| Метод | Путь | Ответ | Описание |
|---|---|---|---|
| GET | `/api/db/documents` | `{items, total}` | Документы через LanceDB API (`?vault_id=`) |
| DELETE | `/api/db/documents/{id}` | JSON `{deleted_count}` | Удаление чанков из LanceDB |
| POST | `/api/db/search/domain` | `TextSearchResponse` | Текстовый поиск по домену |
| GET | `/api/db/stats` | `{vault_count, chunk_count, ...}` | Статистика индекса |

**Важно:** DELETE /api/db/documents/{id} возвращает JSON (не 204!). `?vault_id=` обязателен.  
API `api.js.getDocumentsByVault()` → `/api/db/documents?vault_id=`, `deleteDocumentById()` → DELETE `/api/db/documents/{id}?vault_id=`.

---

## 5. Vaults/Indexer API (rag-backend proxy)

Дополнительные роуты вне /api/settings и /api/db:

| Метод | Путь | Описание |
|---|---|---|
| POST | `/vaults/{vault_id}/reindex` | Запуск индексации, `body: {force_reindex: bool}` → `{task_id}` |
| GET | `/index-tasks/{task_id}/state` | `TaskStateResponse` |
| WS | `/ws/index-tasks/{task_id}` | WebSocket прогресс индексации |
| GET | `/health` | `{status: "ok"}` |

---

## 6. Frontend JS: `api.js` + `chat.js`

### 6.1 `api.js` — ChatAPI класс

**Глобальный синглтон:** `window.chatAPI = new ChatAPI()`

**Ключевые методы:**

```js
createChat(domainId, campaignId)
// POST /chat/create, body: {domain_id, campaign_id}
// !!! domainId=null -> body: {domain_id: null} -> 422 Pydantic
// Надо предавать валидный domain_id или защищаться от null!

sendMessage(chatId, content, stream=true)
// stream=true -> POST /chat/{id}/send_stream, body: {content, stream: true}
// stream=false -> POST /chat/{id}/send, body: {content}
// Возвращает: ReadableStream (stream) или JSON (non-stream)
// Ошибки: err.status + err.message (разбирает detail/message из JSON)

runIndexer(vaultId=null, force=false)
// если vaultId=null — авто берёт первый активный vault из getSettingsVaults()

connectToTaskStream(taskId)  // WS /ws/index-tasks/{id}
getIndexTaskState(taskId)    // GET /index-tasks/{id}/state
```

**Нюанс `sendMessage` + поле `stream`:**  
`SendMessageRequest` имеет `stream: bool = True`. Фронтенд посылает `{content, stream: true}` при stream=true и `{content}` при stream=false. Бэкенд принимает оба варианта без ошибок (stream=True/False по умолчанию True).

### 6.2 `chat.js` — ChatManager класс

**Инициализация:** `DOMContentLoaded` -> `window.chatManager = new ChatManager()`

**DOM-элементы:**
```
messages-container, input-area, message-input, send-btn, chat-title,
welcome-message, chat-context-bar, world-name, pipeline-select, lock-pipeline-btn
```

**Ключевые методы:**

```js
loadChat(chatId)         // загрузка истории + setupContextBar
sendMessage(override?)   // отправка + handleStreamResponse
handleStreamResponse()   // чтение ReadableStream + SSE-парсинг
handleJSONResponse()     // JSON-ответ с clarification_id-проверкой
setupContextBar(chat)    // загрузка pipeline select + domain label
```

**SSE-парсинг в `handleStreamResponse`:**
- `data: {...}` — разбирает JSON, диспатчит по `type`
- `data: [DONE]` — устанавливает `streamDone=true`, но не прерывает петлю (в чанке могут быть sources)
- `scheduleMarkdownRender` — debounced через `requestAnimationFrame` (~60fps)
- `clarification` SSE — удаляет пустой assistantMessage, создаёт отдельный div с `data-clarification-id`

**Ошибки:**
```js
// LLM недоступен (503 + сообщение)
if (error.status === 503 || error.message.includes('generation model'))
    // сообщение пользователю "LLM недоступен"
// Остальные ошибки -> message прямо в UI
```

**Функции маркдаун:**
```js
renderMarkdown(text)         // marked.parse + DOMPurify.sanitize (GFM, breaks)
preprocessMarkdown(text)     // GitHub callouts [!NOTE] -> ** **
renderSourcesBlock(sources, answerText)  // фильтр: только [N] цитируемые
```

---

## 7. Ключевые нюансы API-слоя

1. **`/chat/create` + `domain_id=null`** — вернёт 422 (Pydantic), т.e. фронтенд должен передавать валидный domain_id или обрабатывать 422 на уровне UI.
2. **`SendMessageRequest.stream`** — поле `stream: bool = True`, бэк не проверяет его, использует только URL (/send vs /send_stream).
3. **`_get_chat_or_404` uuid parse** — если `chat_id` не UUID-формат — `ValueError` → 500 (нет обработки). Фронтенд всегда передаёт UUID из `CreateChatResponse.chat_id`.
4. **`PipelineRouter.select()` = None** — 503 (нет активного пайплайна); фронтенд показывает специальное сообщение.
5. **`vault_id` на Chat deprecated** — `retrieval_strategy` на запросы строится по chat.vault_id (старый путь). Новый путь — через `vault_ids` из `config_for_vault.vaults`.
6. **`config_for_vault = VaultConfigService()`** — создаётся один раз при импорте модуля. Если VaultConfigService обновляет конфиг динамически — изменения видны без рестарта.
7. **`delta` -> `token` нормализация** — делается в `event_stream()` (бэк), фронтенд видит только `type: "token"`.
8. **`GET /config/domains` vs `/api/settings/domains`** — разные эндпоинты с одинаковым ответом. api.js.getDomains() использует /config/domains для sidebar и создания чата.
9. **`db_management` отключается** через `AppConfig.ui.db_management_enabled`.
10. **`sendMessage` ошибка LLM** — 503 или message content — фронтенд показывает кнопку повторного запроса `_appendRetryButton`.
