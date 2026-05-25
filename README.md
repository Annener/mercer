# Local Multi-Domain RAG Platform

Локальная multi-domain RAG-платформа для индексации vault-документов, поиска по чанкам, domain-aware чата, уточняющих вопросов и hot-reload pipeline'ов. Общее техническое задание лежит в [TZ-Local-Multi-Domain-RAG-v2-codex-ready.md](/home/riargard/dns_2try/TZ-Local-Multi-Domain-RAG-v2-codex-ready.md).

## Требования

- Docker и Docker Compose v2.
- 8 GB RAM минимум; больше требуется для локальных LLM/OCR и больших vault'ов.
- CPU с AVX для LanceDB.
- Свободные порты: `8000` на хосте, внутренние `8080`, `9000`, `5432` в Docker-сети.
- Для локальных моделей: Ollama или OpenAI-compatible сервер, доступный контейнерам.

## Quick Start

1. Скопируйте шаблоны:

```bash
cp .env.example .env
cp config/config.example.yaml config/config.yaml
cp config/storage.config.example.yaml config/storage.config.yaml
```

2. Создайте папки для документов:

```bash
mkdir -p vaults/dnd vaults/work
```

3. Запустите платформу:

```bash
docker compose up -d
```

4. Проверьте health:

```bash
curl http://localhost:8000/health
docker compose ps
```

5. Откройте:

- Backend API и UI: `http://localhost:8000`
- OpenAPI: `http://localhost:8000/docs`
- DB management UI: `http://localhost:8000/db/ui`

## Архитектура

```text
Browser/API client
        |
        v
rag-backend:8000  ---->  rag-db:5432
   |       |
   |       +---------> db-api-server:8080 ----> LanceDB files
   |
   +-----------------> rag-indexer:9000
                          |
                          +---------> vaults, state, embedding cache
```

Сервисы работают в сети `rag-net`:

- `rag-backend` - публичный FastAPI-сервис для чата, Web UI, DB management и pipeline execution.
- `rag-indexer` - внутренний FastAPI-сервис индексации, WebSocket прогресса и отмены задач.
- `db-api-server` - внутренняя HTTP-прослойка над LanceDB.
- `rag-db` - PostgreSQL 16 для чатов, сообщений, аудита и служебных привязок.

`shared_contracts` устанавливается внутрь Python-образов на этапе сборки и не монтируется как volume.

## Конфигурация

Главный файл: `config/config.yaml`, пример с комментариями: [config/config.example.yaml](/home/riargard/dns_2try/config/config.example.yaml).

Основные секции:

- `vaults` - локальные документные хранилища, `vault_id`, `domain_id`, путь и флаг `enabled`.
- `embedding_models` - провайдеры embeddings, размерность, timeout и retries.
- `generation_models` - OpenAI-compatible генераторы ответов.
- `reranker` - опциональный reranker.
- `chat` - лимиты clarification, streaming и auto-title.
- `retrieval` - параметры поиска чанков.
- `chunking.entity_aware_mode` - включает regex-based извлечение сущностей во время чанкинга.
- `pipelines` - путь, hot-reload interval и debounce.
- `ui` - включение DB management UI.
- `validation_rules` - диапазоны для UI-контролов.

Storage-конфиг: [config/storage.config.example.yaml](/home/riargard/dns_2try/config/storage.config.example.yaml). Он задаёт путь LanceDB, cache budget, host, port и уровень логирования storage-сервиса.

Секреты не кладутся в YAML. В `generation_models.*.api_key_env` указывается имя переменной окружения, например `OPENAI_API_KEY`.

## Провайдеры

Локальный Ollama для embeddings:

```yaml
embedding_models:
  nomic-local:
    model_id: "nomic-local"
    provider: "ollama"
    model_name: "nomic-embed-text"
    base_url: "http://host.docker.internal:11434"
    dimensions: 768
    enabled: true
```

OpenAI-compatible generation:

```yaml
generation_models:
  default-chat:
    model_id: "default-chat"
    provider: "openai_compatible"
    base_url: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"
    enabled: true
```

OpenAI-compatible локальный сервер можно указать тем же способом, заменив `base_url` на адрес, доступный из контейнера.

## Vault'ы

Чтобы добавить новый vault:

1. Создайте папку, например `vaults/my-domain`.
2. Добавьте Markdown/PDF/TXT документы.
3. Добавьте секцию в `config/config.yaml`:

```yaml
vaults:
  my-domain:
    vault_id: "my-domain"
    domain_id: "work"
    path: "/data/vaults/my-domain"
    enabled: true
```

4. Перезапустите сервисы или перезагрузите конфиг там, где это поддерживается.
5. Запустите индексацию через UI или API:

```bash
curl -X POST http://localhost:9000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"vault_id":"my-domain","force_reindex":false}'
```

Progress stream доступен по WebSocket:

```text
ws://localhost:9000/api/v1/tasks/{task_id}/stream
```

## Чат

Backend хранит сессии и сообщения в PostgreSQL. Короткие или неоднозначные запросы проходят через clarification FSM: сервис задаёт уточняющий вопрос, ограничивает число раундов `chat.max_clarification_turns`, затем строит план поиска и ответа.

OpenAPI для всех chat endpoints доступен на `http://localhost:8000/docs`.

## Pipelines

Pipeline состоит из YAML-манифеста и Python-модуля в доменной папке внутри `rag-backend/pipelines`:

```text
rag-backend/pipelines/
└── work/
    ├── pipeline.yaml
    └── pipeline.py
```

Минимальная структура манифеста:

```yaml
pipeline_id: "work-default"
domain_id: "work"
version: "1.0.0"
enabled: true
entrypoint: "pipeline:run"
```

Hot-reload отслеживает изменения и атомарно заменяет валидные pipeline'ы. Невалидный pipeline игнорируется, последняя рабочая версия остаётся активной.

## API

FastAPI генерирует OpenAPI:

- `http://localhost:8000/docs` - backend.
- Внутренние сервисы `rag-indexer:9000` и `db-api-server:8080` доступны внутри Docker-сети; их можно тестировать через `docker compose exec`.

Полезные backend endpoints:

- `GET /health`
- `GET /db/ui`
- `GET /db/documents`
- `GET /db/documents/{document_id}/chunks`
- `POST /db/search/text`
- `DELETE /db/vault/{vault_id}`

## Тесты

Unit-тесты запускаются локально:

```bash
python -m pip install -r requirements-dev.txt
pytest tests/unit
```

Интеграционные Docker smoke-тесты требуют поднятых контейнеров:

```bash
docker compose up -d
RUN_DOCKER_TESTS=1 pytest tests/integration
```

Полный набор:

```bash
pytest tests
```

Без `RUN_DOCKER_TESTS=1` Docker-зависимые integration-тесты пропускаются.

## Docker И Volumes

Образы собираются multi-stage Dockerfile'ами на базе `python:3.13-slim`. `rag-indexer` дополнительно содержит OCR-зависимости: `tesseract-ocr`, `tesseract-ocr-rus`, `tesseract-ocr-eng`, `poppler-utils`.

Volumes:

- `./config:/app/config:ro` - конфигурация backend/indexer.
- `./config/storage.config.example.yaml:/app/config.yaml:ro` - storage-конфиг в compose-шаблоне.
- `./vaults:/data/vaults:ro` - исходные документы.
- `./state:/app/state` - состояние задач индексации.
- `./cache/embeddings:/app/cache/embeddings` - embedding cache.
- `./logs:/app/logs` - файловые логи.
- `./data/postgres:/var/lib/postgresql/data` - PostgreSQL.
- `./data/lancedb:/data/lancedb` - LanceDB.

Healthchecks настроены для всех сервисов с интервалом `30s`, timeout `10s`, retries `3`.

## Логирование

Каждый Python-сервис пишет в stdout и в файл `/app/logs/{service}.log` через `RotatingFileHandler`:

- `logs/backend.log`
- `logs/indexer.log`
- `logs/storage.log`

Docker logging driver: `local`, `max-size: 50m`, `max-file: "5"`.

## Troubleshooting

Порт `8000` занят:

```bash
docker compose ps
lsof -i :8000
```

Ollama недоступна из контейнера:

- Проверьте, что Ollama слушает внешний интерфейс или доступна через `host.docker.internal`.
- Проверьте `base_url` в `config/config.yaml`.

OCR не извлекает текст:

- Убедитесь, что PDF содержит сканы, а не повреждённые страницы.
- Проверьте логи `logs/indexer.log`.
- В образе indexer установлены русская и английская языковые модели Tesseract.

Нет места на диске:

- Проверьте `data/postgres`, `data/lancedb`, `cache/embeddings`.
- Удаляйте runtime-данные только осознанно и при остановленных контейнерах.

Сервис unhealthy:

```bash
docker compose ps
docker compose logs --tail=100 rag-backend
docker compose logs --tail=100 rag-indexer
docker compose logs --tail=100 db-api-server
```

Pipeline не обновился:

- Проверьте `pipeline.yaml`.
- Убедитесь, что `pipelines.enabled: true`.
- Невалидная новая версия игнорируется, чтобы не ломать активные чаты.

## Лицензия И Контакты

Лицензия пока не выбрана. Контакты владельца проекта задаются в репозитории или внутренней документации команды.
