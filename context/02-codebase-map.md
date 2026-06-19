# 02 — Карта кодовой базы

## Структура репозитория

```
mercer/
├── config/                    # Конфиги платформы
│   ├── config.yaml            # Главный конфиг (вольты, модели, пайплайны)
│   └── storage.config.yaml    # Конфиг LanceDB
├── rag-backend/               # FastAPI backend (:8000)
│   ├── app/
│   │   ├── main.py            # Lifespan, маршрутизация, статика
│   │   ├── config.py          # Pydantic-модели конфига
│   │   ├── api/               # HTTP-роутеры
│   │   │   ├── chat.py        # Чаты + SSE-стриминг (~26KB, центральный)
│   │   │   ├── pipeline_resume.py # /pipeline_confirm, /pipeline_resume
│   │   │   ├── db_management.py   # CRUD: domains, vaults, models, tags...
│   │   │   ├── config_api.py  # GET/reload конфига
│   │   │   └── settings/      # CRUD настроек платформы
│   │   ├── db/
│   │   │   ├── models.py      # SQLAlchemy ORM модели
│   │   │   ├── session.py     # AsyncSession фабрика
│   │   │   └── migrations.py  # Запуск Alembic при старте
│   │   ├── services/          # Бизнес-логика
│   │   │   ├── retrieval.py   # Поиск в LanceDB (~30KB, главный)
│   │   │   ├── pipeline_executor.py # DAG-исполнитель
│   │   │   ├── pipeline_router.py   # Выбор пайплайна для запроса
│   │   │   ├── pipeline_dag.py      # DAG топологическая сортировка
│   │   │   ├── pipeline_service.py  # CRUD пайплайнов
│   │   │   ├── planner.py     # Планирование ответа
│   │   │   ├── query_rewriter.py    # Переформулировка запросов
│   │   │   ├── clarification_fsm.py # FSM уточняющих вопросов
│   │   │   ├── prompt_pack.py       # resolve_step_vars(), шаблоны промтов
│   │   │   ├── settings_service.py  # Управление настройками (~23KB)
│   │   │   ├── domain_service.py    # Управление доменами
│   │   │   └── vault_config_service.py
│   │   ├── providers/
│   │   │   └── generation/    # LLM-провайдеры (openai_compatible)
│   │   ├── domains/           # Доменные конфигурации
│   │   │   ├── dnd/prompts.yaml
│   │   │   ├── work/
│   │   │   ├── default/
│   │   │   └── registry.py    # Реестр доменов
│   │   ├── planners/          # Расширенные планировщики
│   │   ├── pipelines/         # Hot-reload пайплайны (runtime)
│   │   ├── static/            # SPA фронтенд (HTML/JS/CSS)
│   │   └── tests/             # Unit-тесты (часть)
│   ├── migrations/            # Alembic-миграции (0001..0019)
│   ├── pipelines/             # DAG-пайплайны (YAML/JSON, hot-reload)
│   ├── tools/                 # CLI-утилиты
│   │   └── migrate_pipelines.py # Миграция старых пайплайнов в DAG-формат
│   └── requirements.txt
├── rag-indexer/               # Индексатор документов (:9000)
│   ├── indexer_worker.py      # Ядро индексации (~29KB)
│   ├── config.py              # Pydantic-конфиг индексатора
│   ├── embedding/             # Клиенты эмбеддингов
│   ├── parser/                # Парсеры документов
│   ├── storage/               # Клиент db-api-server
│   ├── api/                   # HTTP API индексатора
│   └── app/                   # main.py индексатора
├── db-api-server/             # LanceDB REST API (:8080)
│   ├── main.py
│   ├── storage/               # LanceDB адаптеры
│   └── api/                   # Эндпоинты upsert/search/delete
├── pdf-sidecar/               # PDF-парсер (macOS host)
│   ├── app.py                 # FastAPI-сервер
│   ├── parser.py              # Основной парсер (~40KB)
│   ├── preprocessor.py        # Предобработка
│   └── reranker.py            # Ре-ранкер
├── shared_contracts/          # Общие Pydantic-контракты
│   └── models.py              # Все межсервисные модели (~25KB)
├── tests/                     # Корневые тесты
├── Plan/                      # Проектная документация
│   ├── STATUS.md              # Статус разработки
│   ├── pipeline-redesign-concept.md
│   └── pipeline-redesign-execution-plan.md
├── docker-compose.yml
├── pytest.ini
└── .env.example
```

## Ключевые модули по важности

### Критические (изменения требуют особой осторожности)
- `shared_contracts/models.py` — контракты между сервисами, изменения ломают всё
- `rag-backend/app/db/models.py` — ORM, изменения требуют миграции
- `rag-backend/app/api/chat.py` — центральный обработчик чатов, SSE-стриминг
- `rag-backend/app/services/pipeline_executor.py` — исполнитель DAG

### Важные
- `rag-backend/app/services/retrieval.py` — поиск, гибридный + семантический
- `rag-backend/app/services/settings_service.py` — кэш настроек, загрузка конфига
- `rag-indexer/indexer_worker.py` — core индексации

### Конфигурационные
- `config/config.yaml` — основной конфиг платформы
- `rag-backend/app/domains/*/prompts.yaml` — доменные промты

## Тесты

```
tests/                         # pytest корень
├── test_pipeline_dag.py       # 17 тестов DAG-движка
├── test_prompt_pack.py        # 26 тестов разворачивания переменных
├── test_pipeline_resume.py    # 13 тестов API endpoint
└── ...                        # прочие unit-тесты
```

**Статус:** `104 passed, 1 warning` (2026-06-19)

Запуск: `pytest` из корня (настроен в `pytest.ini`)
