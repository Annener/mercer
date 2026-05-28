# Spec-00: Architecture Overview

Это read-only документ. Он не содержит задач для реализации.
Codex обязан прочитать этот файл перед выполнением любого другого Spec.
Все технические решения в Spec-01..06 основаны на образе системы, описанном здесь.

## 1. Финальный образ системы

После выполнения всех Spec (01–06) система выглядит так:

- `config.yaml` не существует. Все рантайм-параметры хранятся в PostgreSQL (таблица `platform_settings`).
- Домены, vault'ы, модели управляются через Settings UI и хранятся в PostgreSQL.
- Генеративная модель переключается без рестарта (hot-swap через `asyncio.Lock`).
- `rag-indexer` читает конфигурацию напрямую из PostgreSQL через `asyncpg`.
- URL pdf-sidecar хранится в `platform_settings`, не в переменной окружения.
- URL db‑api‑server передаётся через переменную окружения `STORAGE_API_URL` (в `docker-compose.yml`).
- Pipeline'ы — декларативные JSONB-записи в PostgreSQL, не YAML-файлы. Связи с документами (`document_ids`) хранятся непосредственно в массиве внутри JSONB-поля `steps` каждой записи pipeline. Отдельная таблица связок не используется.
- Миры и кампании — сущности в PostgreSQL; управляют metadata-фильтрацией в LanceDB.
- **Миры и кампании НЕ удаляются через UI или API.** Удаление происходит только вручную в файловой системе + удаление соответствующих чанков через окно «Управление хранилищем» (`DELETE /db/docs/{id}`).
- Чат поддерживает два пути: через Planner (fallback) и через PipelineExecutor (основной).

## 2. Сервисная архитектура (без изменений)

```
Browser SPA
    │ HTTP / SSE
    ▼
rag-backend :8000  (FastAPI, Python 3.13)
    │ asyncpg / SQLAlchemy async
    ├──► rag-db :5432  (PostgreSQL)
    │ HTTP
    ├──► db-api-server :8080  (LanceDB, vector search)
    │ HTTP SSE
    └──► pdf-sidecar :8765  (macOS host, unstructured hires)

rag-indexer :9000  (FastAPI, отдельный контейнер)
    │ asyncpg.pool (прямое подключение к PostgreSQL — NEW)
    ├──► rag-db :5432
    │ HTTP
    ├──► db-api-server :8080
    └──► pdf-sidecar :8765
```

**Не трогать никогда:**
- `db-api-server` — его код, конфиг, API
- `storage.config.yaml` — конфиг db-api-server, остаётся как есть (будет вынесен на отдельный сервер)
- `pdf-sidecar` — весь код, скрипты, `requirements.txt`

## 3. Полная схема PostgreSQL

### 3.1. Домены и промпты

```sql
CREATE TABLE domains (
    domain_id    VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(255) NOT NULL,
    description  TEXT,
    is_system    BOOLEAN DEFAULT FALSE,
    enabled      BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE domain_prompts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id   VARCHAR(32) NOT NULL REFERENCES domains(domain_id) ON DELETE CASCADE,
    prompt_type VARCHAR(32) NOT NULL,  -- system, clarification, planner, pipeline_router
    content     TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(domain_id, prompt_type)
);

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

### 3.2. Рантайм-параметры

```sql
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

**Seed-данные (16 параметров):**

| key | value_type | group_name | default | label | hint |
|---|---|---|---|---|---|
| retrieval.enabled | bool | retrieval | true | Поиск по базе знаний | Включает поиск по базе знаний при ответах. Если выключено — модель отвечает только из своих знаний. |
| retrieval.top_k | int | retrieval | 10 | Глубина поиска | Сколько фрагментов текста передавать модели. Больше — полнее контекст, но медленнее. |
| retrieval.reranker_enabled | bool | retrieval | false | Переранжирование | Включает переранжирование результатов поиска для повышения релевантности. |
| chunking.chunk_size | int | chunking | 2000 | Размер фрагмента | Максимальный размер одного фрагмента текста при индексации (в словах). |
| chunking.overlap | int | chunking | 64 | Перекрытие | Количество слов, повторяющихся между соседними фрагментами. |
| chunking.entity_aware_mode | bool | chunking | true | Умный чанкинг | Распознаёт именованные сущности и старается не разрывать связанные описания. |
| chat.max_clarification_turns | int | chat | 3 | Лимит уточнений | Максимальное количество уточняющих вопросов перед ответом. 0 — без уточнений. |
| chat.stream_answers | bool | chat | true | Стриминг ответов | Показывает ответ по мере генерации. Если выключено — ответ появится целиком. |
| chat.auto_title | bool | chat | true | Автозаголовок | Автоматически придумывает название для нового чата. |
| reranker.enabled | bool | reranker | false | Включить reranker | Требует настройки провайдера ниже. |
| reranker.provider | str | reranker | null | Провайдер reranker | Например: cohere, jina. |
| reranker.base_url | str | reranker | null | URL reranker | URL API reranker-провайдера. |
| reranker.model_name | str | reranker | null | Модель reranker | Название reranker-модели у провайдера. |
| pdf_sidecar.url | str | sidecar | http://host.docker.internal:8765 | URL PDF-сайдкара | Сервис для парсинга PDF. host.docker.internal — стандартный адрес хоста из Docker. |
| pdf_sidecar.timeout_seconds | int | sidecar | 180 | Таймаут сайдкара | Максимальное время ожидания ответа от сайдкара на один файл. |
| pdf_sidecar.fallback_to_pdfminer | bool | sidecar | true | Фоллбэк на pdfminer | Если сайдкар недоступен — использовать быстрый парсер pdfminer вместо него. |

### 3.3. Модели

```sql
CREATE TABLE generation_models (
    model_id          VARCHAR(128) PRIMARY KEY,
    provider          VARCHAR(32) NOT NULL DEFAULT 'openai_compatible',
    display_name      VARCHAR(255),
    base_url          VARCHAR(512) NOT NULL,
    encrypted_api_key TEXT,
    timeout_seconds   INT DEFAULT 60,
    is_active         BOOLEAN DEFAULT FALSE,
    enabled           BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_generation_models_active ON generation_models(is_active) WHERE is_active = TRUE;

CREATE TABLE embedding_models (
    model_id          VARCHAR(128) PRIMARY KEY,
    provider          VARCHAR(32) NOT NULL,  -- ollama | openai_compatible
    display_name      VARCHAR(255),
    model_name        VARCHAR(255) NOT NULL,
    base_url          VARCHAR(512) NOT NULL,
    encrypted_api_key TEXT,
    dimensions        INT NOT NULL,
    timeout_seconds   INT DEFAULT 30,
    max_retries       INT DEFAULT 3,
    enabled           BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.4. Vault'ы

```sql
CREATE TABLE vaults (
    vault_id           VARCHAR(64) PRIMARY KEY,
    domain_id          VARCHAR(32) NOT NULL REFERENCES domains(domain_id),
    display_name       VARCHAR(255),
    enabled            BOOLEAN DEFAULT TRUE,
    embedding_model_id VARCHAR(128) REFERENCES embedding_models(model_id),
    expected_dimensions INT,
    chunk_size         INT,      -- NULL = use platform_settings default
    overlap            INT,      -- NULL = use platform_settings default
    entity_aware_mode  BOOLEAN,  -- NULL = use platform_settings default
    binding_status     VARCHAR(16) DEFAULT 'unbound',  -- unbound|indexing|bound|error
    chunk_count        INT DEFAULT 0,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_vaults_domain   ON vaults(domain_id);
CREATE INDEX idx_vaults_enabled  ON vaults(enabled);
```

**Примечание:** Таблица `vault_bindings` удалена. Все поля (модель, размеры, статус, счётчик) перенесены в `vaults`.

**Путь vault'а:** Формируется по соглашению `/data/vaults/{vault_id}`. Это хардкод, соответствующий монтированию volume в `docker-compose.yml`. Отдельное поле `path` в таблице отсутствует.

### 3.5. Чаты и сообщения

```sql
CREATE TABLE chats (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              VARCHAR(512),
    vault_id           VARCHAR(64) REFERENCES vaults(vault_id),
    domain_id          VARCHAR(32) REFERENCES domains(domain_id),
    world_id           VARCHAR(64) DEFAULT NULL,   -- NEW (Spec-04), nullable
    locked_pipeline_id VARCHAR(64) DEFAULT NULL,   -- NEW (Spec-04), nullable
    pipeline_versions  JSONB,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE messages (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id    UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role       VARCHAR(16) NOT NULL,  -- user | assistant
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE clarification_states (
    chat_id        UUID PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
    stage          VARCHAR(32) NOT NULL,
    missing_fields JSONB,
    collected      JSONB,
    turn           INT DEFAULT 0,
    next_question  TEXT,
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action      VARCHAR(64) NOT NULL,
    entity_type VARCHAR(32),
    entity_id   VARCHAR(128),
    details     JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.6. Миры, кампании, pipeline'ы

```sql
CREATE TABLE worlds (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    world_id    VARCHAR(64) NOT NULL,
    vault_id    VARCHAR(64) NOT NULL REFERENCES vaults(vault_id),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    path_prefix VARCHAR(512) NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(world_id, vault_id)
);
CREATE INDEX idx_worlds_vault ON worlds(vault_id);

CREATE TABLE campaigns (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id VARCHAR(64) NOT NULL,
    world_id    VARCHAR(64) NOT NULL,
    vault_id    VARCHAR(64) NOT NULL REFERENCES vaults(vault_id),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    path_prefix VARCHAR(512) NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(campaign_id, world_id),
    -- Примечание: внешний ключ на worlds.world_id отсутствует — приложение обеспечивает целостность.
    -- Однако для SQLAlchemy ORM при необходимости можно объявить ForeignKeyConstraint.
);

CREATE TABLE pipelines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id       VARCHAR(64) NOT NULL,
    domain_id         VARCHAR(32) NOT NULL REFERENCES domains(domain_id),
    version           VARCHAR(16) NOT NULL,
    name              VARCHAR(255) NOT NULL,
    description       TEXT,
    steps             JSONB NOT NULL,
    final_composition JSONB NOT NULL,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(pipeline_id, version)
);
CREATE INDEX idx_pipelines_domain ON pipelines(domain_id, is_active);
```

**Примечание:** Связь pipeline с документами хранится непосредственно в массиве `document_ids` внутри JSONB-поля `steps`. Отдельная таблица `pipeline_book_bindings` не создаётся.

```sql
CREATE TABLE pipeline_decisions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id              UUID NOT NULL REFERENCES chats(id),
    message_id           UUID NOT NULL REFERENCES messages(id),
    query                TEXT NOT NULL,
    selected_pipeline_id VARCHAR(64) NOT NULL,
    confidence           FLOAT NOT NULL,
    reasoning            TEXT,
    mode                 VARCHAR(16) NOT NULL,  -- auto | override | lock
    created_at           TIMESTAMPTZ DEFAULT NOW()
);
```

#### 3.6.1. JSONB-схема поля `steps`

Массив объектов. Каждый объект описывает один шаг pipeline.

**Обязательные поля каждого шага:**
- `order` (int) — порядок выполнения, уникален в рамках pipeline
- `type` (string, enum: `book` | `world` | `campaign`) — тип источника контекста
- `name` (string) — человекочитаемое имя шага (отображается в UI прогресс-бара)
- `role` (string, enum: `methodology` | `lore` | `campaign_context` | `character_sheet` | `session_log` | `rules`) — роль контекста, используется для заголовков разделителей в `format_context_with_role`
- `system_prompt` (string) — промпт для LLM на этом шаге; поддерживает переменную `{context}`
- `top_k` (int, optional) — если задан, переопределяет глобальный `retrieval.top_k`

**Условные поля (в зависимости от `type`):**
- При `type: book` — обязательное поле `document_ids` (массив строк, ID документов)
- При `type: world` — обязательное поле `world_id` (строка) и опциональное `categories` (массив строк, соответствует подпапкам в `worlds/{world_id}/`, например `["lore", "rules", "pantheon"]`)
- При `type: campaign` — обязательное поле `campaign_id` (строка)

**Пример валидной структуры:**

```json
[
  {
    "order": 1,
    "type": "book",
    "name": "Методология DM",
    "role": "methodology",
    "system_prompt": "Проанализируй запрос с точки зрения методологии ведения игры.\n\nКонтекст:\n{context}",
    "top_k": 5,
    "document_ids": ["doc_abc123", "doc_def456"]
  },
  {
    "order": 2,
    "type": "world",
    "name": "Лор мира",
    "role": "lore",
    "system_prompt": "Найди в лоре мира релевантные факты.\n\nКонтекст:\n{context}",
    "world_id": "forgotten_realms",
    "categories": ["pantheon", "factions"]
  },
  {
    "order": 3,
    "type": "campaign",
    "name": "Контекст кампании",
    "role": "campaign_context",
    "system_prompt": "Учти текущий прогресс кампании.\n\nКонтекст:\n{context}",
    "campaign_id": "curse_of_strahd"
  }
]
```

#### 3.6.2. JSONB-схема поля `final_composition`

Объект, описывающий финальную стадию pipeline (объединение результатов всех шагов).

**Обязательные поля:**
- `system_prompt` (string) — промпт для финального LLM-вызова; поддерживает переменные `{context}` и `{collected_fields}`

**Пример:**

```json
{
  "system_prompt": "Объедини результаты всех шагов в связный ответ для DM.\n\nКонтекст по шагам:\n{context}\n\nСобранные поля уточнения:\n{collected_fields}"
}
```

## 4. Карта зависимостей

```
rag-backend
  ├─ settings_service.py     читает → platform_settings, generation_models
  ├─ domain_service.py       читает → domains, domain_prompts, domain_clarification_fields
  ├─ pipeline_service.py     читает → pipelines
  ├─ pipeline_executor.py    использует → settings_service, retrieval
  ├─ pipeline_router.py      использует → pipeline_service, domain_service, settings_service
  └─ api/chat.py             использует → все сервисы выше

rag-indexer
  └─ app/db_client.py        читает → platform_settings, vaults, embedding_models, worlds, campaigns
                             пишет → vaults (binding_status, chunk_count)
```

## 5. Конфигурация окружения

`.env` (локальный, не коммитится)

```
POSTGRES_USER=raguser
POSTGRES_PASSWORD=changeme
POSTGRES_DB=ragplatform
DATABASE_URL=postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform
OPENAI_API_KEY=sk-...
ENCRYPTION_KEY=<Fernet key>
VAULTS_PATH=./vaults
LOGS_PATH=./logs
STATE_PATH=./state
CACHE_PATH=./cache
STORAGE_API_URL=http://db-api-server:8080   # URL db-api-server (переменная окружения)
```

`ENCRYPTION_KEY` генерируется: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

`docker-compose.yml` — финальное состояние:
- `rag-backend`: монтирование `config.yaml` удалено. `environment` добавлен `ENCRYPTION_KEY`, `STORAGE_API_URL`.
- `rag-indexer`: монтирование `config.yaml` удалено. `environment` добавлены `DATABASE_URL`, `ENCRYPTION_KEY`, `STORAGE_API_URL`. Vault'ы монтируются `:rw` (вместо `:ro`).

## 6. API — полная карта эндпоинтов

### Существующие (сигнатуры не меняем, добавляем новые поля)

| Метод | URL | Описание |
|---|---|---|
| POST | /chat/create | Создать чат (принимает `world_id` в body) |
| GET | /chat/list | Список чатов |
| GET | /chat/{id} | Чат + `vault_enabled: bool` (new field) |
| DELETE | /chat/{id} | Удалить чат |
| POST | /chat/{id}/rename | Переименовать |
| POST | /chat/{id}/message | SSE-стрим ответа |
| PUT | /chat/{id}/pipeline | Привязать pipeline к чату (`locked_pipeline_id`) |
| GET | /config/domains | Список enabled доменов (из БД) |
| GET | /config/vaults | Список enabled vault'ов (из БД) |
| GET | /db/documents | Документы vault'а |
| DELETE | /db/docs/{id} | Удалить документ |
| POST | /db/search-text | Текстовый поиск |
| POST | /vaults/{id}/reindex | Перезапустить индексацию |
| POST | /vaults/{id}/detach | Отвязать vault от LanceDB |

### Новые — Settings API

| Метод | URL | Описание |
|---|---|---|
| GET | /settings/status | Статус платформы (4 bool поля) |
| GET | /settings/params | Все рантайм-параметры |
| PUT | /settings/params/{key} | Обновить параметр |
| POST | /settings/params/reset | Сбросить все к дефолтам |
| GET | /settings/domains | Все домены |
| POST | /settings/domains | Создать домен |
| PUT | /settings/domains/{id} | Обновить домен |
| DELETE | /settings/domains/{id} | Удалить (запрет на системные, проверка на наличие vault'ов) |
| GET | /settings/domains/{id}/prompts | Промпты домена |
| PUT | /settings/domains/{id}/prompts/{type} | Обновить промпт |
| GET | /settings/domains/{id}/fields | Поля уточнения |
| PUT | /settings/domains/{id}/fields | Обновить поля уточнения |
| GET | /settings/generation-models | Все генеративные модели |
| POST | /settings/generation-models | Создать модель |
| PUT | /settings/generation-models/{id} | Обновить модель |
| DELETE | /settings/generation-models/{id} | Удалить (запрет на активную) |
| POST | /settings/generation-models/{id}/activate | Активировать (hot-swap) |
| POST | /settings/generation-models/{id}/check | Проверить доступность |
| GET | /settings/embedding-models | Все embedding-модели |
| POST | /settings/embedding-models | Создать модель |
| PUT | /settings/embedding-models/{id} | Обновить модель |
| DELETE | /settings/embedding-models/{id} | Удалить (запрет если есть привязанные vault'ы) |
| POST | /settings/embedding-models/{id}/check | Проверить доступность |
| GET | /settings/vaults | Все vault'ы |
| POST | /settings/vaults | Создать vault |
| PUT | /settings/vaults/{id} | Обновить vault |
| DELETE | /settings/vaults/{id} | Удалить vault |
| POST | /settings/vaults/{id}/toggle | Включить/выключить vault |
| GET | /settings/worlds | Все миры (фильтр: vault_id) |
| POST | /settings/worlds | Создать мир |
| PUT | /settings/worlds/{world_id} | Обновить мир (параметр `world_id` — slug) |
| GET | /settings/worlds/{world_id}/campaigns | Кампании мира |
| POST | /settings/worlds/{world_id}/campaigns | Создать кампанию |
| PUT | /settings/worlds/{world_id}/campaigns/{campaign_id} | Обновить кампанию |
| POST | /settings/worlds/{world_id}/campaigns/{campaign_id}/toggle | Вкл/выкл кампанию |
| GET | /settings/pipelines | Pipeline'ы (фильтр: domain_id) |
| POST | /settings/pipelines | Создать pipeline |
| PUT | /settings/pipelines/{id} | Обновить pipeline (новая версия) |
| DELETE | /settings/pipelines/{id} | **Деактивировать pipeline (soft delete: `is_active=false`)**. Физическое удаление не производится. Чаты с `locked_pipeline_id`, указывающим на деактивируемую версию, продолжают использовать её. |
| POST | /settings/pipelines/{id}/activate | Активировать pipeline |

**Примечание:** Эндпоинты `DELETE /settings/worlds/{world_id}` и `DELETE /settings/worlds/{world_id}/campaigns/{campaign_id}` **отсутствуют**. Удаление миров и кампаний выполняется только вручную в файловой системе + удаление соответствующих документов через `DELETE /db/docs/{id}`.

## 7. Соглашения по коду

- Async SQLAlchemy: `async with AsyncSession(engine) as db: ...`
- Pydantic v2: `class Model(BaseModel): model_config = ConfigDict(from_attributes=True)`
- SQLAlchemy 2.x ORM: `class Model(Base): __tablename__ = "..."; col: Mapped[str] = mapped_column(...)`
- Singleton-сервисы: создаются один раз в lifespan FastAPI, хранятся в `app.state`.
- Шифрование: только через `settings_service.encrypt_api_key()` / `decrypt_api_key()`. Plain-текст в БД запрещён.
- **Параметризованные запросы к LanceDB:** При построении `.where()` использовать `?` плейсхолдеры, не конкатенацию строк. Запрещены f-строки для подстановки значений.
- **URL db-api-server:** читается из переменной окружения `STORAGE_API_URL`, значение по умолчанию `http://db-api-server:8080`. В коде использовать константу, получаемую через `os.getenv("STORAGE_API_URL", "http://db-api-server:8080")`.

**SSE-формат** (оба варианта должны поддерживаться параллельно):

```
# Старый (Planner path):
data: {"token": "..."}
data: {"sources": [...]}
data: [DONE]

# Новый (Pipeline path):
data: {"type": "pipeline_selected", "pipeline_id": "...", "pipeline_name": "...", "reasoning": "...", "mode": "auto"}
data: {"type": "progress", "step": 1, "total": 3, "step_name": "Сюжетная арка"}
data: {"type": "step_done", "step": 1, "step_name": "Сюжетная арка", "partial_length": 412}
data: {"type": "token", "content": "..."}
data: {"type": "sources", "grouped_by_step": true, "step_groups": [...]}
data: [DONE]
```

#### 7.1. JSONB-схема поля `step_groups` в событии `sources`

Поле `step_groups` — массив объектов, каждый описывает источники, собранные на конкретном шаге pipeline.

**Структура каждого объекта:**
- `step` (int) — номер шага (соответствует `order` в JSONB `steps`)
- `step_name` (string) — имя шага (из `steps[].name`)
- `sources` (массив объектов) — список источников этого шага
  - `path` (string) — относительный путь файла в vault
  - `page` (int | null) — номер страницы (для PDF, null для Markdown)
  - `vault_id` (string) — ID vault'а

**Пример события `sources` с `grouped_by_step`:**

```json
{
  "type": "sources",
  "grouped_by_step": true,
  "step_groups": [
    {
      "step": 1,
      "step_name": "Методология DM",
      "sources": [
        {"path": "rules/dmg.pdf", "page": 42, "vault_id": "dnd-main"},
        {"path": "rules/phb.pdf", "page": 15, "vault_id": "dnd-main"}
      ]
    },
    {
      "step": 2,
      "step_name": "Лор мира",
      "sources": [
        {"path": "worlds/forgotten_realms/pantheon.md", "page": null, "vault_id": "dnd-main"},
        {"path": "worlds/forgotten_realms/factions.md", "page": null, "vault_id": "dnd-main"}
      ]
    },
    {
      "step": 3,
      "step_name": "Контекст кампании",
      "sources": [
        {"path": "worlds/forgotten_realms/campaigns/curse_of_strahd/act1.md", "page": null, "vault_id": "dnd-main"}
      ]
    }
  ]
}
```

## 8. Информационная плашка (Settings Status)

`GET /settings/status` возвращает 4 поля. UI отображает баннер:

| Условие | Тип | Сообщение |
|---|---|---|
| `has_active_generation_model: false` | 🔴 | «Не настроена генеративная модель. Чат недоступен.» |
| `has_active_embedding_model: false` | 🟡 | «Не настроена embedding-модель. Индексация невозможна.» |
| `has_vaults: false` | ℹ️ | «Создайте vault и добавьте документы для работы с RAG.» |
| `pdf_sidecar_available: false` | ℹ️ | «PDF Sidecar недоступен. PDF будут обработаны через pdfminer.» |

При `has_active_generation_model: false` поле ввода чата заблокировать (`disabled`).

## 9. Файловая структура после выполнения всех Spec

**Удалённые файлы:**
- `rag-backend/app/config.py` — заменён settings_service
- `rag-backend/app/domains/registry.py` — заменён domain_service
- `rag-backend/app/pipelines/registry.py` — заменён pipeline_service
- `rag-backend/app/pipelines/impl.py` — заменён pipeline_executor
- `rag-backend/app/pipelines/*.yaml` — перенесены в PostgreSQL
- `config/config.yaml` — удалён
- `rag-backend/migrations/versions/0001_chat_pg.py`
- `rag-backend/migrations/versions/0002_domain_isolation.py`

**Файл-заглушка (удаляется в Spec-03):**
- `rag-backend/app/config_loader.py` — deprecated-stub до миграции indexer

**Новые файлы:**
- `rag-backend/app/services/settings_service.py`
- `rag-backend/app/services/domain_service.py`
- `rag-backend/app/services/pipeline_service.py`
- `rag-backend/app/services/pipeline_executor.py`
- `rag-backend/app/services/pipeline_router.py`
- `rag-backend/app/api/settings.py`
- `rag-backend/migrations/versions/0001_initial.py`
- `rag-indexer/app/db_client.py`
- `.env.example`
