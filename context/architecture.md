# Архитектура Mercer

## Назначение проекта

Mercer — мультидоменная RAG-платформа для работы с документами через LLM.
Поддерживает несколько доменов знаний (dnd, work, default), каждый со своими промптами,
кампаниями, хранилищами документов (Vault) и пайплайнами обработки запросов.

Ключевые возможности:

- **Campaign Update Mode** — управляемый процесс актуализации markdown-контекста кампаний:
  пользователь вводит заметку, LLM предлагает правки, Indexer применяет их с git-фиксацией
  и запускает targeted reindex. Полная документация: `context/campaign-update-mode.md`.
- **Campaign State** — компактное версионируемое состояние конкретной кампании
  (настраиваемые `single/list` поля, монтируется в prompt через детерминированный
  компилятор; см. ниже раздел «Campaign State»).
- **Conditional / cyclic RAG в чате** — LLM получает tool `search_knowledge` и bounded
  agent loop (до 2 раундов поиска в grounded-режиме); см. ниже раздел
  «Conditional / cyclic RAG (chat)».
- **Full Document Mode** — пауза для отправки полного текста документа вместо набора чанков.

## Сервисы

```
┌──────────────────────────────────────────────────────────────────┐
│                           rag-net                                │
│                                                                  │
│  rag-backend :8000  ←──→  rag-indexer :9000 (internal)          │
│       │                        │                                 │
│       │                   db-api-server :8080                    │
│       │                        │                                 │
│       └──────→  rag-db (PostgreSQL :5432)                        │
│                 redis :6379                                      │
│                 lancedb (volume /data/lancedb)                   │
│                 /data/vaults (shared mount)                      │
└──────────────────────────────────────────────────────────────────┘
         │
         │ HTTP → host.docker.internal:9090
         ↓
   host-agent  (хост, вне Docker)
         │ subprocess
         ↓
   pdf-sidecar (процесс на хосте :8765)
```

### rag-backend
- **Роль**: главный API-сервис, единственный порт наружу (8000)
- **Стек**: FastAPI + SQLAlchemy async + asyncpg
- **Расположение**: `rag-backend/`
- Обрабатывает чаты, пайплайны, настройки, документы
- Проксирует запросы к rag-indexer через внутренний HTTP
- Проксирует запросы управления pdf-sidecar к host-agent через `api/settings/sidecar.py`
- Хранит состояние в PostgreSQL, сессии чатов, Update Mode review-сессии и Initial State proposals в Redis
- Раздаёт SPA-фронтенд из `app/static/` (ванильный JS, без фреймворков)
- **Campaign Update Mode**: orchestrирует retrieval → LLM edit intents + state_patch → review session; управляет через `api/update_mode.py`
- **Campaign State**: CRUD полей через `api/settings/campaigns.py`, apply patch, Initial State flow, debug effective-context endpoint
- **Conditional RAG в чате**: tool-call path в `plain_stream` через `AgentLoop.run_stream` + `SearchKnowledgeService`

### rag-indexer
- **Роль**: асинхронный воркер индексации документов; единственный filesystem/git writer
- **Стек**: FastAPI (HTTP API для управления) + собственный воркер
- **Расположение**: `rag-indexer/`
- Не доступен снаружи — только через rag-backend
- Читает файлы из vault (`/data/vaults`), парсит через pdf-sidecar
- Создаёт чанки, вычисляет эмбеддинги, сохраняет в LanceDB через db-api-server
- Watchdog: периодически проверяет изменения файлов в vault; переход Markdown → reindex влияет на `CampaignStateStaleService` через `Document.md5` (Stage 7)
- **Campaign Update Mode**: обрабатывает internal endpoints `/internal/update-mode/resolve` и `/internal/update-mode/apply`; единолично читает/пишет `.md`-файлы, выполняет git snapshot/commit, запускает targeted reindex

### db-api-server
- **Роль**: HTTP-обёртка над LanceDB (векторное хранилище)
- **Расположение**: `db-api-server/`
- Один экземпляр LanceDB на весь проект (файловая БД: `/data/lancedb`)
- API: CRUD чанков, векторный поиск, BM25 full-text search, восстановление полного текста документа по chunks
- Конфиг: `config/storage.config.yaml`

### pdf-sidecar
- **Роль**: внешний Python-сервис парсинга PDF, реранкинга и эмбеддинга
- **Расположение**: `pdf-sidecar/`
- **Запуск**: отдельно, НЕ в docker-compose — через host-agent или скрипты `start.sh`/`stop.sh`
- **Порт**: `8765` (переопределяется через `PDF_SIDECAR_PORT`)
- **Стек**: `unstructured` (hi_res + yolox), `pdfminer`, `pymupdf`
- **Модели**: CrossEncoder `BAAI/bge-reranker-v2-m3` (reranker), SentenceTransformer `BAAI/bge-m3` (embedder)
- Эндпоинты: `POST /parse`, `POST /parse/stream`, `POST /rerank`, `POST /embed`, `GET /health`
- `/embed` совместим с OpenAI `/embeddings` API — бэкенд может использовать sidecar как embedding-провайдер
- `pdf-sidecar/agent/` — альтернативная копия host-agent для macOS (с launchd plist)
- Подробности: `context/pdf-sidecar.md`

### host-agent
- **Роль**: HTTP-агент на хосте для управления процессом pdf-sidecar из Docker-контейнера
- **Расположение**: `host-agent/`
- **Запуск**: вручную или через systemd (`mercer-host-agent.service`)
- **Порт**: `9090` (только `127.0.0.1`)
- Управляет pdf-sidecar через bash-скрипты (`start.sh`, `stop.sh`, `install.sh`)
- Аутентификация: shared secret через заголовок `X-Agent-Token`
- Подробности: `context/host-agent.md`

### PostgreSQL (rag-db)
- Основная реляционная БД
- Хранит: домены, вольты, документы, чаты, сообщения, пайплайны, модели, audit log,
  конфигурацию полей Campaign State, версии state, audit-trail patch operations
- Миграции: **Alembic** (`rag-backend/migrations/`), запускаются при старте через `run_migrations()` в `rag-backend/app/db/migrations.py`
- Текущий head миграций: `0009_retrieval_tool_settings`
- Полная схема и список миграций: `context/db_schema.md`

### Redis
- Используется для: состояния индексатора (IndexState), кэширования, review-сессий Update Mode,
  Initial State proposal, `campaign:{id}:prev_stale` (для отслеживания переходов stale-статуса)
- `RedisStateManager` живёт в rag-indexer
- rag-backend читает состояние напрямую через `redis.asyncio`
- Campaign Update Mode: ключ `update_mode:{chat_id}`, TTL 3 часа; vault lock `update_mode:vault_lock:{vault_id}`, TTL 60 сек
- Campaign State Initial: ключ `campaign_state_initial:{campaign_id}`, TTL 3 часа
- Campaign State Stale: ключ `campaign:{id}:prev_stale`

## Общая структура репозитория

```
mercer/
├── rag-backend/         # Главный API (FastAPI)
│   ├── alembic.ini
│   ├── migrations/      # Alembic-миграции
│   └── app/
│       ├── api/         # HTTP роутеры
│       │   ├── chat.py
│       │   ├── pipeline_resume.py
│       │   ├── fulldoc_confirm.py
│       │   ├── update_mode.py       # Campaign Update Mode public API
│       │   ├── settings/            # CRUD settings + Campaign State + Initial + Effective Context + Stale
│       │   ├── indexer_state.py
│       │   ├── watchdog_settings.py
│       │   └── db_management.py
│       ├── db/          # ORM-модели, сессии, запуск Alembic
│       ├── services/    # Бизнес-логика
│       │   ├── retrieval.py
│       │   ├── pipeline_executor.py
│       │   ├── update_mode_executor.py
│       │   ├── update_mode_store.py
│       │   ├── indexer_client.py
│       │   ├── campaign_state_service.py             # Stage 1 — field config
│       │   ├── campaign_state_value_service.py       # Stage 2/5 — versioned state + patch
│       │   ├── campaign_state_initial_service.py     # Stage 3 — initial proposal/apply
│       │   ├── campaign_state_initial_store.py       # Redis-сессия initial proposal
│       │   ├── campaign_state_stale_service.py       # Stage 7 — potentially_stale
│       │   ├── campaign_state_compiler.py            # Stage 6 — prompt compiler
│       │   ├── effective_context.py                   # Stage 6 — runtime helper
│       │   ├── agent_loop.py                          # Stage 8.4 — bounded LLM ↔ tool cycle
│       │   ├── search_knowledge_service.py            # Stage 8.3 — host-side search tool
│       │   └── retrieval_tool_settings.py             # Stage 8.2 — typed accessor
│       ├── providers/   # Провайдеры генерации (OpenAI-compatible)
│       ├── domains/     # Домены (dnd, work, default) + registry
│       ├── pipelines/   # Pipeline registry
│       └── static/      # SPA-фронтенд (ванильный JS, без фреймворков)
├── rag-indexer/         # Индексатор + filesystem/git writer
│   ├── app/             # FastAPI app + db_client
│   ├── api/             # API роутеры индексатора
│   │   └── update_mode.py              # Internal update-mode API
│   ├── services/        # Сервисы (в т.ч. Update Mode)
│   │   ├── update_mode_file_service.py # Чтение файлов, diff, path validation
│   │   └── vault_git_service.py        # Git: init, snapshot, commit
│   ├── embedding/       # Провайдеры эмбеддингов (ollama, openai, sidecar)
│   ├── parser/          # Парсеры документов
│   ├── storage/         # HTTP-клиент к db-api-server
│   └── indexer_worker.py # Основной воркер индексации (поддерживает targeted reindex по source_paths)
├── db-api-server/       # LanceDB HTTP API
│   ├── api/             # Роутеры
│   └── storage/
│       └── lancedb_store.py  # Вся логика LanceDB
├── pdf-sidecar/         # PDF-парсер + reranker + embedder (внешний сервис)
│   └── agent/           # Копия host-agent для macOS (launchd)
├── host-agent/          # HTTP-агент управления pdf-sidecar (на хосте)
├── shared_contracts/
│   └── models.py        # Общие Pydantic-схемы между сервисами
│                        # (Update Mode + Campaign State + LLM tool-call contracts)
├── config/
│   └── storage.config.yaml  # Конфиг LanceDB
├── tests/               # Интеграционные тесты
├── docker-compose.yml
└── .env.example
```

## Переменные окружения (ключевые)

| Переменная | Сервис | Назначение |
|---|---|---|
| `DATABASE_URL` | backend, indexer | `postgresql+asyncpg://...` |
| `DB_API_URL` | backend | URL db-api-server |
| `STORAGE_API_URL` | backend, indexer | URL db-api-server |
| `INDEXER_API_URL` | backend | URL rag-indexer |
| `REDIS_URL` | backend, indexer | `redis://redis:6379` |
| `ENCRYPTION_KEY` | backend, indexer | Ключ шифрования API-ключей моделей |
| `WATCHDOG_INTERVAL_SEC` | indexer | Интервал watchdog (сек) |
| `HOST_AGENT_URL` | backend | URL host-agent (`http://host.docker.internal:9090`) |
| `HOST_AGENT_TOKEN` | backend | Shared secret для аутентификации host-agent |
| `VAULTS_PATH` | backend, indexer | Host-side путь к vault root (монтируется как `/data/vaults`) |
| `GIT_AUTHOR_NAME` | indexer | Deployment-level fallback git identity (дефолт: `Mercer`) |
| `GIT_AUTHOR_EMAIL` | indexer | Deployment-level fallback git identity (дефолт: `mercer@local`) |
| `RERANK_OLLAMA_CONCURRENCY` | backend | Параллелизм запросов к Ollama reranker |
| `RERANK_OLLAMA_NUM_PREDICT` | backend | Лимит токенов ответа reranker |

## Campaign State

Полная спецификация контрактов: `context/shared_contracts.md` (раздел «Campaign State»).  
Карта файлов и детали реализации: `context/rag-backend-services.md` (раздел «Campaign State»).

### Назначение

Campaign State — компактное версионируемое состояние конкретной кампании, подтверждаемое пользователем.
Цель — убрать обязательный retrieval из обычного чата: модель получает актуальный state кампании
и недавний контекст диалога сразу, а RAG использует как инструмент только для точных деталей.

### Слои

```
┌──────────────────────────────────────────────────────────────────┐
│                         Campaign State                           │
│                                                                  │
│  Domain system prompt (не меняется)                              │
│       ↓                                                           │
│  Active Campaign State выбранной кампании                        │
│       ↓                                                           │
│  Recent chat history                                              │
│       ↓                                                           │
│  Retrieved evidence — только если модель вызвала search_knowledge│
│       ↓                                                           │
│  Текущее сообщение пользователя                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Конфигурация полей (Stage 1)

- Поля не имеют глобального фиксированного набора; пользователь настраивает упорядоченный список.
- Контракт поля: `key` (immutable), `label`, `description`, `mode` (`single | list`), `enabled`, `display_order`.
- Хранение: `campaign_state_field_configs` (миграция `0007`).
- Любая мутация инкрементирует `Campaign.config_version` (миграция `0008`).
- Удаление поля каскадно очищает значение в активной версии state, создаёт новую `state_version`,
  пишет `AuditLog` `action='campaign_state_field_cascade_purged'`.

### Версионированное состояние (Stage 2)

- Каждая `state_patch` создаёт новый snapshot в `campaign_state_versions` (`source_kind='patch'`).
- Initial proposal → первая версия (`source_kind='initial'`, `state_version=1`, `base_state_version=NULL`).
- Optimistic locking: `base_state_version` + `config_version` проверяются сервером.
- LLM не возвращает state целиком — только точечные patch-операции:
  - `replace_single`, `clear_single` — для `mode='single'`;
  - `add_list_item`, `update_list_item`, `resolve_list_item`, `remove_list_item` — для `mode='list'`.
- Каждая операция содержит `reason` и `source_refs`.
- Fail-fast валидация (Stage 2); будущие версии могут поддержать partial apply.

### Initial State (Stage 3)

- Источник — только Markdown (PDF исключён).
- Пользователь выбирает `.md`-документы кампании через существующий Full Documents UI.
- LLM получает конфигурацию полей + полные тексты; возвращает proposal со статусами
  `proposed | empty | needs_clarification` per field.
- Proposal сохраняется в Redis (`campaign_state_initial:{campaign_id}`, TTL 3h) с `DocumentSnapshot`-ами
  (md5) для проверки неизменности источника.
- Apply создаёт первую `state_version='initial'`.

### Update Mode — интеграция (Stage 5)

- `UpdateModeGenerationResult.state_patch` (discriminated union) — patch-операции относительно `state_field_snapshot`.
- Update Mode user-review поддерживает частичный apply для state-операций через
  `UpdateModeStatePatchDecisions` (accepted_op_indexes / rejected_op_indexes / edited).
- `ApplyUpdateModeResponse.state_patch_result` — результат отдельной части apply
  (`failed_op_indexes` + `failed_reasons`); файловые правки не валятся из-за state-ошибок.

### Prompt Assembly (Stage 6)

- `campaign_state_compiler.compile_campaign_state(...)` — детерминированный, без LLM, чистая функция.
- Budget ~800 токенов (ключ `chat.campaign_state_token_budget`).
- Поля исключаются целиком, не обрезаются посередине.
- Эвристика токенов: `math.ceil(len(text) / 4)` (согласована с retrieval/update_mode/pipeline_executor).
- `effective_context.compose_full_system_prompt` инжектирует блок в system prompt plain-RAG-пути;
  `compose_state_block_only` подмешивает блок после `_resolve_prompt` в pipeline-пути.
- `GET /api/settings/campaigns/{id}/effective-context?chat_id=...` — debug endpoint без retrieval/LLM.

### Potentially Stale (Stage 7)

- `CampaignStateStaleService.compute_stale_status(campaign_id, db) -> CampaignStateStaleStatus` —
  вычисляется на лету.
- Для всех `source_ref` формата `file:<doc_id>:sha:<sha>` активной версии сравнивается с текущим `Document.md5`.
- AuditLog `chat.agent_loop` пишется на переходе `false → true` (один раз на кампанию).
- Frontend отображает информационное сообщение «В источниках появились обновления» + кнопку запуска Update Mode.
- PDF не является триггером: `Document.status` не отслеживается для PDF-кампаний.

## Conditional / cyclic RAG (chat)

Полные контракты: `context/shared_contracts.md` (раздел «LLM tool-call contracts»).  
Детали реализации: `context/rag-backend-services.md` (раздел «Conditional / cyclic RAG»).

### Архитектура

```
chat turn
    │
    ├─ provider.generate_stream_with_tools(tool_choice='auto')
    │     ↓ tool_calls = [{name=search_knowledge, args={queries,reason}}, ...]
    ├─ SearchKnowledgeService.search(...)
    │     ├─ dedupe queries
    │     ├─ resolve scope (campaign > domain > empty > no_vault)
    │     ├─ retrieve_multi_vault(...) × N queries in parallel
    │     ├─ rerank + truncate to evidence_token_budget
    │     └─ return SearchKnowledgeResult
    ├─ host appends role=tool messages (tool_call_id → result)
    │
    ├─ next round (< max_rounds): tool_choice='auto'
    │     или final round: tool_choice='none' → text answer
    │
    └─ AuditLog chat.agent_loop (rounds, tool_calls_made, policy)
```

### Поведение

- Обычный чат-турн НЕ запускает retrieval автоматически. Модель решает сама, нужно ли
  вызвать `search_knowledge`.
- Scope фиксируется хостом: модель не может расширить или сузить его.
- Если `campaign_id` задан и у кампании ноль тегов → `scope='empty'` (НЕ fallback на домен).
- Если нет enabled-vault → `scope='no_vault'`.

### Retrieval policy

`retrieval.policy` (`platform_settings` → `RetrievalToolSettings.policy`):

| Policy | Семантика |
|---|---|
| `grounded` (default) | Модель обязана искать evidence для кампанийских фактов/лора/именованных сущностей/истории |
| `assistive` | Модель сама решает, нужен ли поиск |

Round cap per turn:

| Policy | Round cap |
|---|---|
| `grounded` | `retrieval.max_rounds_chat` (default 2) |
| `assistive` | `retrieval.max_rounds_assistive` (default 1) |

Token budget evidence per round: `retrieval.evidence_token_budget` (default 4000).

### Дедупликация и bounded latency

- Одинаковый нормализованный query → пустой tool_result с `note='duplicate_query'` (модель увидит dead-end).
- Если `max_rounds==0` — единственный финальный вызов без tool.
- Если хиты не меняются между раундами — host может прервать loop раньше (early-exit логика в `AgentLoop`).

### Observability

На каждом чат-турне с tool-циклом пишется `AuditLog action='chat.agent_loop'` с `payload`:
`rounds` (per-round `queries`, `tool_name`, `hits_count`, `evidence_tokens`, `scope`),
`tool_calls_made`, `policy`.

## Campaign Update Mode — краткое описание

Полная документация: `context/campaign-update-mode.md`

Режим позволяет пользователю актуализировать markdown-документы vault через review-цикл:

1. **Start** — backend ищет релевантные `.md` chunks, восстанавливает полный indexed text, вызывает LLM для получения `edit intents` + `state_patch` операций (Stage 5)
2. **Resolve** — indexer читает оригинальные файлы, вычисляет SHA-256, строит unified diff
3. **Review** — пользователь принимает/отклоняет каждую файловую правку И каждую state-операцию через UI
4. **Apply** — indexer проверяет checksums, делает snapshot-commit, применяет atomic writes, выполняет `git commit`, запускает targeted reindex; backend параллельно применяет state_patch через `campaign_state_value_service.apply_patch`

Архитектурные инварианты:
- `rag-indexer` — единственный владелец filesystem/git операций
- `rag-backend` не читает и не пишет vault файлы напрямую
- Настройки vault хранятся только в PostgreSQL (`vaults` таблица)
- Vault physical root: `/data/vaults/{vault_id}` (не хранится в БД)
- Поддерживаются только `.md` файлы; только `update`, `append`, `create`, `delete_section`, `delete_unique_text`
- Campaign State patch в Update Mode НЕ индексируется как RAG-документ и использует только Markdown-источники (PDF исключён из Update Mode)