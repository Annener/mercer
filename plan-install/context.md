# plan-install: Контекст задачи деплоя

> Дата: 2026-06-27
> Состояние: итоговый контекст после аудита кода и переменных окружения

---

## Что такое Mercer

RAG/LLM-платформа на Python/FastAPI. Состоит из нескольких сервисов:

```
mercer/
├── rag-backend/        FastAPI-бэкенд (порт 8000, публичный)
├── rag-indexer/        сервис индексации документов (порт 9000, внутренний)
├── db-api-server/      LanceDB HTTP API (порт 8080, внутренний)
├── pdf-sidecar/        embedding + reranker сервер на хосте (порт 8765)
├── pdf-sidecar/agent/  host-agent FastAPI (порт 9090) — управление sidecar из Docker
├── scripts/            вспомогательные скрипты
├── Makefile
└── .env.example
```

Целевой сценарий установки на чистый хост:
```
git clone https://github.com/Annener/mercer
cd mercer
make setup
```

---

## Целевое состояние после всех изменений

### Целевой `.env.example`

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

Переменные, **удалённые** из `.env.example` по итогам аудита:

| Переменная | Причина удаления |
|---|---|
| `DATABASE_URL` | Собирается составной в `docker-compose.yml` из `POSTGRES_*` |
| `OPENAI_API_KEY` | API-ключи моделей хранятся зашифрованными в БД (Fernet), через `os.environ` не читаются |
| `VAULTS_PATH` | Путь захардкожен как volume в compose: `./vaults:/data/vaults` |
| `LOGS_PATH` | Путь захардкожен как volume в compose: `./logs:/app/logs` |
| `STATE_PATH` | Путь захардкожен в коде; файловый StateManager полностью заменён Redis |
| `CACHE_PATH` | Кэш эмбеддингов удалён из кода (no-op стаб), volume не используется |
| `WATCHDOG_INTERVAL_SEC` | Переносится в БД + UI (отдельная задача, не входит в эти изменения) |

### Целевой `make setup`

```
make setup
  └─ init-env                → scripts/generate_env.py (интерактивный диалог)
  └─ _agent-setup-dispatch   → диспетчер по AGENT_MODE
       ├─ AGENT_MODE=host    → _agent-setup-launchd (macOS, текущий agent-setup)
       ├─ AGENT_MODE=docker  → no-op (Linux, агент в compose)
       └─ AGENT_MODE=host-win → инструкция по ручной установке (Windows, отложено)
  └─ up                      → docker compose up -d
  └─ seed                    → scripts/seed_models.py
```

---

## Блок A — Чистка мёртвого кода (без зависимостей)

### A1. `docker-compose.yml` — убрать мёртвые volumes у `rag-indexer`

```yaml
# Удалить:
- ./state:/app/state
- ./cache/embeddings:/app/cache/embeddings
```

**Обоснование:**
- `./state` — файловый `state_manager.py` полностью заменён `RedisStateManager` (redis уже в compose).
  Все импорты в коде (`app/main.py`, `indexer_worker.py`, `indexer_service.py`, `vault_watchdog.py`)
  ссылаются только на `redis_state_manager`. Старый модуль помечен DEPRECATED.
- `./cache/embeddings` — кэш эмбеддингов удалён из логики (баг: stale vectors при re-index).
  `rag-indexer/embedding/cache.py` — no-op стаб, функции возвращают None/ничего не делают.

### A2. `docker-compose.yml` — исправить `DATABASE_URL`

В секциях `rag-indexer` и `rag-backend` заменить:
```yaml
# Было:
DATABASE_URL: ${DATABASE_URL:-postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform}

# Стало:
DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-raguser}:${POSTGRES_PASSWORD:-changeme}@rag-db:5432/${POSTGRES_DB:-ragplatform}
```

### A3. `docker-compose.yml` — добавить `profiles` для `INSTALL_MODE`

Для поддержки режима `no-db-api` (разнесённый деплой):
```yaml
db-api-server:
  profiles: ["with-db-api"]

rag-db:
  profiles: ["with-db-api"]
```

`COMPOSE_PROFILES` в `.env` читается Docker Compose автоматически — изменений в Makefile не требует.

> **Открытый вопрос:** При `profiles: ["with-db-api"]` на `db-api-server` + `rag-db` — сервисы без
> профиля (`rag-backend`, `rag-indexer`, `redis`) всё равно поднимаются при `docker compose up`.
> Для сценария `db-api-only` нужна отдельная compose-команда или второй профиль. Решить при реализации.

### A4. Файлы под удаление

- `rag-indexer/parser/state/state_manager.py` — DEPRECATED, ни один production-файл не импортирует
- `rag-indexer/embedding/cache.py` — no-op стаб

  Перед удалением проверить отсутствие импортов:
  ```bash
  grep -r "from embedding.cache\|import cache" rag-indexer/
  grep -r "state_manager" rag-indexer/ | grep -v "redis_state_manager"
  ```

### A5. `.env.example` — привести к целевому виду

Удалить: `DATABASE_URL`, `OPENAI_API_KEY`, `VAULTS_PATH`, `LOGS_PATH`, `STATE_PATH`, `CACHE_PATH`.
Добавить: `INSTALL_MODE`, `AGENT_MODE`, `COMPOSE_PROFILES` (с комментарием «заполняется generate_env.py»).
Исправить: команду генерации `ENCRYPTION_KEY` — убрать зависимость от `cryptography`, использовать stdlib.

---

## Блок B — `scripts/generate_env.py`

Интерактивный Python-скрипт (только stdlib) для подготовки `.env` при первом `make setup`.

### Поведение

**Идемпотентность:**
- `.env` не существует → создать из `.env.example`, пройти диалог
- `.env` существует, все переменные заполнены корректно → выйти молча
- `.env` существует, часть переменных пустые/placeholder → спросить только недостающие

**Диалог:**

| Переменная | Режим | Логика |
|---|---|---|
| `INSTALL_MODE` | Интерактивный | Первый вопрос. `full` / `db-api-only` / `no-db-api` |
| `POSTGRES_USER` | Интерактивный | Дефолт `raguser` |
| `POSTGRES_PASSWORD` | Интерактивный | (g)енерировать / (с)вой; свой — через `getpass.getpass()` |
| `POSTGRES_DB` | Интерактивный | Дефолт `ragplatform` |
| `STORAGE_API_URL` | Интерактивный | Только при `INSTALL_MODE=no-db-api` |
| `ENCRYPTION_KEY` | Автоматический | Fernet-ключ через stdlib; не перезаписывать если уже 44 символа |
| `HOST_AGENT_TOKEN` | Автоматический | `secrets.token_urlsafe(32)`; не перезаписывать если не `changeme` и не пусто |
| `AGENT_MODE` | Автоматический | `platform.system()`: Darwin→`host`, Linux→`docker`, Windows→`host-win` |
| `COMPOSE_PROFILES` | Вычисляется | `full`/`db-api-only` → `with-db-api`; `no-db-api` → пусто |
| `HOST_AGENT_URL` | Вычисляется | `host`/`host-win` → `http://host.docker.internal:9090`; `docker` → `http://host-agent:9090` |

**Генерация секретов (только stdlib):**
```python
import base64, secrets

def generate_fernet_key() -> str:
    # urlsafe base64, 32 байта → всегда ровно 44 символа
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

def generate_token() -> str:
    return secrets.token_urlsafe(32)  # ~43 символа

def generate_password() -> str:
    return secrets.token_urlsafe(16)  # ~22 символа
```

**Запись в `.env`:**
```python
import re

def set_env_value(content: str, key: str, value: str) -> str:
    pattern = rf'^{re.escape(key)}=.*$'
    return re.sub(pattern, f'{key}={value}', content, flags=re.MULTILINE)
```

**Валидация «уже задано»:**
- `ENCRYPTION_KEY` — длина значения == 44 символа
- `HOST_AGENT_TOKEN` — не пустое и не `changeme`
- `POSTGRES_PASSWORD` — не пустое и не `changeme`

### Интеграция в Makefile

```makefile
init-env:
	python3 scripts/generate_env.py
```

`init-env` должен быть **первым** в `setup` — `agent-setup` и `up` читают `.env`.

---

## Блок C — Makefile: мультиплатформенный `agent-setup`

### C1. Диспетчер по `AGENT_MODE`

Заменить прямой вызов `agent-setup: _check-macos ...` на диспетчерскую цель:

```makefile
_agent-setup-dispatch:
	@AGENT_MODE=$$(grep '^AGENT_MODE=' .env | cut -d= -f2); \
	if [ "$$AGENT_MODE" = "host" ]; then \
	    $(MAKE) _agent-setup-launchd; \
	elif [ "$$AGENT_MODE" = "docker" ]; then \
	    echo "Linux: host-agent запускается в Docker, пропускаю agent-setup"; \
	else \
	    echo "Windows: запустите scripts/install-service.ps1 вручную"; \
	fi

# Переименовать текущий agent-setup в:
_agent-setup-launchd: _venv-create agent-install
```

### C2. Прокинуть `HOST_AGENT_TOKEN` в plist

**Проблема:** `HOST_AGENT_TOKEN` в plist-шаблоне закомментирован → host-agent запускается
без токена → авторизация де-факто отключена, даже если backend шлёт токен.

**Файл:** `pdf-sidecar/agent/com.mercer.host-agent.plist.template`
Раскомментировать и добавить placeholder:
```xml
<key>HOST_AGENT_TOKEN</key>
<string>{{HOST_AGENT_TOKEN}}</string>
```

**В `_render-plist`** добавить подстановку токена:
```makefile
_render-plist:
	@HOST_AGENT_TOKEN=$$(grep '^HOST_AGENT_TOKEN=' .env | cut -d= -f2); \
	sed \
	    -e 's|{{VENV_PYTHON}}|$(VENV_PYTHON)|g' \
	    -e 's|{{AGENT_PY}}|$(AGENT_PY)|g' \
	    -e 's|{{AGENT_DIR}}|$(AGENT_DIR)|g' \
	    -e 's|{{SIDECAR_DIR}}|$(SIDECAR_DIR)|g' \
	    -e 's|{{PATH}}|$(PATH)|g' \
	    -e "s|{{HOST_AGENT_TOKEN}}|$$HOST_AGENT_TOKEN|g" \
	    "$(PLIST_TEMPLATE)" > "$(PLIST_DST)"
```

**Порядок** `init-env → _agent-setup-dispatch` строго соблюдать: plist рендерится
уже с финальным токеном из `.env`.

---

## Что уже готово (не трогать)

### `scripts/seed_models.py` ✓

Ждёт доступности rag-backend (`/health`, 15 ретраев по 2 сек), затем:
- `POST /api/settings/models/embedding/` — создаёт embedding-модель `sidecar_bge_m3`
- `POST /api/settings/models/rerank/` — создаёт reranker `bge-reranker-v2-m3`
- `POST /api/settings/models/rerank/{id}/activate` — активирует reranker

Идемпотентен: HTTP 409/422 молча пропускается. Вызывается через `make seed`.

### `make seed`, `make up`, базовый `make setup` ✓

Текущий `setup: agent-setup up seed` работает на macOS. После Блока C будет заменён на
`setup: init-env _agent-setup-dispatch up seed`.

---

## Открытые вопросы

### Pydantic-схема reranker

Нужно подтвердить наличие поля `timeout_seconds` в модели reranker.
Файл: `rag-backend/app/api/settings/rerank_models.py`
Если поля нет — убрать из `seed_models.py`.

### Активация embedding-модели

У reranker есть `POST /api/settings/models/rerank/{id}/activate`.
У embedding судя по роутам — нет `/activate`. Проверить: привязывается ли
embedding к vault через `/bind` на vault'е, или просто создание записи достаточно.
Файл для проверки: `rag-backend/app/api/settings/emb_models.py`

---

## Справочные данные

### HOST_AGENT_TOKEN: как работает авторизация

```
.env (HOST_AGENT_TOKEN)
    ↓
docker-compose.yml → rag-backend environment
    ↓
rag-backend/app/api/settings/sidecar.py → os.getenv("HOST_AGENT_TOKEN")
    ↓
HTTP-запрос к host-agent с заголовком X-Agent-Token
    ↓
pdf-sidecar/agent/agent.py → check_token(x_agent_token)
```

Если `HOST_AGENT_TOKEN` не задан в окружении агента — авторизация отключена.

### ENCRYPTION_KEY: требования к формату

Backend (`rag-backend/app/services/settings_service.py`) и indexer
(`rag-indexer/app/db_client.py`) передают ключ в `Fernet(key.encode("utf-8"))`.
Ключ обязан быть urlsafe base64 от ровно 32 байт → всегда 44 символа.

### Режимы деплоя

| `INSTALL_MODE` | Что поднимается | Сценарий |
|---|---|---|
| `full` | Все сервисы | Один хост, всё вместе |
| `db-api-only` | `db-api-server` + `rag-db` | Выделенный хост под хранилище |
| `no-db-api` | Всё кроме `db-api-server` | Основной хост при разнесённом деплое |

| `AGENT_MODE` | Где агент | ОС |
|---|---|---|
| `host` | Процесс на хосте (venv + launchd) | macOS |
| `docker` | Контейнер в compose | Linux |
| `host-win` | Процесс на хосте (venv + Task Scheduler) | Windows (отложено) |
