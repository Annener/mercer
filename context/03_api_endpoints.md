# Mercer — API Эндпоинты

> **Проход 3 из N.**
> Базовый URL: `http://localhost:8000` (сервис `rag-backend`).
> Все эндпоинты — JSON, если не указано иное. Коды ошибок: `422` — валидация, `404` — не найдено, `503` — нет LLM-провайдера.

---

## Чат `/chat`

### `POST /chat/create`
Создать новый чат.

**Body:**
```json
{
  "domain_id": "string",       // Обязательно
  "vault_id": "string | null", // Deprecated back-compat
  "campaign_id": "string | null"
}
```

**Response `200`:**
```json
{ "chat_id": "uuid", "title": "New Chat" }
```

---

### `GET /chat/list`
Список чатов, отсортирован по `updated_at DESC`.

**Query params:**
- `domain_id?: string` — фильтр по домену

**Response `200`:**
```json
{
  "chats": [
    {
      "chat_id": "uuid",
      "title": "string",
      "vault_id": "string | null",
      "domain_id": "string | null",
      "vault_enabled": false,
      "created_at": "datetime",
      "updated_at": "datetime"
    }
  ]
}
```

---

### `GET /chat/{chat_id}/history`
История чата: метаданные + все сообщения.

**Response `200`:**
```json
{
  "chat": { "chat_id": "uuid", "title": "...", "domain_id": "..." },
  "messages": [
    {
      "message_id": "uuid",
      "role": "user|assistant|system",
      "content": "string",
      "created_at": "datetime",
      "pipeline_id": "string | null"
    }
  ],
  "vault_enabled": false
}
```

---

### `POST /chat/{chat_id}/rename`

**Body:** `{ "title": "string" }` (1–255 символов)

**Response `200`:** `{ "chat_id": "uuid", "title": "string" }`

---

### `DELETE /chat/{chat_id}`

**Response `204`:** пустой ответ.

---

### `POST /chat/{chat_id}/lock_pipeline`
Принудительно зафиксировать пайплайн для чата (обход PipelineRouter).

**Body:** `{ "pipeline_id": "string | null" }` (чтобы разблокировать — передать `null`)

**Response `200`:** `{ "status": "ok", "locked_pipeline_id": "string | null" }`

---

### `POST /chat/{chat_id}/send`
Отправить сообщение и получить ответ (не стриминг).

**Body:**
```json
{ "content": "string" }
```

**Поток обработки:**
1. Сохранение user-сообщения в `messages`
2. Загрузка истории (20 последних сообщений)
3. Query rewriting через LLM
4. `PipelineRouter.select()` — выбор пайплайна
5a. Если пайплайн найден: `PipelineExecutor.run(context)` → `MessageResponse`
5b. Если нет: fallback LLM с RAG-поиском по всему домену
6. Автотайтл чата (если `title == "New Chat"`)

**Response `200`:** `{ "content": "string", "message_id": "uuid" }`

---

### `POST /chat/{chat_id}/send_stream`
Стриминговый аналог `/send`.

**Body:** `{ "content": "string" }`

**Response:** `StreamingResponse`, `Content-Type: text/event-stream` (SSE)

**Формат SSE-чанков:**
```
data: {"type": "token", "content": "..."}
data: {"type": "sources", "grouped_by_step": false, "sources": [{"path": "...", "page": 3, "vault_id": "..."}]}
data: {"type": "error", "message": "..."}
data: [DONE]
```

---

### `POST /chat/{chat_id}/clarify`
Отправить ответы на вопросы уточнения (FSM). После сбора всех данных запускает pipeline.

**Body:** `ClarificationAnswer` (structure в shared_contracts)

**Response `200`:** `ClarificationResponse`

---

## Конфиг `/config`

### `GET /config/domains`
Список enabled-доменов с информацией о vault. Сортировка: `dnd` → `work` → остальные по алфавиту → `default`.

**Response `200`:**
```json
{
  "domains": [
    {
      "domain_id": "string",
      "display_name": "string",
      "description": "string | null",
      "has_vault": true,
      "vault_enabled": true
    }
  ]
}
```

---

### `GET /config/vaults`

**Query params:**
- `domain_id?: string`
- `search?: string` — поиск `ILIKE %{search}%` по `vault_id`

**Response `200`:**
```json
{
  "vaults": [
    { "vault_id": "string", "domain_id": "string", "enabled": true }
  ]
}
```

---

## Настройки `/settings`

> Файл: `rag-backend/app/api/settings/`

### `GET /settings/`
Все платформенные настройки.

**Response `200`:** `{ "settings": [PlatformSettingRead, ...] }`

---

### `GET /settings/{key}`
Одна настройка по ключу.

**Response `200`:** `PlatformSettingRead`

---

### `PUT /settings/{key}`
Обновить настройку.

**Body:** `{ "value": any }`

**Response `200`:** `PlatformSettingRead`

---

### `GET /settings/models/generation`
Список моделей генерации.

**Response `200`:** `{ "models": [GenerationModelRead, ...] }`

---

### `POST /settings/models/generation`
Добавить модель генерации.

**Body:** `GenerationModelCreate`

**Response `200`:** `GenerationModelRead`

---

### `PATCH /settings/models/generation/{model_id}`
Обновить модель генерации.

**Body:** `GenerationModelUpdate`

**Response `200`:** `GenerationModelRead`

---

### `DELETE /settings/models/generation/{model_id}`

**Response `200`:** `{ "status": "deleted", "model_id": "string" }`

---

### `POST /settings/models/generation/{model_id}/activate`
Сделать модель активной (сбрасывает `is_active=false` для остальных).

**Response `200`:** `GenerationModelRead`

---

### `GET /settings/models/embedding`

**Response `200`:** `{ "models": [EmbeddingModelRead, ...] }`

---

### `POST /settings/models/embedding`

**Body:** `EmbeddingModelCreate`

**Response `200`:** `EmbeddingModelRead`

---

### `PATCH /settings/models/embedding/{model_id}`

**Body:** `EmbeddingModelUpdate`

**Response `200`:** `EmbeddingModelRead`

---

### `DELETE /settings/models/embedding/{model_id}`

**Response `200`:** `{ "status": "deleted", "model_id": "string" }`

---

### `GET /settings/models/rerank`

**Response `200`:** `{ "models": [RerankModelRead, ...] }`

---

### `POST /settings/models/rerank`

**Body:** `RerankModelCreate`

**Response `200`:** `RerankModelRead`

---

### `PATCH /settings/models/rerank/{model_id}`

**Body:** `RerankModelUpdate`

**Response `200`:** `RerankModelRead`

---

### `DELETE /settings/models/rerank/{model_id}`

**Response `200`:** `{ "status": "deleted", "model_id": "string" }`

---

### `POST /settings/models/rerank/{model_id}/activate`

**Response `200`:** `RerankModelRead`

---

## Домены `/domains`

### `GET /domains`

**Response `200`:** `{ "items": [DomainRead, ...] }`

---

### `POST /domains`

**Body:** `DomainCreate`

**Response `200`:** `DomainRead`

---

### `GET /domains/{domain_id}`

**Response `200`:** `DomainRead`

---

### `PATCH /domains/{domain_id}`

**Body:** `DomainUpdate`

**Response `200`:** `DomainRead`

---

### `DELETE /domains/{domain_id}`

**Response `200`:** `{ "status": "deleted", "domain_id": "string" }`

---

### `GET /domains/{domain_id}/prompts`

**Response `200`:** `{ "prompts": [DomainPromptRead, ...] }`

---

### `GET /domains/{domain_id}/prompts/{prompt_type}`

`prompt_type`: `system` | `clarification` | `planner` | `pipeline_router`

**Response `200`:** `DomainPromptRead`

---

### `PUT /domains/{domain_id}/prompts/{prompt_type}`

**Body:** `{ "content": "string" }`

**Response `200`:** `DomainPromptRead`

---

### `GET /domains/{domain_id}/clarification-fields`

**Response `200`:** `{ "fields": [DomainClarificationFieldRead, ...] }` (sorted by `display_order`)

---

### `POST /domains/{domain_id}/clarification-fields`

**Body:** `DomainClarificationFieldCreate`

**Response `200`:** `DomainClarificationFieldRead`

---

### `DELETE /domains/{domain_id}/clarification-fields/{field_id}`

**Response `200`:** `{ "status": "deleted" }`

---

## Хранилища `/vaults`

### `GET /vaults`

**Query params:** `domain_id?: string`

**Response `200`:** `{ "vaults": [VaultRead, ...] }`

---

### `POST /vaults`

**Body:** `VaultCreate`

**Response `200`:** `VaultRead`

---

### `GET /vaults/{vault_id}`

**Response `200`:** `VaultRead`

---

### `PATCH /vaults/{vault_id}`

**Body:** `VaultUpdate`

**Response `200`:** `VaultRead`

---

### `DELETE /vaults/{vault_id}`

**Response `200`:** `{ "status": "deleted" }`

---

### `POST /vaults/{vault_id}/reindex`
Запустить задачу индексации. Проксирует в `rag-indexer: POST /api/v1/tasks`.

**Body:** `{ "force_reindex": false }`

**Response `200`:** `{ "task_id": "string", ... }` (ответ indexer)

---

### `POST /vaults/{vault_id}/detach`
Отвязать vault: удалить данные из LanceDB, сбросить `binding_status = unbound`, `chunk_count = 0`.

**Response `200`:** `{ "status": "ok", "vault_id": "string", "storage": {...} }`

---

## Теги `/tags`

### `GET /tags`

**Query params:** `domain_id: string` (required)

**Response `200`:** `TagsGrouped` — `{ "global_tags": [...], "by_campaign": { "uuid": [...] } }`

---

### `POST /tags`

**Body:** `TagCreate`

**Response `200`:** `TagRead`

---

### `PATCH /tags/{tag_id}`

**Body:** `TagUpdate`

**Response `200`:** `TagRead`

---

### `DELETE /tags/{tag_id}`

**Response `200`:** `{ "status": "deleted" }`

---

## Кампании `/campaigns`

### `GET /campaigns`

**Query params:** `domain_id: string` (required)

**Response `200`:** `{ "items": [CampaignRead, ...] }`

---

### `POST /campaigns`

**Body:** `CampaignCreate`

**Response `200`:** `CampaignRead`

---

### `GET /campaigns/{campaign_id}`

**Response `200`:** `CampaignRead`

---

### `PATCH /campaigns/{campaign_id}`

**Body:** `CampaignUpdate`

**Response `200`:** `CampaignRead`

---

### `DELETE /campaigns/{campaign_id}`

**Response `200`:** `{ "status": "deleted" }`

---

### `PUT /campaigns/{campaign_id}/tags`
Полная замена тегов кампании.

**Body:** `{ "tag_ids": ["uuid", ...] }`

**Response `200`:** `CampaignRead`

---

## Документы `/documents`

### `GET /documents`

**Query params:** `vault_id: string` (required)

**Response `200`:** `{ "documents": [DocumentRead, ...] }`

---

### `PUT /documents/{document_id}/labels`
Полная замена тегов документа.

**Body:** `{ "tag_ids": ["uuid", ...] }`

**Response `200`:** `DocumentRead`

---

## Пайплайны `/pipelines`

### `GET /pipelines`

**Query params:**
- `domain_id: string` (required)
- `campaign_id?: string`

**Response `200`:** `{ "pipelines": [PipelineRead, ...] }`

---

### `POST /pipelines`

**Body:** `PipelineCreate`

**Response `200`:** `PipelineRead`

---

### `GET /pipelines/{pipeline_id}`

**Query params:** `domain_id: string`

**Response `200`:** `PipelineRead`

---

### `PUT /pipelines/{pipeline_id}`

**Body:** `PipelineUpdate`

**Response `200`:** `PipelineRead`

---

### `DELETE /pipelines/{pipeline_id}`

**Response `200`:** `{ "status": "deleted" }`

---

## Управление БД `/api/db`

> Прокси к `db-api-server` (LanceDB). Тег `db-management`.

### `GET /api/db/documents`

**Query params:**
- `vault_id: string` (required)
- `limit: int = 100` (1–500)
- `offset: int = 0`
- `order_by: string = "document_id"`

**Response `200`:** `{ "documents": [DocumentRecord, ...] }`

---

### `GET /api/db/chunks`

**Query params:**
- `document_id: string` (required)
- `vault_id: string` (required)

**Response `200`:** `{ "chunks": [ChunkRecord, ...] }`

---

### `POST /api/db/search/text`
Полнотекстовый поиск в LanceDB по одному vault.

**Body:**
```json
{ "vault_id": "string", "query_text": "string", "limit": 20 }
```

**Response `200`:** `{ "results": [SearchHit, ...] }`

---

### `POST /api/db/search/domain`
Параллельный полнотекстовый поиск по всем enabled-vault'am домена.

**Body:**
```json
{ "domain_id": "string", "query_text": "string", "limit": 20 }
```

**Response `200`:** `{ "results": [SearchHit, ...] }`

---

### `DELETE /api/db/documents/{document_id}`

**Query params:** `vault_id: string` (required)

**Последовательность:**
1. Удаление чанков в LanceDB через `db-api-server`
2. Удаление записи из `documents` в PostgreSQL
3. Пересчёт `chunk_count` vault
4. Запись в `audit_logs`

**Response `200`:** `{ "deleted_count": int, ... }` (ответ db-api-server)

---

## Индексация `/index-tasks`

### `GET /index-tasks/{task_id}/state`
Состояние задачи индексации. Прокси к `rag-indexer: GET /api/v1/tasks/{task_id}/state`.

**Response `200`:** `IndexState` (structure в shared_contracts)

---

### `DELETE /index-tasks/{task_id}`
Отмена задачи индексации. Прокси к `rag-indexer: POST /api/v1/tasks/{task_id}/cancel`.

**Response `200`:** `{ "status": "cancelled", ... }`

---

## WebSocket `/ws`

### `WS /ws/index-tasks/{task_id}`
Прокси WebSocket-потока от `rag-indexer /api/v1/tasks/{task_id}/stream` к клиенту.

**Сообщения:**
```json
{"type": "progress", "chunks_processed": 12, "chunks_total": 50, "status": "indexing"}
{"type": "done", "status": "done"}
{"type": "error", "error": "string"}
```

---

## Структура `SendMessageRequest`

```json
{ "content": "string" }
```

## Структура `SearchHit`

```json
{
  "chunk_id": "string",
  "document_id": "string",
  "vault_id": "string",
  "score": 0.92,
  "text": "string",
  "metadata": {
    "source_path": "path/to/file.pdf",
    "page_number": 3,
    "vault_id": "string"
  }
}
```

---

## Сводная таблица эндпоинтов

| Метод | Путь | Тег | Описание |
|---|---|---|---|
| POST | `/chat/create` | chat | Создать чат |
| GET | `/chat/list` | chat | Список чатов |
| GET | `/chat/{id}/history` | chat | История |
| POST | `/chat/{id}/rename` | chat | Переименовать |
| DELETE | `/chat/{id}` | chat | Удалить |
| POST | `/chat/{id}/lock_pipeline` | chat | Зафиксировать пайплайн |
| POST | `/chat/{id}/send` | chat | Отправить сообщение |
| POST | `/chat/{id}/send_stream` | chat | Отправить (стриминг) |
| POST | `/chat/{id}/clarify` | chat | Ответы на уточнение |
| GET | `/config/domains` | config | Список доменов |
| GET | `/config/vaults` | config | Список vault |
| GET/PUT | `/settings/...` | settings | Настройки платформы |
| CRUD | `/settings/models/generation` | settings | Модели генерации |
| CRUD | `/settings/models/embedding` | settings | Модели эмбеддинга |
| CRUD | `/settings/models/rerank` | settings | Модели реранкинга |
| CRUD | `/domains` | domains | Домены |
| CRUD | `/domains/{id}/prompts` | domains | Промпты домена |
| CRUD | `/domains/{id}/clarification-fields` | domains | Поля уточнения |
| CRUD | `/vaults` | vaults | Хранилища |
| POST | `/vaults/{id}/reindex` | vaults | Индексация |
| POST | `/vaults/{id}/detach` | vaults | Отвязать |
| CRUD | `/tags` | tags | Теги |
| CRUD | `/campaigns` | campaigns | Кампании |
| PUT | `/campaigns/{id}/tags` | campaigns | Теги кампании |
| CRUD | `/documents` | documents | Документы |
| PUT | `/documents/{id}/labels` | documents | Теги документа |
| GET | `/api/db/documents` | db-management | Документы LanceDB |
| GET | `/api/db/chunks` | db-management | Чанки документа |
| POST | `/api/db/search/text` | db-management | Полнотекст. поиск |
| POST | `/api/db/search/domain` | db-management | Поиск по домену |
| DELETE | `/api/db/documents/{id}` | db-management | Удалить документ |
| GET | `/index-tasks/{id}/state` | indexer | Статус задачи |
| DELETE | `/index-tasks/{id}` | indexer | Отмена задачи |
| WS | `/ws/index-tasks/{id}` | indexer | Прогресс индексации |
