# Local Multi-Domain RAG Platform - Project Context

**Версия документа:** 1.0  
**Дата генерации:** 2025-06-01  
**Назначение:** Контекст для ИИ-диагностики и разработки

---

## 📋 О Проекте

Локальная multi-domain RAG-платформа для индексации vault-документов, поиска по чанкам, domain-aware чата, уточняющих вопросов и hot-reload pipeline'ов.

### Ключевые возможности

- **Multi-domain архитектура** - поддержка различных предметных областей (DnD, Work, etc.)
- **Vault-based хранение** - документы организованы в хранилища (vaults)
- **Entity-aware chunking** - извлечение сущностей при чанкинге
- **Clarification FSM** - система уточняющих вопросов для неоднозначных запросов
- **Hot-reload pipelines** - декларативные pipeline'ы с горячей перезагрузкой
- **Worlds & Campaigns** - иерархическая организация контекста (для DnD)
- **Settings UI** - управление настройками через веб-интерфейс без рестарта

---

## 🏗️ Архитектура Системы

### Сервисы

```
┌─────────────────────────────────────────────────────────────────┐
│                      Browser / API Client                        │
└─────────────────────────────────────────────────────────────────┘
                                │ HTTP/WebSocket
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    rag-backend :8000                             │
│              (FastAPI, Python 3.13, Public API)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Chat API     │  │ Settings API │  │ DB Management API    │   │
│  │ Pipelines    │  │ Domains      │  │ Vault Operations     │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
        │                      │                      │
        │ asyncpg/SQLAlchemy   │ HTTP                 │ HTTP/SSE
        ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   rag-db :5432   │  │db-api-server:8080│  │rag-indexer :9000 │
│   (PostgreSQL)   │  │  (LanceDB HTTP)  │  │  (FastAPI)       │
│                  │  │                  │  │                  │
│ - Domains        │  │ - Vector Search  │  │ - Indexing       │
│ - Vaults         │  │ - BM25           │  │ - Parsing        │
│ - Chats          │  │ - CRUD Chunks    │  │ - Embedding      │
│ - Messages       │  │                  │  │ - WebSocket      │
│ - Pipelines      │  │                  │  │                  │
│ - Settings       │  │                  │  │                  │
│ - Worlds         │  │                  │  │                  │
│ - Campaigns      │  │                  │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
                               │
                               │ HTTP
                               ▼
                    ┌──────────────────┐
                    │pdf-sidecar :8765 │
                    │  (macOS host)    │
                    │  (unstructured)  │
                    └──────────────────┘
```

### Docker Compose Сервисы

| Сервис | Порт | Описание | Зависимости |
|--------|------|----------|-------------|
| `rag-db` | 5432 | PostgreSQL 16 для метаданных | - |
| `db-api-server` | 8080 | HTTP-прослойка над LanceDB | rag-db |
| `rag-indexer` | 9000 | Индексация документов (внутренний) | db-api-server, rag-db |
| `rag-backend` | 8000 | Публичный API + Web UI | rag-db, db-api-server |
| `pdf-sidecar` | 8765 | OCR/Parsing на хосте (macOS) | - |

### Сеть

Все сервисы работают в Docker сети `rag-net`. Только `rag-backend:8000` проброшен наружу.

---

## 📁 Структура Проекта

```
/workspace/
├── README.md                          # Основная документация
├── docker-compose.yml                 # Оркестрация сервисов
├── requirements-dev.txt               # Dev зависимости
├── pytest.ini                         # Конфиг тестов
│
├── config/
│   ├── config.yaml                    # Главный конфиг (vaults, модели, настройки)
│   └── storage.config.yaml            # Конфиг LanceDB storage
│
├── shared_contracts/
│   ├── __init__.py
│   ├── models.py                      # Pydantic модели для API контрактов
│   └── pyproject.toml
│
├── rag-backend/                       # Основной backend сервис
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini                    # Миграции БД
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # Точка входа FastAPI
│   │   ├── config.py                  # Парсинг config.yaml
│   │   ├── logging_config.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── models.py              # SQLAlchemy ORM модели
│   │   │   ├── session.py             # DB сессии
│   │   │   └── migrations.py          # Alembic миграции
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── chat.py                # Chat endpoints
│   │   │   ├── settings.py            # Settings management API
│   │   │   ├── db_management.py       # DB/Vault operations
│   │   │   └── config_api.py          # Config reload API
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── settings_service.py    # Settings singleton
│   │   │   ├── domain_service.py      # Domain logic
│   │   │   ├── retrieval.py           # Retrieval from LanceDB
│   │   │   ├── planner.py             # LLM-based planning
│   │   │   ├── pipeline_executor.py   # Pipeline execution
│   │   │   ├── pipeline_router.py     # Pipeline selection
│   │   │   ├── prompt_pack.py         # Prompt templates
│   │   │   └── clarification_fsm.py   # Clarification state machine
│   │   ├── providers/
│   │   │   └── generation/
│   │   │       ├── __init__.py
│   │   │       ├── base.py            # Base generation provider
│   │   │       └── openai_compatible.py
│   │   ├── domains/
│   │   │   ├── __init__.py
│   │   │   ├── registry.py
│   │   │   ├── default/
│   │   │   ├── dnd/
│   │   │   └── work/
│   │   ├── pipelines/
│   │   │   ├── __init__.py
│   │   │   └── registry.py
│   │   ├── planners/
│   │   │   └── __init__.py
│   │   └── static/
│   │       └── js/
│   │           ├── api.js
│   │           ├── chat.js
│   │           ├── db_management.js
│   │           ├── settings.js
│   │           └── sidebar.js
│   └── pipelines/                     # Hot-reload pipelines
│       ├── dnd/
│       │   ├── impl.py
│       │   └── rule_lookup.yaml
│       └── work/
│           ├── impl.py
│           └── work_lookup.yaml
│
├── rag-indexer/                       # Индексация документов
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── indexer_worker.py
│   ├── config.py
│   ├── config_loader.py
│   ├── logging_config.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── db_client.py               # Async DB client
│   │   ├── indexer_service.py         # Indexing logic
│   │   └── websocket_manager.py       # WS progress streaming
│   ├── embedding/
│   │   ├── __init__.py
│   │   ├── base_provider.py
│   │   ├── cache.py
│   │   ├── ollama_provider.py
│   │   └── openai_provider.py
│   └── parser/
│       ├── chunking/
│       │   ├── __init__.py
│       │   ├── embedding_enricher.py
│       │   ├── entity_chunker.py
│       │   └── generic_chunker.py
│       ├── parsing/
│       │   ├── __init__.py
│       │   ├── md_parser.py
│       │   └── pdf_parser.py
│       ├── preprocessing/
│       │   ├── __init__.py
│       │   ├── pdf_page_merger.py
│       │   └── preprocessor.py
│       ├── scanning/
│       │   └── vault_scanner.py
│       └── state/
│           ├── __init__.py
│           └── state_manager.py
│
├── db-api-server/                     # LanceDB HTTP wrapper
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── config.py
│   ├── config_loader.py
│   ├── logging_config.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── index.py                   # Index CRUD + search
│   └── storage/
│       ├── __init__.py
│       └── lancedb_store.py           # LanceDB operations
│
├── pdf-sidecar/                       # PDF parsing на macOS хосте
│   ├── README.md
│   ├── app.py
│   ├── parser.py
│   ├── preprocessor.py
│   ├── requirements.txt
│   ├── install.sh
│   ├── start.sh
│   └── status.sh
│
└── specs_update/                      # Технические спецификации
    ├── Spec-00-Architecture-Overview-artifact.md
    ├── Spec-01-Database-Foundation.md
    ├── Spec-02a-Settings-Services.md
    ├── Spec-02b-Settings-API.md
    ├── Spec-02c-Settings-API.md
    ├── Spec-03a-Indexer-DB-Client.md
    ├── Spec-03b-Indexer-Parser-and-Cleanup.md
    ├── Spec-04a-Retrieval-and-Pipeline-Service.md
    ├── Spec-04b-Pipeline-Executor.md
    ├── Spec-04c-Pipeline-Router-and-Chat-Integration.md
    ├── Spec-05a-Settings-UI-Foundation.md
    ├── Spec-05b-Settings-UI.md
    ├── Spec-05c-Settings-UI.md
    └── Spec-06-Pipelines-And-Worlds-UI.md
```

---

## 🗄️ Схема Базы Данных (PostgreSQL)

### Таблицы

#### 1. Домены и Промпты

```sql
-- domains - предметные области
CREATE TABLE domains (
    domain_id    VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(255) NOT NULL,
    description  TEXT,
    is_system    BOOLEAN DEFAULT FALSE,
    enabled      BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- domain_prompts - промпты для доменов
CREATE TABLE domain_prompts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id   VARCHAR(32) NOT NULL REFERENCES domains(domain_id) ON DELETE CASCADE,
    prompt_type VARCHAR(32) NOT NULL,  -- system, clarification, planner, pipeline_router
    content     TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(domain_id, prompt_type)
);

-- domain_clarification_fields - поля для уточняющих вопросов
CREATE TABLE domain_clarification_fields (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id     VARCHAR(32) NOT NULL REFERENCES domains(domain_id) ON DELETE CASCADE,
    field_name    VARCHAR(64) NOT NULL,
    label         VARCHAR(255) NOT NULL,
    hint          TEXT,
    required      BOOLEAN DEFAULT TRUE,
    display_order INT DEFAULT 0,
    UNIQUE(domain_id, field_name)
);
```

#### 2. Настройки Платформы

```sql
-- platform_settings - runtime параметры
CREATE TABLE platform_settings (
    key        VARCHAR(128) PRIMARY KEY,
    value      TEXT NOT NULL,
    value_type VARCHAR(16) NOT NULL,  -- int, float, bool, str
    group_name VARCHAR(64) NOT NULL,
    label      VARCHAR(255) NOT NULL,
    hint       TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Seed данные (16 параметров):**
- `retrieval.enabled` (bool) = true
- `retrieval.top_k` (int) = 10
- `retrieval.reranker_enabled` (bool) = false
- `chunking.chunk_size` (int) = 2000
- `chunking.overlap` (int) = 64
- `chunking.entity_aware_mode` (bool) = true
- `chat.max_clarification_turns` (int) = 3
- `chat.stream_answers` (bool) = true
- `chat.auto_title` (bool) = true
- `reranker.enabled` (bool) = false
- `reranker.provider` (str) = null
- `reranker.base_url` (str) = null
- `reranker.model_name` (str) = null
- `pdf_sidecar.url` (str) = "http://host.docker.internal:8765"
- `pdf_sidecar.timeout_seconds` (int) = 180
- `pdf_sidecar.fallback_to_pdfminer` (bool) = true

#### 3. Модели

```sql
-- generation_models - LLM для генерации ответов
CREATE TABLE generation_models (
    model_id          VARCHAR(128) PRIMARY KEY,
    provider          VARCHAR(32) NOT NULL DEFAULT 'openai_compatible',
    display_name      VARCHAR(255),
    base_url          VARCHAR(512) NOT NULL,
    encrypted_api_key TEXT,
    timeout_seconds   INT NOT NULL DEFAULT 60,
    is_active         BOOLEAN NOT NULL DEFAULT FALSE,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_generation_models_active 
ON generation_models(is_active) WHERE is_active = true;

-- embedding_models - модели для эмбеддингов
CREATE TABLE embedding_models (
    model_id        VARCHAR(128) PRIMARY KEY,
    provider        VARCHAR(32) NOT NULL,  -- ollama, openai_compatible
    display_name    VARCHAR(255),
    model_name      VARCHAR(255) NOT NULL,
    base_url        VARCHAR(512) NOT NULL,
    encrypted_api_key TEXT,
    dimensions      INT NOT NULL,
    timeout_seconds INT NOT NULL DEFAULT 30,
    max_retries     INT NOT NULL DEFAULT 3,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

#### 4. Vaults

```sql
-- vaults - хранилища документов
CREATE TABLE vaults (
    vault_id           VARCHAR(64) PRIMARY KEY,
    domain_id          VARCHAR(32) NOT NULL REFERENCES domains(domain_id),
    display_name       VARCHAR(255),
    enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    embedding_model_id VARCHAR(128) REFERENCES embedding_models(model_id),
    expected_dimensions INT,
    chunk_size         INT,
    overlap            INT,
    entity_aware_mode  BOOLEAN,
    binding_status     VARCHAR(16) NOT NULL DEFAULT 'unbound',
    chunk_count        INT NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_vaults_domain ON vaults(domain_id);
CREATE INDEX idx_vaults_enabled ON vaults(enabled);
```

#### 5. Чаты и Сообщения

```sql
-- chats - сессии чатов
CREATE TABLE chats (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              VARCHAR(512),
    vault_id           VARCHAR(64) REFERENCES vaults(vault_id),
    domain_id          VARCHAR(32) REFERENCES domains(domain_id),
    world_id           VARCHAR(64),
    locked_pipeline_id VARCHAR(64),
    pipeline_versions  JSONB,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

-- messages - сообщения в чатах
CREATE TABLE messages (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id    UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role       VARCHAR(16) NOT NULL,  -- user, assistant, system
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- clarification_states - FSM состояния уточнений
CREATE TABLE clarification_states (
    chat_id       UUID PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
    stage         VARCHAR(32) NOT NULL,  -- idle, collecting, complete, fallback
    missing_fields JSONB,
    collected     JSONB,
    turn          INT NOT NULL DEFAULT 0,
    next_question TEXT,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
```

#### 6. Worlds и Campaigns (DnD)

```sql
-- worlds - миры (контекстные группы)
CREATE TABLE worlds (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    world_id    VARCHAR(64) NOT NULL,
    vault_id    VARCHAR(64) NOT NULL REFERENCES vaults(vault_id),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    path_prefix VARCHAR(512) NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(world_id, vault_id)
);
CREATE INDEX idx_worlds_vault ON worlds(vault_id);

-- campaigns - кампании внутри миров
CREATE TABLE campaigns (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id VARCHAR(64) NOT NULL,
    world_id    VARCHAR(64) NOT NULL,
    vault_id    VARCHAR(64) NOT NULL REFERENCES vaults(vault_id),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    path_prefix VARCHAR(512) NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(campaign_id, world_id)
);
```

#### 7. Pipelines

```sql
-- pipelines - декларативные pipeline'ы
CREATE TABLE pipelines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id       VARCHAR(64) NOT NULL,
    domain_id         VARCHAR(32) NOT NULL REFERENCES domains(domain_id),
    version           VARCHAR(16) NOT NULL,
    name              VARCHAR(255) NOT NULL,
    description       TEXT,
    steps             JSONB NOT NULL,
    final_composition JSONB NOT NULL,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(pipeline_id, version)
);
CREATE INDEX idx_pipelines_domain ON pipelines(domain_id, is_active);

-- pipeline_decisions - аудит выбора pipeline
CREATE TABLE pipeline_decisions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id             UUID NOT NULL REFERENCES chats(id),
    message_id          UUID NOT NULL REFERENCES messages(id),
    query               TEXT NOT NULL,
    selected_pipeline_id VARCHAR(64) NOT NULL,
    confidence          FLOAT NOT NULL,
    reasoning           TEXT,
    mode                VARCHAR(16) NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
```

#### 8. Аудит

```sql
-- audit_logs - логирование действий
CREATE TABLE audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action      VARCHAR(64) NOT NULL,
    entity_type VARCHAR(32),
    entity_id   VARCHAR(128),
    details     JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 🔌 API Endpoints

### Backend API (`http://localhost:8000`)

#### Health & Status

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Platform status |

#### Settings API (`/api/settings`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/settings/status` | Platform readiness status |
| GET | `/api/settings/params` | Get all platform settings |
| PUT | `/api/settings/params/{key}` | Update setting value |
| POST | `/api/settings/params/reset` | Reset to defaults |
| GET | `/api/settings/domains` | List domains |
| POST | `/api/settings/domains` | Create domain |
| PUT | `/api/settings/domains/{domain_id}` | Update domain |
| DELETE | `/api/settings/domains/{domain_id}` | Delete domain |
| GET | `/api/settings/domains/{domain_id}/prompts` | Get domain prompts |
| PUT | `/api/settings/domains/{domain_id}/prompts/{prompt_type}` | Update prompt |
| GET | `/api/settings/domains/{domain_id}/fields` | Get clarification fields |
| PUT | `/api/settings/domains/{domain_id}/fields` | Update fields |
| GET | `/api/settings/generation-models` | List generation models |
| POST | `/api/settings/generation-models` | Create model |
| PUT | `/api/settings/generation-models/{model_id}` | Update model |
| DELETE | `/api/settings/generation-models/{model_id}` | Delete model |
| POST | `/api/settings/generation-models/{model_id}/activate` | Activate model |
| GET | `/api/settings/embedding-models` | List embedding models |
| POST | `/api/settings/embedding-models` | Create model |
| PUT | `/api/settings/embedding-models/{model_id}` | Update model |
| DELETE | `/api/settings/embedding-models/{model_id}` | Delete model |
| GET | `/api/settings/vaults` | List vaults |
| POST | `/api/settings/vaults` | Create vault |
| PUT | `/api/settings/vaults/{vault_id}` | Update vault |
| DELETE | `/api/settings/vaults/{vault_id}` | Delete vault |
| GET | `/api/settings/worlds` | List worlds |
| POST | `/api/settings/worlds` | Create world |
| PUT | `/api/settings/worlds/{world_id}` | Update world |
| GET | `/api/settings/campaigns` | List campaigns |
| POST | `/api/settings/campaigns` | Create campaign |
| PUT | `/api/settings/campaigns/{campaign_id}` | Update campaign |
| GET | `/api/settings/pipelines` | List pipelines |
| POST | `/api/settings/pipelines` | Create pipeline |
| PUT | `/api/settings/pipelines/{pipeline_id}` | Update pipeline |

#### Chat API (`/api/chat`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat/create` | Create new chat |
| GET | `/api/chat/list` | List chats |
| GET | `/api/chat/{chat_id}` | Get chat with messages |
| DELETE | `/api/chat/{chat_id}` | Delete chat |
| POST | `/api/chat/{chat_id}/rename` | Rename chat |
| POST | `/api/chat/{chat_id}/message` | Send message (streaming) |
| PUT | `/api/chat/{chat_id}/pipeline` | Lock pipeline for chat |

#### DB Management API (`/api/db`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/db/documents?vault_id=...` | List documents in vault |
| GET | `/api/db/docs/{document_id}/chunks?vault_id=...` | Get document chunks |
| POST | `/api/db/search/text` | Text search in vault |
| POST | `/api/db/search/text/by-domain` | Text search by domain |
| DELETE | `/api/db/docs/{document_id}?vault_id=...` | Delete document |
| POST | `/api/vaults/{vault_id}/reindex` | Trigger reindex |
| POST | `/api/indexer/tasks/{task_id}/cancel` | Cancel indexer task |
| GET | `/api/indexer/tasks/{task_id}/state` | Get task state |
| POST | `/api/vaults/{vault_id}/detach` | Detach vault (clear data) |
| GET | `/api/db/ui` | DB Management UI page |

### Indexer API (внутренний, `http://rag-indexer:9000`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/tasks` | Start indexing task |
| GET | `/api/v1/tasks` | List active tasks |
| POST | `/api/v1/tasks/{task_id}/cancel` | Cancel task |
| GET | `/api/v1/tasks/{task_id}/state` | Get task state |
| WS | `/api/v1/tasks/{task_id}/stream` | WebSocket progress stream |

### DB API Server (внутренний, `http://db-api-server:8080`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/index/upsert` | Upsert chunks |
| POST | `/index/search` | Vector search |
| DELETE | `/index/document/{id}` | Delete document |
| GET | `/index/documents?vault_id=...` | List documents |
| GET | `/index/document/{id}/chunks?vault_id=...` | Get chunks |
| POST | `/index/search/text` | BM25 text search |
| DELETE | `/index/vault/{vault_id}` | Delete vault data |

---

## 📊 Shared Contracts (Pydantic Models)

### Ключевые модели из `shared_contracts/models.py`

#### Индексация

```python
FileIndexState:
  - checksum_md5: str
  - chunk_ids: list[str]
  - status: Literal["pending", "parsing", "chunking", "indexing", "done", "error", "cancelled", "empty", "indexed"]
  - chunks_total: int
  - chunks_processed: int
  - error: str | None

IndexState:
  - task_id: str
  - vault_id: str
  - status: Literal["running", "done", "error", "cancelled"]
  - files: dict[str, FileIndexState]
```

#### Документы и Чанки

```python
DocumentRecord:
  - document_id: str
  - vault_id: str
  - source_path: str
  - checksum: str
  - metadata: dict
  - chunk_count: int

ChunkRecord:
  - chunk_id: str
  - document_id: str
  - vault_id: str
  - text: str
  - vector: list[float] | None
  - metadata: dict
  - summary: str | None
```

#### Чат

```python
ChatMessage:
  - message_id: str
  - chat_id: str
  - role: Literal["user", "assistant", "system"]
  - content: str
  - created_at: datetime

ChatRecord:
  - chat_id: str
  - title: str
  - vault_id: str | None
  - domain_id: str | None
  - world_id: str | None
  - locked_pipeline_id: str | None
  - pipeline_versions: dict[str, str]

ClarificationState:
  - stage: Literal["idle", "collecting", "complete", "fallback"]
  - missing_fields: list[str]
  - collected: dict[str, Any]
  - turn: int
  - next_question: str | None
```

#### Pipeline

```python
PipelineStep:
  - order: int
  - type: Literal["book", "world", "campaign"]
  - name: str
  - role: Literal["methodology", "lore", "campaign_context", "character_sheet", "session_log", "rules"]
  - system_prompt: str
  - top_k: int | None
  - document_ids: list[str] | None
  - world_id: str | None

PipelineRead:
  - pipeline_id: str
  - domain_id: str
  - version: str
  - name: str
  - steps: list[PipelineStep]
  - final_composition: FinalComposition
  - is_active: bool
```

#### WebSocket сообщения

```python
WSFileChunkProgressMessage:
  - type: "file_chunk_progress"
  - task_id: str
  - file_path: str
  - stage: Literal["parsing", "chunking", "indexing", "done", "error"]
  - chunks_total: int
  - chunks_processed: int

WSTaskCompleteMessage:
  - type: "task_complete"
  - task_id: str
  - files_total: int
  - files_indexed: int
```

---

## ⚙️ Конфигурация

### config/config.yaml

Основные секции:

```yaml
vaults:
  dnd-main:
    vault_id: "dnd-main"
    domain_id: "dnd"
    path: "/data/vaults/dnd"
    enabled: true

embedding_models:
  nomic-local:
    model_id: "nomic-local"
    provider: "ollama"
    model_name: "nomic-embed-text"
    base_url: "http://host.docker.internal:11434"
    dimensions: 768
    enabled: true

generation_models:
  deepseek:
    model_id: "deepseek-chat"
    provider: "openai_compatible"
    base_url: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"
    enabled: true

chat:
  max_clarification_turns: 3
  stream_answers: true
  auto_title: true

retrieval:
  enabled: true
  top_k: 10
  reranker_enabled: false

chunking:
  chunk_size: 2000
  overlap: 64
  entity_aware_mode: true

pipelines:
  enabled: true
  path: "/app/pipelines"
  reload_interval_seconds: 2.0

ui:
  db_management_enabled: true

pdf_sidecar:
  url: "http://host.docker.internal:8765"
  timeout_seconds: 180
  fallback_to_pdfminer: true
```

### Environment Variables

```bash
DATABASE_URL=postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform
ENCRYPTION_KEY=<fernet-key-32-bytes>
STORAGE_API_URL=http://db-api-server:8080
INDEXER_API_URL=http://rag-indexer:9000
DB_API_URL=http://db-api-server:8080
OPENAI_API_KEY=<your-key>
SERVICE_PORT=8000
```

---

## 🔄 Основные Процессы

### 1. Индексация документа

```
User → POST /api/vaults/{vault_id}/reindex
     ↓
rag-backend → POST http://rag-indexer:9000/api/v1/tasks
     ↓
rag-indexer:
  1. Scan vault directory
  2. For each file:
     a. Check MD5 checksum
     b. Parse (PDF → text via sidecar or pdfminer)
     c. Chunk (entity-aware, 2000 words, overlap 64)
     d. Enrich chunks with entities
     e. Generate embeddings (via Ollama/OpenAI)
     f. Upsert to LanceDB via db-api-server
  3. Stream progress via WebSocket
  4. Update state in PostgreSQL
```

### 2. Обработка сообщения в чате

```
User → POST /api/chat/{chat_id}/message
     ↓
rag-backend:
  1. Save user message to DB
  2. Load ClarificationState
  3. If stage="idle":
     a. Call Planner.decide()
     b. If clarification_needed → start_collecting()
     c. Return clarification question
  4. If stage="collecting":
     a. Process answer via FSM
     b. If complete → execute pipeline
  5. Execute pipeline:
     a. Retrieve chunks from LanceDB
     b. Build context
     c. Call LLM for answer
     d. Stream response
  6. Save assistant message
```

### 3. Hot-reload Pipeline

```
Pipeline Executor (background):
  1. Poll /app/pipelines every 2s
  2. Detect changes (debounce 2s)
  3. Parse YAML manifest + load Python module
  4. Validate pipeline structure
  5. If valid → atomic swap in registry
  6. If invalid → log error, keep old version
```

---

## 🛠️ Диагностика и Troubleshooting

### Типичные проблемы и решения

#### Порт 8000 занят
```bash
docker compose ps
lsof -i :8000
```

#### Ollama недоступна из контейнера
- Проверить, что Ollama слушает внешний интерфейс
- Проверить `base_url` в config.yaml
- Для macOS: использовать `host.docker.internal`

#### OCR не извлекает текст
- Проверить логи `logs/indexer.log`
- Убедиться, что PDF содержит сканы
- Проверить доступность pdf-sidecar: `curl http://host.docker.internal:8765/health`

#### Нет места на диске
Проверить объёмы:
- `data/postgres` - метаданные чатов
- `data/lancedb` - векторы и чанки
- `cache/embeddings` - кэш эмбеддингов

#### Сервис unhealthy
```bash
docker compose logs --tail=100 rag-backend
docker compose logs --tail=100 rag-indexer
docker compose logs --tail=100 db-api-server
```

#### Pipeline не обновился
- Проверить синтаксис pipeline.yaml
- Убедиться, что `pipelines.enabled: true`
- Проверить логи на ошибки валидации

---

## 📦 Запросы файлов для диагностики

При работе с этим контекстом, ИИ может запросить следующие файлы для углублённой диагностики:

### Для проблем с индексацией:
- `rag-indexer/app/indexer_service.py`
- `rag-indexer/parser/chunking/entity_chunker.py`
- `rag-indexer/parser/parsing/pdf_parser.py`
- `rag-indexer/embedding/openai_provider.py`
- `rag-indexer/storage/storage_client.py`

### Для проблем с чатом:
- `rag-backend/app/services/planner.py`
- `rag-backend/app/services/pipeline_executor.py`
- `rag-backend/app/services/retrieval.py`
- `rag-backend/app/services/clarification_fsm.py`
- `rag-backend/app/providers/generation/openai_compatible.py`

### Для проблем с настройками:
- `rag-backend/app/services/settings_service.py`
- `rag-backend/app/services/domain_service.py`
- `rag-backend/app/api/settings.py`

### Для проблем с БД:
- `rag-backend/app/db/models.py`
- `rag-backend/app/db/migrations.py`
- `rag-backend/migrations/versions/*.py`

### Для проблем с UI:
- `rag-backend/app/static/js/chat.js`
- `rag-backend/app/static/js/settings.js`
- `rag-backend/app/static/js/db_management.js`

### Для проблем со storage:
- `db-api-server/storage/lancedb_store.py`
- `db-api-server/api/index.py`
- `config/storage.config.yaml`

---

## 📝 Примечания для ИИ

1. **Конфигурация хранится в PostgreSQL**, не в YAML (кроме storage.config.yaml для db-api-server)
2. **ENCRYPTION_KEY** обязателен для работы с API ключами моделей
3. **pdf-sidecar** работает на macOS хосте, не в Docker
4. **Миры и кампании НЕ удаляются через API** - только вручную через ФС
5. **Pipelines декларативные** - JSONB в БД, не YAML файлы (кроме legacy lookup файлов)
6. **Clarification FSM** ограничивает число раундов через `chat.max_clarification_turns`
7. **Hot-reload pipeline'ов** атомарный - невалидная версия игнорируется

---

## 🔗 Ссылки

- OpenAPI Docs: `http://localhost:8000/docs`
- DB Management UI: `http://localhost:8000/db/ui`
- Specs: `/workspace/specs_update/`
