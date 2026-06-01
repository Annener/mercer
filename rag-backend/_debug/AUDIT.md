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
|---|---|---|---|
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
| S14-B | `settings.js` | `showGenModelModal()` → метода нет; должно быть `showGenerationModelModal()` | 🔴 → C17 |
| S15-B | `settings.js` | `showEmbModelModal()` → метода нет; должно быть `showEmbeddingModelModal()` | 🔴 → C17 |
| S16-B | `tab-gen-models.js` | Кнопка `toggle-gen` отсутствует в `renderModelList` для `kind='gen'` | 🔴 → C17 |
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

## Changelog

| Дата | Баги | Файлы | Описание | Коммит |
|---|---|---|---|---|
| 2026-06-01 | D03+D04 | `app/api/settings/campaigns.py` | N+1 → batch IN(); `payload: dict` → `CampaignTagCreateRequest` | [596f4af](https://github.com/Annener/mercer/commit/596f4af71d7a69bd1f0caa7c62e1dcb5d6288737) |
| 2026-06-01 | D08+D09+D10 | `app/static/js/api.js` | null-safe getCampaigns; 8 campaign/tag методов; deleteChat/deleteCampaign/deleteTag — 204 no-json | [581e5c1](https://github.com/Annener/mercer/commit/581e5c171f1fa6d28e6fe05deeeee0893d6816fa) |
| 2026-06-01 | S1-A..S13-A | `app/static/js/api.js`, `settings.js`, `tab-domains.js`, `tab-params.js` | Settings group S1–S13: все методы api.js добавлены; handleParamsAction / handleDomainsAction реализованы; showPromptsModal / showFieldsModal добавлены | — |
| 2026-06-01 | S14-A..S16-A | `app/static/js/settings.js` | handleVaultsAction / handleGenModelsAction / handleEmbModelsAction реализованы | — |
| 2026-06-01 | S17-B, S18-B, S19-A | `app/static/js/api.js`, `app/static/js/settings.js`, `app/api/settings/emb_models.py` | toggleVault добавлен в api.js; setActiveGenerationModel исправлен на /activate; setActiveEmbeddingModel удалён | — |
| 2026-06-01 | S14-B, S15-B, S16-B | `app/static/js/settings.js`, `app/static/js/settings/tab-gen-models.js` | showGenerationModelModal / showEmbeddingModelModal; toggle-gen кнопка | C17 |