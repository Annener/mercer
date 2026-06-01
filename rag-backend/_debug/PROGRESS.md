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
| CF1 | GET `/config/domains` | ? | 🔴 | Не аудировался |
| CF2 | GET `/config/vaults` | ? | 🔴 | Не аудировался |

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
| S36-S39 | tags CRUD | ? | 🔴 | TagCreate требует `domain_id` (vault_id удалён в 0005) |
| S40-S44 | documents CRUD | ? | 🔴 | |
| S45-S51 | campaigns CRUD | ? | 🔴 | **Приоритет**: schema drift исправлен миграцией 0009 + models.py — начинать отсюда |

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

---

## Для следующей сессии

**Стартовать с:** `S45–S51 · campaigns CRUD (both)` — схема только что исправлена, нужно проверить роут + Pydantic-схемы + фронт.

**Контекст для нового чата:**
```
Репозиторий: https://github.com/Annener/mercer
Проект: Mercer — RAG-чат, FastAPI бэк + JS фронт

Архитектура: concept_plan/arch.md
API контракты: rag-backend/_debug/CONTRACTS.md
Лог багов: rag-backend/_debug/AUDIT.md  (все C1–C9 закрыты)
Прогресс: rag-backend/_debug/PROGRESS.md

Следующая задача: S45–S51, эндпоинты /settings/campaigns/* (both)
Схема campaigns исправлена миграцией 0009: колонки system_prompt + last_session_at добавлены,
устаревшие (campaign_id str, world_id, path_prefix, is_active, updated_at) — удалены.
Alembic нужно прогнать: alembic upgrade head
```
