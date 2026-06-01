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
| S14-S19 | generation models CRUD | `tab-gen-models.js` | ✅ | C16 аудит ⬜; C17: S14-B ✅ showGenerationModelModal; S16-B ✅ toggle-gen кнопка добавлена |
| S20-S24 | embedding models CRUD | `tab-emb-models.js` | ✅ | C16 аудит ⬜; C17: S15-B ✅ showEmbeddingModelModal |
| S25-S29 | vaults CRUD | `tab-vaults.js` | ✅ | C16: S36-new ✅; handleVaultsAction ✅; deleteVault 204-safe ✅ |
| S30-S35 | pipelines CRUD | `tab-pipelines.js` | ✅ | C16: pipeline.id=UUID ✅; activate/deactivate/delete 204-safe ✅ |
| S36-S39 | tags CRUD | `api.js`, `tab-campaigns.js` | ✅ | D09 (getTags/deleteTag в api.js); tags.py корректен |
| S40-S44 | documents CRUD | `tab-documents.js` | ✅ | C16: deleteDocumentById 204-safe ✅; reindexVault/connectToTaskStream ✅ |
| S45-S51 | campaigns CRUD | `api.js`, `tab-campaigns.js`, `sidebar.js` | ✅ | D03, D04, D08, D09, D10, D14 |

---

## DB Management группа

| ID | Группа | Файл | Статус | Примечания |
|---|---|---|---|---|
| D1-D9 | db-management | — | 🔴 | Не аудировано |

---

## Следующая задача

- [ ] D1–D9: db-management group — начать аудит по паттерну