# Блок B — `scripts/generate_env.py`

> Зависит от: A3, A5 (финальный `.env.example` должен быть готов).

---

## Цель

Интерактивный Python-скрипт (только stdlib) для подготовки `.env` при первом `make setup`.

---

## Guard на версию Python

Добавить в самое начало скрипта:

```python
import sys
if not (3, 11) <= sys.version_info < (3, 14):
    sys.exit(
        f"ERROR: требуется Python 3.11–3.13, "
        f"запущен {sys.version_info.major}.{sys.version_info.minor}"
    )
```

---

## Идемпотентность

| Состояние `.env` | Поведение |
|---|---|
| Не существует | Проверить `.env.example` (ошибка если нет), создать из него, запустить диалог |
| Существует, все переменные заполнены | Выйти молча |
| Существует, часть переменных пустые/placeholder | Спросить только недостающие |

---

## Диалог (интерактивные переменные)

| Переменная | Тип | Логика |
|---|---|---|
| `INSTALL_MODE` | Интерактивный | Первый вопрос. Варианты: `full` / `db-api-only` / `no-db-api` |
| `POSTGRES_USER` | Интерактивный | Дефолт: `raguser` |
| `POSTGRES_PASSWORD` | Интерактивный | **(g)** сгенерировать / **(с)** свой; свой — через `getpass.getpass()` |
| `POSTGRES_DB` | Интерактивный | Дефолт: `ragplatform` |
| `STORAGE_API_URL` | Интерактивный | Только при `INSTALL_MODE=no-db-api` |

---

## Автоматические переменные

| Переменная | Логика |
|---|---|
| `ENCRYPTION_KEY` | Fernet-ключ через stdlib; **не перезаписывать** если уже ровно 44 символа |
| `HOST_AGENT_TOKEN` | `secrets.token_urlsafe(32)`; **не перезаписывать** если не `changeme` и не пусто |
| `AGENT_MODE` | `platform.system()`: `Darwin`→`host`, `Linux`→`docker`, `Windows`→`host-win` |
| `COMPOSE_PROFILES` | Вычисляется из `INSTALL_MODE`: `full`→`with-db-api`; `no-db-api`→`core`; `db-api-only`→`db-api-only` |
| `HOST_AGENT_URL` | `host`/`host-win` → `http://host.docker.internal:9090`; `docker` → `http://host-agent:9090` |

---

## Вспомогательные функции

```python
import base64, secrets

def generate_fernet_key() -> str:
    # urlsafe base64, 32 байта → всегда ровно 44 символа
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

def generate_token() -> str:
    return secrets.token_urlsafe(32)  # ~43 символа, alphanumeric-safe

def generate_password() -> str:
    return secrets.token_urlsafe(16)  # ~22 символа
```

---

## Запись в `.env`

```python
import re

def set_env_value(content: str, key: str, value: str) -> str:
    pattern = rf'^{re.escape(key)}=.*$'
    return re.sub(pattern, f'{key}={value}', content, flags=re.MULTILINE)
```

---

## Валидация «уже задано» (не перезаписывать)

| Переменная | Критерий «задано» |
|---|---|
| `ENCRYPTION_KEY` | Длина значения == 44 символа |
| `HOST_AGENT_TOKEN` | Не пустое и не `changeme` |
| `POSTGRES_PASSWORD` | Не пустое и не `changeme` |

---

## Интеграция в Makefile

Добавить/обновить цель:

```makefile
init-env:
	python3 scripts/generate_env.py
```

`init-env` должен быть **первым** в `setup` — `agent-setup` и `up` читают `.env`:

```makefile
setup: init-env _agent-setup-dispatch up seed
```
