# Mercer — Audit Log

> Статусы: 🔴 баг | ⚠️ нарушение инварианта / предупреждение | ✅ исправлен | ⬜ проверен, OK

---

## C1–C9 · Chat group

✅ Закрыто.

---

## C10–C12 · Config group (CF1–CF2)

✅ Закрыто.

---

## C13 · tab-vaults.js — showVaultModal вызывает getDomains() вместо getSettingsDomains()

| ID | Файл | Проблема | Что должно быть | Статус |
|---|---|---|---|---|
| S36-new | `tab-vaults.js` | `showVaultModal` → `getDomains()` (`/config/domains`, только enabled) | `getSettingsDomains()` (`/api/settings/domains`, полный список) | ✅ |

---

## C14 · settings.js — пустые заглушки handlers

| ID | Файл | Проблема | Статус |
|---|---|---|
| S14-A | `settings.js` | `handleVaultsAction` — пустая заглушка `{}` | ✅ |
| S15-A | `settings.js` | `handleGenModelsAction` — пустая заглушка `{}` | ✅ |
| S16-A | `settings.js` | `handleEmbModelsAction` — пустая заглушка `{}` | ✅ |

---

## C15 · api.js — расхождения путей (S17-B, S18-B, S19-A)

| ID | Файл | Проблема | Что в бэке | Статус |
|---|---|---|---|---|
| S17-B | `api.js` | `toggleVault()` отсутствует | `POST /api/settings/vaults/{vault_id}/toggle` | ✅ |
| S18-B | `api.js` | `setActiveGenerationModel()` → `/set_active` (404) | `POST /api/settings/models/generation/{model_id:path}/activate` | ✅ |
| S19-A | `api.js` + `emb_models.py` | `setActiveEmbeddingModel()` → роута нет | Роут не создавался (концепция неприменима); метод удалён из api.js | ✅ |

---

## C16 · Аудит S14–S44: имена методов, toggle-gen, 204-safe, pipeline.id

| ID | Файл | Проблема | Статус |
|---|---|---|---|
| S14-B | `settings.js` | `showGenModelModal()` → метода нет; должно быть `showGenerationModelModal()` | ✅ → C17 |
| S15-B | `settings.js` | `showEmbModelModal()` → метода нет; должно быть `showEmbeddingModelModal()` | ✅ → C17 |
| S16-B | `tab-gen-models.js` | Кнопка `toggle-gen` отсутствует в `renderModelList` для `kind='gen'` | ✅ → C17 |
| S20-A | `tab-emb-models.js` | Рендер корректен; `activate-emb` не рендерится (инвариант) | ⬜ |
| S25-A | `tab-vaults.js` | `showVaultModal` исправлен → `getSettingsDomains()` (S36-new) | ⬜ |
| S27-A | `api.js` | `deleteVault` — 204-safe, нет `.json()` | ⬜ |
| S30-A | `tab-pipelines.js` | `pipeline.id` = UUID (из `pipeline_dict`), `_get_pipeline_by_uuid` — корректно | ⬜ |
| S31-A | `api.js` | `activatePipeline`, `deactivatePipeline`, `deletePipeline` — все 204-safe | ⬜ |
| S40-A | `tab-documents.js` | `deleteDocumentById` 204-safe; `reindexVault`/`connectToTaskStream`/`getIndexTaskState` — все есть | ⬜ |

---

## C17 · settings.js — исправление имён методов + кнопка toggle-gen

| ID | Файл | Проблема | Исправление | Статус |
|---|---|---|---|---|
| S14-B | `settings.js` | `showGenModelModal()` → `TypeError` | `showGenerationModelModal()` | ✅ |
| S15-B | `settings.js` | `showEmbModelModal()` → `TypeError` | `showEmbeddingModelModal()` | ✅ |
| S16-B | `tab-gen-models.js` | Кнопка `toggle-gen` отсутствовала | Добавлена строка с `data-action="toggle-gen"`, текст ▶️/⏸️ по `model.enabled` | ✅ |

**Закрыто в коммите C17.**

---

## C18 · Аудит D1–D9: db-management group — расхождения путей api.js vs db_management.py

### Маппинг бэк-роутов (db_management.py)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/db/documents?vault_id=&limit=&offset=&order_by=` | Список документов по vault |
| GET | `/api/db/chunks?document_id=&vault_id=` | Чанки документа |
| POST | `/api/db/search/text` | Текстовый поиск `{vault_id, query_text, limit}` |
| POST | `/api/db/search/domain` | Поиск по домену `{domain_id, query_text, limit}` |
| DELETE | `/api/db/documents/{document_id}?vault_id=` | Удаление документа → **JSON** (не 204!) |
| POST | `/vaults/{vault_id}/reindex` | Запуск индексации |
| DELETE | `/index-tasks/{task_id}` | Отмена задачи |
| GET | `/index-tasks/{task_id}/state` | Состояние задачи |
| POST | `/vaults/{vault_id}/detach` | Detach vault |
| WS | `/ws/index-tasks/{task_id}` | WebSocket прогресс |

### Баги api.js

| ID | Метод api.js | Путь в api.js (до фикса) | Правильный путь | Доп. проблема | Статус |
|---|---|---|---|---|---|
| D1 | `getDocumentsByDomain(domainId)` | `GET /api/settings/documents?domain_id=` | `GET /api/db/documents?vault_id=` | Нужен `vault_id`, не `domain_id`; tab-documents.js обновлён | ✅ → C19 |
| D2 | `deleteDocumentById(docId)` | `DELETE /api/settings/documents/{id}` | `DELETE /api/db/documents/{id}?vault_id=` | vault_id обязателен как query-param; ответ JSON, не 204 | ✅ → C19 |
| D3 | `reindexVault(vaultId)` | `POST /api/settings/vaults/{id}/reindex` | `POST /vaults/{id}/reindex` | Лишний prefix `/api/settings` | ✅ → C19 |
| D4 | `connectToTaskStream(taskId)` | `WS /api/settings/tasks/{id}/stream` | `WS /ws/index-tasks/{id}` | Неверный путь WS | ✅ → C19 |
| D5 | `getIndexTaskState(taskId)` | `GET /api/settings/tasks/{id}` | `GET /index-tasks/{id}/state` | Нет суффикса `/state` | ✅ → C19 |
| D6 | `updateDocumentLabels(docId, tagIds)` | `PUT /api/settings/documents/{id}/labels` | `PUT /api/settings/documents/{id}/labels` | Роут существует в `settings/documents.py`; схема `DocumentLabelWrite {tag_ids: list[str]}`; ответ `DocumentRead`; фронт совпадает | ✅ |
| D7 | `textSearchByDomain` | отсутствовал | `POST /api/db/search/domain` `{domain_id, query_text, limit}` → `TextSearchResponse` | `db_management.js` вызывал метод, которого не было → `TypeError` | ✅ → C22 |

---

## C19 · api.js + tab-documents.js — исправление D1–D5

| ID | Файл | Исправление | Статус |
|---|---|---|---|
| D1 | `api.js` | `getDocumentsByDomain` → переименован в `getDocumentsByVault(vaultId)`, путь `/api/db/documents?vault_id=` | ✅ |
| D2 | `api.js` | `deleteDocumentById(docId, vaultId)` — добавлен `vaultId`, путь `/api/db/documents/{id}?vault_id=`, ответ JSON | ✅ |
| D3 | `api.js` | `reindexVault` → путь `/vaults/{id}/reindex` | ✅ |
| D4 | `api.js` | `connectToTaskStream` → `WS /ws/index-tasks/{id}` | ✅ |
| D5 | `api.js` | `getIndexTaskState` → `GET /index-tasks/{id}/state` | ✅ |
| D1-tab | `tab-documents.js` | `loadDocumentsData` → `_resolveVaultId()` + `getDocumentsByVault(vaultId)`; `delete-doc` передаёт `data-vault` | ✅ |

**D6 — верифицирован: роут уже реализован в бэке, фронт корректен. Статус обновлён до ✅.**

---

## C20 · gen_models.py + settings.js — toggle роут и check-gen ответ

| ID | Файл | Проблема | Исправление | Статус |
|---|---|---|---|---|
| S16-C | `gen_models.py` | `POST /models/generation/{model_id:path}/toggle` отсутствовал → 404 при нажатии ⏸️/▶️ | Добавлен роут: атомарный flip `enabled`; если `is_active=True && enabled=True` → 409 | ✅ |
| S16-D | `settings.js` | `check-gen`: `result?.status === 'ok'` → всегда `false` (бэк возвращает `{ok, latency_ms, error}`) | Исправлено на `result?.ok`; алерт показывает latency_ms | ✅ |
| S21-B | `settings.js` | `check-emb`: аналогичная ошибка `result?.status === 'ok'` | Исправлено на `result?.ok` (попутно) | ✅ |

**Закрыто в коммите C20.**

---

## C21 · settings.js — edit-pipeline вызывает showPipelineModal вместо showPipelineEditModal

### Аудит (цепочка проверки)

**arch.md / инвариант:** Pipeline редактируется через `PipelineBuilder.openEdit`, который принимает существующий объект pipeline.

**tab-pipelines.js (mixin):**
- `showPipelineModal()` — без аргументов → `PipelineBuilder.openCreate` (создание нового)
- `showPipelineEditModal(pipelineId)` — принимает UUID → ищет pipeline в списке → `PipelineBuilder.openEdit`

**settings.js → `handlePipelinesAction`:**
- `new-pipeline` → `this.showPipelineModal()` ✅ корректно
- `edit-pipeline` → раньше `this.showPipelineModal(id)` 🔴 — открывало форму создания вместо редактирования

### Таблица багов

| ID | Файл | Проблема | Исправление | Статус |
|---|---|---|---|---|
| C21-A | `settings.js` | `edit-pipeline` → `this.showPipelineModal(id)` → открывает форму создания вместо редактирования | `this.showPipelineEditModal(id)` | ✅ |

**Закрыто в коммите C21.**

---

## C22 · settings.js + api.js — DOMContentLoaded wrong ids (S22) + textSearchByDomain missing (D7)

### Аудит

**S22 — settings.js DOMContentLoaded:**  
`DOMContentLoaded` обращался к 4 несуществующим идентификаторам → все `getElementById` возвращали `null` → обработчики кнопок «Настройки» и «Назад» не цеплялись → страница настроек не открывалась.

**D7 — api.js textSearchByDomain:**  
`db_management.js` вызывал `chatAPI.textSearchByDomain(domainId, query, limit)`, которого не было в классе `ChatAPI` → `TypeError: chatAPI.textSearchByDomain is not a function` при поиске по домену.

### Таблица багов

| ID | Файл | Проблема | Исправление | Статус |
|---|---|---|---|---|
| S22 | `settings.js` | `getElementById('open-settings-btn')` → `null`; `getElementById('settings-back-btn')` → `null`; `getElementById('main-app')` → `null`; `getElementById('settings-tab-nav')` → `null` | `#settings-btn`, `#back-to-chat-btn`, `querySelector('.app-container')`, `querySelector('.settings-tabs')` | ✅ |
| D7 | `api.js` | `textSearchByDomain` отсутствовал → `TypeError` в `db_management.js` | Добавлен метод: `POST /api/db/search/domain` `{domain_id, query_text, limit}` → `TextSearchResponse` | ✅ |

**Закрыто в коммите C22 (два коммита: fix: S22, fix: D7).**

---

## C23 · S44 — POST /api/settings/documents/labels/batch

### Аудит (цепочка проверки)

**Бэк (`app/api/settings/documents.py`):**
- Роут существует: `POST /documents/labels/batch`, `status_code=204`
- Принимает `payload: dict` → `document_ids: list[str]`, `tag_ids: list[str]`
- Семантика: **additive** (добавляет теги, не заменяет существующие), пропускает дубликаты через IntegrityError
- Возвращает **204 No Content**

**CONTRACTS.md:**
- `S44 | POST | /api/settings/documents/labels/batch | {document_ids, tag_ids} | 204` ✅

**api.js:**
- Метод `batchLabelDocuments` добавлен: `POST /api/settings/documents/labels/batch`, body `{document_ids, tag_ids}`, 204-safe → ✅ S44-A

**tab-documents.js:**
- Batch-операция не реализована в UI — нет multi-select и вызова бэкенда → ⚠️ S44-B (отсутствующая фича, не сломанная)

### Таблица багов

| ID | Файл | Проблема | Исправление | Статус |
|---|---|---|---|---|
| S44-A | `api.js` | Метод `batchLabelDocuments(documentIds, tagIds)` отсутствовал | Добавлен: `POST /api/settings/documents/labels/batch`, body `{document_ids, tag_ids}`, 204-safe | ✅ |
| S44-B | `tab-documents.js` | Нет UI для multi-select и batch-назначения тегов | Отдельная задача (фича) | ⚠️ фича / backlog |

---

## C24 · S40–S42 — settings documents layer: фильтр по тегу сломан, методы api.js отсутствуют

### Аудит (цепочка проверки)

**Бэк (`app/api/settings/documents.py` → `GET /api/settings/documents`):**
- Принимает: `vault_id?`, `domain_id?`, `status?`, `tag_id?`
- `domain_id` **или** `vault_id` обязателен — иначе **HTTP 400**
- `status` и `tag_id` — опциональные серверные фильтры

**CONTRACTS.md:**
- `S40 | GET | /api/settings/documents | query: vault_id?, domain_id?, status?, tag_id? | DocumentRead[]`
- `S41 | GET | /api/settings/documents/{document_id} | — | DocumentRead`
- `S42 | DELETE | /api/settings/documents/{document_id} | — | 204`

**api.js — методы S40–S42:**
- `getSettingsDocuments(params)` → **отсутствует** 🔴
- `getSettingsDocument(documentId)` → **отсутствует** ⚠️ (не вызывается фронтом)
- `deleteSettingsDocument(documentId)` → **отсутствует** ⚠️ (фронт использует DB-слой `deleteDocumentById`)

**tab-documents.js → `loadDocumentsData`:**
- Вызывает `this.api.getDocumentsByVault(vaultId)` — DB-слой, без серверных фильтров
- Фильтр по статусу (`_docsFilterStatus`) → **клиентский** `docs.filter(...)` — работает, но неэффективно ⚠️
- Фильтр по тегу (`_docsFilterTagId`) → `sel.onchange` устанавливает `this._docsFilterTagId`, затем вызывает `loadDocumentsData()`, но `loadDocumentsData` **нигде не передаёт** `_docsFilterTagId` в запрос → **фильтр по тегу полностью не работает** 🔴

### Таблица багов

| ID | Файл | Проблема | Исправление | Статус |
|---|---|---|---|---|
| S40-B | `api.js` | `getSettingsDocuments(params)` отсутствует — нет метода для `GET /api/settings/documents` с фильтрами | Добавить метод; поддерживает `{vaultId?, domainId?, status?, tagId?}` | ✅ |
| S40-A | `tab-documents.js` | `_docsFilterTagId` устанавливается но не передаётся в запрос → фильтр по тегу не работает | `loadDocumentsData` переключить на `getSettingsDocuments` с передачей `status` и `tagId` серверно | ✅ |
| S41-A | `api.js` | `getSettingsDocument(documentId)` отсутствует | Добавить: `GET /api/settings/documents/{id}` → `DocumentRead` | ✅ |
| S42-A | `api.js` / `tab-documents.js` | Удаление через DB-слой (`/api/db/documents/{id}?vault_id=`) вместо settings-слоя (`/api/settings/documents/{id}`, 204) | Контрактное расхождение; функционально равнозначно | ⚠️ |

---

## C25 · Chat C1–C9 + Config CF1–CF2 — аудит и фиксы

### Цепочка проверки

`arch.md §chat` → `models/chat.py` → pydantic-схемы → `app/api/chat.py` → `CONTRACTS.md C1–C9, CF1–CF2` → `api.js` + `chat.js` + `sidebar.js`

### Верифицированы (OK)

| ID | Эндпоинт | Файл | Статус |
|---|---|---|---|
| C1 | `POST /chat/create` | `api.js` + `sidebar.js` | ⬜ `domain_id` + `campaign_id` передаются корректно; `null` вместо `""` |
| C2 | `GET /chat/list?domain_id=` | `api.js` + `sidebar.js` | ⬜ query-param передаётся; ответ `{chats:[]}` парсится |
| C3 | `GET /chat/{id}/history` | `api.js` + `chat.js` | ⬜ URL верный; `data.chat` + `data.messages` читаются |
| C4 | `POST /chat/{id}/rename` | `api.js` + `sidebar.js` | ⬜ body `{title}` совпадает с `RenameChatRequest` |
| C5 | `DELETE /chat/{id}` | `api.js` | ⬜ 204-safe, нет `.json()` |
| C6 | `POST /chat/{id}/lock_pipeline` | `api.js` + `chat.js` | ⬜ body `{pipeline_id}`; `togglePipelineLock()` реализован |
| C7 | `POST /chat/{id}/send` | `api.js` | ⬜ body `{content}` корректно |
| CF1 | `GET /config/domains` | `api.js` + `sidebar.js` | ⬜ оба формата ответа поддержаны |

### Таблица багов

| ID | Файл | Проблема | Приоритет | Статус |
|---|---|---|---|---|
| C25-A | `api.js` | `sendMessage` не передавал `stream: true` в body → расхождение с `SendMessageRequest` | 🔴 | ✅ исправлен |
| C25-B | `chat.js` | `setupContextBar` читает `chat.locked_pipeline_id` — null-safe guard добавлен | ⚠️ | ✅ исправлен |
| C25-C | `chat.js` | SSE-поток: при `type === 'clarification'` `clarification_id` не сохранялся | 🔴 | ✅ исправлен |
| C25-D | `api.js` | `getConfigVaults` (`GET /config/vaults`) отсутствует — фронт не вызывает сейчас | ⚠️ | ⚠️ backlog |

**Закрыто в коммите C25.**

---

## C26 · M01–M04 — documents.id, tags.id, document_labels: VARCHAR(36) → UUID

### Аудит (цепочка проверки)

**Источник:** анализ миграций 0010→0012 + ORM `models.py`

**Проблема:** Миграции 0010–0011 создали несколько колонок как `VARCHAR(36)` вместо нативного PostgreSQL UUID. Миграция 0012 исправила только `tags.campaign_id`, оставив нетронутыми:
- `tags.id` — создан в 0010 как `String(36)`, так и остался
- `documents.id` — пересоздан в 0011 как `String(36)` (server_default `gen_random_uuid()::text`)
- `document_labels.document_id` — создан в 0011 как `String(36)`
- `document_labels.tag_id` — создан в 0011 как `String(36)`

**Эффект:** ORM объявляет все четыре колонки как `UUID(as_uuid=True)`. PostgreSQL возвращает ошибку `operator does not exist: character varying = uuid` при любом ORM-запросе с фильтром или JOIN по этим полям — идентична ошибке из `tags.campaign_id` (исправленной в 0012).

**Ошибочная запись в предыдущем аудите:** таблица итогов помечала `tags.id` как «✅ исправлено в 0012» — это неверно; 0012 трогал только `tags.campaign_id`.

### Таблица багов

| ID | Таблица | Колонка | Тип в БД (после 0011) | Тип ORM | Статус |
|---|---|---|---|---|---|
| M01 | `documents` | `id` | `VARCHAR(36)` | `UUID(as_uuid=True)` | ✅ исправлен в 0013 |
| M02 | `document_labels` | `document_id` | `VARCHAR(36)` | `UUID(as_uuid=True)` | ✅ исправлен в 0013 |
| M03 | `document_labels` | `tag_id` | `VARCHAR(36)` | `UUID(as_uuid=True)` | ✅ исправлен в 0013 |
| M04 | `tags` | `id` | `VARCHAR(36)` | `UUID(as_uuid=True)` | ✅ исправлен в 0013 |

### Стратегия фикса (0013)

1. DROP TABLE `document_labels` (зависит от обоих FK)
2. ALTER `tags.id` VARCHAR → UUID + пересоздать FK из `campaign_tags.tag_id`
3. ALTER `documents.id` VARCHAR → UUID
4. CREATE TABLE `document_labels` с UUID-типами
5. Восстановить constraint `uq_tag_name_domain` если потерян

Все шаги idempotent — проверка текущего типа перед ALTER.

**Закрыто в коммите [24fc654](https://github.com/Annener/mercer/commit/24fc65449b314efe3cb3d16337040c39a6e52efb).**

---

## C27 · F01–F03 + B01 — deleteDocument, createPipeline, is_final UX, backend errors

### Аудит (цепочка проверки)

`arch.md §documents §pipeline` → `models.py` → pydantic-схемы → роуты → `CONTRACTS.md` → `api.js` → `tab-documents.js` / `pipeline_builder.js`

---

### F01 · tab-documents.js — `deleteDocument is not a function`

**Файл:** `tab-documents.js`, метод `handleDocumentsAction`, ветка `delete-doc`  
**Симптом:** `Ошибка удаления: this.api.deleteDocument is not a function`  
**Причина:** `handleDocumentsAction` вызывает `this.api.deleteDocument(docId, vaultId)`, которого **никогда не существовало** в `api.js`. Корректный метод — `deleteDocumentById(documentId, vaultId)` (добавлен в D2, коммит C19).

```js
// tab-documents.js:254 — было:
await this.api.deleteDocument(docId, vaultId || null);

// должно быть:
await this.api.deleteDocumentById(docId, vaultId || null);
```

| ID | Файл | Строка | Проблема | Исправление | Статус |
|---|---|---|---|---|---|
| F01 | `tab-documents.js` | `handleDocumentsAction` / `delete-doc` | `this.api.deleteDocument` → `TypeError: not a function` | Переименовать в `this.api.deleteDocumentById` | 🔴 |

---

### F02 · api.js — `createPipeline` и `updatePipeline` отсутствуют

**Файл:** `api.js`, `pipeline_builder.js` → `_save()`  
**Симптом:** `Ошибка сохранения: _api.createPipeline is not a function`  
**Причина:** `pipeline_builder.js._save()` вызывает `_api.createPipeline(payload)` и `_api.updatePipeline(_pipeline.id, payload)`. В `api.js` существуют только `getPipelines`, `activatePipeline`, `deactivatePipeline`, `deletePipeline` — методы **создания и обновления отсутствуют**.

**Контракт (CONTRACTS.md):**
- `P-CREATE | POST | /api/settings/pipelines | PipelineCreate | PipelineRead`
- `P-UPDATE | PUT  | /api/settings/pipelines/{pipeline_id} | PipelineUpdate | PipelineRead`

**Дополнительный риск:** в `_save()` при обновлении используется `_pipeline.id` как идентификатор в URL. По arch.md pipeline идентифицируется строковым `pipeline_id` (не UUID). Необходимо проверить, что бэк возвращает поле `id` (UUID) или `pipeline_id` (string) и что `_pipeline.id` → `_pipeline.pipeline_id` при необходимости.

```js
// Добавить в api.js (секция Pipelines):

async createPipeline(data) {
    const response = await fetch(`${this.baseUrl}/api/settings/pipelines`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`Failed to create pipeline: ${response.statusText}`);
    return response.json();
}

async updatePipeline(pipelineId, data) {
    const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${encodeURIComponent(pipelineId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`Failed to update pipeline: ${response.statusText}`);
    return response.json();
}
```

| ID | Файл | Проблема | Исправление | Статус |
|---|---|---|---|---|
| F02-A | `api.js` | `createPipeline` отсутствует | Добавить: `POST /api/settings/pipelines` | 🔴 |
| F02-B | `api.js` | `updatePipeline` отсутствует | Добавить: `PUT /api/settings/pipelines/{id}` | 🔴 |
| F02-C | `pipeline_builder.js` | `_save()` использует `_pipeline.id` — нужно уточнить `id` vs `pipeline_id` | Проверить контракт бэка; при необходимости заменить на `_pipeline.pipeline_id` | ⚠️ |

---

### F03 · pipeline_builder.js — чекбокс `is_final` в UI нарушает архитектурный инвариант

**Файл:** `pipeline_builder.js`, `_stepHTML()`, `_bindStepEvents()`  
**Проблема:** По архитектуре `is_final` — **служебный атрибут шага**, который должен автоматически ставиться у шага типа `final`. Текущий UI показывает явный чекбокс `is_final` для каждого шага и требует от пользователя вручную его проставить — иначе `_save()` возвращает ошибку «Отметьте ровно один шаг как is_final». Это одновременно UX-антипаттерн и потенциальный источник состояния «0 is_final» или «2+ is_final», которые бэк отвергнет с 422.

**Правильное поведение:**
- Убрать чекбокс `is_final` из `_stepHTML()` полностью
- При смене `type` шага на `'final'` — автоматически ставить `is_final: true` этому шагу и снимать у всех остальных
- При смене с `'final'` на другой тип — снимать `is_final`
- Валидацию «ровно один is_final» в `_save()` оставить как guard (на случай программных ошибок), но убрать из пользовательских сообщений
- Финальный шаг (`type='final'`) при добавлении должен автоматически скрывать секцию `tag_ids`

| ID | Файл | Проблема | Исправление | Статус |
|---|---|---|---|---|
| F03-A | `pipeline_builder.js` | Чекбокс `is_final` в UI — пользователь должен проставлять вручную | Убрать чекбокс; автоставить `is_final` при `type=final` | ⚠️ |
| F03-B | `pipeline_builder.js` | `_bindStepEvents`: смена `type` на `final` не снимает `is_final` у других шагов | При `type=final` → `_steps.forEach(s => s.is_final = false)` до установки текущего | ⚠️ |

---

### B01 · Backend errors — generation 500 + embedding empty vector

**Область:** бэкенд, фронт не причём.

#### B01-A · Generation HTTP 500 — `'str' object has no attribute 'get'`

**Лог:**
```
WARNING app.providers.generation.openai_compatible — Generation request failed on attempt 1:
HTTP 500 — body: {"error":{"message":"APIConnectionError: OpenrouterException -
'str' object has no attribute 'get'. Received Model Group=openrouter/deepseek/deepseek-chat-v3.1"}}
```
**Причина:** В `app/providers/generation/openai_compatible.py` при обработке ответа от OpenRouter ожидается `dict` (вызывается `.get()`), но приходит `str`. Вероятно, ответ от OpenRouter не десериализуется перед обращением по ключу — либо в маппинге `model_group`, либо в `_parse_response`. Требует аудита бэкенда провайдера.

#### B01-B · Embedding empty vector — `dengcao/Qwen3-Embedding-4B:Q4_K_M`

**Лог:**
```
ValueError: Embedding provider returned empty vector for chunk 3
(file='dm-guides/Впечатляющие столицы.pdf', model='dengcao/Qwen3-Embedding-4B:Q4_K_M').
Check model availability, dimension settings, and provider logs.
```
**Причина:** Две возможные причины:
1. Модель недоступна или не загружена в провайдере (ollama/lm-studio) — проверить `GET /api/settings/models/embedding/{id}/check`
2. Chunk 3 пустой или whitespace-only после парсинга PDF — guard на пустые чанки до обращения к эмбеддеру

| ID | Файл | Проблема | Приоритет | Статус |
|---|---|---|---|---|
| B01-A | `app/providers/generation/openai_compatible.py` | `'str' object has no attribute 'get'` при маппинге ответа OpenRouter | 🔴 бэк | 🔴 не исправлен |
| B01-B | `indexer_worker.py` | Пустой вектор от embedding-модели; возможна недоступность модели или whitespace-чанки | ⚠️ бэк | ⚠️ требует диагностики |

---

## C28 · M19 — messages.pipeline_id: UUID в БД vs String(64) в ORM

### Аудит (цепочка проверки)

**Трейс ошибки:**
```
asyncpg.exceptions.DatatypeMismatchError: column "pipeline_id" is of type uuid
but expression is of type character varying
[SQL: INSERT INTO messages (..., pipeline_id) VALUES (..., $5::VARCHAR)]
```

**Источник расхождения — два слоя:**

| Слой | Объявление | Тип |
|---|---|---|
| Миграция 0004 (`0004_add_pipeline_id_to_messages.py`) | `postgresql.UUID(as_uuid=True)` | **UUID** в БД |
| ORM `Message.pipeline_id` (`models.py`) | `String(64)` | **VARCHAR(64)** → SQLAlchemy биндит `$5::VARCHAR` |

**Цепочка:** миграция 0004 добавила колонку как `UUID`, но `models.py` объявляет `pipeline_id: Mapped[str | None] = mapped_column(String(64), nullable=True)`. При `INSERT INTO messages` SQLAlchemy генерирует `$5::VARCHAR` — PostgreSQL отвергает c `DatatypeMismatchError`.

**Семантика `pipeline_id`:**  
По arch.md `Message.pipeline_id` хранит строковый slug пайплайна (например `"default"`, `"dnd"`), **не UUID**. Миграция 0004 создала колонку с неверным типом — нужно привести тип БД к `VARCHAR(64)`, а не наоборот менять ORM.

> Важно: `pipeline_id` в таблице `messages` — это **pipeline_id (String slug)**, не `Pipeline.id (UUID)`. Это поле без FK. ORM-объявление `String(64)` — правильное. Исправлять нужно **БД**, не ORM.

### Таблица багов

| ID | Таблица | Колонка | Тип в БД (0004) | Тип ORM | Нужно | Статус |
|---|---|---|---|---|---|---|
| M19 | `messages` | `pipeline_id` | `UUID` | `String(64)` | `VARCHAR(64)` (миграция 0015) | 🔴 |

### Стратегия фикса (0015)

Идемпотентный ALTER: если `pipeline_id` имеет тип `uuid` — преобразовать в `VARCHAR(64)` (существующие значения `NULL`, потерь нет).

```python
def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(sa.text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'messages' AND column_name = 'pipeline_id'"
    )).fetchone()
    if row and row[0].lower() == 'uuid':
        conn.execute(sa.text(
            "ALTER TABLE messages ALTER COLUMN pipeline_id TYPE VARCHAR(64) USING pipeline_id::text"
        ))
```

---

## Changelog

| Дата | Баги | Файлы | Описание | Коммит |
|---|---|---|---|---|
| 2026-06-01 | D03+D04 | `app/api/settings/campaigns.py` | N+1 → batch IN(); `payload: dict` → `CampaignTagCreateRequest` | [596f4af](https://github.com/Annener/mercer/commit/596f4af71d7a69bd1f0caa7c62e1dcb5d6288737) |
| 2026-06-01 | D08+D09+D10 | `app/static/js/api.js` | null-safe getCampaigns; 8 campaign/tag методов; deleteChat/deleteCampaign/deleteTag — 204 no-json | [581e5c1](https://github.com/Annener/mercer/commit/581e5c171f1fa6d28e6fe05deeeee0893d6816fa) |
| 2026-06-01 | S1-A..S13-A | `app/static/js/api.js`, `settings.js`, `tab-domains.js`, `tab-params.js` | Settings group S1–S13: все методы api.js добавлены; handleParamsAction / handleDomainsAction реализованы; showPromptsModal / showFieldsModal добавлены | — |
| 2026-06-01 | S14-A..S16-A | `app/static/js/settings.js` | handleVaultsAction / handleGenModelsAction / handleEmbModelsAction реализованы | — |
| 2026-06-01 | S17-B, S18-B, S19-A | `app/static/js/api.js`, `app/static/js/settings.js`, `app/api/settings/emb_models.py` | toggleVault добавлен в api.js; setActiveGenerationModel исправлен на /activate; setActiveEmbeddingModel удалён | — |
| 2026-06-01 | S14-B, S15-B, S16-B | `app/static/js/settings.js`, `app/static/js/settings/tab-gen-models.js` | showGenerationModelModal / showEmbeddingModelModal; toggle-gen кнопка | C17 |
| 2026-06-01 | D1–D5 | `app/static/js/api.js`, `app/static/js/settings/tab-documents.js` | 6 неверных путей db-management; vault_id-aware delete | C19 |
| 2026-06-01 | S16-C, S16-D, S21-B | `app/api/settings/gen_models.py`, `app/static/js/settings.js` | toggle роут добавлен в бэк; check-gen/check-emb алерт исправлен на result.ok | C20 |
| 2026-06-01 | C21-A | `app/static/js/settings.js` | edit-pipeline: showPipelineModal(id) → showPipelineEditModal(id) | C21 |
| 2026-06-01 | D6 | — | Верификация: роут PUT /api/settings/documents/{id}/labels уже реализован в бэке; фронт корректен; статус ⚠️ → ✅ | — |
| 2026-06-01 | S22, D7 | `app/static/js/settings.js`, `app/static/js/api.js` | S22: DOMContentLoaded исправлены 4 несуществующих id; D7: добавлен метод textSearchByDomain | C22 |
| 2026-06-01 | S44-A | `app/static/js/api.js` | Аудит S44: batchLabelDocuments отсутствовал → добавлен метод; S44-B: batch UI → ⚠️ backlog | C23 |
| 2026-06-01 | S40-A, S40-B, S41-A, S42-A | `app/static/js/api.js`, `app/static/js/settings/tab-documents.js` | Аудит C24: фильтр по тегу сломан; getSettingsDocuments/getSettingsDocument отсутствуют | C24 |
| 2026-06-01 | C25-A, C25-B, C25-C | `app/static/js/api.js`, `app/static/js/chat.js` | C25-A: stream:true добавлен в sendMessage; C25-B: locked_pipeline_id null-safe; C25-C: clarification_id сохраняется в SSE | C25 |
| 2026-06-01 | M01, M02, M03, M04 | `rag-backend/migrations/versions/0013_fix_documents_tags_uuid.py` | documents.id + tags.id + document_labels.*_id: VARCHAR(36) → UUID; idempotent; campaign_tags FK пересоздан | [24fc654](https://github.com/Annener/mercer/commit/24fc65449b314efe3cb3d16337040c39a6e52efb) |
| 2026-06-01 | F01, F02-A, F02-B, F02-C, F03-A, F03-B, B01-A, B01-B | `tab-documents.js`, `api.js`, `pipeline_builder.js`, `openai_compatible.py`, `indexer_worker.py` | Аудит C27: deleteDocument typo; createPipeline/updatePipeline отсутствуют; is_final UX нарушение; backend generation/embedding ошибки | — |
| 2026-06-02 | M19 | `rag-backend/migrations/versions/0015_fix_messages_pipeline_id_type.py` | messages.pipeline_id: UUID → VARCHAR(64); ORM объявляет String(64), миграция 0004 создала UUID ошибочно | — |
