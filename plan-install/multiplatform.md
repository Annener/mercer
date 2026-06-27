# plan-install: Мультиплатформенный деплой

> Дата: 2026-06-27  
> Контекст: проектирование точек изменений для будущей поддержки Linux / Windows  
> Текущая реализация: macOS (полный сценарий)

---

## Принцип

Текущая реализация пишется под macOS, но **без хардкода**, который нельзя убрать за одну правку.  
Все платформо-зависимые точки параметризуются уже сейчас через переменные `.env` и профили compose,  
даже если Linux/Windows ветки будут реализованы позже.

---

## Режимы установки (`INSTALL_MODE`)

Первичное ветвление — **не по ОС**, а по тому, *что* разворачивается на хосте.

| `INSTALL_MODE` | Что запускается | Типичный сценарий |
|---|---|---|
| `full` | Всё: rag-backend, rag-indexer, db-api-server, postgres, redis, host-agent | Единственный хост, всё на одной машине |
| `db-api-only` | Только `db-api-server` + `rag-db` | Выделенный хост под хранилище |
| `no-db-api` | Всё кроме `db-api-server` — он уже поднят отдельно | Основной хост при разнесённом деплое |

`generate_env.py` спрашивает `INSTALL_MODE` **первым**, до остальных вопросов.  
При `no-db-api` — дополнительно спрашивает `STORAGE_API_URL` (адрес удалённого db-api-server).

### Сценарий разнесённого деплоя

```
Хост A (db-api-server):
  git clone https://github.com/Annener/mercer
  cd mercer
  make setup          # INSTALL_MODE=db-api-only → поднимает только db-api-server + postgres

Хост B (основной):
  git clone https://github.com/Annener/mercer
  cd mercer
  make setup          # INSTALL_MODE=no-db-api → спрашивает STORAGE_API_URL=http://host-a:8080
```

---

## Режим агента (`AGENT_MODE`)

Определяет, где живёт `host-agent` и `pdf-sidecar`.

| `AGENT_MODE` | Где агент | ОС | init-система |
|---|---|---|---|
| `host` | Процесс на хосте (venv) | macOS | launchd |
| `docker` | Контейнер в compose | Linux | — (compose manages) |
| `host-win` | Процесс на хосте (venv) | Windows | Task Scheduler / NSSM |

`generate_env.py` определяет `AGENT_MODE` автоматически через `platform.system()`:
- `Darwin` → `host`
- `Linux` → `docker`
- `Windows` → `host-win` *(ветка реализуется позже)*

> **Windows + CUDA:** WSL2 + NVIDIA поддерживается официально, но стек нестабилен.  
> Для Windows оставляем `AGENT_MODE=host-win` (venv на хосте), GPU-контейнер не закладываем.

---

## Реестр точек изменений

### 1. `Makefile` — `_check-macos` и `agent-setup`

**Текущий хардкод:**
```makefile
agent-setup: _check-macos _venv-create agent-install
_check-macos:
    @if [ "$$(uname -s)" != "Darwin" ]; then exit 1; fi
```

**Что изменить сейчас:**  
Переименовать `_check-macos` → `_require-agent-mode-host`, проверять `AGENT_MODE` из `.env`,  
а не `uname`. Ввести диспетчерскую цель:

```makefile
_agent-setup-dispatch:
    @AGENT_MODE=$$(grep '^AGENT_MODE=' .env | cut -d= -f2); \
    if [ "$$AGENT_MODE" = "host" ]; then \
        $(MAKE) _agent-setup-launchd; \
    elif [ "$$AGENT_MODE" = "docker" ]; then \
        echo "Linux: host-agent runs in Docker, skipping agent-setup"; \
    else \
        echo "$(YELLOW)Windows: run scripts/install-service.ps1 manually$(RESET)"; \
    fi

setup: init-env _agent-setup-dispatch up seed
```

На Linux `_agent-setup-dispatch` = no-op: агент поднимается через `docker compose up`.

---

### 2. `_render-plist` — добавить `HOST_AGENT_TOKEN` сейчас

**Текущий хардкод:**  
`_render-plist` подставляет только пути (`VENV_PYTHON`, `AGENT_PY`, `AGENT_DIR`, `SIDECAR_DIR`, `PATH`).  
`HOST_AGENT_TOKEN` в plist-шаблоне закомментирован.

**Что изменить сейчас** (до Linux-ветки):

1. Раскомментировать `HOST_AGENT_TOKEN` в `com.mercer.host-agent.plist.template`
2. Добавить в `_render-plist`:
   ```makefile
   -e 's|{{HOST_AGENT_TOKEN}}|$(HOST_AGENT_TOKEN)|g' \
   ```
3. `HOST_AGENT_TOKEN` читать из `.env` перед вызовом `_render-plist`

На Linux/Windows аналогами plist будут systemd unit / NSSM config — другой шаблон, та же переменная.

---

### 3. `HOST_AGENT_URL` — значение зависит от `AGENT_MODE`

**Текущий дефолт в compose:**
```yaml
HOST_AGENT_URL: ${HOST_AGENT_URL:-http://host.docker.internal:9090}
```

| `AGENT_MODE` | `HOST_AGENT_URL` |
|---|---|
| `host` | `http://host.docker.internal:9090` |
| `docker` | `http://host-agent:9090` |
| `host-win` | `http://host.docker.internal:9090` |

`generate_env.py` записывает значение автоматически по определённому `AGENT_MODE`.  
Дефолт в compose оставить как есть (`host.docker.internal`) — он корректен для macOS/Windows.

---

### 4. `docker-compose.yml` — профили для `INSTALL_MODE`

**Что добавить:**

```yaml
db-api-server:
  profiles: ["with-db-api"]   # не запускается если профиль не указан
  ...

rag-db:
  profiles: ["with-db-api"]   # связан с db-api-server
  ...
```

Docker Compose читает `COMPOSE_PROFILES` из `.env` автоматически — без изменений в `Makefile`:

```dotenv
# .env (генерируется generate_env.py)
COMPOSE_PROFILES=with-db-api          # INSTALL_MODE=full или db-api-only
# COMPOSE_PROFILES=                   # INSTALL_MODE=no-db-api → db-api-server не поднимается
```

При `INSTALL_MODE=db-api-only` в compose включается только `db-api-server` + `rag-db` —  
остальные сервисы (`rag-backend`, `rag-indexer`, `redis`) не имеют профиля и **не** запускаются.

> ⚠️ Сервисы без `profiles:` (rag-backend, rag-indexer, redis) запускаются всегда при `docker compose up`.  
> Для `db-api-only` нужна отдельная compose-команда или второй профильный файл. Решить при реализации.

---

### 5. `STORAGE_API_URL` — зависит от `INSTALL_MODE`

| `INSTALL_MODE` | `STORAGE_API_URL` |
|---|---|
| `full` | `http://db-api-server:8080` (локальный compose-сервис) |
| `db-api-only` | не используется в этом режиме |
| `no-db-api` | `http://<remote-host>:8080` — **спрашивать у пользователя** |

---

### 6. `extra_hosts` — уже решено корректно

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

На macOS/Windows Docker Desktop `host.docker.internal` работает автоматически, запись безвредна.  
На Linux без этой записи `host.docker.internal` не резолвится — запись обязательна.  
**Трогать не нужно**, текущий вариант корректен для всех платформ.

---

## Целевые переменные в `.env`

Новые переменные, которые добавляет `generate_env.py`:

```dotenv
# --- Режим установки ---
INSTALL_MODE=full              # full | db-api-only | no-db-api
AGENT_MODE=host                # host | docker | host-win

# --- Compose профили (вычисляется из INSTALL_MODE) ---
COMPOSE_PROFILES=with-db-api

# --- Адрес db-api-server (только при INSTALL_MODE=no-db-api) ---
# STORAGE_API_URL=http://192.168.1.10:8080
```

---

## Что реализовать сейчас (macOS-итерация)

Минимальный набор правок, закладывающих мультиплатформенность без реализации Linux/Windows:

| # | Что | Где |
|---|---|---|
| 1 | Добавить `{{HOST_AGENT_TOKEN}}` в plist-шаблон | `pdf-sidecar/agent/com.mercer.host-agent.plist.template` |
| 2 | Читать `HOST_AGENT_TOKEN` из `.env` в `_render-plist` | `Makefile` |
| 3 | Переименовать `_check-macos` → `_require-agent-mode-host`, проверять `AGENT_MODE` | `Makefile` |
| 4 | Ввести `_agent-setup-dispatch`, вызывать из `setup` | `Makefile` |
| 5 | Добавить `profiles: ["with-db-api"]` на `db-api-server` и `rag-db` | `docker-compose.yml` |
| 6 | `generate_env.py` спрашивает `INSTALL_MODE`, пишет `AGENT_MODE` + `COMPOSE_PROFILES` | `scripts/generate_env.py` |

---

## Что отложено на Linux/Windows итерации

- Systemd unit шаблон для `AGENT_MODE=docker` (Linux host-agent как сервис — если понадобится)
- `NSSM` / Task Scheduler шаблон для `AGENT_MODE=host-win`
- GPU: `deploy.resources.reservations.devices` в compose для `rag-indexer` на Linux
- PowerShell-обёртка `setup.ps1` для Windows (замена `make`)
- Полное тестирование `INSTALL_MODE=db-api-only` изоляции в compose
