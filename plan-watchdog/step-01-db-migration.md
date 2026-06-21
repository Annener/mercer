# Этап 1 — БД: миграция platform_settings

## Цель

Добавить настройку `watchdog_auto_index_extensions` в таблицу `platform_settings`
с значением по умолчанию `.md,.pdf`.

## Контекст из кодовой базы

### Таблица `platform_settings`

Таблица имеет расширенную схему (см. миграцию `0018`):

```sql
platform_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    value_type TEXT,       -- 'str' | 'bool' | 'int' | 'float'
    group_name TEXT,       -- группировка в UI
    label      TEXT,       -- отображаемое название
    hint       TEXT        -- подсказка в UI
)
```

### Расположение миграций

Миграции находятся в `rag-backend/migrations/versions/`.
Используется **Alembic** — Python-файлы с функциями `upgrade()` / `downgrade()`.
Текущая последняя миграция: `0019_pipeline_pause_state.py`.

Запускаются автоматически при старте `rag-backend`.

### Актуальные ключи `platform_settings`

Перед добавлением можно свериться:

```bash
docker compose exec postgres psql -U mercer -d mercer -c \
  "SELECT key, value_type, group_name FROM platform_settings ORDER BY group_name, key;"
```

## Что нужно сделать

### Новый файл миграции

Создать файл `rag-backend/migrations/versions/0020_add_watchdog_setting.py`:

```python
"""Add watchdog_auto_index_extensions to platform_settings.

Revision ID: 0020_add_watchdog_setting
Revises: 0019_pipeline_pause_state
Create Date: 2026-06-21

Добавляет глобальную настройку watchdog-а: список расширений файлов,
для которых индексация запускается автоматически при обнаружении изменений.
Значение по умолчанию — '.md,.pdf' (Сценарий 1: всё автоматически).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0020_add_watchdog_setting"
down_revision = "0019_pipeline_pause_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO platform_settings (key, value, value_type, group_name, label, hint)
            VALUES (
                'watchdog_auto_index_extensions',
                '.md,.pdf',
                'str',
                'indexing',
                'Авто-индексация расширений',
                'Расширения файлов через запятую (.md,.pdf). Пусто — только ручная индексация.'
            )
            ON CONFLICT (key) DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM platform_settings WHERE key = 'watchdog_auto_index_extensions';"
        )
    )
```

### Проверка после применения

```bash
docker compose exec postgres psql -U mercer -d mercer -c \
  "SELECT key, value, group_name FROM platform_settings WHERE key = 'watchdog_auto_index_extensions';"
```

Ожидаемая строка:
```
              key               |   value  | group_name
---------------------------------+----------+------------
 watchdog_auto_index_extensions | .md,.pdf | indexing
```

## Файлы для создания

| Файл | Действие |
|---|---|
| `rag-backend/migrations/versions/0020_add_watchdog_setting.py` | Создать |

## Критерий готовности

- [ ] Файл `0020_add_watchdog_setting.py` создан в `rag-backend/migrations/versions/`
- [ ] `revision = "0020_add_watchdog_setting"`, `down_revision = "0019_pipeline_pause_state"`
- [ ] `ON CONFLICT (key) DO NOTHING` присутствует в `upgrade()`
- [ ] `downgrade()` удаляет запись по ключу
- [ ] После `docker compose up` ключ виден в `SELECT`
- [ ] `STATUS.md` обновлён: этап 1 → ✅
