# Этап 1 — БД: миграция platform_settings

## Цель

Добавить настройку `watchdog_auto_index_extensions` в таблицу `platform_settings`
с значением по умолчанию `.md,.pdf`.

## Контекст из кодовой базы

### Таблица `platform_settings`

```sql
CREATE TABLE platform_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
```

Уже существует. По ключу `GET /settings` в `rag-backend` читает
все значения и возвращает как dict.

### Существующие ключи `platform_settings`

Узнайте актуальные ключи перед добавлением через:

```bash
docker compose exec postgres psql -U mercer -d mercer -c \
  "SELECT key, value FROM platform_settings ORDER BY key;"
```

### Файлы миграций

Миграции находятся в `db-api-server/migrations/` (уточнить путь перед реализацией).

## Что нужно сделать

### Новый файл миграции

Найдите последний по номеру файл миграции (напр., `V007_...sql`) и создайте следующий:

```sql
-- VN__add_watchdog_setting.sql
-- Добавляет настройку watchdog_auto_index_extensions.
-- ON CONFLICT DO NOTHING: безопасно при повторном запуске.

INSERT INTO platform_settings (key, value)
VALUES ('watchdog_auto_index_extensions', '.md,.pdf')
ON CONFLICT (key) DO NOTHING;
```

> ❗ Номер `N` выберите самостоятельно, посмотрев текущие миграции в репозитории.

### Проверка после применения

```bash
docker compose exec postgres psql -U mercer -d mercer -c \
  "SELECT key, value FROM platform_settings WHERE key = 'watchdog_auto_index_extensions';"
```

Ожидаемая строка:
```
              key               |   value
---------------------------------+-----------
 watchdog_auto_index_extensions | .md,.pdf
```

## Файлы для создания

| Файл | Действие |
|---|---|
| `db-api-server/migrations/VN__add_watchdog_setting.sql` | Создать (заменить `N` на актуальный номер) |

## Критерий готовности

- [ ] Миграционный файл создан с правильным номером
- [ ] `ON CONFLICT DO NOTHING` присутствует
- [ ] После `docker compose up` ключ виден в `SELECT`
- [ ] `STATUS.md` обновлён: этап 1 → ✅
