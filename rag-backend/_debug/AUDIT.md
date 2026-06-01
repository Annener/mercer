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
| A01 | model    | `app/db/models.py`          | `Chat.domain_id` — `nullable=True`, по концепту должен быть NOT NULL     | ⚠️     |
| A02 | model    | `app/db/models.py`          | `Chat` не имеет поля `pipeline_versions`                                 | ✅     |
| A03 | model    | `app/db/models.py`          | `Chat` не имеет поля `locked_pipeline_id`                                | ✅     |
| A04 | route    | `app/api/chat.py`           | `_audit()` вызывался с `payload=`, в модели `AuditLog` поле `details=`  | ✅     |
| A05 | schema   | `app/api/chat.py`           | `CreateChatRequest.domain_id` — опционален, концепт требует обязательного | ⚠️     |
| A06 | frontend | `app/static/js/sidebar.js`  | `createChat(domain, campaign)` — соответствует контракту                 | ⬜     |

---

## C2 · GET /chat/list

Аудит: 2026-06-01 · Проверено: chat.py, api.js, sidebar.js

| ID  | Слой     | Файл                        | Проблема                                                                                   | Статус |
|-----|----------|-----------------------------|--------------------------------------------------------------------------------------------|--------|
| B01 | route    | `app/api/chat.py`           | N+1: `_vault_enabled()` вызывается для каждого чата в цикле (await в list comprehension)  | ⚠️     |
| —   | frontend | `app/static/js/sidebar.js`  | `data.chats \|\| []` — корректный разбор `{chats:[...]}`                                  | ⬜     |

---

## C3 · GET /chat/{id}/history

Аудит: 2026-06-01 · Проверено: chat.py, api.js, chat.js

| ID  | Слой     | Файл                        | Проблема                                                                                              | Статус |
|-----|----------|-----------------------------|-------------------------------------------------------------------------------------------------------|--------|
| B02 | frontend | `app/static/js/chat.js`     | `setupContextBar()` читает `chat.world_id` — поля нет в модели/контракте; должно быть `chat.domain_id` | 🔴     |
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
| —   | frontend | `app/static/js/api.js`  | `{content}` — верно, бэк не требует поле `stream` (два эндпоинта)  | ⬜     |
| —   | frontend | `app/static/js/chat.js` | `handleJSONResponse` разбирает `response.content` — верно           | ⬜     |

---

## C8 · POST /chat/{id}/send_stream (SSE)

Аудит: 2026-06-01 · Проверено: chat.py, api.js, chat.js

| ID  | Слой     | Файл                        | Проблема                                                                                         | Статус |
|-----|----------|-----------------------------|--------------------------------------------------------------------------------------------------|--------|
| B05 | frontend | `app/static/js/chat.js`     | Мёртвая ветка `else if (parsed.token)` — бэкенд шлёт только `{type:"token",content}`, не `{token}` | ⚠️     |
| B06 | frontend | `app/static/js/chat.js`     | Мёртвая переменная `assistant_msg_id` объявлена но нигде не используется                         | ⚠️     |

---

## C9 · POST /chat/{id}/clarify

Аудит: 2026-06-01 · Проверено: chat.py, api.js, chat.js

| ID  | Слой     | Файл                        | Проблема                                                                                                             | Статус |
|-----|----------|-----------------------------|----------------------------------------------------------------------------------------------------------------------|--------|
| B07 | frontend | `app/static/js/chat.js`     | `handleJSONResponse`: проверяет `response.role === 'assistant' && response.state` — `ClarificationResponse` не имеет поля `role`, условие никогда не выполняется | 🔴     |
| B08 | frontend | `app/static/js/api.js`      | Отсутствует метод `submitClarification(chatId, answers)` — эндпоинт C9 недоступен с фронта                          | 🔴     |

---

## Лог исправлений

| Дата       | ID  | Файл                        | Что исправлено                                                    |
|------------|-----|-----------------------------|-------------------------------------------------------------------|
| 2026-06-01 | —   | `app/api/chat.py`           | IndentationError в `send_message_stream` (context.steps)          |
| 2026-06-01 | A02 | `app/db/models.py`          | Добавлено поле `pipeline_versions: JSONB` в модель `Chat`         |
| 2026-06-01 | A03 | `app/db/models.py`          | Добавлено поле `locked_pipeline_id: String` в модель `Chat`       |
| 2026-06-01 | A04 | `app/api/chat.py`           | `_audit()`: `payload=` → `details=` (соответствие AuditLog)       |
