# plan-install: Интерактивная инициализация .env

## Цель

При первом `make setup` на чистом хосте скрипт `scripts/generate_env.py` проводит
пользователя через интерактивный диалог и формирует полностью заполненный `.env`
без ручного редактирования файла.

---

## Поведение скрипта

### Идемпотентность (главное правило)

- Если `.env` **не существует** — создать из `.env.example`, затем пройти диалог
- Если `.env` **существует** и все переменные заполнены корректно — выйти молча,
  ничего не спрашивать, ничего не перезаписывать
- Если `.env` существует но **часть переменных пустые/placeholder** — спросить
  только по недостающим

### Диалог по переменным

| Переменная | Режим | Поведение |
|---|---|---|
| `POSTGRES_USER` | Интерактивный | Предложить дефолт `raguser`, пользователь может изменить |
| `POSTGRES_PASSWORD` | Интерактивный | (g)енерировать / (с)вой. При вводе своего — `getpass.getpass()` |
| `POSTGRES_DB` | Интерактивный | Предложить дефолт `ragplatform`, пользователь может изменить |
| `ENCRYPTION_KEY` | Автоматический | Генерировать через stdlib, не спрашивать |
| `HOST_AGENT_TOKEN` | Автоматический | Генерировать через stdlib, не спрашивать |
| `STORAGE_API_URL` | Пропустить | Уже имеет корректный дефолт в `.env.example` |
| `WATCHDOG_INTERVAL_SEC` | Пропустить | Уже имеет корректный дефолт |
| `HOST_AGENT_URL` | Пропустить | Уже имеет корректный дефолт |

### Пример диалога в терминале

```
[mercer] Инициализация окружения...

PostgreSQL
  Имя пользователя [raguser]: ▌
  Пароль: (g)енерировать / (с)вой [g]: ▌
  → Сгенерирован: xK9mP2qR...
  База данных [ragplatform]: ▌

[mercer] ENCRYPTION_KEY   — сгенерирован автоматически
[mercer] HOST_AGENT_TOKEN — сгенерирован автоматически

[mercer] ✓ .env создан
```

---

## Технические детали реализации

### Генерация секретов (только stdlib)

```python
import base64, secrets

# Fernet-совместимый ключ (urlsafe base64, 32 байта → 44 символа)
def generate_fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

# Случайный токен для HOST_AGENT_TOKEN
def generate_token() -> str:
    return secrets.token_urlsafe(32)  # 43 символа, без спецсимволов

# Случайный пароль (без спецсимволов, безопасен для YAML/sed)
def generate_password() -> str:
    return secrets.token_urlsafe(16)  # ~22 символа
```

**Почему не `cryptography.fernet.Fernet.generate_key()`:**  
Пакет `cryptography` есть в venv внутри Docker-контейнеров, но **не** на хосте
при первом `make setup`. Использование stdlib математически эквивалентно.

### Валидация «ключ уже задан»

Для `ENCRYPTION_KEY` — проверять длину: валидный Fernet-ключ всегда ровно **44 символа**.
Если значение после `=` не равно 44 символам — считать незаполненным и генерировать.

Для `HOST_AGENT_TOKEN` — проверять что значение не `changeme` и не пустое.

Для `POSTGRES_PASSWORD` — проверять что значение не `changeme` и не пустое.

### Скрытый ввод пароля

```python
import getpass
password = getpass.getpass("  Введите пароль: ")  # не отображается в терминале
```

### Запись в .env

Использовать `re.sub` на содержимом файла — безопасно, без `sed`, портабельно:

```python
import re

def set_env_value(content: str, key: str, value: str) -> str:
    pattern = rf'^{re.escape(key)}=.*$'
    replacement = f'{key}={value}'
    return re.sub(pattern, replacement, content, flags=re.MULTILINE)
```

### Структура файла

```
scripts/
    generate_env.py   ← новый скрипт (рядом с seed_models.py)
    seed_models.py    ← уже существует
```

---

## Интеграция в Makefile

### Новые цели

```makefile
# Интерактивная инициализация .env
init-env:
	python3 scripts/generate_env.py

# Обновлённая составная цель
setup: init-env agent-setup up seed
	@echo ""
	@echo "$(GREEN)✓ Mercer готов к работе.$(RESET)"
	@echo "  UI: http://localhost:8000"
```

**Важно:** цель `init-env` без префикса `@` перед `python3` — иначе Makefile
может буферизовать stdout и `input()` не будет работать корректно в терминале.

### Порядок в make setup

```
1. init-env      → .env создан и заполнен
2. agent-setup   → venv + launchd для host-agent (macOS only)
3. up            → docker compose up -d
4. seed          → регистрация embedding + rerank моделей в API
```

`init-env` должен быть **первым** — `agent-setup` и `up` могут читать `.env`.

---

## HOST_AGENT_TOKEN: проверенный вывод

Проверка кода показала, что `HOST_AGENT_TOKEN` **реально используется** и на стороне
backend, и на стороне host-agent.

### Как работает проверка токена

В `pdf-sidecar/agent/agent.py` (и дублирующем `host-agent/agent.py`) есть логика:

```python
AGENT_TOKEN: str | None = os.getenv("HOST_AGENT_TOKEN")

def check_token(x_agent_token: str | None = Header(default=None)) -> None:
    if AGENT_TOKEN and x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid agent token")
```

Это означает:
- если `HOST_AGENT_TOKEN` **не задан** у агента — авторизация отключена
- если `HOST_AGENT_TOKEN` **задан** — агент требует совпадение заголовка `X-Agent-Token`

### Как токен проходит по системе

```
.env (HOST_AGENT_TOKEN)
    ↓
docker-compose.yml → environment для rag-backend
    ↓
rag-backend/app/api/settings/sidecar.py → os.getenv("HOST_AGENT_TOKEN")
    ↓
HTTP-запрос к host-agent с заголовком X-Agent-Token
    ↓
pdf-sidecar/agent/agent.py → check_token(...)
```

### Проблема текущей реализации

В `docker-compose.yml` `HOST_AGENT_TOKEN` уже пробрасывается в `rag-backend`:

```yaml
HOST_AGENT_TOKEN: ${HOST_AGENT_TOKEN:-}
```

Но в `pdf-sidecar/agent/com.mercer.host-agent.plist.template` токен сейчас
**закомментирован**:

```xml
<!-- <key>HOST_AGENT_TOKEN</key> -->
<!-- <string>changeme</string> -->
```

Следствие:
- backend **может** отправлять токен
- host-agent, запущенный через launchd, **может не иметь токена в окружении**
- тогда auth на агенте фактически отключена, даже если `.env` уже содержит секрет

### Практический вывод

`HOST_AGENT_TOKEN` нужно:
1. **Генерировать автоматически** в `scripts/generate_env.py`
2. **Передавать в launchd plist** при `agent-setup`
3. Обеспечить порядок `init-env -> agent-setup`, чтобы plist рендерился уже с финальным токеном

### Что нужно учесть при реализации

- `_render-plist` в `Makefile` сейчас подставляет только пути (`VENV_PYTHON`, `AGENT_PY`, `AGENT_DIR`, `SIDECAR_DIR`, `PATH`)
- в шаблон `com.mercer.host-agent.plist.template` нужно добавить placeholder `{{HOST_AGENT_TOKEN}}`
- `_render-plist` должен подставлять значение токена из `.env`
- если токен пустой — нужно явно решить политику:
  - либо не добавлять ключ в plist и тем самым оставить auth отключённой
  - либо считать пустой токен ошибкой для production setup

**Рекомендация для текущего setup-потока:** токен всегда генерировать автоматически и всегда прокидывать в plist. Это согласует backend и host-agent.

---

## Открытые вопросы

### `_check-macos` в agent-setup

Текущий `make setup` вызывает `agent-setup`, который вызывает `_check-macos`.
На Linux `make setup` упадёт на шаге `agent-setup`.

Если деплой планируется только на macOS — ок.
Если нужна поддержка Linux — `agent-setup` нужно сделать опциональным
или вынести в отдельную команду.
