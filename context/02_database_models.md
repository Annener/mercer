# Mercer — Схема базы данных (PostgreSQL)

> **Проход 2 из N.**
> Источник: `rag-backend/app/db/models.py` + миграции `0001`–`0018`.
> ORM: SQLAlchemy 2.x (async, `mapped_column`). Движок: PostgreSQL 16.
> Миграции: Alembic, запускаются автоматически при старте `rag-backend`.

---

## Цепочка миграций

| № | Файл | Суть изменения |
|---|---|---|
| 0001 | `0001_initial.py` | Начальная схема: все основные таблицы |
| 0002 | `0002_refactor_tags_documents_remove_worlds.py` | Рефактор тегов/документов, удаление устаревших сущностей |
| 0003 | `0003_add_campaign_id_to_chats.py` | `campaign_id` в `chats` |
| 0004 | `0004_add_pipeline_id_to_messages.py` | `pipeline_id` в `messages` |
| 0005 | `0005_iter1_domain_schema.py` | Домены, промпты, поля уточнения |
| 0006 | `0006_add_uuid_pk_to_models_vaults.py` | UUID PK для моделей и vault |
| 0007 | `0007_rename_api_key_encrypted.py` | Переименование `api_key` → `encrypted_api_key` |
| 0008 | `0008_chat_domain_id_not_null.py` | `domain_id NOT NULL` в `chats` |
| 0009 | `0009_campaigns_schema_sync.py` | Синхронизация схемы campaigns |
| 0010 | `0010_add_tags_and_documents.py` | Добавление tags/documents |
| 0011 | `0011_fix_documents_vault_id.py` | Исправление vault_id в documents |
| 0012 | `0012_fix_tags_campaign_id_type.py` | Тип campaign_id в tags → UUID |
| 0013 | `0013_fix_documents_tags_uuid.py` | UUID-поля в documents/tags |
| 0014 | `0014_sync_orm_schema.py` | Полная синхронизация ORM |
| 0015 | `0015_fix_messages_pipeline_id_type.py` | pipeline_id в messages → String |
| 0016 | `0016_fix_platform_settings_value_type.py` | Тип value в platform_settings |
| 0017 | `0017_add_rerank_models.py` | Новая таблица `rerank_models` |
| 0018 | `0018_cleanup_reranker_platform_settings.py` | Очистка настроек reranker |

---

## Таблицы

### `domains`

Логический контекст платформы. Все сущности привязаны к домену.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `domain_id` | `VARCHAR(64)` | NOT NULL | — | **PK** (строковый, не UUID) |
| `display_name` | `VARCHAR(256)` | NOT NULL | — | Отображаемое имя |
| `description` | `TEXT` | NULL | — | Описание домена |
| `is_system` | `BOOLEAN` | NOT NULL | `false` | Системный домен (не удаляется) |
| `enabled` | `BOOLEAN` | NOT NULL | `true` | Домен активен |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | Дата создания |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | Дата обновления |

**Relationships:** `prompts` → `domain_prompts`, `clarification_fields` → `domain_clarification_fields`

---

### `domain_prompts`

Системные промпты домена (system, clarification, planner, pipeline_router).

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `domain_id` | `VARCHAR(64)` | NOT NULL | — | FK → `domains.domain_id` ON DELETE CASCADE |
| `prompt_type` | `VARCHAR(32)` | NOT NULL | — | Тип: `system`, `clarification`, `planner`, `pipeline_router` |
| `content` | `TEXT` | NOT NULL | — | Текст промпта |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | Дата обновления |

---

### `domain_clarification_fields`

Поля уточнения запроса для домена (FSM уточнения).

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `domain_id` | `VARCHAR(64)` | NOT NULL | — | FK → `domains.domain_id` ON DELETE CASCADE |
| `field_name` | `VARCHAR(64)` | NOT NULL | — | Имя поля (машиночитаемое) |
| `label` | `VARCHAR(256)` | NOT NULL | — | Метка для UI |
| `hint` | `TEXT` | NULL | — | Подсказка пользователю |
| `required` | `BOOLEAN` | NOT NULL | `true` | Обязательное поле |
| `display_order` | `INTEGER` | NOT NULL | `0` | Порядок отображения |

---

### `platform_settings`

Ключ-значение настройки платформы (retrieval.enabled, top_k, и др.).

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `key` | `VARCHAR(128)` | NOT NULL | — | **PK** |
| `value` | `TEXT` | NOT NULL | — | Значение (сериализованное в TEXT) |
| `value_type` | `VARCHAR(16)` | NOT NULL | — | Тип: `int`, `float`, `bool`, `str` |
| `group_name` | `VARCHAR(64)` | NOT NULL | — | Группа настройки |
| `label` | `VARCHAR(256)` | NOT NULL | — | Метка для UI |
| `hint` | `TEXT` | NOT NULL | `""` | Подсказка |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | Дата обновления |

> **Десериализация:** `SettingsService.deserialize_value()` конвертирует TEXT → Python-тип по `value_type`.

---

### `generation_models`

Модели генерации текста (LLM). OpenAI-compatible или Ollama.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `model_id` | `VARCHAR(128)` | NOT NULL | — | Уникальный идентификатор модели (UNIQUE) |
| `provider` | `VARCHAR(64)` | NOT NULL | `openai_compatible` | Провайдер |
| `display_name` | `VARCHAR(256)` | NULL | — | Отображаемое имя |
| `base_url` | `TEXT` | NOT NULL | — | URL API |
| `encrypted_api_key` | `TEXT` | NULL | — | Зашифрованный API-ключ (Fernet) |
| `timeout_seconds` | `INTEGER` | NOT NULL | `60` | Таймаут запроса |
| `is_active` | `BOOLEAN` | NOT NULL | `false` | Активная модель (только одна одновременно) |
| `enabled` | `BOOLEAN` | NOT NULL | `true` | Модель доступна |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

---

### `embedding_models`

Модели эмбеддинга для индексации и поиска.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `model_id` | `VARCHAR(128)` | NOT NULL | — | Уникальный идентификатор (UNIQUE) |
| `provider` | `VARCHAR(32)` | NOT NULL | — | `ollama` или `openai_compatible` |
| `display_name` | `VARCHAR(256)` | NULL | — | |
| `model_name` | `VARCHAR(128)` | NOT NULL | — | Имя модели (для API-запроса) |
| `base_url` | `TEXT` | NOT NULL | — | URL API |
| `encrypted_api_key` | `TEXT` | NULL | — | Зашифрованный API-ключ (Fernet) |
| `dimensions` | `INTEGER` | NOT NULL | — | Размерность вектора |
| `timeout_seconds` | `INTEGER` | NOT NULL | `30` | |
| `max_retries` | `INTEGER` | NOT NULL | `3` | |
| `enabled` | `BOOLEAN` | NOT NULL | `true` | |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

---

### `rerank_models`

Модели реранкинга (добавлены в миграции 0017).

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `model_id` | `VARCHAR(128)` | NOT NULL | — | Уникальный идентификатор (UNIQUE) |
| `provider` | `VARCHAR(64)` | NOT NULL | `openai_compatible` | |
| `display_name` | `VARCHAR(256)` | NULL | — | |
| `base_url` | `TEXT` | NOT NULL | — | |
| `encrypted_api_key` | `TEXT` | NULL | — | Зашифрованный API-ключ (Fernet) |
| `timeout_seconds` | `INTEGER` | NOT NULL | `30` | |
| `is_active` | `BOOLEAN` | NOT NULL | `false` | Активная модель реранкинга |
| `enabled` | `BOOLEAN` | NOT NULL | `true` | |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

---

### `vaults`

Хранилище документов. Привязано к домену. Файлы физически на диске в `./vaults/{vault_id}/`.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `vault_id` | `VARCHAR(128)` | NOT NULL | — | Строковый идентификатор (UNIQUE) |
| `domain_id` | `VARCHAR(64)` | NULL | — | FK → `domains.domain_id` ON DELETE SET NULL |
| `display_name` | `VARCHAR(256)` | NULL | — | |
| `enabled` | `BOOLEAN` | NOT NULL | `true` | |
| `embedding_model_id` | `VARCHAR(128)` | NULL | — | ID модели эмбеддинга (ссылка, не FK) |
| `expected_dimensions` | `INTEGER` | NULL | — | Ожидаемая размерность вектора |
| `chunk_size` | `INTEGER` | NULL | — | Размер чанка в токенах |
| `overlap` | `INTEGER` | NULL | — | Перекрытие чанков |
| `entity_aware_mode` | `BOOLEAN` | NULL | — | Режим entity-aware чанкинга |
| `binding_status` | `VARCHAR(32)` | NOT NULL | `unbound` | `unbound / binding / bound / error` |
| `chunk_count` | `INTEGER` | NOT NULL | `0` | Кол-во проиндексированных чанков |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

**Relationships:** `documents` → `documents`

---

### `tags`

Теги для маркировки документов. Принадлежат домену (не vault).

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `name` | `VARCHAR(128)` | NOT NULL | — | Название тега |
| `domain_id` | `VARCHAR(64)` | NOT NULL | — | FK → `domains.domain_id` ON DELETE CASCADE |
| `campaign_id` | `UUID` | NULL | — | FK → `campaigns.id` ON DELETE SET NULL |
| `color` | `VARCHAR(32)` | NULL | — | Цвет тега для UI (hex или название) |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

**Constraints:** `UNIQUE(name, domain_id)` — `uq_tag_name_domain`

---

### `documents`

Записи об индексируемых файлах внутри vault.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `vault_id` | `VARCHAR(128)` | NOT NULL | — | FK → `vaults.vault_id` ON DELETE CASCADE |
| `source_path` | `TEXT` | NOT NULL | — | Путь к файлу внутри vault |
| `title` | `VARCHAR(512)` | NULL | — | Заголовок (извлекается при парсинге) |
| `md5` | `VARCHAR(32)` | NOT NULL | — | MD5-хэш файла (для обнаружения изменений) |
| `mtime` | `INTEGER` | NOT NULL | — | Время изменения файла (unix timestamp) |
| `indexed_at` | `TIMESTAMPTZ` | NULL | — | Дата успешной индексации |
| `status` | `VARCHAR(32)` | NOT NULL | `pending` | `pending / indexed / error` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

**Relationships:** `labels` → `document_labels`

---

### `document_labels`

Связь многие-ко-многим: документ ↔ тег.

| Колонка | Тип | Nullable | Описание |
|---|---|---|---|
| `document_id` | `UUID` | NOT NULL | **PK**, FK → `documents.id` ON DELETE CASCADE |
| `tag_id` | `UUID` | NOT NULL | **PK**, FK → `tags.id` ON DELETE CASCADE |

---

### `campaigns`

Подконтекст внутри домена. Изолирует набор документов через теги.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `domain_id` | `VARCHAR(64)` | NOT NULL | — | FK → `domains.domain_id` ON DELETE CASCADE |
| `name` | `VARCHAR(256)` | NOT NULL | — | Название кампании |
| `description` | `TEXT` | NULL | — | Описание |
| `system_prompt` | `TEXT` | NULL | — | Системный промпт (приоритет над промптом домена) |
| `last_session_at` | `TIMESTAMPTZ` | NULL | — | Время последней сессии (для сортировки) |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

**Relationships:** `chats`, `tags` (через `campaign_tags`)

---

### `campaign_tags`

Связь многие-ко-многим: кампания ↔ тег.

| Колонка | Тип | Nullable | Описание |
|---|---|---|---|
| `campaign_id` | `UUID` | NOT NULL | **PK**, FK → `campaigns.id` ON DELETE CASCADE |
| `tag_id` | `UUID` | NOT NULL | **PK**, FK → `tags.id` ON DELETE CASCADE |

---

### `chats`

Сессии чата. Обязательно привязаны к домену.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `title` | `VARCHAR(512)` | NOT NULL | `New Chat` | Заголовок (автогенерируется из первого запроса) |
| `vault_id` | `VARCHAR(128)` | NULL | — | Deprecated back-compat; не использовать |
| `domain_id` | `VARCHAR(64)` | NOT NULL | — | FK → `domains.domain_id` ON DELETE CASCADE |
| `campaign_id` | `UUID` | NULL | — | FK → `campaigns.id` ON DELETE SET NULL |
| `pipeline_versions` | `JSONB` | NULL | — | Версии пайплайнов на момент создания (A02) |
| `locked_pipeline_id` | `VARCHAR(64)` | NULL | — | Принудительно зафиксированный pipeline (A03) |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

**Relationships:** `messages`, `clarification_state` (1:1), `campaign`

---

### `messages`

Сообщения чата (user / assistant / system).

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `chat_id` | `UUID` | NOT NULL | — | FK → `chats.id` ON DELETE CASCADE |
| `role` | `VARCHAR(16)` | NOT NULL | — | `user`, `assistant`, `system` |
| `content` | `TEXT` | NOT NULL | — | Текст сообщения |
| `pipeline_id` | `VARCHAR(64)` | NULL | — | ID пайплайна, которым сгенерирован ответ |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

---

### `clarification_states`

Состояние FSM уточнения запроса (1:1 к chat).

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `chat_id` | `UUID` | NOT NULL | — | **PK**, FK → `chats.id` ON DELETE CASCADE |
| `stage` | `VARCHAR(32)` | NOT NULL | — | Стадия: `idle`, `collecting`, `done` и др. |
| `missing_fields` | `JSONB` | NULL | — | Список незаполненных полей (`list[str]`) |
| `collected` | `JSONB` | NULL | — | Собранные ответы (`dict[str, str]`) |
| `turn` | `INTEGER` | NOT NULL | `0` | Счётчик ходов уточнения |
| `next_question` | `TEXT` | NULL | — | Следующий вопрос для пользователя |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

---

### `pipelines`

Конфигурация пайплайнов обработки запросов.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `pipeline_id` | `VARCHAR(64)` | NOT NULL | — | Строковый идентификатор |
| `domain_id` | `VARCHAR(64)` | NOT NULL | — | FK → `domains.domain_id` ON DELETE CASCADE |
| `campaign_id` | `UUID` | NULL | — | FK → `campaigns.id` ON DELETE SET NULL; NULL = общий пайплайн домена |
| `version` | `VARCHAR(32)` | NOT NULL | — | Версия (`v1`, `v2`, ...) |
| `name` | `VARCHAR(256)` | NOT NULL | — | Имя пайплайна |
| `description` | `TEXT` | NULL | — | |
| `steps` | `JSONB` | NOT NULL | — | Список шагов `[PipelineStep, ...]` |
| `final_composition` | `JSONB` | NOT NULL | — | `FinalComposition` (system_prompt финальной композиции) |
| `is_active` | `BOOLEAN` | NOT NULL | `true` | |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

**Constraints:** `UNIQUE(pipeline_id, domain_id, version)` — `uq_pipeline_domain_version`

---

### `pipeline_decisions`

Лог решений PipelineRouter: какой пайплайн был выбран и почему.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `chat_id` | `UUID` | NOT NULL | — | FK → `chats.id` ON DELETE CASCADE |
| `message_id` | `UUID` | NOT NULL | — | ID сообщения (без FK) |
| `selected_pipeline_id` | `VARCHAR(64)` | NOT NULL | — | Выбранный пайплайн |
| `confidence` | `FLOAT` | NOT NULL | — | Уверенность выбора (0.0–1.0) |
| `reasoning` | `TEXT` | NULL | — | Объяснение выбора (от LLM) |
| `mode` | `VARCHAR(16)` | NOT NULL | — | Режим: `llm`, `heuristic`, `locked` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

---

### `audit_logs`

Журнал аудита действий на платформе.

| Колонка | Тип | Nullable | Default | Описание |
|---|---|---|---|---|
| `id` | `UUID` | NOT NULL | `uuid4()` | **PK** |
| `action` | `VARCHAR(64)` | NOT NULL | — | Тип действия (`chat.create`, `vault.delete`, ...) |
| `entity_type` | `VARCHAR(32)` | NULL | — | Тип сущности (`chat`, `vault`, `domain`, ...) |
| `entity_id` | `VARCHAR(128)` | NULL | — | ID сущности |
| `details` | `JSONB` | NULL | — | Детали в JSON |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `now()` | |

---

## Диаграмма связей

```
domains (domain_id PK)
  │
  ├─── domain_prompts (domain_id FK)
  ├─── domain_clarification_fields (domain_id FK)
  ├─── vaults (domain_id FK, SET NULL)
  ├─── tags (domain_id FK, CASCADE)
  ├─── campaigns (domain_id FK, CASCADE)
  │      ├─── campaign_tags (campaign_id FK)
  │      └─── chats (campaign_id FK, SET NULL)
  ├─── chats (domain_id FK, CASCADE)
  │      ├─── messages (chat_id FK, CASCADE)
  │      ├─── clarification_states (chat_id FK, CASCADE)
  │      └─── pipeline_decisions (chat_id FK, CASCADE)
  └─── pipelines (domain_id FK, CASCADE)

vaults (vault_id UNIQUE)
  └─── documents (vault_id FK, CASCADE)
         └─── document_labels (document_id FK, CASCADE)

tags
  └─── document_labels (tag_id FK, CASCADE)
  └─── campaign_tags (tag_id FK, CASCADE)

generation_models  (независимая таблица)
embedding_models   (независимая таблица)
rerank_models      (независимая таблица)
platform_settings  (key-value, независимая таблица)
audit_logs         (независимая таблица)
```

---

## Важные замечания

- **`domain_id`** — строковый PK (не UUID), выбирается вручную при создании домена.
- **`vault_id`** в `vaults` — строковый UNIQUE, не UUID (для удобства именования).
- **Шифрование API-ключей** — `encrypted_api_key` хранится зашифрованным через Fernet. Ключ берётся из env `ENCRYPTION_KEY`. Расшифровка происходит в `SettingsService`.
- **`vault_id` в `chats`** — deprecated, оставлен для обратной совместимости. Основной идентификатор — `domain_id`.
- **`pipeline_versions` в `chats`** — JSONB-словарь `{pipeline_id: version}`, снимок версий на момент создания чата.
- **`steps` и `final_composition` в `pipelines`** — JSONB. Структура описана в `shared_contracts/models.py` классами `PipelineStep` и `FinalComposition`.
- **`clarification_states.chat_id`** — одновременно PK и FK, отношение 1:1 с `chats`.
