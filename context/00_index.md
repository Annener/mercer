# Mercer — Контекстная документация: оглавление

> Этот файл — **точка входа** для (ИИ ассистента | разработчика).
> Прочитай его первым, затем открывай нужные разделы.
> Все файлы находятся в `context/`.

---

## О проекте

**Mercer** — RAG-платформа (чат-ассистент) с поддержкой многошаговых pipeline, уточнения контекста (clarification FSM), доменов, кампаний, векторного хранилища (LanceDB) и поддержкой OpenAI-совместимых моделей.

**Техстас:** Python (FastAPI), PostgreSQL, LanceDB, Docker.

---

## Мап файлов контекста

| Файл | Содержимое | Когда открывать |
|---|---|---|
| `01_overview.md` | Суть проекта, сервисы, Docker, порты, структура папок | Всегда |
| `02_backend_api.md` | Все HTTP-эндпойнты `rag-backend` (методы, схемы) | Работа с API |
| `03_shared_contracts.md` | Pydantic-модели `shared_contracts` | Изменение контрактов |
| `04_pipeline.md` | Структура pipeline (шаги, JSONB-формат, registry) | Создание/редактирование pipeline |
| `05_indexer.md` | `rag-indexer`: парсинг, чанкинг, embedding | Работа с документами |
| `06_db_models.md` | Все 15 таблиц PostgreSQL (колонки, FK, constraints) | Работа с БД, миграции |
| `07_rag_runtime.md` | **Полный поток запроса**: chat.py → FSM → router → executor → retrieval | Любые изменения в логике ответа |
| `08_lancedb.md` | LanceDB: схема таблиц, HTTP API, upsert/search/delete | Изменения retrieval или индекса |
| `09_config_env.md` | Env-переменные, volumes, порты, platform_settings | Деплой, настройка, отладка |

---

## Быстрый навигатор: что открыть первым

### Ты меняешь логику ответа на запрос
→ `07_rag_runtime.md` + `04_pipeline.md`

### Ты меняешь API-эндпойнт / аддаешь новый
→ `02_backend_api.md` + `03_shared_contracts.md`

### Ты меняешь схему БД / делаешь миграцию
→ `06_db_models.md`

### Ты меняешь логику индексации / чанкинга
→ `05_indexer.md` + `08_lancedb.md`

### Ты добавляешь сервис / меняешь деплой
→ `09_config_env.md` + `01_overview.md`

### Ты меняешь pipeline (JSON-структура, шаги, роутинг)
→ `04_pipeline.md` + `07_rag_runtime.md` (разделы 3–4)

---

## Ключевые связи между компонентами

```
Frontend (static JS)
    │  HTTP
    ▼
rag-backend (:8000)
    ├─ PostgreSQL (rag-db:5432)
    ├─ db-api-server (:8080) ─► LanceDB (/data/lancedb)
    └─ rag-indexer (:9000) ──► db-api-server (:8080)
                              └─► PostgreSQL
```

### Три типа моделей

| Тип | Таблица (PG) | Реестр |
|---|---|---|
| Generation LLM | `generation_models` | `settings_service` |
| Embedding | `embedding_models` | `settings_service` |
| Rerank | `rerank_models` | `settings_service` |

### Пять типов запросов пользователя

| Режим | Условие | Ответ |
|---|---|---|
| Clarification | FSM stage=collecting | Вопрос уточнения |
| Pipeline | router выбрал pipeline | Многошаговый ответ |
| Plain RAG | router вернул None | Прямой RAG-ответ |
| Locked | `chat.locked_pipeline_id` установлен | Pipeline без LLM-роутинга |
| Campaign | `chat.campaign_id` установлен | Pipeline/RAG с фильтром по тегам |

---

## Часто задаваемые вопросы

**Q: Как добавить новый pipeline?**
→ Создать запись в таблице `pipelines` (JSON-поля `steps` и `final_composition`). См. `04_pipeline.md`.

**Q: Как изменить промпт роутера?**
→ Запись в `domain_prompts` с `prompt_type="pipeline_router"`. См. `07_rag_runtime.md` раздел 4.

**Q: Как добавить новый тип документа для индексации?**
→ Добавить parser в `rag-indexer/app/parsers/`. См. `05_indexer.md`.

**Q: Как добавить поле уточнения?**
→ `DomainClarificationField` в БД через API. См. `06_db_models.md` (таблица `domain_clarification_fields`).

**Q: Как сменить LLM-модель?**
→ Обновить `generation_models` в БД, выставить `is_active=True` для нужной. См. `09_config_env.md` + `06_db_models.md`.

**Q: Как переиндексировать документ?**
→ `DELETE /index/document/{id}?vault_id=...` → повторно запустить индексацию через `rag-indexer`. См. `08_lancedb.md`.
