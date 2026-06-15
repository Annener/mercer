# Mercer — Модели БД (PostgreSQL)

> **Проход 6 из N.**
> Файл: `rag-backend/app/db/models.py`.
> Миграции: `rag-backend/alembic/versions/`.
> БД: PostgreSQL. ORM: SQLAlchemy 2.x (async, `DeclarativeBase`).

---

## Общая схема таблиц

```
domains
  ├── domain_prompts          (domain_id FK CASCADE)
  ├── domain_clarification_fields (domain_id FK CASCADE)
  ├── vaults                  (domain_id FK SET NULL)
  ├── tags                    (domain_id FK CASCADE)
  ├── campaigns               (domain_id FK CASCADE)
  ├── chats                   (domain_id FK CASCADE)
  └── pipelines               (domain_id FK CASCADE)

vaults
  └── documents               (vault_id FK CASCADE)
        └── document_labels     (document_id FK CASCADE)

tags
  └── document_labels         (tag_id FK CASCADE)

campaigns
  ├── campaign_tags           (M2M: campaign_id + tag_id)
  ├── chats                   (campaign_id FK SET NULL)
  └── pipelines               (campaign_id FK SET NULL)

chats
  ├── messages                (chat_id FK CASCADE)
  ├── clarification_states    (chat_id FK CASCADE, 1:1)
  └── pipeline_decisions      (chat_id FK CASCADE)

platform_settings                  (автономная)
generation_models                  (автономная)
embedding_models                   (автономная)
rerank_models                      (автономная)
audit_logs                         (автономная)
```

---

## Таблицы

### `domains`

| Колонка | Тип | Констраинт | Описание |
|---|---|---|---|
| `domain_id` | `VARCHAR(64)` | PK | Строковый слаг, напр. `"dnd"`, `"work"`, `"default"` |
| `display_name` | `VARCHAR(256)` | NOT NULL | Отображаемое название |
| `description` | `TEXT` | NULL | Описание домена |
| `is_system` | `BOOLEAN` | NOT NULL, default `false` | Системный домен |
| `enabled` | `BOOLEAN` | NOT NULL, default `true` | Виден в UI |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | |

**Relationships:** `prompts` (1:N), `clarification_fields` (1:N)

---

### `domain_prompts`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `domain_id` | `VARCHAR(64)` FK → `domains` CASCADE | |
| `prompt_type` | `VARCHAR(32)` | `system` / `clarification` / `planner` / `pipeline_router` |
| `content` | `TEXT` | Текст промпта |
| `updated_at` | `TIMESTAMPTZ` | |

---

### `domain_clarification_fields`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `domain_id` | `VARCHAR(64)` FK → `domains` CASCADE | |
| `field_name` | `VARCHAR(64)` | Техническое имя поля |
| `label` | `VARCHAR(256)` | Отображаемое название поля |
| `hint` | `TEXT` | Подсказка для пользователя |
| `required` | `BOOLEAN` | Обязательное поле |
| `display_order` | `INTEGER` | Порядок отображения |

---

### `platform_settings`

| Колонка | Тип | Описание |
|---|---|---|
| `key` | `VARCHAR(128)` PK | Ключ настройки, напр. `"retrieval.top_k"` |
| `value` | `TEXT` | Сериализованное значение |
| `value_type` | `VARCHAR(16)` | `"string"` / `"int"` / `"float"` / `"bool"` |
| `group_name` | `VARCHAR(64)` | Группа (для UI) |
| `label` | `VARCHAR(256)` | Отображаемое название |
| `hint` | `TEXT` | Подсказка |
| `updated_at` | `TIMESTAMPTZ` | |

> `SettingsService.deserialize_value()` преобразует `value` в нативный Python-тип по `value_type`.

---

### `generation_models`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `model_id` | `VARCHAR(128)` UNIQUE | Слаг, напр. `"gpt-4o"` |
| `provider` | `VARCHAR(64)` | `"openai_compatible"` |
| `display_name` | `VARCHAR(256)` | |
| `base_url` | `TEXT` | URL эндпоинта |
| `encrypted_api_key` | `TEXT` | Шифрованный API-ключ |
| `timeout_seconds` | `INTEGER` | default 60 |
| `is_active` | `BOOLEAN` | Только одна модель может быть `true` |
| `enabled` | `BOOLEAN` | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

---

### `embedding_models`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `model_id` | `VARCHAR(128)` UNIQUE | |
| `provider` | `VARCHAR(32)` | `"ollama"` / `"openai_compatible"` |
| `display_name` | `VARCHAR(256)` | |
| `model_name` | `VARCHAR(128)` | Техническое имя модели |
| `base_url` | `TEXT` | |
| `encrypted_api_key` | `TEXT` | |
| `dimensions` | `INTEGER` | Размерность вектора |
| `timeout_seconds` | `INTEGER` | default 30 |
| `max_retries` | `INTEGER` | default 3 |
| `enabled` | `BOOLEAN` | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

---

### `rerank_models`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `model_id` | `VARCHAR(128)` UNIQUE | |
| `provider` | `VARCHAR(64)` | `"openai_compatible"` |
| `display_name` | `VARCHAR(256)` | |
| `base_url` | `TEXT` | |
| `encrypted_api_key` | `TEXT` | |
| `timeout_seconds` | `INTEGER` | default 30 |
| `is_active` | `BOOLEAN` | Только одна может быть `true` |
| `enabled` | `BOOLEAN` | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

---

### `vaults`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | Internal UUID |
| `vault_id` | `VARCHAR(128)` UNIQUE | Строковый слаг, используется повсюду |
| `domain_id` | `VARCHAR(64)` FK → `domains` SET NULL | |
| `display_name` | `VARCHAR(256)` | |
| `enabled` | `BOOLEAN` | |
| `embedding_model_id` | `VARCHAR(128)` | Ссылка на `embedding_models.model_id` (не FK!) |
| `expected_dimensions` | `INTEGER` | Ожидаемая размерность |
| `chunk_size` | `INTEGER` | Переопределяет `platform_settings` |
| `overlap` | `INTEGER` | Переопределяет `platform_settings` |
| `entity_aware_mode` | `BOOLEAN` | Переопределяет `platform_settings` |
| `binding_status` | `VARCHAR(32)` | `unbound` / `indexing` / `bound` / `error` |
| `chunk_count` | `INTEGER` | Общее количество чанков |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

**Relationship:** `documents` (1:N, cascade)

> `embedding_model_id` — не foreign key (строка), не UUID. Связь программная.

---

### `documents`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | Этот UUID = `document_id` в LanceDB |
| `vault_id` | `VARCHAR(128)` FK → `vaults.vault_id` CASCADE | |
| `source_path` | `TEXT` | Относительный путь файла внутри vault |
| `title` | `VARCHAR(512)` | |
| `md5` | `VARCHAR(32)` | Checksum для skip-логики |
| `mtime` | `INTEGER` | Unix timestamp изменения файла |
| `indexed_at` | `TIMESTAMPTZ` | NULL до завершения индексации |
| `status` | `VARCHAR(32)` | `pending` / `indexed` / `error` |
| `created_at` | `TIMESTAMPTZ` | |

**Relationship:** `labels` (1:N → `document_labels`)

---

### `tags`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `name` | `VARCHAR(128)` | |
| `domain_id` | `VARCHAR(64)` FK → `domains` CASCADE | |
| `campaign_id` | `UUID` FK → `campaigns` SET NULL | NULL = глобальный тег домена |
| `color` | `VARCHAR(32)` | HEX-цвет |
| `created_at` | `TIMESTAMPTZ` | |

**Constraint:** `UNIQUE(name, domain_id)`

> Тег с `campaign_id = NULL` — глобальный (домен). Тег с `campaign_id != NULL` — принадлежит кампании.

---

### `document_labels` (связка M2M)

| Колонка | Тип |
|---|---|
| `document_id` | `UUID` FK → `documents.id` CASCADE, PK |
| `tag_id` | `UUID` FK → `tags.id` CASCADE, PK |

---

### `campaigns`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `domain_id` | `VARCHAR(64)` FK → `domains` CASCADE | |
| `name` | `VARCHAR(256)` | |
| `description` | `TEXT` | |
| `system_prompt` | `TEXT` | Системный промпт кампании (prior. 1 перед доменом) |
| `last_session_at` | `TIMESTAMPTZ` | |
| `created_at` | `TIMESTAMPTZ` | |

**Relationships:** `campaign_tags` (M2M), `chats` (1:N), `tags` (through `campaign_tags`)

---

### `campaign_tags` (связка M2M)

| Колонка | Тип |
|---|---|
| `campaign_id` | `UUID` FK → `campaigns.id` CASCADE, PK |
| `tag_id` | `UUID` FK → `tags.id` CASCADE, PK |

---

### `chats`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `title` | `VARCHAR(512)` | default `"New Chat"` → автотайтл |
| `vault_id` | `VARCHAR(128)` | Deprecated back-compat, не FK |
| `domain_id` | `VARCHAR(64)` FK → `domains` CASCADE | NOT NULL (инвариант) |
| `campaign_id` | `UUID` FK → `campaigns` SET NULL | Опциональная привязка |
| `pipeline_versions` | `JSONB` | История выполнения pipeline (`last_used.pipeline_id`, `started_at`, `completed_at`) |
| `locked_pipeline_id` | `VARCHAR(64)` | Принудительно зафиксированный pipeline |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |

**Relationships:** `messages` (1:N), `clarification_state` (1:1), `campaign`

---

### `messages`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `chat_id` | `UUID` FK → `chats` CASCADE | |
| `role` | `VARCHAR(16)` | `"user"` / `"assistant"` / `"system"` |
| `content` | `TEXT` | |
| `pipeline_id` | `VARCHAR(64)` | Какой pipeline генерировал (если есть) |
| `created_at` | `TIMESTAMPTZ` | |

---

### `clarification_states`

| Колонка | Тип | Описание |
|---|---|---|
| `chat_id` | `UUID` FK → `chats` CASCADE, PK | 1:1 с чатом |
| `stage` | `VARCHAR(32)` | `"idle"` / `"asking"` / `"done"` |
| `missing_fields` | `JSONB` | `list[str]` незаполненных полей |
| `collected` | `JSONB` | `dict` собранных ответов |
| `turn` | `INTEGER` | Номер хода диалога |
| `next_question` | `TEXT` | Следующий вопрос |
| `updated_at` | `TIMESTAMPTZ` | |

> Алиас `ClarificationStateRow = ClarificationState` — используется в `chat.py` для back-compat.

---

### `pipelines`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | Internal UUID |
| `pipeline_id` | `VARCHAR(64)` | Слаг, используется в логике |
| `domain_id` | `VARCHAR(64)` FK → `domains` CASCADE | |
| `campaign_id` | `UUID` FK → `campaigns` SET NULL | NULL = общий pipeline домена |
| `version` | `VARCHAR(32)` | `"v1"`, `"v2"`, ... автоинкремент |
| `name` | `VARCHAR(256)` | |
| `description` | `TEXT` | |
| `steps` | `JSONB` | `list[PipelineStep]` |
| `final_composition` | `JSONB` | `{"system_prompt": "..."}` |
| `is_active` | `BOOLEAN` | |
| `created_at` | `TIMESTAMPTZ` | |

**Constraint:** `UNIQUE(pipeline_id, domain_id, version)`

---

### `pipeline_decisions`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `chat_id` | `UUID` FK → `chats` CASCADE | |
| `message_id` | `UUID` | |
| `selected_pipeline_id` | `VARCHAR(64)` | |
| `confidence` | `FLOAT` | |
| `reasoning` | `TEXT` | |
| `mode` | `VARCHAR(16)` | `"general"` / `"campaign"` / `"locked"` |
| `created_at` | `TIMESTAMPTZ` | |

---

### `audit_logs`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | `UUID` PK | |
| `action` | `VARCHAR(64)` | Напр. `"chat.create"`, `"pipeline_router_failure"`, `"document.delete"` |
| `entity_type` | `VARCHAR(32)` | `"chat"` / `"pipeline"` / `"document"` / ... |
| `entity_id` | `VARCHAR(128)` | UUID или слаг сущности |
| `details` | `JSONB` | Произвольные данные |
| `created_at` | `TIMESTAMPTZ` | |

---

## Ключевые нюансы

- **`domain_id` в `chats` — NOT NULL** (инвариант arch): чат всегда привязан к домену.
- **`vault_id` в `chats`** — deprecated, не FK, хранится для обратной совместимости.
- **`documents.id` = `document_id` в LanceDB** — связь через UUID.
- **`embedding_model_id` в `vaults`** — строка, не FK; связь программная через `model_id`.
- **Тег с `campaign_id = NULL`** = глобальный тег домена; тег с `campaign_id != NULL` = принадлежит кампании.
- **`platform_settings.value`** хранится как TEXT; тип задаёт `value_type`.
- **`pipelines.steps`** и **`final_composition`** хранятся как JSONB; десериализируются в `PipelineStep`/`FinalComposition` в `pipeline_service.py`.
- **API-ключи** моделей хранятся зашифрованными (`encrypted_api_key`). Расшифровка через `IndexerDBClient.decrypt_api_key()` / `SettingsService`.

---

## Миграции Alembic

**Директория:** `rag-backend/alembic/versions/`

| Файл | Описание |
|---|---|
| `0001_initial.py` | Инициальная схема: domains, vaults, documents, chats, messages, settings, generation_models |
| `0002_*.py` | Добавление embedding_models |
| `0003_*.py` | Добавление полей к доменам/vaults |
| `0004_*.py` | Pipelines: таблицы `pipelines`, `pipeline_decisions` |
| `0005_*.py` | Tags и document_labels |
| `0006_*.py` | Campaigns + campaign_tags |
| `0007_*.py` | `clarification_states`, `domain_clarification_fields`, `domain_prompts` |
| `0008_*.py` | `audit_logs`, rerank_models, `chats.domain_id NOT NULL` |
| `0009_campaigns_schema_sync.py` | Синхронизация схемы campaigns (finalized schema) |

> **Запуск миграций:** `alembic upgrade head` (выполняется автоматически при старте контейнера через entrypoint).
