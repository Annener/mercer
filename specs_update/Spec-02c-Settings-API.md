# Spec-02c: Settings API — Part 2 (Embedding Models, Vaults, Worlds, Campaigns, Pipelines)

Перед выполнением прочитай `Spec-00-Architecture-Overview.md`, `Spec-02a` и `Spec-02b`.

**Зависит от:** `Spec-02a` (сервисы), `Spec-02b` (уже реализованы эндпоинты первой группы).

**Цель:** Реализовать оставшиеся эндпоинты `/settings/*`: embedding-модели, vault'ы, миры, кампании, pipeline'ы. Также обновить существующие файлы (`planner.py`, `chat.py`, `db_management.py`) для работы с новой БД.

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/app/services/settings_service.py`
- `rag-backend/app/services/domain_service.py`
- `rag-backend/app/api/settings.py` (создан в Spec-02b)
- `rag-backend/app/services/planner.py`
- `rag-backend/app/api/chat.py`
- `rag-backend/app/api/db_management.py`
- `rag-backend/app/db/models.py`

## Задачи

### 1. Добавить эндпоинты для Embedding-моделей в `api/settings.py`

```
GET /settings/embedding-models
```

Список всех embedding-моделей (без `encrypted_api_key`, с полем `has_api_key: bool`).

```
POST /settings/embedding-models
```

Тело:
```json
{
    "model_id": "unique",
    "provider": "ollama | openai_compatible",
    "display_name": "опционально",
    "model_name": "string",
    "base_url": "valid URL",
    "api_key": "plain text (опционально)",
    "dimensions": 768,
    "timeout_seconds": 30,
    "max_retries": 3
}
```

- Шифровать `api_key`.
- Вернуть `201 Created`.

```
PUT /settings/embedding-models/{id}
```

Обновление (аналогично POST). При смене `model_name`, `dimensions` или `base_url` — не требуется автоматическая реиндексация (это ответственность пользователя).

```
DELETE /settings/embedding-models/{id}
```

Запретить, если `SELECT count(*) FROM vaults WHERE embedding_model_id = :id > 0` → `409 Conflict` с сообщением "Model is used by existing vaults".

```
POST /settings/embedding-models/{id}/check
```

- Загрузить модель, расшифровать ключ.
- Создать провайдер (Ollama или OpenAICompatible).
- Отправить тестовый embed строки `"test"`.
- Замерить latency, получить размерность.
- Вернуть `{"ok": bool, "latency_ms": int, "dimensions": int, "error": str | null}`.

### 2. Добавить эндпоинты для Vault'ов

```
GET /settings/vaults
```

Список всех vault'ов из таблицы `vaults` (включая все поля).

```
POST /settings/vaults
```

Тело:
```json
{
    "vault_id": "slug (3-64)",
    "domain_id": "existing domain",
    "display_name": "опционально",
    "embedding_model_id": "опционально",
    "create_folder": false
}
```

- Проверить существование `domain_id`.
- Если `embedding_model_id` указан — проверить существование.
- Если `create_folder = true` — вызвать `os.makedirs(f"/data/vaults/{vault_id}", exist_ok=True)`. (Путь монтируется в Docker, при локальной разработке будет создана папка).
- Вставить запись в `vaults` с `binding_status = 'unbound'`, `chunk_count = 0`.
- Вернуть `201 Created`.

```
PUT /settings/vaults/{id}
```

Тело: любые поля `display_name`, `enabled`, `embedding_model_id`, `chunk_size`, `overlap`, `entity_aware_mode`.

**Обработка смены embedding_model_id:**
- Если новое значение отличается от текущего:
  - Выполнить HTTP DELETE к `{STORAGE_API_URL}/index/vault/{vault_id}` (удалить все векторы из LanceDB).
  - Таймаут 30 секунд. При ошибке (таймаут, 5xx) → откатить транзакцию БД, вернуть `502 Bad Gateway` или `503`.
  - Если успешно — установить `binding_status = 'unbound'`, `chunk_count = 0`.
  - Залогировать предупреждение.

**Обработка смены параметров чанкинга (`chunk_size`, `overlap`, `entity_aware_mode`):**
- Если хотя бы одно из них изменилось — установить `binding_status = 'unbound'` (но `chunk_count` не трогать). Залогировать "Reindexing recommended".
- Обновить запись.

Все изменения выполняются в одной транзакции БД. HTTP-вызов к db-api-server должен быть **внутри транзакции**, но если он падает — транзакция откатывается.

```
DELETE /settings/vaults/{id}
```

- Выполнить HTTP DELETE к `{STORAGE_API_URL}/index/vault/{id}` (игнорировать ошибки — логировать WARNING).
- Удалить запись из таблицы `vaults`. Связанные `worlds`, `campaigns`, `chats` удалятся каскадно (ON DELETE CASCADE).
- Вернуть `204 No Content`.

```
POST /settings/vaults/{id}/toggle
```

Переключить `enabled = NOT enabled`. Вернуть `200 OK` с обновлённым объектом.

### 3. Добавить эндпоинты для Миров и Кампаний

**Важно:** Миры и кампании **не удаляются** через API.

```
GET /settings/worlds?vault_id={vault_id}
```

Список миров для указанного vault'а (или всех, если параметр опущен). Для каждого: `id` (UUID), `world_id`, `vault_id`, `name`, `description`, `path_prefix`, `is_active`.

```
POST /settings/worlds
```

Тело:
```json
{
    "world_id": "slug (3-64)",
    "vault_id": "existing vault",
    "name": "...",
    "description": "опционально",
    "path_prefix": "/worlds/forgotten_realms/",
    "is_active": true
}
```

- Уникальность по `(world_id, vault_id)`.
- `path_prefix` должен заканчиваться на `/`.
- Вернуть `201 Created`.

```
PUT /settings/worlds/{world_id}
```

Обновление (по `world_id` — slug, не по UUID). Обновить любые поля (кроме `world_id` и `vault_id`). Вернуть `200 OK`.

```
GET /settings/worlds/{world_id}/campaigns
```

Список кампаний мира.

```
POST /settings/worlds/{world_id}/campaigns
```

Тело:
```json
{
    "campaign_id": "slug",
    "name": "...",
    "description": "опционально",
    "path_prefix": "/worlds/forgotten_realms/campaigns/curse_of_strahd/",
    "is_active": true
}
```

- `path_prefix` должен начинаться с `path_prefix` мира и заканчиваться на `/`.
- Уникальность по `(campaign_id, world_id)`.
- Вернуть `201 Created`.

```
PUT /settings/worlds/{world_id}/campaigns/{campaign_id}
```

Обновление кампании. Вернуть `200 OK`.

```
POST /settings/worlds/{world_id}/campaigns/{campaign_id}/toggle
```

Переключить `is_active`. Вернуть `200 OK`.

### 4. Добавить эндпоинты для Pipelines

```
GET /settings/pipelines?domain_id={domain_id}
```

Список pipeline'ов (все версии) для указанного домена. Для каждого: `id` (UUID), `pipeline_id`, `version`, `name`, `description`, `is_active`.

```
POST /settings/pipelines
```

Тело:
```json
{
    "pipeline_id": "slug",
    "domain_id": "existing domain",
    "name": "...",
    "description": "опционально",
    "steps": [...],   // JSONB по схеме 3.6.1
    "final_composition": {...},  // по схеме 3.6.2
    "is_active": true
}
```

- Валидация JSONB `steps` и `final_composition` по схемам из Spec-00 (см. детали в задаче 2 Spec-04, но для этого Spec достаточно базовой проверки наличия обязательных полей).
- Версия устанавливается `"1.0.0"`.
- Вернуть `201 Created`.

```
PUT /settings/pipelines/{id}
```

Тело аналогично POST. **Всегда** создаёт новую версию:
- Инкрементировать минорную версию (`1.0.0` → `1.0.1`).
- Старую версию (с тем же `pipeline_id`) пометить `is_active = false`.
- Вставить новую запись с новой версией.
- Вернуть `200 OK` с новым объектом (включая `version`).

```
DELETE /settings/pipelines/{id}
```

Soft delete: установить `is_active = false` для указанной записи. Не удалять физически. Вернуть `204 No Content`.

```
POST /settings/pipelines/{id}/activate
```

- Найти pipeline по `id` (UUID).
- Сбросить `is_active = false` у всех версий с тем же `pipeline_id`.
- Установить `is_active = true` у указанной версии.
- Вернуть `200 OK`.

### 5. Обновить `services/planner.py`

**Прочитать текущий файл.**

- Удалить все обращения к `config.retrieval` и `config.chat`. Заменить на `settings_service.get(key)`.
- Поля уточнения брать через `domain_service.get_clarification_fields(domain_id, db)`.

**Переписать `_strategy_for_vault` и `_strategy_for_domain`:**

```python
async def _strategy_for_vault(self, db: AsyncSession, vault_id: str) -> str:
    result = await db.execute(
        select(Vault).where(Vault.vault_id == vault_id, Vault.enabled == True)
    )
    vault = result.scalar_one_or_none()
    if not vault or vault.chunk_count <= 0:
        return "none"
    return "semantic"

async def _strategy_for_domain(self, db: AsyncSession, domain_id: str) -> str:
    result = await db.execute(
        select(func.count()).select_from(Vault).where(
            Vault.domain_id == domain_id,
            Vault.enabled == True,
            Vault.chunk_count > 0
        )
    )
    count = result.scalar()
    return "semantic" if count > 0 else "none"
```

### 6. Обновить `api/chat.py`

- Заменить `get_config()` на `settings_service.get()`.
- В `POST /chat/create` принимать `world_id` (опционально) и сохранять в `chats` таблицу.
- В `GET /chat/{id}` добавить поле `vault_enabled: bool` (проверить `vaults.enabled` для `chat.vault_id`).
- Реализовать `PUT /chat/{id}/pipeline`:
  - Принимает `{"pipeline_id": "..."}` или `{"pipeline_id": null}`.
  - Обновляет `locked_pipeline_id` в таблице `chats`.
  - Возвращает `200 OK`.
- Обновить функцию `_prompt_pack_for_chat` — использовать `domain_service.get_domain()`.

### 7. Обновить `api/db_management.py` (эндпоинт `DELETE /db/docs/{id}`)

**Текущий эндпоинт удаляет документ из LanceDB и из PostgreSQL? Нужно пересчитать `chunk_count`.**

Алгоритм:
1. Получить `vault_id` из query параметра.
2. Выполнить HTTP DELETE к `{STORAGE_API_URL}/index/document/{id}?vault_id={vault_id}`.
3. **После** успешного удаления выполнить `GET {STORAGE_API_URL}/index/documents?vault_id={vault_id}`. Ответ: массив документов с полем `chunk_count`.
4. Вычислить `new_total = sum(doc["chunk_count"] for doc in documents)`.
5. Выполнить `UPDATE vaults SET chunk_count = :new_total WHERE vault_id = :vault_id`.
6. Если шаг 3 или 4 завершился ошибкой — логировать, но не возвращать ошибку клиенту (документ уже удалён, `chunk_count` останется старым — не критично, следующий успешный вызов восстановит синхронизацию).

### 8. Обновить `services/clarification_fsm.py`

Список полей уточнения брать из `domain_service.get_clarification_fields(domain_id, db)`.

### 9. Обновить `services/retrieval.py` (подготовка к Spec-04)

Заменить обращения к `config.embedding_models` на чтение активной embedding-модели из БД (пока заглушкой, полная реализация в Spec-04).

## Финальный контракт

- Все эндпоинты `/settings/*` реализованы.
- `planner.py` использует БД, не читает `config.yaml`.
- `chat.py` поддерживает `world_id` и `locked_pipeline_id`.
- `DELETE /db/docs/{id}` корректно обновляет `chunk_count`.
- Система запускается и работает без `config.yaml`.

## Критерии приёмки

- [ ] `POST /settings/embedding-models` → модель создаётся.
- [ ] `POST /settings/vaults` с `create_folder=true` → папка создаётся на хосте.
- [ ] `PUT /settings/vaults/{id}` со сменой `embedding_model_id` → вызывает DELETE к db-api-server, сбрасывает `binding_status`.
- [ ] `POST /settings/worlds` → мир создаётся.
- [ ] `POST /settings/worlds/{world_id}/campaigns` → кампания создаётся, `path_prefix` валидируется.
- [ ] `DELETE /settings/pipelines/{id}` → `is_active=false` (soft delete).
- [ ] `planner._strategy_for_vault` возвращает `"semantic"` только если `chunk_count > 0`.
- [ ] `PUT /chat/{id}/pipeline` обновляет `locked_pipeline_id`.
- [ ] Удаление документа через `DELETE /db/docs/{id}` корректно обновляет `chunk_count`.
