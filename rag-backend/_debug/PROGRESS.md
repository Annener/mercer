# Progress — Bug Fix Tracker

> Статусы: 🔴 не проверен | 🟡 в работе | ✅ проверен и исправлен | ⬜ проверен, OK (без правок) | ⚪ не затронут фронтом

---

## Settings группа

| ID | Группа | Файл | Статус | Примечания |
|---|---|---|---|---|
| S1 | settings status | `api.js` | ✅ | getSettingsStatus добавлен |
| S2-S4 | params | `tab-params.js`, `api.js` | ✅ | handleParamsAction реализован; S2-D (boolKeys — оба ключа реальны) |
| S5-S9 | domains CRUD | `tab-domains.js`, `api.js` | ✅ | S5-A..S5-C, domains CRUD |
| S10-S11 | prompts | `tab-domains.js` | ✅ | showPromptsModal |
| S12-S13 | fields | `tab-domains.js` | ✅ | showFieldsModal |
| S14-S19 | generation models CRUD | `tab-gen-models.js`, `gen_models.py` | ✅ | C17: имена ✅; C20: toggle роут ✅; check-gen result.ok ✅ |
| S20-S24 | embedding models CRUD | `tab-emb-models.js` | ✅ | C17: showEmbeddingModelModal ✅; C20: check-emb result.ok ✅; activate-emb не рендерится — по инварианту корректно |
| S25-S29 | vaults CRUD | `tab-vaults.js` | ✅ | S36-new ✅; handleVaultsAction ✅; deleteVault 204-safe ✅ |
| S30-S35 | pipelines CRUD | `tab-pipelines.js`, `settings.js` | ✅ | pipeline.id=UUID ✅; activate/deactivate/delete 204-safe ✅; C21: edit-pipeline → showPipelineEditModal ✅ |
| S36-S39 | tags CRUD | `api.js`, `tab-campaigns.js` | ✅ | D09 (getTags/deleteTag в api.js); tags.py корректен |
| S40-S44 | documents CRUD | `tab-documents.js`, `api.js` | ✅ | C19: D1–D5 ✅ пути исправлены; C23: S44-A ✅ batchLabelDocuments добавлен; **C24**: S40-A ✅ loadDocumentsData → getSettingsDocuments; S40-B ✅ getSettingsDocuments в api.js; S41-A ✅ getSettingsDocument в api.js; S42-A ⚠️ контрактное расхождение DB vs settings DELETE — функционально равнозначно; S44-B ⚠️ batch UI → backlog |
| S45-S51 | campaigns CRUD | `api.js`, `tab-campaigns.js`, `sidebar.js` | ✅ | D03, D04, D08, D09, D10, D14 |
| S22 | DOMContentLoaded ids | `settings.js` | ✅ | 4 несуществующих id → реальные; C22 |

---

## DB Management группа

| ID | Группа | файл | Статус | Примечания |
|---|---|---|---|---|
| D1-D5 | db-management paths | `api.js`, `tab-documents.js` | ✅ | C18 аудит; C19: 5 путей исправлены |
| D6 | updateDocumentLabels | `api.js` | ✅ | Роут `PUT /api/settings/documents/{id}/labels` есть в `settings/documents.py`; фронт совпадает — верифицирован |
| D7 | textSearchByDomain | `api.js` | ✅ | Метод добавлен: `POST /api/db/search/domain`; C22 |
| D8-D9 | search/text + chunks | `api.js` | ⬜ | `/api/db/chunks`, `/api/db/search/text` — фронт не использует напрямую |

---

## Chat группа

| ID | Группа | Файл | Статус | Примечания |
|---|---|---|---|---|
| C1-C9 | chat CRUD + send + stream | `api.js`, `chat.js`, `sidebar.js` | ✅ | **C25**: C1–C9 + CF1–CF2 проверены; C25-A ✅ stream:true в sendMessage; C25-B ✅ locked_pipeline_id null-safe; C25-C ✅ clarification_id сохраняется при SSE; C25-D ⚠️ getConfigVaults → backlog |

## Config группа

| ID | Группа | Файл | Статус | Примечания |
|---|---|---|---|---|
| CF1-CF2 | config domains + vaults | `api.js`, `sidebar.js`, `chat.js` | ✅ | **C25**: CF1 ✅ getDomains корректен; CF2 ⚠️ getConfigVaults отсутствует → backlog |

---

## Следующая задача

- [ ] **Финальный smoke-test**: поднять dev-окружение, пройтись по всем вкладкам settings и chat
- [ ] S44-B: batch-выбор документов в UI (`tab-documents.js`) — backlog, отдельная задача
- [ ] C25-D: `getConfigVaults` (`GET /config/vaults`) — backlog, фронт не вызывает сейчас
