# Mercer — Обзор проекта и архитектура

> **Проход 1 из N.** Этот файл — стартовый контекст для ИИ-ассистента.
> Последующие проходы покроют: API-эндпоинты, модели БД, пайплайны, индексер, db-api-server, shared_contracts.

---

## Суть проекта

**Mercer** — RAG-платформа (Retrieval-Augmented Generation) с полным стеком:
- хранение документов и их векторных представлений,
- индексация файлов из «хранилищ» (Vault),
- чат-интерфейс с поддержкой пайплайнов, кампаний и доменов,
- управление моделями генерации и эмбеддингов через UI/API.

Проект — **монорепозиторий** из четырёх Docker-сервисов + общей библиотеки контрактов.

---

## Сервисы (docker-compose)

| Сервис | Порт (внутр.) | Внешний порт | Назначение |
|---|---|---|---|
| `rag-db` | 5432 | — | PostgreSQL 16, основное хранилище метаданных |
| `db-api-server` | 8080 | — | HTTP API над LanceDB (векторная БД); upsert/search чанков |
| `rag-indexer` | 9000 | — | Индексация файлов из Vault: парсинг → чанкинг → эмбеддинг → запись в LanceDB |
| `rag-backend` | 8000 | **8000** | Основной backend: чат, пайплайны, управление доменами/моделями/вольтами; отдаёт статику (SPA) |

Все сервисы объединены в сеть `rag-net` (bridge). `rag-backend` — единственная точка входа снаружи.

### Зависимости старта
```
rag-db (healthy)
  └── db-api-server (healthy)
        └── rag-indexer
        └── rag-backend
```

---

## Структура монорепозитория

```
mercer/
├── docker-compose.yml          # оркестрация 4 сервисов
├── .env.example                # шаблон переменных окружения
├── config/
│   └── storage.config.yaml     # конфиг LanceDB для db-api-server
├── shared_contracts/           # общая Pydantic-библиотека (pip install -e .)
│   └── models.py               # все DTO/контракты между сервисами
├── db-api-server/              # сервис векторного хранилища
│   ├── main.py
│   ├── api/                    # FastAPI роутеры
│   └── storage/                # LanceDB-адаптер
├── rag-indexer/                # сервис индексации
│   ├── indexer_worker.py       # основной воркер (парсинг/чанкинг/эмбеддинг)
│   ├── app/                    # FastAPI (task API + WebSocket progress)
│   ├── api/                    # доп. роутеры
│   ├── embedding/              # провайдеры эмбеддингов
│   ├── parser/                 # парсеры документов (PDF и др.)
│   └── storage/                # клиент к db-api-server
├── rag-backend/                # основной backend
│   ├── app/
│   │   ├── main.py             # FastAPI app, lifespan, роутеры
│   │   ├── config.py           # Pydantic settings (env vars)
│   │   ├── api/                # HTTP-роутеры
│   │   │   ├── chat.py         # чат, send/stream, clarification
│   │   │   ├── config_api.py   # управление вольтами, моделями
│   │   │   ├── db_management.py# CRUD доменов, кампаний, тегов, документов
│   │   │   └── settings/       # платформенные настройки
│   │   ├── db/
│   │   │   ├── models.py       # SQLAlchemy ORM-модели (все таблицы)
│   │   │   ├── session.py      # async engine + SessionLocal
│   │   │   └── migrations.py   # запуск alembic при старте
│   │   ├── services/           # бизнес-логика
│   │   │   ├── retrieval.py            # RAG-поиск по LanceDB
│   │   │   ├── pipeline_executor.py    # исполнение пайплайнов
│   │   │   ├── pipeline_router.py      # выбор пайплайна (LLM/heuristic)
│   │   │   ├── pipeline_service.py     # CRUD пайплайнов
│   │   │   ├── settings_service.py     # кэш платф. настроек + провайдеры
│   │   │   ├── domain_service.py       # домены, промпты
│   │   │   ├── query_rewriter.py       # переформулировка запроса
│   │   │   ├── clarification_fsm.py    # FSM уточнения запроса
│   │   │   ├── vault_config_service.py # кэш конфигурации Vault
│   │   │   ├── planner.py              # планировщик шагов
│   │   │   └── prompt_pack.py          # сборка промптов
│   │   ├── providers/          # LLM-провайдеры (OpenAI-compatible, Ollama)
│   │   ├── domains/            # доп. доменная логика
│   │   ├── planners/           # планировщики
│   │   └── static/             # SPA (index.html + assets)
│   ├── migrations/             # Alembic-миграции
│   └── pipelines/              # YAML/JSON-определения пайплайнов (legacy)
├── pdf-sidecar/                # вспомогательный сервис для парсинга PDF
└── tests/                      # тесты (pytest)
```

---

## Переменные окружения (`.env`)

| Переменная | Пример | Описание |
|---|---|---|
| `POSTGRES_USER` | `raguser` | Пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | `changeme` | Пароль PostgreSQL |
| `POSTGRES_DB` | `ragplatform` | Имя базы данных |
| `DATABASE_URL` | `postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform` | DSN для SQLAlchemy async |
| `ENCRYPTION_KEY` | — | Ключ шифрования API-ключей моделей (Fernet) |
| `STORAGE_API_URL` | `http://db-api-server:8080` | URL db-api-server для rag-indexer и rag-backend |
| `INDEXER_API_URL` | `http://rag-indexer:9000` | URL rag-indexer для rag-backend |
| `DB_API_URL` | `http://db-api-server:8080` | URL db-api-server для rag-backend |

---

## Ключевые концепции

### Domain (Домен)
Логический контекст/тема платформы (например: «Поддержка», «HR», «Юриспруденция»). Каждый чат, Vault, тег, кампания и пайплайн **принадлежат домену**. `domain_id` — строковый PK (не UUID). Домен имеет:
- системный промпт (`domain_prompts`)
- поля уточнения (`domain_clarification_fields`)
- флаг `is_system` для системных доменов

### Vault (Хранилище документов)
Привязанная к домену папка с документами. Хранит файлы в `./vaults/{vault_id}/`. Каждый Vault имеет:
- `embedding_model_id` — привязанная модель эмбеддинга
- `binding_status` — статус привязки: `unbound / binding / bound / error`
- `chunk_count` — счётчик проиндексированных чанков
- настройки чанкинга: `chunk_size`, `overlap`, `entity_aware_mode`

### Campaign (Кампания)
Подконтекст внутри домена. Позволяет изолировать набор документов (через теги) и использовать свой `system_prompt`. Чат может быть привязан к кампании.

### Pipeline (Пайплайн)
Конфигурируемый многошаговый процесс обработки запроса:
1. Шаги `type=retrieval` — извлечение чанков из LanceDB с конкретными тегами и промптом
2. Шаг `type=final` — финальная композиция ответа через LLM

Пайплайны хранятся в таблице `pipelines` (JSONB-поля `steps`, `final_composition`). Уникальность: `(pipeline_id, domain_id, version)`.

### Query Rewriting
Перед retrieval запрос пользователя переформулируется через LLM (`query_rewriter.py`) с учётом истории чата и описания домена.

### Clarification FSM
Если запрос неполный, система запускает FSM уточнения (`clarification_fsm.py`): задаёт пользователю вопросы по `domain_clarification_fields` до получения всех обязательных данных.

---

## Поток обработки сообщения (send_message)

```
POST /chat/{chat_id}/send
│
├── 1. Сохранить user-сообщение в БД
├── 2. Загрузить историю чата (последние 20 сообщений)
├── 3. QueryRewriter: переформулировать запрос (если есть активный LLM)
├── 4. PipelineRouter.select(): выбрать подходящий пайплайн для домена
│   ├── Если пайплайн найден → PipelineExecutor.run(context)
│   │   ├── Для каждого retrieval-шага: retrieve_multi_vault() → LLM-шаг
│   │   └── FinalComposition: собрать финальный ответ
│   └── Если пайплайна нет → plain LLM fallback
│       ├── _fallback_retrieve(): RAG по всем Vault домена
│       └── provider.generate(messages)
├── 5. Сохранить assistant-сообщение в БД
└── 6. Вернуть MessageResponse (или StreamingResponse для /send_stream)
```

### Streaming (`/send_stream`)
Аналогичный поток, но возвращает `StreamingResponse` (SSE). Чанки типов:
- `{"type": "token", "content": "..."}` — токен ответа
- `{"type": "sources", "sources": [...]}` — источники (путь, страница, vault_id)
- `data: [DONE]` — завершение

---

## Межсервисное взаимодействие

```
[Frontend/Client]
       │ HTTP :8000
       ▼
[rag-backend]
   │                │
   │ HTTP :8080     │ HTTP :9000
   ▼                ▼
[db-api-server]  [rag-indexer]
   │
   └── LanceDB (./data/lancedb)

[rag-backend] ──► [rag-db (PostgreSQL)] (напрямую через SQLAlchemy)
[rag-indexer] ──► [rag-db (PostgreSQL)] (напрямую через SQLAlchemy)
```

- `rag-backend` проксирует запросы к `rag-indexer` (запуск задач индексации, статус)
- `rag-backend` вызывает `db-api-server` для векторного поиска при retrieval
- `rag-indexer` пишет чанки в `db-api-server` (upsert), читает конфиг vault из него же
- `rag-indexer` не открыт наружу — доступен только изнутри `rag-net`

---

## Volumes (постоянные данные)

| Путь на хосте | Монтируется в | Назначение |
|---|---|---|
| `./data/postgres` | rag-db | Данные PostgreSQL |
| `./data/lancedb` | db-api-server | Векторная БД LanceDB |
| `./vaults` | rag-indexer, rag-backend | Файлы документов по Vault |
| `./state` | rag-indexer | Состояние задач индексации (JSON) |
| `./cache/embeddings` | rag-indexer | Кэш эмбеддингов |
| `./logs` | все сервисы | Логи |
| `./config/storage.config.yaml` | db-api-server | Конфиг LanceDB (ro) |

---

## Следующие проходы (план)

| № | Файл | Содержание |
|---|---|---|
| 02 | `02_database_models.md` | Все таблицы PostgreSQL: колонки, типы, связи, constraints |
| 03 | `03_api_endpoints.md` | Все HTTP-эндпоинты с методами, параметрами, схемами запрос/ответ |
| 04 | `04_pipelines.md` | Структура пайплайнов, PipelineExecutor, PipelineRouter, шаги |
| 05 | `05_indexer.md` | Процесс индексации: парсинг, чанкинг, эмбеддинг, запись в LanceDB |
| 06 | `06_shared_contracts.md` | Все Pydantic-модели из shared_contracts/models.py |
| 07 | `07_settings_and_providers.md` | Платформенные настройки, LLM/Embedding провайдеры, шифрование |
| 08 | `08_retrieval.md` | Стратегии retrieval: hybrid, vector, полнотекстовый поиск |
