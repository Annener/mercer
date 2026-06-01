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
| D6 | `updateDocumentLabels(docId, tagIds)` | `PUT /api/settings/documents/{id}/labels` | **Роута нет в бэке** | TODO: добавить роут в settings/documents.py или db_management.py | ⚠️ |

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

**D6 (updateDocumentLabels) — роут отсутствует в бэке, помечен ⚠️, требует отдельного решения.**

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
