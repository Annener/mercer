# Progress — Bug Fix Tracker

> Статусы: 🔴 не проверен | 🟡 в работе | ✅ проверен и исправлен | ⬜ проверен, OK (без правок) | ⚪ не затронут фронтом

---

## Группа: chat

| ID | Эндпоинт | Фронт-файл | Статус | Комментарий |
|---|---|---|---|---|
| C1 | POST `/chat/create` | `sidebar.js` | ✅ | A01 (domain_id NOT NULL), A02 (pipeline_versions), A03 (locked_pipeline_id), A04 (_audit payload→details), A05 (domain_id required) — всё закрыто |
| C2 | GET `/chat/list` | `sidebar.js` | ✅ | B01 — N+1 vault_enabled убран, кэш за один SELECT |
| C3 | GET `/chat/{id}/history` | `api.js`, `chat.js` | ✅ | B02 — `world_id` → `domain_id` в setupContextBar |
| C4 | POST `/chat/{id}/rename` | `api.js`, `sidebar.js` | ⬜ | Всё верно |
| C5 | DELETE `/chat/{id}` | `api.js`, `sidebar.js` | ⬜ | Всё верно |
| C6 | POST `/chat/{id}/lock_pipeline` | `api.js`, `chat.js` | ⬜ | Всё верно |
| C7 | POST `/chat/{id}/send` | `api.js`, `chat.js` | ⬜ | `{content}` — верно; поле `stream` не нужно (роутинг по URL) |
| C8 | POST `/chat/{id}/send_stream` | `api.js`, `chat.js` | ✅ | B05 (мёртвая ветка token), B06 (мёртвая переменная assistant_msg_id) — удалены |
| C9 | POST `/chat/{id}/clarify` | `api.js`, `chat.js` | ✅ | B07 (clarification check), B08 (submitClarification), C01 (clarification_id в body), C02 (handleJSONResponse) — всё закрыто |

## Группа: config

| ID | Эндпоинт | Фронт-файл | Статус | Комментарий |
|---|---|---|---|---|
| CF1 | GET `/config/domains` | `api.js`, `sidebar.js` | ✅ | `getDomains()` → `/config/domains` ✓; `DomainsResponse.domains` ✓; парсинг обоих форматов (массив/объект) ✓ |
| CF2 | GET `/config/vaults` | `api.js`, `sidebar.js` | ⬜ | `getVaults()` не вызывается из UI — gap, не баг. CF2-W: нет empty-state в loadDomains при ошибке |

## Группа: settings

| ID | Эндпоинт | Фронт-файл | Статус | Комментарий |
|---|---|---|---|---|
| S1 | GET `/api/settings/status` | `settings.js` | ✅ | S1-A добавлен getSettingsStatus(); renderStatusTab реализован |
| S2-S4 | params CRUD | `tab-params.js` | ✅ | S2-A..S4-A api.js; S2-B handleParamsAction; S2-C bool checkbox; S2-D — оба ключа реальны, комментарий добавлен |
| S5-S9 | domains CRUD | `tab-domains.js` | ✅ | S5-A (getDomains→getSettingsDomains), S5-B (4 метода api.js), S5-C (handleDomainsAction) |
| S10-S11 | domain prompts | `tab-domains.js` | ✅ | S10-A (getDomainPrompts/updateDomainPrompt), S11-A (showPromptsModal) |
| S12-S13 | domain fields (clarification) | `tab-domains.js` | ✅ | S12-A (getDomainFields/updateDomainFields), S13-A (showFieldsModal) |
| S14-S19 | generation models CRUD | `tab-gen-models.js` | 🟡 | C16: S14-B 🔴 (showGenModelModal→showGenerationModelModal), S16-B 🔴 (checkGenerationModel отсутствует в api.js). S15-A ✅ handleGenModelsAction реализован. Фикс в следующем коммите |
| S20-S24 | embedding models CRUD | `tab-emb-models.js` | 🟡 | C16: S15-B 🔴 (showEmbModelModal→showEmbeddingModelModal), S17-C 🔴 (checkEmbeddingModel отсутствует в api.js). S16-A ✅ handleEmbModelsAction реализован. Фикс в следующем коммите |
| S25-S29 | vaults CRUD | `tab-vaults.js` | 🟡 | S36-new ✅, S14-A ✅ handleVaultsAction. S27-A 🔴 — проверить deleteVault в api.js на 204 без .json() |
| S30-S35 | pipelines CRUD | `tab-pipelines.js` | 🟡 | S30-A 🔴 pipeline.pipeline_id\|\|pipeline.id — двойное поле, нужно сверить PipelineRead. S31-A..S33-A 🔴 — проверить api.js методы activatePipeline/deactivatePipeline/deletePipeline |
| S36-S39 | tags CRUD | `api.js`, `tab-campaigns.js` | ✅ | D09 (getTags/deleteTag в api.js); tags.py корректен (domain_id required); tab-campaigns.js — getTags возвращает TagsGrouped (объект), парсинг OK; D13-W (мёртвая Array.isArray ветка) |
| S40-S44 | documents CRUD | `tab-documents.js` | 🔴 | Не аудировано |
| S45-S51 | campaigns CRUD | `api.js`, `tab-campaigns.js`, `sidebar.js` | ✅ | D03 (N+1→batch), D04 (typed payload), D08 (null-safe), D09 (8 методов), D10 (204 no-json), D14 (c.campaign_id→c.id в sidebar) |

## Группа: db-management

| ID | Эндпоинт | Фронт-файл | Статус | Комментарий |
|---|---|---|---|---|
| D1-D5 | documents/chunks/search | ? | 🔴 | |
| D6-D9 | reindex/detach/tasks | ? | 🔴 | |

---

## Схема БД — история дрейфа

| Миграция | Что изменила |
|---|---|
| 0001 | Начальная схема: `campaigns` без `system_prompt`, `last_session_at`, `domain_id` |
| 0005 | `campaigns.vault_id` → `domain_id` |
| **0009** | ADD `system_prompt`, `last_session_at`; DROP `campaign_id`(str), `world_id`, `path_prefix`, `is_active`, `updated_at` |

---

## Лог изменений

| Дата | ID | Файл | Что исправлено | Коммит |
|---|---|---|---|---|
| 2026-06-01 | — | `app/api/chat.py` | IndentationError в `send_message_stream` | [1bddf09](https://github.com/Annener/mercer/commit/1bddf09e2e6062337f35e508fb1a488ccf5c0505) |
| 2026-06-01 | A01 | `app/db/models.py` | `Chat.domain_id`: nullable→NOT NULL, CASCADE | [4966c39](https://github.com/Annener/mercer/commit/4966c394791e51a4a7a734fd8432f934e4b6dbb0) |
| 2026-06-01 | A02 | `app/db/models.py` | Добавлено `pipeline_versions: JSONB` | — |
| 2026-06-01 | A03 | `app/db/models.py` | Добавлено `locked_pipeline_id: String` | — |
| 2026-06-01 | A04 | `app/api/chat.py` | `_audit()`: `payload=` → `details=` | — |
| 2026-06-01 | A05 | `app/api/chat.py` | `CreateChatRequest.domain_id`: Optional → required | [c06876d](https://github.com/Annener/mercer/commit/c06876dc9ea6b58c06445e0bfebdfcb09912b419) |
| 2026-06-01 | B01 | `app/api/chat.py` | N+1 vault_enabled → кэш + один SELECT | [699f446](https://github.com/Annener/mercer/commit/699f446248c3cb6dcaf8b9e6512cad7f1e077219) |
| 2026-06-01 | B02 | `app/static/js/chat.js` | `world_id` → `domain_id` в setupContextBar | [0fbe5f0](https://github.com/Annener/mercer/commit/0fbe5f010267055009f7dcca1c7de0b5d3a32646) |
| 2026-06-01 | B05 | `app/static/js/chat.js` | Удалена мёртвая ветка `else if (parsed.token)` | [0fbe5f0](https://github.com/Annener/mercer/commit/0fbe5f010267055009f7dcca1c7de0b5d3a32646) |
| 2026-06-01 | B06 | `app/static/js/chat.js` | Удалена мёртвая переменная `assistant_msg_id` | [0fbe5f0](https://github.com/Annener/mercer/commit/0fbe5f010267055009f7dcca1c7de0b5d3a32646) |
| 2026-06-01 | B07 | `app/static/js/chat.js` | clarification check → `state && question` | [0fbe5f0](https://github.com/Annener/mercer/commit/0fbe5f010267055009f7dcca1c7de0b5d3a32646) |
| 2026-06-01 | B08 | `app/static/js/api.js` | Добавлен `submitClarification(chatId, answers)` | [10a9401](https://github.com/Annener/mercer/commit/10a9401f09e8f7682885d9c01f99cdb987fcb0ac) |
| 2026-06-01 | C01 | `app/static/js/api.js` | `submitClarification`: добавлен `clarification_id` | [d10977b](https://github.com/Annener/mercer/commit/d10977b45bc31cf55d0eaff1c82ebd4a92eb5066) |
| 2026-06-01 | C02 | `app/static/js/chat.js` | `handleJSONResponse`: чек по `clarification_id` | [6931bd7](https://github.com/Annener/mercer/commit/6931bd722c12dec50752ae27aad9a549c9a5a574) |
| 2026-06-01 | — | `migrations/0009` + `models.py` | `campaigns` schema drift: ADD system_prompt, last_session_at; DROP устаревшие колонки | [b6a8f88](https://github.com/Annener/mercer/commit/b6a8f88d304a27f5415b3994579954462acc964e) / [72098f4](https://github.com/Annener/mercer/commit/72098f42315ccc55d89992cc8d665275a1fc74cb) |
| 2026-06-01 | D04 | `app/api/settings/schemas.py` | Добавлен `CampaignTagCreateRequest(name, color)` | [afb77dd](https://github.com/Annener/mercer/commit/afb77ddc566dce8b8640cf41b0ca6fb0177dd6e8) |
| 2026-06-01 | D03+D04 | `app/api/settings/campaigns.py` | N+1 → batch IN(); `payload: dict` → `CampaignTagCreateRequest` | [596f4af](https://github.com/Annener/mercer/commit/596f4af71d7a69bd1f0caa7c62e1dcb5d6288737) |
| 2026-06-01 | D08+D09+D10 | `app/static/js/api.js` | null-safe getCampaigns; 8 campaign/tag методов; 204 no-json fixes | [210917f](https://github.com/Annener/mercer/commit/210917ff13b8c0701c7da7576929d51141345e1b) |
| 2026-06-01 | D14 | `app/static/js/sidebar.js` | `c.campaign_id` → `c.id` — CampaignRead возвращает `id`, не `campaign_id`; кампания теперь реально применяется к новому чату | — |

---

## Следующая задача

**C16 · Фикс имён методов и недостающих методов api.js** (коммит после обновления AUDIT+PROGRESS)

1. `tab-gen-models.js`: `showGenerationModelModal` → `showGenModelModal`
2. `tab-emb-models.js`: `showEmbeddingModelModal` → `showEmbModelModal`
3. `api.js`: добавить `checkGenerationModel(id)` → `GET /api/settings/models/generation/{id}/check`
4. `api.js`: добавить `checkEmbeddingModel(id)` → `GET /api/settings/models/embedding/{id}/check`
5. `api.js`: проверить `deleteVault` — убедиться нет `.json()` на 204
6. `api.js`: проверить `activatePipeline`, `deactivatePipeline`, `deletePipeline` — пути и 204-safe
7. `tab-pipelines.js`: сверить `pipeline.pipeline_id || pipeline.id` с `PipelineRead` из `shared_contracts/models.py`

После фиксов — **аудит S40–S44 (tab-documents.js)** и **D1–D9 (db-management)**.
