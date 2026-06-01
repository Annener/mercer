# Mercer — Audit Log

> Статусы: 🔴 баг | ⚠️ нарушение инварианта / предупреждение | ✅ исправлен | ⬜ проверен, OK

---

## Как читать эту таблицу

- **Слой** — где найдена проблема: `model` / `schema` / `route` / `service` / `frontend`
- **ID** — уникальный идентификатор бага, используется в коммитах (`fix: B02`)
- После исправления меняем статус на ✅ и добавляем запись в **Лог исправлений**

---

## C1 · POST /chat/create

Аудит: 2026-06-01 · Проверено: models.py, chat.py, api.js, sidebar.js

| ID  | Слой     | Файл                        | Проблема                                                                 | Статус |
|-----|----------|-----------------------------|--------------------------------------------------------------------------|--------|
| A01 | model    | `app/db/models.py`          | `Chat.domain_id` — `nullable=True`, по концепту должен быть NOT NULL; также `ondelete="SET NULL"` → исправлено на `CASCADE` | ✅     |
| A02 | model    | `app/db/models.py`          | `Chat` не имеет поля `pipeline_versions`                                 | ✅     |
| A03 | model    | `app/db/models.py`          | `Chat` не имеет поля `locked_pipeline_id`                                | ✅     |
| A04 | route    | `app/api/chat.py`           | `_audit()` вызывался с `payload=`, в модели `AuditLog` поле `details=`  | ✅     |
| A05 | schema   | `app/api/chat.py`           | `CreateChatRequest.domain_id` — был опционален (`str \| None = None`), концепт требует обязательного; исправлено на `str` | ✅     |
| A06 | frontend | `app/static/js/sidebar.js`  | `createChat(domain, campaign)` — соответствует контракту                 | ⬜     |

---

## C2 · GET /chat/list

Аудит: 2026-06-01 · Проверено: chat.py, api.js, sidebar.js

| ID  | Слой     | Файл                        | Проблема                                                                                   | Статус |
|-----|----------|-----------------------------|--------------------------------------------------------------------------------------------|--------|
| B01 | route    | `app/api/chat.py`           | N+1: `_vault_enabled()` вызывался для каждого чата в цикле (await в list comprehension)  | ✅     |
| —   | frontend | `app/static/js/sidebar.js`  | `data.chats \|\| []` — корректный разбор `{chats:[...]}`                                  | ⬜     |

---

## C3 · GET /chat/{id}/history

Аудит: 2026-06-01 · Проверено: chat.py, api.js, chat.js

| ID  | Слой     | Файл                        | Проблема                                                                                              | Статус |
|-----|----------|-----------------------------|-------------------------------------------------------------------------------------------------------|--------|
| B02 | frontend | `app/static/js/chat.js`     | `setupContextBar()` читал `chat.world_id` — поля нет в модели/контракте; исправлено на `chat.domain_id` | ✅     |
| —   | frontend | `app/static/js/api.js`      | `getChat()` → `/chat/${chatId}/history`, разбор `{chat, messages}` — верно                           | ⬜     |

---

## C4 · POST /chat/{id}/rename

Аудит: 2026-06-01 · Проверено: chat.py, api.js, sidebar.js

| ID  | Слой | Файл | Проблема    | Статус |
|-----|------|------|-------------|--------|
| —   | —    | —    | Всё верно   | ⬜     |

---

## C5 · DELETE /chat/{id}

Аудит: 2026-06-01 · Проверено: chat.py, api.js, sidebar.js

| ID  | Слой | Файл | Проблема    | Статус |
|-----|------|------|-------------|--------|
| —   | —    | —    | Всё верно   | ⬜     |

---

## C6 · POST /chat/{id}/lock_pipeline

Аудит: 2026-06-01 · Проверено: chat.py, api.js, chat.js

| ID  | Слой | Файл | Проблема    | Статус |
|-----|------|------|-------------|--------|
| —   | —    | —    | Всё верно   | ⬜     |

---

## C7 · POST /chat/{id}/send

Аудит: 2026-06-01 · Проверено: chat.py, api.js, chat.js

| ID  | Слой     | Файл                    | Проблема                                                            | Статус |
|-----|----------|-------------------------|---------------------------------------------------------------------|--------|
| —   | frontend | `app/static/js/api.js`  | `{content}` — верно, бэк не требует поле `stream` (два эндпойнта)  | ⬜     |
| —   | frontend | `app/static/js/chat.js` | `handleJSONResponse` разбирает `response.content` — верно           | ⬜     |

---

## C8 · POST /chat/{id}/send_stream (SSE)

Аудит: 2026-06-01 · Проверено: chat.py, api.js, chat.js

| ID  | Слой     | Файл                        | Проблема                                                                                         | Статус |
|-----|----------|-----------------------------|--------------------------------------------------------------------------------------------------|--------|
| B05 | frontend | `app/static/js/chat.js`     | Мёртвая ветка `else if (parsed.token)` — удалена                                               | ✅     |
| B06 | frontend | `app/static/js/chat.js`     | Мёртвая переменная `assistant_msg_id` — удалена                                                           | ✅     |

---

## C9 · POST /chat/{id}/clarify

Аудит: 2026-06-01 · Проверено: chat.py, api.js, chat.js

| ID  | Слой     | Файл                        | Проблема                                                                                                             | Статус |
|-----|----------|-----------------------------|----------------------------------------------------------------------------------------------------------------------|--------|
| B07 | frontend | `app/static/js/chat.js`     | `handleJSONResponse`: `response.role === 'assistant' && response.state` → исправлено на `response.state && response.question` | ✅     |
| B08 | frontend | `app/static/js/api.js`      | Добавлен `submitClarification(chatId, answers)` — эндпойнт C9 доступен с фронта                      | ✅     |
| C01 | frontend | `app/static/js/api.js`      | `submitClarification` шлёт `{ answers }` без `clarification_id` — бэк возвращал 422 (поле обязательно по `ClarificationAnswer`) | ✅     |
| C02 | frontend | `app/static/js/chat.js`     | `handleJSONResponse` проверял `response.state && response.question` — таких полей нет в `ClarificationResponse`; исправлено на `response.clarification_id` | ✅     |

> **Примечание к CONTRACTS.md**: поле `stream` в `SendMessageRequest` — документационная неточность. Фронт корректно использует URL, не поле. CONTRACTS.md требует уточнения, но это не баг кода.

---

## C10 · S45–S51 · /api/settings/campaigns/*

Аудит: 2026-06-01 · Проверено: campaigns.py, schemas.py, models.py, api.js, tab-campaigns.js

| ID  | Слой     | Файл                                       | Проблема                                                                                     | Статус |
|-----|----------|--------------------------------------------|----------------------------------------------------------------------------------------------|--------|
| D01 | model    | `app/db/models.py`                         | `Campaign.updated_at` удалён миграцией 0009; `CampaignRead` не объявляет `updated_at` — OK | ⬜     |
| D02 | model    | `app/db/models.py`                         | `campaign_tags` secondary + viewonly — архитектурный выбор, не баг                               | ⬜     |
| D03 | route    | `app/api/settings/campaigns.py`            | N+1: `_campaign_with_tags` вызывался в цикле в `list_campaigns` — заменён batch-запросом IN() | ✅     |
| D04 | route    | `app/api/settings/campaigns.py`            | S51: `payload: dict` — нет валидации, KeyError → 500; заменён `CampaignTagCreateRequest` | ✅     |
| D05 | schema   | `shared_contracts/models.py`               | `CampaignRead.tags: list = []` — заполняется бэком, OK                               | ⬜     |
| D06 | schema   | `shared_contracts/models.py`               | `CampaignCreate.domain_id: str` — обязательное, соответствует контракту        | ⬜     |
| D07 | route    | `app/api/settings/campaigns.py`            | `update_campaign` использует `exclude_unset=True` — правильно                       | ⬜     |
| D08 | frontend | `app/static/js/api.js`                     | `getCampaigns(null)` → `?domain_id=null` (строка); исправлено null-сафети | ✅     |
| D09 | frontend | `app/static/js/api.js`                     | Отсутствовали 8 методов campaigns/tags API — TypeError на любом действии; добавлены | ✅     |
| D10 | frontend | `app/static/js/api.js`                     | `deleteChat` вызывал `.json()` на 204 No Content → SyntaxError; исправлено    | ✅     |

---

## Лог исправлений

| Дата       | ID       | Файл                        | Что исправлено                                                                  | Коммит |
|------------|----------|-----------------------------|---------------------------------------------------------------------------|--------|
| 2026-06-01 | —        | `app/api/chat.py`           | IndentationError в `send_message_stream` (context.steps)                 | [1bddf09](https://github.com/Annener/mercer/commit/1bddf09e2e6062337f35e508fb1a488ccf5c0505) |
| 2026-06-01 | A02      | `app/db/models.py`          | Добавлено поле `pipeline_versions: JSONB`                                        | — |
| 2026-06-01 | A03      | `app/db/models.py`          | Добавлено поле `locked_pipeline_id: String`                                      | — |
| 2026-06-01 | A04      | `app/api/chat.py`           | `_audit()`: `payload=` → `details=`                                        | — |
| 2026-06-01 | B02      | `app/static/js/chat.js`     | `setupContextBar`: `chat.world_id` → `chat.domain_id`                       | [0fbe5f0](https://github.com/Annener/mercer/commit/0fbe5f010267055009f7dcca1c7de0b5d3a32646) |
| 2026-06-01 | B05      | `app/static/js/chat.js`     | Удалена мёртвая ветка `else if (parsed.token)`                         | [0fbe5f0](https://github.com/Annener/mercer/commit/0fbe5f010267055009f7dcca1c7de0b5d3a32646) |
| 2026-06-01 | B06      | `app/static/js/chat.js`     | Удалена мёртвая переменная `assistant_msg_id`                          | [0fbe5f0](https://github.com/Annener/mercer/commit/0fbe5f010267055009f7dcca1c7de0b5d3a32646) |
| 2026-06-01 | B07      | `app/static/js/chat.js`     | `handleJSONResponse`: clarification check → `state && question`             | [0fbe5f0](https://github.com/Annener/mercer/commit/0fbe5f010267055009f7dcca1c7de0b5d3a32646) |
| 2026-06-01 | B08      | `app/static/js/api.js`      | Добавлен `submitClarification(chatId, answers)`                            | [10a9401](https://github.com/Annener/mercer/commit/10a9401f09e8f7682885d9c01f99cdb987fcb0ac) |
| 2026-06-01 | C01      | `app/static/js/api.js`      | `submitClarification`: добавлен `clarification_id` в сигнатуру и body       | [d10977b](https://github.com/Annener/mercer/commit/d10977b45bc31cf55d0eaff1c82ebd4a92eb5066) |
| 2026-06-01 | C02      | `app/static/js/chat.js`     | `handleJSONResponse`: чек по `clarification_id`; `addMessage` принимает clarificationId | [6931bd7](https://github.com/Annener/mercer/commit/6931bd722c12dec50752ae27aad9a549c9a5a574) |
| 2026-06-01 | A01      | `app/db/models.py`          | `Chat.domain_id`: `nullable=True` → `nullable=False`; `ondelete="SET NULL"` → `CASCADE` | [4966c39](https://github.com/Annener/mercer/commit/4966c394791e51a4a7a734fd8432f934e4b6dbb0) |
| 2026-06-01 | A05      | `app/api/chat.py`           | `CreateChatRequest.domain_id`: `str \| None = None` → `str` (required)     | [c06876d](https://github.com/Annener/mercer/commit/c06876dc9ea6b58c06445e0bfebdfcb09912b419) |
| 2026-06-01 | **B01**  | `app/api/chat.py`           | N+1 в `list_chats`: заменён один запрос `settings_service.get` + кэш `vault_enabled_cache` | [699f446](https://github.com/Annener/mercer/commit/699f446248c3cb6dcaf8b9e6512cad7f1e077219) |
| 2026-06-01 | D04      | `app/api/settings/schemas.py` | Добавлен `CampaignTagCreateRequest(name, color)` | [afb77dd](https://github.com/Annener/mercer/commit/afb77ddc566dce8b8640cf41b0ca6fb0177dd6e8) |
| 2026-06-01 | D03+D04  | `app/api/settings/campaigns.py` | N+1 → batch IN(); `payload: dict` → `CampaignTagCreateRequest` | [596f4af](https://github.com/Annener/mercer/commit/596f4af71d7a69bd1f0caa7c62e1dcb5d6288737) |
| 2026-06-01 | D08+D09+D10 | `app/static/js/api.js` | null-safe getCampaigns; 8 campaign/tag методов; deleteChat/deleteCampaign/deleteTag — 204 no-json | [581e5c1](https://github.com/Annener/mercer/commit/581e5c171f1fa6d28e6fe05deeeee0893d6816fa) |
