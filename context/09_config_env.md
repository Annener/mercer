# Mercer — Конфигурация и переменные окружения

> **Проход 9 из N.**
> Все env-переменные, конфиг-файлы и дефолты по каждому сервису.

---

## Переменные окружения (`.env`)

Все сервисы подключают `.env` через `env_file: .env` в `docker-compose.yml`.

| Переменная | Обязательна | Дефолт | Описание |
|---|---|---|---|
| `POSTGRES_USER` | нет | `raguser` | Пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | нет | `changeme` | Пароль PostgreSQL |
| `POSTGRES_DB` | нет | `ragplatform` | Имя базы данных |
| `DATABASE_URL` | нет | `postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform` | AsyncPG URL для `rag-backend` и `rag-indexer` |
| `DB_API_URL` | нет | `http://db-api-server:8080` | URL db-api-server для rag-backend |
| `STORAGE_API_URL` | нет | `http://db-api-server:8080` | URL db-api-server для rag-indexer и rag-backend |
| `INDEXER_API_URL` | нет | `http://rag-indexer:9000` | URL rag-indexer для rag-backend |
| `ENCRYPTION_KEY` | **да** | — | Ключ шифрования (Fernet). Обязателен для rag-backend и rag-indexer |

> **`ENCRYPTION_KEY`** — единственная переменная без дефолта. Генерируется через `cryptography.fernet.Fernet.generate_key()`. Используется для шифрования чувствительных данных (API-ключи моделей).

---

## Сервис: `rag-backend`

**Порт:** `8000` (единственный сервис с проброшенным портом наружу).

### Env-переменные

| Переменная | Источник | Описание |
|---|---|---|
| `DATABASE_URL` | `.env` | PostgreSQL DSN |
| `DB_API_URL` | `.env` | URL db-api-server |
| `STORAGE_API_URL` | `.env` | Алиас для db-api-server |
| `INDEXER_API_URL` | `.env` | URL rag-indexer |
| `ENCRYPTION_KEY` | `.env` | Ключ шифрования |
| `SERVICE_PORT` | docker-compose | `8000` |

### Volumes

| Host | Container | Режим |
|---|---|---|
| `./logs` | `/app/logs` | rw |
| `./rag-backend/app/static` | `/app/app/static` | ro |
| `./vaults` | `/data/vaults` | rw |

### Конфиг-класс (`rag-backend/app/config.py`)

Конфигурация хранится в PostgreSQL (таблица `platform_settings`) и управляется через `settings_service`. Файловый `AppConfig` (Pydantic) описывает структуру, но **не используется напрямую** — настройки берутся из БД.

| Раздел | Класс | Ключевые поля |
|---|---|---|
| Vaults | `VaultConfig` | `vault_id`, `domain_id`, `path`, `enabled` |
| Embedding | `EmbeddingModelConfig` | `model_id`, `provider`, `model_name`, `base_url`, `dimensions` |
| Generation | `GenerationModelConfig` | `model_id`, `provider`, `base_url`, `api_key_env` |
| Reranker | `RerankerConfig` | `enabled`, `provider`, `base_url`, `model_name` |
| Chat | `ChatConfig` | `max_clarification_turns`, `stream_answers`, `auto_title` |
| Retrieval | `RetrievalConfig` | `top_k` (дефолт 10), `reranker_enabled` |
| Pipelines | `PipelinesConfig` | `enabled`, `path`, `reload_interval_seconds` |
| UI | `UIConfig` | `db_management_enabled` |

---

## Сервис: `db-api-server`

**Порт:** `8080` (только внутри `rag-net`, наружу не пробрасывается).

### Env-переменные

| Переменная | Дефолт | Описание |
|---|---|---|
| `SERVICE_PORT` | `8080` | HTTP-порт |

### Volumes

| Host | Container | Режим |
|---|---|---|
| `./config/storage.config.yaml` | `/app/config.yaml` | ro |
| `./data/lancedb` | `/data/lancedb` | rw |
| `./logs` | `/app/logs` | rw |

### Файл конфига `config/storage.config.yaml`

```yaml
lancedb:
  data_path: /data/lancedb
  cache_size_mb: 256
host: 0.0.0.0
port: 8080
log_level: INFO
```

---

## Сервис: `rag-indexer`

**Порт:** `9000` (только внутри `rag-net`, наружу не пробрасывается).

### Env-переменные

| Переменная | Дефолт | Описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform` | PostgreSQL DSN |
| `ENCRYPTION_KEY` | — | Ключ шифрования (**обязателен**) |
| `STORAGE_API_URL` | `http://db-api-server:8080` | URL db-api-server |
| `SERVICE_PORT` | `9000` | HTTP-порт |

### Volumes

| Host | Container | Режим |
|---|---|---|
| `./vaults` | `/data/vaults` | rw |
| `./state` | `/app/state` | rw |
| `./cache/embeddings` | `/app/cache/embeddings` | rw |
| `./logs` | `/app/logs` | rw |

---

## Сервис: `rag-db` (PostgreSQL)

**Образ:** `postgres:16`

### Env-переменные

| Переменная | Дефолт |
|---|---|
| `POSTGRES_USER` | `raguser` |
| `POSTGRES_PASSWORD` | `changeme` |
| `POSTGRES_DB` | `ragplatform` |

### Volumes

| Host | Container |
|---|---|
| `./data/postgres` | `/var/lib/postgresql/data` |

---

## Сеть

Все сервисы в одной bridge-сети `rag-net`.

| Сервис | Внутренний хост | Порт | Наружу |
|---|---|---|---|
| `rag-backend` | `rag-backend` | 8000 | **да** (`0.0.0.0:8000`) |
| `db-api-server` | `db-api-server` | 8080 | нет |
| `rag-indexer` | `rag-indexer` | 9000 | нет |
| `rag-db` | `rag-db` | 5432 | нет |

---

## platform_settings — runtime-ключи (хранятся в PostgreSQL)

Настройки, которые меняются через UI без рестарта. Хранятся в таблице `platform_settings`.

| Ключ | Тип | Дефолт | Описание |
|---|---|---|---|
| `retrieval.top_k` | int | 10 | Количество результатов retrieval |
| `retrieval.score_threshold` | float | 0.0 | Минимальный порог релевантности |
| `planner.enabled` | bool | false | Включить planner |
| `clarification.enabled` | bool | false | Включить clarification FSM |
| `clarification.max_turns` | int | 3 | Максимум ходов FSM |
| `generation.active_model_id` | str | — | ID активной generation-модели |
| `embedding.active_model_id` | str | — | ID активной embedding-модели |
| `reranker.enabled` | bool | false | Включить reranker |

---

## Зависимости запуска (healthcheck-цепочка)

```
rag-db (postgres:healthy)
    └─► db-api-server (curl /health: healthy)
            ├─► rag-indexer (curl /health: healthy)
            └─► rag-backend (curl /health: healthy)
```

`rag-backend` также зависит напрямую от `rag-db`.

---

## Логирование

Все сервисы монтируют `./logs → /app/logs`.

Docker logging driver: `local`, `max-size: 50m`, `max-file: 5`.

Уровень логирования для `db-api-server` задаётся в `storage.config.yaml` (`log_level: INFO`).
Для остальных сервисов — через `logging_config.py` (structlog/стандартный logging).
