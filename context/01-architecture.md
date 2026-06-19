# 01 — Архитектура Mercer

## Обзор

Mercer — многосервисная RAG-платформа для управления знаниями с поддержкой D&D и рабочих документов.
Всё развёртывается через `docker-compose.yml`.

## Сервисы

```
┌─────────────────────────────────────────────────────────────────────┐
│                         docker-compose (rag-net)                    │
│                                                                     │
│  ┌──────────────┐     ┌─────────────────┐     ┌─────────────────┐  │
│  │  rag-backend │────▶│  rag-indexer    │────▶│  db-api-server  │  │
│  │  :8000 (pub) │     │  :9000 (intern) │     │  :8080 (intern) │  │
│  └──────┬───────┘     └────────┬────────┘     └────────┬────────┘  │
│         │                      │                        │           │
│         └──────────────────────┴────────────────────────┘           │
│                                │                                    │
│                         ┌──────▼──────┐                            │
│                         │   rag-db    │                            │
│                         │  postgres16 │                            │
│                         └─────────────┘                            │
└─────────────────────────────────────────────────────────────────────┘

  + pdf-sidecar (macOS host :8765, не в Docker)
```

## Роли сервисов

### rag-backend (:8000, публичный)
- FastAPI приложение — единственная точка входа
- Обслуживает Frontend (SPA из `app/static/`)
- API: чаты, пайплайны, настройки, управление БД
- Проксирует запросы к rag-indexer и db-api-server
- Алembic-миграции запускаются при старте
- Настройки (модели, вольты) хранятся в PostgreSQL, кэшируются в памяти через `settings_service`

### rag-indexer (:9000, внутренний)
- Индексирует документы из `./vaults/` в LanceDB
- Разбирает PDF (через pdf-sidecar или pdfminer fallback)
- Создаёт эмбеддинги через Ollama / OpenAI-compatible
- Chunking с entity-aware mode
- Statefile-трекинг задач индексации (`./state/`)
- Websocket-прогресс в реальном времени

### db-api-server (:8080, внутренний)
- Абстракция над LanceDB
- REST API: `POST /upsert`, `POST /search`, `DELETE /vault/{id}`
- Конфиг из `config/storage.config.yaml`
- Данные в `./data/lancedb/`

### rag-db (PostgreSQL 16)
- Основное хранилище метаданных
- Таблицы: domains, vaults, chats, messages, pipelines, documents, tags, campaigns...
- Данные в `./data/postgres/`

### pdf-sidecar (macOS host :8765)
- Не Docker-контейнер, запускается на хосте
- Использует unstructured hi_res (detectron2 + tesseract) для OCR
- Fallback: pdfminer (fast, без OCR)
- URL: `http://host.docker.internal:8765`

## Переменные окружения (`.env`)

```
POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
DATABASE_URL=postgresql+asyncpg://...
OPENAI_API_KEY
ENCRYPTION_KEY   # Fernet-ключ для шифрования API-ключей моделей в БД
STORAGE_API_URL=http://db-api-server:8080
INDEXER_API_URL=http://rag-indexer:9000
```

## Конфигурация (`config/config.yaml`)

Главный конфиг платформы. Определяет:
- `vaults`: хранилища документов (vault_id, domain_id, path)
- `embedding_models`: провайдеры эмбеддингов (ollama, openai_compatible)
- `generation_models`: LLM-провайдеры (только openai_compatible)
- `reranker`: конфиг ре-ранкера (сейчас отключён)
- `chat`: поведение чата (кол-во уточнений, стриминг, авто-заголовок)
- `retrieval`: top_k, reranker_enabled
- `pipelines`: hot-reload из `/app/pipelines`
- `pdf_sidecar`: URL, таймаут, fallback

**Текущие активные модели:**
- Embedding: `dengcao/Qwen3-Embedding-4B:Q4_K_M` (Ollama, 2560 dims)
- Generation: `openrouter/deepseek/deepseek-chat-v3.1` (через proxyapi.ru)

## Домены

Концепция домена — изолированный контекст знаний:
- `dnd` — D&D/TTRPG материалы (активен, vault: `dnd-main`)
- `work` — рабочие документы (отключён)
- `default` — системный домен

Каждый домен имеет:
- Свои системные промты (в БД, тип: system/clarification/planner/pipeline_router)
- Поля уточнения (clarification_fields)
- Привязанные vault-ы с документами
- Пайплайны (DAG-конфигурации)
- Кампании и теги
