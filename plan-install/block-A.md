# Блок A — Чистка мёртвого кода

> Зависимостей нет. Можно выполнять первым.

---

## A1. `docker-compose.yml` — убрать мёртвые volumes у `rag-indexer`

**Удалить** из секции `rag-indexer.volumes`:

```yaml
# Удалить эти две строки:
- ./state:/app/state
- ./cache/embeddings:/app/cache/embeddings
```

**Почему безопасно:**
- `./state` — файловый `state_manager.py` полностью заменён `RedisStateManager`. Все импорты в `app/main.py`, `indexer_worker.py`, `indexer_service.py`, `vault_watchdog.py` ссылаются только на `redis_state_manager`.
- `./cache/embeddings` — `rag-indexer/embedding/cache.py` является no-op стабом (функции возвращают `None`).

---

## A2. `docker-compose.yml` — исправить `DATABASE_URL`

В секциях `rag-indexer` и `rag-backend` заменить:

```yaml
# Было:
DATABASE_URL: ${DATABASE_URL:-postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform}

# Стало:
DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-raguser}:${POSTGRES_PASSWORD:-changeme}@rag-db:5432/${POSTGRES_DB:-ragplatform}
```

**Почему:** `DATABASE_URL` удалена из `.env.example`. Compose должен сам собирать строку из отдельных переменных.

---

## A3. `docker-compose.yml` — добавить `profiles` для `INSTALL_MODE`

Добавить в каждый сервис секцию `profiles`:

```yaml
services:
  rag-backend:
    profiles: ["with-db-api", "core"]

  rag-indexer:
    profiles: ["with-db-api", "core"]

  redis:
    profiles: ["with-db-api", "core"]

  rag-db:
    profiles: ["with-db-api", "core"]

  db-api-server:
    profiles: ["with-db-api", "db-api-only"]
```

**Маппинг `INSTALL_MODE` → `COMPOSE_PROFILES`:**

| `INSTALL_MODE` | `COMPOSE_PROFILES` | Что поднимается |
|---|---|---|
| `full` | `with-db-api` | Все сервисы |
| `no-db-api` | `core` | Всё кроме `db-api-server` |
| `db-api-only` | `db-api-only` | Только `db-api-server` |

`COMPOSE_PROFILES` из `.env` Docker Compose читает автоматически — правки в Makefile не нужны.

---

## A4. Удалить файлы мёртвого кода

Перед удалением **проверить отсутствие импортов**:

```bash
grep -r "from embedding.cache\|import cache" rag-indexer/
grep -r "state_manager" rag-indexer/ | grep -v "redis_state_manager"
```

Если вывод пуст — безопасно удалять:

```bash
rm rag-indexer/parser/state/state_manager.py
rm rag-indexer/embedding/cache.py
```

---

## A5. `.env.example` — привести к целевому виду

**Удалить переменные:**
- `DATABASE_URL`
- `OPENAI_API_KEY`
- `VAULTS_PATH`
- `LOGS_PATH`
- `STATE_PATH`
- `CACHE_PATH`

**Добавить переменные** (с комментарием «заполняется `generate_env.py` автоматически»):
- `INSTALL_MODE`
- `AGENT_MODE`
- `COMPOSE_PROFILES`

**Исправить** команду генерации `ENCRYPTION_KEY` — убрать зависимость от `cryptography`, использовать только stdlib:

```dotenv
ENCRYPTION_KEY=<generate with: python -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())">
```

**Целевой `.env.example`:**

```dotenv
POSTGRES_USER=raguser
POSTGRES_PASSWORD=changeme
POSTGRES_DB=ragplatform
ENCRYPTION_KEY=<generate with: python -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())">

STORAGE_API_URL=http://db-api-server:8080

# Host Agent — управление pdf-sidecar с хоста
HOST_AGENT_URL=http://host.docker.internal:9090
HOST_AGENT_TOKEN=changeme

# Режим установки (заполняется generate_env.py автоматически)
INSTALL_MODE=full
AGENT_MODE=host
COMPOSE_PROFILES=with-db-api
```
