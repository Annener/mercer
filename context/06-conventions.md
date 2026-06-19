# 06 — Соглашения и паттерны кода

## Технологический стек

- **Python 3.12+**, `from __future__ import annotations` везде
- **FastAPI** + **uvicorn** (async)
- **SQLAlchemy 2.x** async (`AsyncSession`), Mapped + mapped_column
- **Alembic** для миграций
- **Pydantic v2** для валидации и контрактов
- **PostgreSQL 16** (asyncpg драйвер)
- **LanceDB** для векторного поиска
- **Docker Compose** для локального запуска

## Паттерны

### Async
Весь код async/await. `SessionLocal` — AsyncSession фабрика.
```python
async with SessionLocal() as db:
    result = await db.execute(select(Domain))
```

### Dependency Injection (FastAPI)
Сервисы — синглтоны, хранятся в `app.state`:
```python
app.state.settings_service = settings_service
app.state.domain_service = domain_service
```

### ORM → Pydantic
Используется `ORMModel` из `shared_contracts`:
```python
DomainRead.model_validate(domain_orm_obj)
```
List-поля (relationships) заполняются явно в роутах, а не через `from_attributes`.

### Конфиги
- `config.yaml` — статический конфиг платформы (файл, читается при старте)
- `PlatformSetting` в БД — runtime-настройки (изменяются через UI)
- `settings_service` кэширует обе группы в памяти

### Шифрование
API-ключи хранятся зашифрованными через Fernet:
```python
Fernet(ENCRYPTION_KEY).encrypt(api_key.encode())
```

### Межсервисное взаимодействие
- `rag-backend` → `rag-indexer`: HTTP через `INDEXER_API_URL`
- `rag-backend` → `db-api-server`: HTTP через `STORAGE_API_URL` / `DB_API_URL`
- `rag-indexer` → `db-api-server`: HTTP через `STORAGE_API_URL`
- Все клиенты — httpx AsyncClient

### SSE (Server-Sent Events)
Ответы чата стримируются через SSE. Типы событий:
- `data: {"content": "..."}`  — текстовый чанк
- `data: {"pipeline_confirm_required": {...}}` — ожидание подтверждения
- `data: {"pipeline_step_complete": {...}}` — шаг выполнен
- `data: [DONE]` — конец стрима

### Pipeline переменные
В `system_prompt` шагов поддерживаются:
- `{query}` — запрос пользователя
- `{STEP_ID.result}` — результат шага
- `{STEP_ID.key}` — ключ из JSON-результата

## Соглашения по именованию

- `*_id` — строковые идентификаторы (например `vault_id = "dnd-main"`)
- ORM-первичные ключи `id` — UUID
- Бизнес-ключи `*_id` — строки (slug-like)
- Файлы конфига: `snake_case.yaml`
- Python-модули: `snake_case.py`
- Классы: `PascalCase`

## Структура роутов

```python
router = APIRouter(prefix="/api/...", tags=["..."])

@router.get("/{id}")
async def get_something(
    id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> SomeResponse:
    ...
```

## Тесты

- pytest + pytest-asyncio
- Тесты для pipeline-системы: `tests/test_pipeline_dag.py`, `test_prompt_pack.py`, `test_pipeline_resume.py`
- Запуск: `pytest` из корня
- Конфиг: `pytest.ini`

## Deprecated / Back-compat

- `Chat.vault_id` — deprecated, используй `domain_id`
- `CreateChatRequest.vault_id` — deprecated
- `RetrievalContext.vault_id` — deprecated, используй `vault_ids`
- `ClarificationStateRow` — алиас для `ClarificationState`

При работе с этими полями — игнорировать или пропускать, не удалять без iter4-cleanup.

## Важные архитектурные инварианты

1. `Chat.domain_id` — NOT NULL, CASCADE DELETE. Чат без домена невозможен.
2. Vault привязан к одному домену через `vault_id`
3. API-ключи **никогда** не возвращаются в ответах (`has_api_key: bool` вместо самого ключа)
4. LanceDB-таблица создаётся по `vault_id`; смена модели эмбеддингов требует ре-индексации
5. Все UUID при сериализации в JSON → str (через `ORMModel._coerce_uuid_fields`)
