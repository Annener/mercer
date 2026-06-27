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

[mercer] ENCRYPTION_KEY  — сгенерирован автоматически
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

## Открытые вопросы

### HOST_AGENT_TOKEN: нужна ли генерация?

Токен используется для авторизации запросов docker → host-agent.  
Текущее значение в `.env.example`: `changeme` — security-риск на реальном деплое.

**Нужно проверить** `pdf-sidecar/agent/agent.py`:
- Как токен валидируется на стороне агента?
- Есть ли механизм передачи нового токена в launchd plist?

Если токен прописывается только в `.env` и пробрасывается в контейнер через
`docker-compose.yml` — генерация безопасна и не требует дополнительных действий.

Если токен также используется в `launchd plist` или конфиге агента —
нужно убедиться что `agent-setup` запускается **после** `init-env` (уже так и есть),
чтобы агент стартовал с правильным токеном.

### `_check-macos` в agent-setup

Текущий `make setup` вызывает `agent-setup`, который вызывает `_check-macos`.
На Linux `make setup` упадёт на шаге `agent-setup`.

Если деплой планируется только на macOS — ок.
Если нужна поддержка Linux — `agent-setup` нужно сделать опциональным
или вынести в отдельную команду.
