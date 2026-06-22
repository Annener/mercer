# Архитектура Mercer

## Назначение проекта

Mercer — мультидоменная RAG-платформа для работы с документами через LLM.
Поддерживает несколько доменов знаний (dnd, work, default), каждый со своими промптами,
кампаниями, хранилищами документов (Vault) и пайплайнами обработки запросов.

## Сервисы (docker-compose)

```
┌─────────────────────────────────────────────────────────┐
│                        rag-net                          │
│                                                         │
│  rag-backend :8000  ←──→  rag-indexer :9000 (internal) │
│       │                        │                        │
│       │                   db-api-server :8080           │
│       │                        │                        │
│       └──────→  rag-db (PostgreSQL :5432)               │
│                 redis :6379                             │
│                 lancedb (volume /data/lancedb)          │
└─────────────────────────────────────────────────────────┘
```

### rag-backend
- **Роль**: главный API-сервис, единственный порт наружу (8000)
- **Стек**: FastAPI + SQLAlchemy async + asyncpg
- **Расположение**: `rag-backend/`
- Обрабатывает чаты, пайплайны, настройки, документы
- Проксирует запросы к rag-indexer через внутренний HTTP
- Хранит состояние в PostgreSQL, сессии чатов в Redis
- Раздаёт SPA-фронтенд из `app/static/`

### rag-indexer
- **Роль**: асинхронный воркер индексации документов
- **Стек**: FastAPI (HTTP API для управления) + собственный воркер
- **Расположение**: `rag-indexer/`
- Не доступен снаружи — только через rag-backend
- Читает файлы из vault (`/data/vaults`), парсит через pdf-sidecar
- Создаёт чанки, вычисляет эмбеддинги, сохраняет в LanceDB через db-api-server
- Watchdog: периодически проверяет изменения файлов в vault

### db-api-server
- **Роль**: HTTP-обёртка над LanceDB (векторное хранилище)
- **Расположение**: `db-api-server/`
- Один экземпляр LanceDB на весь проект (файловая БД: `/data/lancedb`)
- API: CRUD чанков, векторный поиск, BM25 full-text search
- Конфиг: `config/storage.config.yaml`

### pdf-sidecar
- **Роль**: внешний Python-сервис парсинга PDF
- **Расположение**: `pdf-sidecar/`
- **Запуск**: отдельно, НЕ в docker-compose (скрипты start.sh/stop.sh)
- Использует pdfminer / pymupdf для извлечения текста
- Предоставляет reranker-функциональность (`reranker.py`)
- rag-indexer обращается к нему по HTTP при индексации PDF

### PostgreSQL (rag-db)
- Основная реляционная БД
- Хранит: домены, вольты, документы, чаты, сообщения, пайплайны, модели
- Миграции: `rag-backend/app/db/migrations.py` (кастомные, не Alembic)

### Redis
- Используется для: состояния индексатора (IndexState), кэширования
- `RedisStateManager` живёт в rag-indexer
- rag-backend читает состояние напрямую через `aioredis`

## Общая структура репозитория

```
mercer/
├── rag-backend/         # Главный API (FastAPI)
│   └── app/
│       ├── api/         # HTTP роутеры
│       ├── db/          # ORM-модели, сессии, миграции
│       ├── services/    # Бизнес-логика (retrieval, pipeline, planner...)
│       ├── providers/   # Провайдеры генерации (OpenAI-compatible)
│       ├── domains/     # Домены (dnd, work, default) + registry
│       ├── pipelines/   # Pipeline registry
│       └── static/      # SPA-фронтенд (Vue)
├── rag-indexer/         # Индексатор
│   ├── app/             # FastAPI app + db_client
│   ├── api/             # API роутеры индексатора
│   ├── embedding/       # Провайдеры эмбеддингов (ollama, openai)
│   ├── parser/          # Парсеры документов
│   ├── storage/         # HTTP-клиент к db-api-server
│   └── indexer_worker.py # Основной воркер индексации
├── db-api-server/       # LanceDB HTTP API
│   ├── api/             # Роутеры
│   └── storage/
│       └── lancedb_store.py  # Вся логика LanceDB
├── pdf-sidecar/         # PDF-парсер (внешний сервис)
├── shared_contracts/
│   └── models.py        # Общие Pydantic-схемы между сервисами
├── config/
│   └── storage.config.yaml  # Конфиг LanceDB
├── tests/               # Интеграционные тесты
├── docker-compose.yml
└── .env.example
```

## Переменные окружения (ключевые)

| Переменная | Сервис | Назначение |
|---|---|---|
| `DATABASE_URL` | backend, indexer | postgresql+asyncpg://... |
| `DB_API_URL` | backend | URL db-api-server |
| `STORAGE_API_URL` | backend, indexer | URL db-api-server |
| `INDEXER_API_URL` | backend | URL rag-indexer |
| `REDIS_URL` | backend, indexer | redis://redis:6379 |
| `ENCRYPTION_KEY` | backend, indexer | Ключ шифрования API-ключей моделей |
| `WATCHDOG_INTERVAL_SEC` | indexer | Интервал watchdog (сек) |
