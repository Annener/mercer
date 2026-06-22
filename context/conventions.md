# Соглашения и паттерны кода

## Стек технологий

| Компонент | Технология |
|---|---|
| Web framework | FastAPI (async) |
| ORM | SQLAlchemy 2.x (async, mapped_column) |
| DB driver | asyncpg |
| Migrations | Кастомные SQL-скрипты (не Alembic) |
| Vector DB | LanceDB (через HTTP db-api-server) |
| Cache/State | Redis (aioredis) |
| Validation | Pydantic v2 |
| HTTP client | httpx (async) |
| Containerization | Docker + docker-compose |

## Структурные паттерны

### Разделение ответственности
- `api/` — только HTTP: валидация входных данных, вызов сервиса, формирование ответа
- `services/` — бизнес-логика без HTTP-зависимостей
- `db/models.py` — только ORM-определения, без логики
- `shared_contracts/models.py` — Pydantic-схемы, используемые несколькими сервисами

### Работа с ORM в async
```python
# ПРАВИЛЬНО: явная загрузка relationship
async with SessionLocal() as db:
    obj = await db.get(Chat, chat_id)
    await db.refresh(obj, ['messages'])  # явно загружаем

# НЕПРАВИЛЬНО: lazy load в async контексте
obj.messages  # MissingGreenlet!
```

### ORMModel и list-поля
- `ORMModel._coerce_uuid_fields()` пропускает list-поля (relationships)
- List-поля всегда заполняются вручную в роуте/хелпере, не через `from_attributes`

### Настройки платформы (PlatformSetting)
- Все настройки хранятся в БД как TEXT
- При старте загружаются в `settings_service` (singleton)
- Доступ: `settings_service.get("key")` → нативный Python-тип
- При изменении через API — обновляются и в БД, и в памяти

## Именование

### ID сущностей
- **Domain**: строковый slug: `"dnd"`, `"work"`, `"default"`
- **Vault**: строковый slug: `"dnd-vault"`, `"work-vault"`
- **Pipeline**: строковый id: `"rag_search"`, `"entity_search"`
- **Модели** (generation, embedding, rerank): строковый model_id
- **Всё остальное** (Chat, Message, Campaign, Document, Tag...): UUID

### Файлы и модули
- Роутеры: по сущности — `campaigns.py`, `vaults.py`, `domains.py`
- Сервисы: суффикс `_service` — `domain_service.py`, `settings_service.py`
- Провайдеры: суффикс `_provider` — `ollama_provider.py`
- Workers: суффикс `_worker` — `indexer_worker.py`

## Домены (Domain system)

Домен — изолированное пространство знаний. Каждый домен имеет:
- **Промпты** (4 типа): `system`, `clarification`, `planner`, `pipeline_router`
- **Вольты** (Vault) с документами
- **Кампании** с тегами и системными промптами
- **Пайплайны** обработки запросов
- **ClarificationFields** — поля для уточняющих вопросов

Системные домены (`is_system=True`) создаются при миграции и не удаляются.
Текущие домены: `default`, `dnd`, `work`.
Статические промпты доменов — в yaml-файлах: `domains/dnd/prompts.yaml`

## Pipeline DAG

Пайплайны — это DAG шагов, хранящийся в `Pipeline.steps` (JSONB).
Орхестратор: `services/pipeline_dag.py` + `services/pipeline_executor.py`

Типы шагов (приблизительно):
- `retrieval` — поиск в LanceDB
- `generation` — вызов LLM
- `validation` — пауза на проверку результата (пользователь подтверждает)
- `planner` — формирование многошагового плана

При паузе на `validation`:
- Состояние сохраняется в `Chat.pipeline_pause_state`
- Резюм через `POST /api/pipeline/{chat_id}/resume`

При необходимости подтверждения запуска:
- Состояние в `Chat.pending_pipeline_confirm`
- Подтверждение через `POST /api/pipeline/{chat_id}/confirm`

## Шифрование API-ключей

- Ключи генерационных/embedding/rerank-моделей хранятся зашифрованными
- Поле в БД: `encrypted_api_key`
- Ключ шифрования: переменная окружения `ENCRYPTION_KEY`
- В API никогда не возвращается raw ключ — только `has_api_key: bool`

## Фронтенд

- SPA на Vue (предположительно), собирается отдельно
- Собранный билд кладётся в `rag-backend/app/static/`
- Монтируется как `/static/`, `index.html` отдаётся на `/`

## Тесты

- Корневые интеграционные тесты: `tests/`
- Тесты rag-indexer: `rag-indexer/tests/`
- Тесты rag-backend: `rag-backend/app/tests/`
- Конфиг pytest: `pytest.ini` в корне и в `rag-indexer/`
