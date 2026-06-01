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
| S20-S24 | embedding models CRUD | `tab-emb-models.js` | ✅ | C17: showEmbeddingModelModal ✅; C20: check-emb result.ok ✅ |
| S25-S29 | vaults CRUD | `tab-vaults.js` | ✅ | S36-new ✅; handleVaultsAction ✅; deleteVault 204-safe ✅ |
| S30-S35 | pipelines CRUD | `tab-pipelines.js` | ✅ | pipeline.id=UUID ✅; activate/deactivate/delete 204-safe ✅ |
| S36-S39 | tags CRUD | `api.js`, `tab-campaigns.js` | ✅ | D09 (getTags/deleteTag в api.js); tags.py корректен |
| S40-S44 | documents CRUD | `tab-documents.js` | ✅ | C19: D1–D5 ✅ пути исправлены; vault_id-aware delete ✅ |
| S45-S51 | campaigns CRUD | `api.js`, `tab-campaigns.js`, `sidebar.js` | ✅ | D03, D04, D08, D09, D10, D14 |

---

## DB Management группа

| ID | Группа | Файл | Статус | Примечания |
|---|---|---|---|---|
| D1-D5 | db-management paths | `api.js`, `tab-documents.js` | ✅ | C18 аудит; C19: 5 путей исправлены |
| D6 | updateDocumentLabels | `api.js` | ⚠️ | Роут `/api/db/documents/{id}/labels` отсутствует в бэке — требует отдельного решения |
| D7-D9 | db-management прочее | — | ⬜ | /api/db/chunks, /api/db/search/text, /api/db/search/domain — фронт не использует напрямую |

---

## Следующая задача

- [ ] D6: добавить роут `PUT /api/db/documents/{document_id}/labels` в бэке — обсудить с командой
- [ ] Финальный smoke-test: поднять dev-окружение, пройтись по всем вкладкам settings
