# Mercer — Шаг 1: Структура репозитория, ORM-модели, shared_contracts

> Файл описывает состояние **as is** на момент создания (июнь 2026).  
> Используется как контекст для AI-доработок. Не является документацией для пользователей.

---

## 1. Структура репозитория (корень)

```
mercer/
├── .env.example               # шаблон переменных окружения
├── docker-compose.yml         # оркестрация всех сервисов
├── pytest.ini                 # конфигурация тестов
├── requirements-dev.txt       # dev-зависимости (pytest, httpx и т.д.)
│
├── shared_contracts/          # ОБЩИЙ пакет контрактов (Pydantic-модели)
│   └── models.py              # все Pydantic-схемы: запросы, ответы, ORM-читалки
│
├── rag-backend/               # основной FastAPI-бэкенд (порт 8000, публичный)
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── logging_config.py
│       ├── api/               # HTTP-роутеры
│       ├── db/                # ORM-модели, сессия, миграции
│       ├── services/          # бизнес-логика
│       ├── pipelines/         # YAML/JSON-описания пайплайнов
│       ├── planners/          # planner-агенты
│       ├── providers/         # LLM-провайдеры
│       ├── domains/           # доменно-специфичная логика
│       └── static/            # фронтенд (HTML + JS + CSS)
│
├── db-api-server/             # LanceDB HTTP-обёртка (порт 8080, внутренний)
├── rag-indexer/               # индексер документов (порт 9000, внутренний)
├── pdf-sidecar/               # PDF-парсинг (сайдкар для индексера)
├── config/                    # YAML-конфиги сервисов (storage.config.yaml и др.)
├── tests/                     # тесты
└── concept_plan/              # архитектурные заметки (arch.md, Concept.md и т.д.)
```

---

## 2. Docker-сервисы

| Сервис | Порт (внутри сети) | Публичный порт | Описание |
|---|---|---|---|
| `rag-db` | 5432 | — | PostgreSQL 16 |
| `db-api-server` | 8080 | — | HTTP-обёртка над LanceDB |
| `rag-indexer` | 9000 | — | Индексер документов |
| `rag-backend` | 8000 | **8000** | Основной FastAPI-бэкенд + фронтенд |

Все сервисы в одной сети `rag-net` (bridge). `rag-indexer` недоступен снаружи — только через `rag-backend` как proxy.

### Ключевые env-переменные (rag-backend)
```
DATABASE_URL          postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform
STORAGE_API_URL       http://db-api-server:8080
INDEXER_API_URL       http://rag-indexer:9000
ENCRYPTION_KEY        (секрет для шифрования API-ключей моделей)
```

---

## 3. Инициализация приложения (main.py)

Порядок при старте (`lifespan`):
1. `setup_logging("backend")`
2. `run_migrations()` — Alembic-миграции применяются автоматически
3. `settings_service.load_settings(db)` — загрузка всех настроек из `platform_settings`
4. `settings_service.load_active_provider(db)` — загрузка активной генеративной модели
5. Если нет активной модели — warning (приложение стартует, LLM-фичи недоступны)

Зарегистрированные роутеры:
- `chat_router` (без prefix, теги chat)
- `config_router` (без prefix, теги config)
- `settings_router` (prefix `/api/settings`)
- `db_management_router` (без prefix)

Статика: `/static` → `rag-backend/app/static/`  
Корневой маршрут `/` → `static/index.html`

---

## 4. База данных — ORM-модели (`app/db/models.py`)

Все модели используют `DeclarativeBase` из SQLAlchemy 2.x с `Mapped`/`mapped_column`.

### 4.1 Domain
```
Таблица: domains
PK: domain_id (String(64)) — НЕ uuid, строковый идентификатор
Поля: display_name, description, is_system, enabled, created_at, updated_at
Relations: prompts → [DomainPrompt], clarification_fields → [DomainClarificationField]
```
**Важно:** `domain_id` — строка (например `"dnd"`, `"legal"`), не UUID. Это PK таблицы, колонки `id` нет.

### 4.2 DomainPrompt
```
Таблица: domain_prompts
PK: id (UUID)
FK: domain_id → domains.domain_id CASCADE DELETE
Поля: prompt_type (String(32)), content (Text), updated_at
prompt_type ∈ {"system", "clarification", "planner", "pipeline_router"}
```

### 4.3 DomainClarificationField
```
Таблица: domain_clarification_fields
PK: id (UUID)
FK: domain_id → domains.domain_id CASCADE DELETE
Поля: field_name, label, hint, required (bool), display_order (int)
Ordered by display_order в relationship
```

### 4.4 PlatformSetting
```
Таблица: platform_settings
PK: key (String(128))
Поля: value (Text — PLAIN TEXT), value_type ("int"|"float"|"bool"|"str"),
      group_name, label, hint, updated_at
```
**Важно:** `value` хранится как строка. Десериализацию делает `SettingsService.deserialize_value()`.

### 4.5 GenerationModel
```
Таблица: generation_models
PK: id (UUID)
Unique: model_id (String(128))
Поля: provider ("openai_compatible"), display_name, base_url,
      encrypted_api_key (зашифровано ENCRYPTION_KEY), timeout_seconds,
      is_active (bool), enabled (bool), created_at, updated_at
```
**Важно:** только одна модель может иметь `is_active=True`. API-ключ хранится зашифрованным.

### 4.6 EmbeddingModel
```
Таблица: embedding_models
PK: id (UUID)
Unique: model_id (String(128))
Поля: provider ("ollama"|"openai_compatible"), display_name, model_name,
      base_url, encrypted_api_key, dimensions (int), timeout_seconds,
      max_retries, enabled, created_at, updated_at
```

### 4.7 Vault
```
Таблица: vaults
PK: id (UUID)
Unique: vault_id (String(128)) — используется как business-key во всём коде
FK: domain_id → domains.domain_id SET NULL
Поля: display_name, enabled, embedding_model_id (str, не FK!),
      expected_dimensions, chunk_size, overlap, entity_aware_mode,
      binding_status ("unbound"|"indexing"|"bound"|"error"),
      chunk_count, created_at, updated_at
Relations: documents → [Document]
```
**Важно:** `embedding_model_id` в Vault — строка, не FK. Связь логическая.  
`vault_id` (не `id`) используется как идентификатор в API и LanceDB.

### 4.8 Tag
```
Таблица: tags
PK: id (UUID)
FK: domain_id → domains.domain_id CASCADE DELETE
FK: campaign_id → campaigns.id SET NULL (nullable)
Поля: name, color
Unique: (name, domain_id) — uq_tag_name_domain
```
**Важно:** теги принадлежат **домену**, а не Vault. `campaign_id` опционален — тег без campaign_id считается глобальным тегом домена.

### 4.9 Document
```
Таблица: documents
PK: id (UUID)
FK: vault_id → vaults.vault_id CASCADE DELETE (по vault_id, не id!)
Поля: source_path (Text), title, md5, mtime (int), indexed_at,
      status ("pending"|"indexed"|"error"), created_at
Relations: labels → [DocumentLabel]
```

### 4.10 DocumentLabel (M2M: Document ↔ Tag)
```
Таблица: document_labels
Composite PK: (document_id UUID FK→documents.id, tag_id UUID FK→tags.id)
Оба CASCADE DELETE
```

### 4.11 Campaign
```
Таблица: campaigns
PK: id (UUID)
FK: domain_id → domains.domain_id CASCADE DELETE
Поля: name, description, system_prompt (Text nullable), last_session_at, created_at
Relations: chats → [Chat], tags → [Tag] (через campaign_tags, viewonly)
```
**Важно:** `system_prompt` в Campaign перекрывает системный промпт домена при наличии.

### 4.12 campaign_tags (M2M: Campaign ↔ Tag)
```
Таблица: campaign_tags
Composite PK: (campaign_id UUID FK→campaigns.id, tag_id UUID FK→tags.id)
Оба CASCADE DELETE
```

### 4.13 Chat
```
Таблица: chats
PK: id (UUID)
FK: domain_id → domains.domain_id CASCADE DELETE (NOT NULL — инвариант)
FK: campaign_id → campaigns.id SET NULL (nullable)
Поля: title (default "New Chat"), vault_id (deprecated, back-compat),
      pipeline_versions (JSONB nullable), locked_pipeline_id (nullable),
      created_at, updated_at
Relations: messages → [Message] (ordered by created_at),
           clarification_state → ClarificationState (uselist=False),
           campaign → Campaign
```
**Инвариант:** `domain_id` обязателен для Chat — это основная единица контекста.  
`vault_id` на Chat deprecated, оставлен для back-compat.

### 4.14 Message
```
Таблица: messages
PK: id (UUID)
FK: chat_id → chats.id CASCADE DELETE
Поля: role ("user"|"assistant"|"system"), content (Text),
      pipeline_id (nullable), created_at
```

### 4.15 ClarificationState (алиас: ClarificationStateRow)
```
Таблица: clarification_states
PK: chat_id (UUID FK→chats.id CASCADE DELETE) — один к одному с Chat
Поля: stage (String(32)), missing_fields (JSONB list), collected (JSONB dict),
      turn (int, default 0), next_question (Text nullable), updated_at
```
Алиас `ClarificationStateRow = ClarificationState` для обратной совместимости импортов в `chat.py`.

### 4.16 AuditLog
```
Таблица: audit_logs
PK: id (UUID)
Поля: action (String(64)), entity_type, entity_id, details (JSONB), created_at
```

### 4.17 Pipeline
```
Таблица: pipelines
PK: id (UUID)
FK: domain_id → domains.domain_id CASCADE DELETE
FK: campaign_id → campaigns.id SET NULL (nullable)
Unique: (pipeline_id, domain_id, version) — uq_pipeline_domain_version
Поля: pipeline_id (String(64)), version, name, description,
      steps (JSONB list), final_composition (JSONB dict),
      is_active (bool), created_at
```

### 4.18 PipelineDecision
```
Таблица: pipeline_decisions
PK: id (UUID)
FK: chat_id → chats.id CASCADE DELETE
Поля: message_id (UUID, не FK), selected_pipeline_id, confidence (float),
      reasoning, mode, created_at
```

---

## 5. DB Session (`app/db/session.py`)

```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform")
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
```

- Используется `asyncpg` (async драйвер)
- `expire_on_commit=False` — объекты не инвалидируются после commit
- `get_db()` — FastAPI dependency (Depends)

---

## 6. App Config (`app/config.py`)

Runtime-конфиг (Pydantic BaseModel, не ORM):

```
AppConfig
├── vaults: dict[str, VaultConfig]           # vault_id → конфиг
├── embedding_models: dict[str, EmbeddingModelConfig]
├── generation_models: dict[str, GenerationModelConfig]
├── reranker: RerankerConfig
├── chat: ChatConfig
│   ├── max_clarification_turns: int = 3
│   ├── stream_answers: bool = True
│   └── auto_title: bool = True
├── retrieval: RetrievalConfig
│   ├── enabled: bool = True
│   └── top_k: int = 10
├── pipelines: PipelinesConfig
│   ├── path: str = "/app/pipelines"
│   ├── reload_interval_seconds: float = 2.0
│   └── debounce_seconds: float = 2.0
├── ui: UIConfig
│   └── db_management_enabled: bool = True
└── validation_rules: dict[str, ValidationRuleRange]
```

`EmbeddingModelConfig.provider` ∈ `{"ollama", "openai_compatible"}`  
`GenerationModelConfig.provider` = `"openai_compatible"` (единственный поддерживаемый)

---

## 7. shared_contracts/models.py — Pydantic-схемы

Единый пакет контрактов, импортируемый всеми сервисами.

### 7.1 Базовый класс ORMModel
```python
class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
```
Содержит `_coerce_uuid_fields` — автоматически конвертирует `uuid.UUID` → `str` при создании из ORM-объекта.  
**Важно:** list-поля (relationships) намеренно пропускаются — lazy-load в async вызвал бы MissingGreenlet. List-поля заполняются **явно** в роутах.

### 7.2 Чат — запросы/ответы

| Класс | Поля | Назначение |
|---|---|---|
| `CreateChatRequest` | `domain_id: str\|None`, `vault_id: str\|None` (deprecated), `campaign_id: str\|None` | POST /chat/create |
| `CreateChatResponse` | `chat_id: str`, `title: str` | ответ на создание чата |
| `SendMessageRequest` | `content: str`, `stream: bool = True` | POST /chat/{id}/send_stream |
| `ClarificationResponse` | `message_id`, `role`, `content`, `clarification_id`, `stage` | ответ при уточнении |
| `ClarificationAnswer` | `clarification_id: str`, `answers: dict[str, str]` | ответ пользователя на clarification |

**Важно:** `CreateChatRequest.domain_id` — `Optional[str]` (для back-compat), но в новом коде должен быть заполнен. `SendMessageRequest.stream` по умолчанию `True`.

### 7.3 Домены

| Класс | Назначение |
|---|---|
| `DomainRead(ORMModel)` | чтение домена |
| `DomainCreate` | создание (domain_id обязателен) |
| `DomainUpdate` | частичное обновление |
| `DomainPromptRead(ORMModel)` | промпт домена (`prompt_type` ∈ system/clarification/planner/pipeline_router) |
| `DomainPromptUpdate` | обновление промпта |
| `DomainClarificationFieldRead/Create` | поля уточнения домена |

### 7.4 Модели

| Класс | Назначение |
|---|---|
| `GenerationModelRead/Create/Update` | генеративные модели |
| `EmbeddingModelRead/Create/Update` | embedding-модели |

`GenerationModelRead.has_api_key: bool` — не хранит ключ, только признак наличия.  
`EmbeddingModelRead.has_api_key: bool` — аналогично.

### 7.5 Vault / Document / Tag / Campaign

| Класс | Назначение |
|---|---|
| `VaultRead/Create/Update(ORMModel)` | vault CRUD |
| `TagRead(ORMModel)` | тег (domain_id + опц. campaign_id) |
| `TagCreate` | создание тега (привязка к домену, не Vault) |
| `TagsGrouped` | `global_tags: list[TagRead]`, `by_campaign: dict[str, list[TagRead]]` |
| `DocumentRead(ORMModel)` | документ с `tags: list[TagRead] = []` (заполняется вручную) |
| `DocumentLabelWrite` | полная замена тегов документа: `tag_ids: list[str]` |
| `CampaignRead(ORMModel)` | кампания с `tags: list[TagRead] = []` |
| `CampaignCreate/Update` | CRUD кампании |

### 7.6 Pipeline

| Класс | Назначение |
|---|---|
| `PipelineStep` | шаг пайплайна: `type` (retrieval\|final), `order`, `system_prompt`, `top_k`, `tag_ids`, `is_final`, `role` |
| `FinalComposition` | `system_prompt: str` — финальная компоновка |
| `PipelineRead/Create/Update(ORMModel)` | CRUD пайплайна |
| `PipelineExecutionContext` | полный контекст запуска: заполняется поэтапно (до и после pipeline_router.select()) |
| `PipelineStepResult` | результат одного шага |
| `PipelineResult` | итоговый результат пайплайна |

**Важно:** `PipelineExecutionContext.pipeline_id/steps/final_composition` — `None` при создании, заполняются после `pipeline_router.select()`. Поле `vault_id` deprecated, использовать `vault_ids: list[str]`.

### 7.7 Retrieval

| Класс | Назначение |
|---|---|
| `RetrievalContext` | контекст поиска (vault_ids, domain_id, campaign_id, tag_ids, top_k) |
| `RetrievalResult` | один результат поиска |
| `SearchHit` | чанк из LanceDB (chunk_id, document_id, text, metadata, score) |
| `SearchRequest` | запрос к db-api-server /index/search |
| `SearchResponse` | ответ с `results: list[SearchHit]` |

### 7.8 Индексер / LanceDB контракты

| Класс | Назначение |
|---|---|
| `UpsertChunk` | чанк для записи в LanceDB |
| `UpsertRequest/Response` | запись чанков пакетом |
| `StartIndexTaskRequest/Response` | запуск задачи индексации |
| `TaskStateResponse` | состояние задачи |
| `IndexState / FileIndexState` | состояние индексации файлов |

### 7.9 WebSocket-сообщения (индексер → фронтенд)

| Класс | `type` | Назначение |
|---|---|---|
| `WSFileChunkProgressMessage` | `file_chunk_progress` | прогресс обработки файла |
| `WSFileStatusMessage` | `file_status` | финальный статус файла |
| `WSTaskCancelledMessage` | `task_cancelled` | отмена задачи |
| `WSTaskCompleteMessage` | `task_complete` | завершение задачи |

---

## 8. Ключевые инварианты и нюансы

1. **domain_id** — обязательный параметр для Chat (NOT NULL). `vault_id` на Chat deprecated.
2. **vault_id** (строка типа `"my_vault"`) — business-key. В API и LanceDB используется именно он, не UUID `id`.
3. **Теги принадлежат домену**, не Vault. `campaign_id` в Tag = `None` → глобальный тег домена.
4. **GenerationModel.is_active** — ровно одна активная модель. Хранится в `settings_service`.
5. **API-ключи** хранятся зашифрованными (`encrypted_api_key`). Десериализует `settings_service`.
6. **PlatformSetting.value** — всегда строка. Тип задаётся `value_type`. Десериализация через `SettingsService.deserialize_value()`.
7. **Lazy relationships в async** — не трогать через `from_attributes`. List-поля заполнять явно после запроса с `selectinload`.
8. **ClarificationStateRow** = алиас `ClarificationState` для обратной совместимости.
9. **Pipeline.campaign_id = None** означает общий пайплайн домена (не привязан к кампании).
10. **PipelineStep.is_final** — ровно один шаг в пайплайне должен быть `True`.
