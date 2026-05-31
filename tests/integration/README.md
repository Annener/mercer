# Integration smoke-tests — Iteration 5

## Что проверяют эти тесты

| # | Инвариант |
|---|---|
| 1 | `TagCreate` / `TagRead` — `domain_id` есть, `vault_id` отсутствует |
| 2 | ORM `Tag` сохраняется с `domain_id` без `vault_id` |
| 3 | `CampaignCreate` / `CampaignRead` — `domain_id` есть, `vault_id` отсутствует |
| 4 | `get_allowed_tag_ids`: пустая кампания → `set()` |
| 5 | Глобальный тег виден в кампании |
| 6 | Тег кампании A не виден в кампании B |
| 7 | `get_document_ids_by_tags([])` → `[]` |
| 8 | Документ с тегом находится |
| 9 | Документ другого домена не попадает |
| 10 | `PipelineCreate.campaign_id` nullable |
| 11 | `PipelineContext.vault_ids` + `domain_id` |
| 12 | `CreateChatRequest` back-compat (`vault_id`) + новый `domain_id` |
| 13 | Документы из disabled vault не участвуют в retrieval |

## Быстрый запуск

```bash
# Из корня репозитория
cd rag-backend

# 1. Поднять postgres
docker compose up -d postgres

# 2. Применить миграции
docker compose run --rm rag-backend alembic upgrade head

# 3. Запустить тесты
docker compose run --rm \\
  -e DATABASE_URL=postgresql+asyncpg://mercer:mercer@postgres:5432/mercer \\
  rag-backend \\
  pytest tests/integration/test_iter5_smoke.py -v
```

## Локальный запуск (без Docker)

```bash
cd rag-backend

pip install pytest pytest-asyncio sqlalchemy[asyncio] asyncpg

DATABASE_URL=postgresql+asyncpg://mercer:mercer@localhost:5432/mercer \\
    pytest tests/integration/test_iter5_smoke.py -v
```

## Изоляция

Каждый тест работает в откатываемой транзакции — никаких данных в БД не остается.  
Тесты schema/contract вообще не требуют БД (только проверяют Pydantic-модели).

## pytest.ini / pyproject.toml

Добавь в `rag-backend/pyproject.toml` (если ещё нет):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```
