# Аудит переменных .env.example

> Дата: 2026-06-27  
> Контекст: подготовка к `make setup`, чистка `.env.example` от мёртвых переменных

---

## Переменные на удаление из `.env.example`

### `OPENAI_API_KEY`
- **Статус:** ❌ удалить
- **Причина:** API-ключи генерационных моделей хранятся зашифрованными в БД в поле `encrypted_api_key` (Fernet, ключ — `ENCRYPTION_KEY`). Переменная окружения `OPENAI_API_KEY` нигде в коде не читается через `os.environ`. Упоминание в `config/config.yaml` (`api_key_env: "OPENAI_API_KEY"`) — устаревший механизм, не задействованный в runtime.
- **Файлы подтверждения:** `rag-backend/app/services/settings_service.py`, `rag-backend/app/api/settings/gen_models.py`, `rag-indexer/indexer_worker.py`

### `DATABASE_URL`
- **Статус:** ❌ удалить из `.env.example`, переделать в составную в `docker-compose.yml`
- **Причина:** Значение дублирует `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`. Лучше собирать прямо в `docker-compose.yml`:
  ```yaml
  DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-raguser}:${POSTGRES_PASSWORD:-changeme}@rag-db:5432/${POSTGRES_DB:-ragplatform}
  ```
  Затронуты два сервиса: `rag-indexer` и `rag-backend`.
- **Файлы для правки:** `docker-compose.yml` (оба сервиса)

### `VAULTS_PATH`
- **Статус:** ❌ удалить
- **Причина:** Нигде не читается через `os.getenv`. Путь к vaults захардкожен как volume в `docker-compose.yml`: `./vaults:/data/vaults:rw`.

### `LOGS_PATH`
- **Статус:** ❌ удалить
- **Причина:** Нигде не читается через `os.getenv`. Путь захардкожен как volume: `./logs:/app/logs`.

### `STATE_PATH`
- **Статус:** ❌ удалить
- **Причина:** Нигде не читается через `os.getenv`. В коде захардкожены константы:
  ```python
  # rag-indexer/parser/state/state_manager.py
  STATE_PATH = Path("/app/state/index_state.json")
  ```
  Volume в compose: `./state:/app/state`.

### `CACHE_PATH`
- **Статус:** ❌ удалить
- **Причина:** Нигде не читается через `os.getenv`. Volume в compose: `./cache/embeddings:/app/cache/embeddings`.

---

## Переменные, которые остаются

| Переменная | Причина оставить |
|---|---|
| `POSTGRES_USER` | Используется postgres-контейнером и в составной `DATABASE_URL` |
| `POSTGRES_PASSWORD` | То же |
| `POSTGRES_DB` | То же |
| `ENCRYPTION_KEY` | Критично — Fernet-ключ шифрования API-ключей моделей |
| `STORAGE_API_URL` | Читается через `os.getenv()` в 5 местах: `retrieval.py`, `helpers.py`, `db_management.py`, `indexer_worker.py`, `main.py` (rag-indexer) |
| `WATCHDOG_INTERVAL_SEC` | Читается в `rag-indexer/app/main.py` |
| `HOST_AGENT_URL` | Читается в `rag-backend` для связи с host-agent |
| `HOST_AGENT_TOKEN` | Секрет авторизации host-agent — требует проверки на автогенерацию (см. открытый вопрос #4 в context.md) |

---

## Целевой `.env.example` после чистки

```dotenv
POSTGRES_USER=raguser
POSTGRES_PASSWORD=changeme
POSTGRES_DB=ragplatform
ENCRYPTION_KEY=<generate with: python -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())">
STORAGE_API_URL=http://db-api-server:8080

# Vault Watchdog
WATCHDOG_INTERVAL_SEC=60

# Host Agent — управление pdf-sidecar с хоста
# Запустите host-agent/agent.py на хосте перед запуском Docker
HOST_AGENT_URL=http://host.docker.internal:9090
HOST_AGENT_TOKEN=changeme
```

**Примечание по `ENCRYPTION_KEY`:** команда генерации заменена на stdlib (без зависимости от `cryptography`), что корректно для хоста при первом `make setup`.

---

## Правки в `docker-compose.yml`

Заменить в секциях `rag-indexer` и `rag-backend`:
```yaml
# Было:
DATABASE_URL: ${DATABASE_URL:-postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform}

# Стало:
DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-raguser}:${POSTGRES_PASSWORD:-changeme}@rag-db:5432/${POSTGRES_DB:-ragplatform}
```
