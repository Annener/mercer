# Spec-01: Database Foundation

Перед выполнением прочитай `Spec-00-Architecture-Overview.md` целиком.

Этот Spec реализует только фундамент — схему БД и конфигурацию окружения. Никакой бизнес-логики здесь нет.

**Зависит от:** `Spec-00` (финальная схема и seed-данные).

**Цель:** Создать единственную чистую миграцию Alembic, которая разворачивает финальную схему БД с нуля, включает seed-данные, и обновить конфигурацию окружения (`.env.example`, `docker-compose.yml`).

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/app/db/models.py` — текущие ORM-модели, которые будут переписаны
- `rag-backend/app/db/migrations.py` — текущие миграции, включая `migrate_vault_bindings_from_json()`, которую необходимо удалить
- `rag-backend/app/db/session.py` — текущая настройка AsyncSession и SessionLocal (не трогать)
- `rag-backend/app/domains/*/prompts.yaml` — существующие промпты для seed
- `rag-backend/app/services/clarification_fsm.py` — текущие поля уточнения домена `dnd`
- `docker-compose.yml` — текущая конфигурация сервисов

## Задачи

### 1. Удалить старые миграции

Удалить все файлы в `rag-backend/migrations/versions/`.

⚠️ **Важно для существующих БД:** Обратная совместимость не требуется. Если в окружении уже применялись старые миграции (`0001_chat_pg.py`, `0002_domain_isolation.py`), выполнить:

```bash
alembic stamp head          # пометить БД как актуальную
rm -rf rag-backend/migrations/versions/*  # очистить папку
alembic revision --autogenerate -m "initial"  # создать заглушку (или пропустить)
alembic upgrade head        # применить новую миграцию
```

На чистой БД достаточно: `alembic upgrade head`.

### 2. Создать `0001_initial.py`

**Файл:** `rag-backend/migrations/versions/0001_initial.py`

Создать таблицы строго в соответствии со схемой из раздела 3 `Spec-00`. Порядок создания (с учётом FK):
1. `domains`
2. `domain_prompts`
3. `domain_clarification_fields`
4. `platform_settings`
5. `generation_models`
6. `embedding_models`
7. `vaults`
8. `chats`
9. `messages`
10. `clarification_states`
11. `audit_logs`
12. `worlds`
13. `campaigns`
14. `pipelines`
15. `pipeline_decisions`

Создать все индексы из схемы `Spec-00`.

**Seed-данные в `upgrade()`:**
- `domains` — три записи: `default` (`is_system=true`), `dnd`, `work`.
- `domain_prompts` — прочитать актуальное содержимое из `prompts.yaml` файлов доменов. Вставить записи для каждого домена по типам `system`, `clarification`, `planner`. Для всех доменов добавить запись `pipeline_router` с пустой строкой `""`. **Примечание:** пустая строка допустима. В коде (Spec-04) проверка будет `if not prompt or not prompt.strip():` использовать дефолтный шаблон.
- `domain_clarification_fields` — прочитать `clarification_fsm.py` и вставить актуальные поля уточнения для домена `dnd`. Для `work` и `default` — пустой список.
- `platform_settings` — вставить все **16** параметров из таблицы в разделе 3.2 `Spec-00`. Поля `label` и `hint` взять напрямую из таблицы `Spec-00` (раздел 3.2, колонки `label`/`hint`).

`downgrade()` — удалить все таблицы в обратном порядке.

### 3. Обновить `db/models.py`

**Файл:** `rag-backend/app/db/models.py`

Переписать ORM-модели в соответствии со схемой из раздела 3 `Spec-00`.

**Прочитать текущий файл `rag-backend/app/db/models.py` перед изменениями.**

Требуемые изменения:
- **Удалить** существующую модель `VaultBinding` (таблица удалена).
- **Переписать** модель `Chat`: добавить поля `world_id` (nullable, `VARCHAR(64)`, `DEFAULT NULL`) и `locked_pipeline_id` (nullable, `VARCHAR(64)`, `DEFAULT NULL`).
- **Создать новые модели** для всех таблиц из схемы Spec-00, которых сейчас нет:
  - `Domain`, `DomainPrompt`, `DomainClarificationField`, `PlatformSetting`
  - `GenerationModel`, `EmbeddingModel`, `Vault`
  - `World`, `Campaign`, `Pipeline`, `PipelineDecision`
- Существующие модели `Message`, `ClarificationState`, `AuditLog` — проверить соответствие схеме, при необходимости синхронизировать.

Использовать SQLAlchemy 2.x декларативный стиль с `mapped_column` и `Mapped`.

**Важно для nullable-полей:** Поля `world_id` и `locked_pipeline_id` в модели `Chat` должны быть явно объявлены как `Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)`.

**Примечание по модели `Campaign`:** В схеме SQL нет внешнего ключа `world_id -> worlds.world_id`, но для удобства ORM можно объявить `ForeignKeyConstraint(['world_id'], ['worlds.world_id'])` (это не повлияет на схему, если в БД FK не создан). Однако лучше оставить как есть — без FK, чтобы соответствовать схеме. Используйте `Column(String(64), nullable=False)` без `ForeignKey`.

### 4. Обновить `shared_contracts/models.py`

Добавить Pydantic v2 модели для новых сущностей:
- `VaultRead`, `VaultCreate`, `VaultUpdate`
- `DomainRead`, `DomainCreate`, `DomainUpdate`
- `DomainPromptRead`, `DomainPromptUpdate`
- `GenerationModelRead`, `GenerationModelCreate`, `GenerationModelUpdate`
- `EmbeddingModelRead`, `EmbeddingModelCreate`, `EmbeddingModelUpdate`
- `PlatformSettingRead`, `PlatformSettingUpdate`
- `WorldRead`, `WorldCreate`, `WorldUpdate` (без `WorldDelete`)
- `CampaignRead`, `CampaignCreate`, `CampaignUpdate` (без `CampaignDelete`)
- `PipelineRead`, `PipelineCreate`, `PipelineUpdate`

Существующие модели (`SearchHit`, `UpsertChunk`, `ChunkRecord`, `DocumentRecord`, `IndexState`, `FileIndexState`, `PlannerDecision`, `WSFileChunkProgressMessage`) — **не трогать**.

### 5. Обновить `db/migrations.py`

**Файл:** `rag-backend/app/db/migrations.py`

**Прочитать текущий файл перед изменениями.**

- **Удалить функцию `migrate_vault_bindings_from_json()`** — таблица `vault_bindings` больше не существует.
- **Удалить импорт `VaultBinding`** из `app.db.models`.
- Убедиться, что `run_migrations()` продолжает работать (вызов `_upgrade_head()` остаётся).

### 6. Обновить `.env.example`

Создать файл `.env.example` в корне репозитория:

```
POSTGRES_USER=raguser
POSTGRES_PASSWORD=changeme
POSTGRES_DB=ragplatform
DATABASE_URL=postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform
OPENAI_API_KEY=sk-...
ENCRYPTION_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
VAULTS_PATH=./vaults
LOGS_PATH=./logs
STATE_PATH=./state
CACHE_PATH=./cache
STORAGE_API_URL=http://db-api-server:8080
```

Добавить в `.gitignore` строку `.env` если её нет.

### 7. Обновить `docker-compose.yml`

**Прочитать текущий `docker-compose.yml` и внести изменения:**

- `rag-backend`:
  - Убрать монтирование `config.yaml`
  - Добавить в `environment`: `ENCRYPTION_KEY=${ENCRYPTION_KEY}`, `STORAGE_API_URL=${STORAGE_API_URL:-http://db-api-server:8080}`
- `rag-indexer`:
  - Убрать монтирование `config.yaml`
  - Добавить в `environment`: `DATABASE_URL=${DATABASE_URL}`, `ENCRYPTION_KEY=${ENCRYPTION_KEY}`, `STORAGE_API_URL=${STORAGE_API_URL:-http://db-api-server:8080}`
  - Изменить монтирование vault'ов с `:ro` на `:rw`

Всё остальное — без изменений.

## Финальный контракт

После выполнения Spec-01:
- Существует единственная миграция `0001_initial.py`, применяется командой `alembic upgrade head`
- `rag-backend/app/db/models.py` содержит ORM-модели для всех таблиц
- `shared_contracts/models.py` содержит Pydantic-модели для всех новых сущностей
- `.env.example` содержит `ENCRYPTION_KEY` и `STORAGE_API_URL`
- `docker-compose.yml` не монтирует `config.yaml`, vault'ы монтируются `rw`, добавлены переменные окружения
- Функция `migrate_vault_bindings_from_json()` удалена
- Бизнес-логика (`config_loader.py`, `domains/registry.py`, etc.) — не тронута, система не обязана запускаться после этого Spec

## Критерии приёмки

Codex проверяет самостоятельно:

- [ ] `alembic upgrade head` выполняется без ошибок на чистой БД
- [ ] `alembic downgrade base` выполняется без ошибок
- [ ] `alembic upgrade head` после `downgrade base` выполняется повторно без ошибок
- [ ] Все 15 таблиц существуют в БД после `upgrade head`
- [ ] Seed: таблица `domains` содержит 3 записи
- [ ] Seed: таблица `platform_settings` содержит **16** записей
- [ ] Seed: промпты для `dnd`, `work`, `default` вставлены в `domain_prompts`, для `pipeline_router` — пустая строка
- [ ] В `shared_contracts/models.py` нет синтаксических ошибок (`python -m py_compile`)
- [ ] В `db/models.py` нет синтаксических ошибок
- [ ] `.env.example` существует и содержит `ENCRYPTION_KEY` и `STORAGE_API_URL`
- [ ] В `docker-compose.yml` vault'ы монтируются с флагом `:rw`, `config.yaml` не монтируется, добавлены `STORAGE_API_URL`
- [ ] Функция `migrate_vault_bindings_from_json()` отсутствует в `db/migrations.py`
- [ ] Поля `world_id` и `locked_pipeline_id` в модели `Chat` — nullable
