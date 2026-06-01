# Progress — Bug Fix Tracker

> Статусы: 🔴 не проверен | 🟡 в работе | ✅ исправлен | ⚪ не затронут фронтом

---

## Группа: chat

| ID | Эндпоинт | Фронт-файл | Статус | Комментарий |
|---|---|---|---|---|
| C1 | POST `/chat/create` | ? | 🔴 | Проверить: фронт передаёт `domain_id`? или старый `vault_id`? |
| C2 | GET `/chat/list` | ? | 🔴 | Ответ — `{chats:[]}`, не массив напрямую |
| C3 | GET `/chat/{id}/history` | ? | 🔴 | Ответ — `{chat, messages, vault_enabled}` |
| C4 | POST `/chat/{id}/rename` | ? | 🔴 | |
| C5 | DELETE `/chat/{id}` | ? | 🔴 | |
| C6 | POST `/chat/{id}/lock_pipeline` | ? | 🔴 | |
| C7 | POST `/chat/{id}/send` | ? | 🔴 | Request: `{content, stream}`. Response: `{content, message_id}` |
| C8 | POST `/chat/{id}/send_stream` | ? | 🔴 | SSE: type=`token`\|`done`, финал `[DONE]` |
| C9 | POST `/chat/{id}/clarify` | ? | 🔴 | |

## Группа: config

| ID | Эндпоинт | Фронт-файл | Статус | Комментарий |
|---|---|---|---|---|
| CF1 | GET `/config/domains` | ? | 🔴 | Ответ — `{domains:[DomainInfo]}` |
| CF2 | GET `/config/vaults` | ? | 🔴 | Ответ — `{vaults:[VaultInfo]}` |

## Группа: settings

| ID | Эндпоинт | Фронт-файл | Статус | Комментарий |
|---|---|---|---|---|
| S1 | GET `/api/settings/status` | ? | 🔴 | |
| S2-S4 | params CRUD | ? | 🔴 | |
| S5-S9 | domains CRUD | ? | 🔴 | |
| S10-S11 | domain prompts | ? | 🔴 | |
| S12-S13 | domain fields (clarification) | ? | 🔴 | |
| S14-S19 | generation models CRUD | ? | 🔴 | |
| S20-S24 | embedding models CRUD | ? | 🔴 | |
| S25-S29 | vaults CRUD | ? | 🔴 | |
| S30-S35 | pipelines CRUD | ? | 🔴 | |
| S36-S39 | tags CRUD | ? | 🔴 | TagCreate требует `domain_id`, vault_id удалён |
| S40-S44 | documents CRUD | ? | 🔴 | |
| S45-S51 | campaigns CRUD | ? | 🔴 | CampaignCreate — привязка к домену, не vault |

## Группа: db-management

| ID | Эндпоинт | Фронт-файл | Статус | Комментарий |
|---|---|---|---|---|
| D1-D5 | documents/chunks/search | ? | 🔴 | |
| D6-D9 | reindex/detach/tasks | ? | 🔴 | |

---

## Лог изменений

| Дата | Файл | Что исправлено |
|---|---|---|
| 2026-06-01 | `rag-backend/app/api/chat.py` | IndentationError в `send_message_stream` — лишний отступ на `context.steps` |
