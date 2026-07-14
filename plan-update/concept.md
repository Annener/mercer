# Campaign Update Mode — Концепт (справочная копия)

> Этот файл является сжатой справочной версией концепта для сверки в процессе реализации.
> Полный оригинальный концепт: см. исходный документ `mercer-campaign-update-mode-concept.md`.

## Цель

Добавить в Mercer режим обновления контекста кампании: пользователь вставляет заметки в чат,
система анализирует **только markdown-файлы кампании**, предлагает diff-правки, пользователь
делает review и подтверждает. Все изменения фиксируются локальным git commit.

## Ключевое разделение

| Режим | Источники | Цель |
|---|---|---|  
| Обычный RAG-чат | MD + PDF + все файлы vault по тегам | Ответ на вопрос |
| Campaign Update Mode | **Только .md-файлы** кампании по тегам | Актуализация документации |

## Что участвует в update-mode

- `.md`-файлы vault, помеченные тегами активной кампании
- Не участвуют: PDF, большие ref-документы, любые read-only источники

## Модель данных — изменения

### Vault (новые поля)
```
versioned_extensions: list[str]  # default: [".md"]
git_author_name: str | None      # если None — использует GIT_AUTHOR_NAME из config
git_author_email: str | None     # если None — использует GIT_AUTHOR_EMAIL из config  
```

### Chat (новые поля)
```
update_mode_enabled: bool = False
update_mode_pending: JSONB | None  # pending changes, хранится в Redis (не в БД)
```

### Config (новые глобальные настройки)
```
GIT_AUTHOR_NAME: str = "Mercer"
GIT_AUTHOR_EMAIL: str = "mercer@local"
```

## Git-стратегия

- **Вариант A**: `git init` для всех vault при старте сервиса (lifespan), + `ensure_repo()` как
  защитный вызов перед каждой git-операцией
- Commit identity задаётся через `GIT_AUTHOR_*` env — **глобальный git config пользователя
  не трогается никогда**
- Локальный identity vault переопределяет глобальный
- Remote/push: **не входит в MVP**

## Пользовательский сценарий (краткий)

1. Открыть чат с кампанией
2. Включить **Campaign Update Mode** (кнопка/toggle в UI чата)
3. Вставить заметки в поле сообщения
4. Backend: собрать `.md`-файлы по тегам кампании → передать в LLM
5. LLM генерирует `ProposedChange[]` (update/create, diff per file)
6. UI показывает diff по каждому файлу, кнопки Accept / Reject / Rephrase
7. Rephrase — instruction-driven: пользователь даёт указание, LLM переформулирует
8. Apply: только подтверждённые правки → запись файлов
9. Git: snapshot commit (если dirty) → apply commit с осмысленным message

## ProposedChange — структура

```python
class ProposedChange(BaseModel):
    change_id: str           # uuid, для адресации в review
    file_path: str           # относительный путь внутри vault
    action: Literal["update", "create"]
    description: str         # краткое описание для UI
    original_content: str    # текущее содержимое файла ("" для create)
    proposed_content: str    # предложенное содержимое
    status: Literal["pending", "accepted", "rejected"] = "pending"
```

## Ограничения MVP

- Только `.md` в update-mode (PDF полностью исключены)
- Review обязателен — автоприменение запрещено  
- Локальность — push/remote вне MVP
- Нет отдельного reindex-flow после apply (используется существующий watchdog)
- Размер editable context: soft limit ~64K токенов, предупреждение в UI

## Ключевые файлы репозитория для реализации

```
rag-backend/app/db/models.py          — Vault, Chat ORM (добавить поля)
rag-backend/app/config.py             — AppConfig (добавить git settings)
rag-backend/app/services/            — новые: vault_git_service.py, update_mode_executor.py
rag-backend/app/api/                  — новый роутер: update_mode.py
rag-backend/app/tests/               — тесты по каждой фазе
shared_contracts/models.py            — ProposedChange, UpdateModeState
rag-backend/app/main.py              — lifespan: git init all vaults
```

## Контекст-файлы для чтения перед работой

```
context/architecture.md
context/rag-backend-services.md
context/db_schema.md
context/shared_contracts.md
context/api_routes.md
```
