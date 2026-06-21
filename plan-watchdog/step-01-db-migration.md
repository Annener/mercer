# Этап 1 — БД: миграция platform_settings

## Цель

Добавить запись `watchdog_auto_index_extensions` в таблицу `platform_settings`.
После этого этапа `db_client.get_platform_settings()` вернёт ключ
`watchdog_auto_index_extensions` со значением `.md,.pdf` при первом запуске.

## Контекст из кодовой базы

### Таблица `platform_settings`

Таблица уже существует. `IndexerDBClient.get_platform_settings()` делает:
```sql
SELECT key, value, value_type FROM platform_settings
```
и кастует значение через `_cast_value(value, value_type)`.

`value_type = 'str'` → `_cast_value` вернёт `value or None`.

Пример существующей записи (из кода — `chunking.chunk_size`, `chunking.overlap` и т.д.).

### Схема таблицы (предполагаемая, из паттернов кода)
```sql
CREATE TABLE platform_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    value_type TEXT NOT NULL  -- 'str' | 'int' | 'float' | 'bool'
);
```

## Что нужно сделать

### 1. Найти файл с миграциями

Перед написанием кода — прочитать директорию `config/` или корень репо на предмет:
- `*.sql` файлов с `CREATE TABLE platform_settings`
- Alembic (`alembic/versions/`, `migrations/`)
- Простых SQL-скриптов инициализации

Поиск:
```
config/
db-api-server/
```

### 2. Добавить INSERT

В существующий файл миграции / SQL-инициализации добавить:

```sql
-- Vault Watchdog: расширения файлов для авто-индексации.
-- Пустая строка = только ручная индексация.
INSERT INTO platform_settings (key, value, value_type)
VALUES ('watchdog_auto_index_extensions', '.md,.pdf', 'str')
ON CONFLICT (key) DO NOTHING;
```

`ON CONFLICT DO NOTHING` — идемпотентность: повторный запуск не сломает
существующее значение, которое пользователь мог поменять через UI.

### 3. Проверить `_cast_value` для `value_type = 'str'`

Существующий код:
```python
if value_type == "str":
    return value or None
```

⚠️ Проблема: если `value = ''` (пустая строка = сценарий «только ручная»),
`_cast_value` вернёт `None` вместо `''`.

Исправить в `rag-indexer/app/db_client.py`:
```python
# БЫЛО:
if value_type == "str":
    return value or None

# СТАЛО:
if value_type == "str":
    return value  # пустая строка — валидное значение для watchdog
```

> ⚠️ Проверить неломает ли это существующих потребителей `get_platform_settings()`.
> В `indexer_worker.py` `settings["pdf_sidecar.url"]` может быть None при
> пустом value — но это настройки которые всегда заполнены, риск минимален.
> Безопаснее: вернуть пустую строку вместо None.

## Файлы для изменения

| Файл | Действие |
|---|---|
| `config/*.sql` или аналог | Добавить `INSERT INTO platform_settings` |
| `rag-indexer/app/db_client.py` | Исправить `_cast_value` для `value_type='str'` |

## Файлы для чтения перед реализацией

- `config/` — вся директория (структура миграций)
- `rag-indexer/app/db_client.py` — актуальная версия (уже прочитан)
- `rag-indexer/indexer_worker.py` — проверить все обращения к `settings[...]`

## ✅ Unit-тесты

```
rag-indexer/tests/test_db_client_cast.py
```

Проверить что `_cast_value('', 'str')` возвращает `''` (не `None`).

```python
import pytest
from app.db_client import IndexerDBClient


def test_cast_str_empty_returns_empty_string():
    client = IndexerDBClient()
    assert client._cast_value('', 'str') == ''


def test_cast_str_value_returns_value():
    client = IndexerDBClient()
    assert client._cast_value('.md,.pdf', 'str') == '.md,.pdf'


def test_cast_str_none_behaviour():
    # value никогда не будет None из БД (NOT NULL), но на всякий случай
    client = IndexerDBClient()
    # после исправления: пустая строка остаётся пустой строкой
    assert client._cast_value('', 'str') == ''
```

## Критерий готовности

- [ ] В SQL-инициализации есть `INSERT ... ON CONFLICT DO NOTHING` для ключа
- [ ] `_cast_value('', 'str')` возвращает `''`
- [ ] Unit-тесты проходят
- [ ] `STATUS.md` обновлён: этап 1 → ✅
