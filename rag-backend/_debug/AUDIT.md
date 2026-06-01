# Mercer — Audit Log

> Статусы: 🔴 баг | ⚠️ нарушение инварианта / предупреждение | ✅ исправлен | ⬜ проверен, OK

---

## Как читать эту таблицу

- **Слой** — где найдена проблема: `model` / `schema` / `route` / `service` / `frontend`
- **ID** — уникальный идентификатор бага, используется в коммитах (`fix: A02`)
- После исправления меняем статус на ✅ и добавляем запись в **Лог исправлений**

---

## C1 · POST /chat/create

Аудит: 2026-06-01 · Проверено: models.py, chat.py, api.js

| ID  | Слой     | Файл                        | Проблема                                                                 | Статус |
|-----|----------|-----------------------------|--------------------------------------------------------------------------|--------|
| A01 | model    | `app/db/models.py`          | `Chat.domain_id` — `nullable=True`, по концепту должен быть NOT NULL     | ⚠️     |
| A02 | model    | `app/db/models.py`          | `Chat` не имеет поля `pipeline_versions` — используется в `create_chat`  | ✅     |
| A03 | model    | `app/db/models.py`          | `Chat` не имеет поля `locked_pipeline_id` — используется в роуте и send  | ✅     |
| A04 | route    | `app/api/chat.py`           | `_audit()` вызывался с `payload=`, в модели `AuditLog` поле `details=`  | ✅     |
| A05 | schema   | `app/api/chat.py`           | `CreateChatRequest.domain_id` — опционален, концепт требует обязательного | ⚠️     |
| A06 | frontend | `app/static/js/api.js`      | Соответствует контракту                                                  | ⬜     |

---

## Лог исправлений

| Дата       | ID  | Файл                   | Что исправлено                                                  |
|------------|-----|------------------------|-----------------------------------------------------------------|
| 2026-06-01 | —   | `app/api/chat.py`      | IndentationError в `send_message_stream` (context.steps)        |
| 2026-06-01 | A02 | `app/db/models.py`     | Добавлено поле `pipeline_versions: JSONB` в модель `Chat`       |
| 2026-06-01 | A03 | `app/db/models.py`     | Добавлено поле `locked_pipeline_id: String` в модель `Chat`     |
| 2026-06-01 | A04 | `app/api/chat.py`      | `_audit()`: `payload=` → `details=` (соответствие AuditLog)     |
