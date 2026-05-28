# Spec-03a: Indexer DB Client

Перед выполнением прочитай `Spec-00-Architecture-Overview.md` целиком. Этот Spec — первая часть перевода `rag-indexer` на PostgreSQL.

**Зависит от:** `Spec-01` (схема БД), `Spec-02` (таблицы заполнены).

**Цель:** Создать `db_client.py` для прямого доступа `rag-indexer` к PostgreSQL, обновить `indexer_worker.py` для чтения конфигурации из БД вместо `config.yaml`, добавить per‑vault параметры чанкинга и метаданные миров/кампаний.

## Контекст

**Прочитать перед реализацией:**
- `rag-indexer/indexer_worker.py` — текущий pipeline индексации
- `rag-indexer/parser/parsing/pdf_parser.py` — будет обновлён в Spec-03b
- `rag-indexer/storage/binding_manager.py` — будет удалён
- `rag-backend/app/db/models.py` — схема БД

## Задачи

### 1. Создать `app/db_client.py`

**Файл:** `rag-indexer/app/db_client.py`

Минимальный async клиент к PostgreSQL. Использовать `asyncpg.create_pool()`.

**Переменные окружения:** `DATABASE_URL`, `ENCRYPTION_KEY`. Если не заданы → `RuntimeError`.

**Интерфейс `IndexerDBClient`:**

```python
class IndexerDBClient:
    async def connect(self, database_url: str, encryption_key: str) -> None
    async def close(self) -> None
    async def get_platform_settings(self) -> dict[str, Any]
    async def get_vault(self, vault_id: str) -> dict | None
    async def get_embedding_model(self, model_id: str) -> dict | None
    async def get_worlds_for_vault(self, vault_id: str) -> list[dict]
    async def update_vault_chunk_count(self, vault_id: str, delta: int) -> None   # delta = приращение (может быть отрицательным)
    async def update_vault_binding_status(self, vault_id: str, status: str) -> None
```

**Детали:**
- `get_platform_settings` возвращает словарь `{key: value}` с правильным типом (int, float, bool, str) согласно `value_type` из БД.
- `get_embedding_model` возвращает запись из `embedding_models`, включая `encrypted_api_key` (будет расшифрована в `indexer_worker`).
- `get_worlds_for_vault` возвращает список миров, у которых `vault_id = :vault_id` и `is_active = true`.
- `update_vault_chunk_count` выполняет `UPDATE vaults SET chunk_count = chunk_count + :delta WHERE vault_id = :vault_id`.
- Пул соединений: `min_size=1, max_size=4`.

**Шифрование:** метод `_decrypt_api_key(encrypted: str) -> str` через `cryptography.fernet`.

### 2. Обновить `indexer_worker.py`

**Прочитать текущий файл целиком.** Заменить использование `get_config()` и `binding_manager` на `db_client`.

**Новая сигнатура `run_indexing`** (добавить параметр `db_client`):

```python
async def run_indexing(
    task_id: str,
    vault_id: str,
    force_reindex: bool,
    db_client: IndexerDBClient,
    is_cancelled: CancelCallable | None = None,
    broadcast: BroadcastCallable | None = None,
) -> None:
```

**Логика:**

1. **Загрузка конфигурации из БД:**
   - `settings = await db_client.get_platform_settings()`
   - `vault = await db_client.get_vault(vault_id)`
   - Если `vault` отсутствует или `enabled = false` → логировать ошибку и завершить.
   - `embedding_model = await db_client.get_embedding_model(vault["embedding_model_id"])`
   - Если модель не найдена или расшифровка ключа не удалась → `update_vault_binding_status(vault_id, "error")` и завершить.

2. **Per‑vault параметры чанкинга:**
   ```python
   chunk_size = vault.get("chunk_size") or settings["chunking.chunk_size"]
   overlap = vault.get("overlap") or settings["chunking.overlap"]
   entity_aware = vault.get("entity_aware_mode")
   if entity_aware is None:
       entity_aware = settings["chunking.entity_aware_mode"]
   ```

3. **Загрузка миров для vault:**
   ```python
   worlds = await db_client.get_worlds_for_vault(vault_id)
   ```

4. **Индексация файлов** (остальная логика похожа на текущую, но с изменениями):
   - `document_id` остаётся `doc` + sha256(vault_id + ":" + relative_path)[:16].
   - При успешной обработке файла: `await db_client.update_vault_chunk_count(vault_id, len(chunk_ids))`.
   - При фатальной ошибке **после** частичной загрузки чанков в LanceDB — откатить: удалить добавленные документы через `storage_client.delete_document(document_id, vault_id)`. Логировать `WARNING`.
   - Обновление статуса vault: перед началом `update_vault_binding_status(vault_id, "indexing")`, после успеха `update_vault_binding_status(vault_id, "bound")`, при ошибке `"error"`.

5. **Embedding провайдер:**
   - Создать провайдер на основе `embedding_model["provider"]`, передав расшифрованный `api_key`, `base_url`, `model_name`, `dimensions`, `timeout_seconds`, `max_retries`.

6. **Метаданные миров/кампаний для чанков:**
   - В функции `_extract_world_metadata(relative_path, worlds)`:
     - Для каждого мира проверить, начинается ли `relative_path` с `world["path_prefix"]`.
     - Если да → проверить, есть ли после префикса подпапка `campaigns/`:
       - Если да → извлечь `campaign_id` (первый сегмент после `campaigns/`), установить `category = "campaigns"`.
       - Если нет → извлечь `category` (первый сегмент после префикса).
     - Вернуть `{"world_id": world["world_id"], "category": category, "campaign_id": campaign_id или None}`.
   - Добавить эти поля в `chunk.metadata` (только если мир найден).

### 3. Обновить `app/main.py` (rag-indexer)

- В lifespan: создать `IndexerDBClient`, подключиться к пулу, сохранить в `app.state.db_client`.
- При shutdown закрыть клиент.
- Передавать `db_client` в `indexer_service.start_task()`.

### 4. Обновить `app/indexer_service.py`

- `start_task()` должна принимать `db_client` и передавать его в `run_indexing`.

### 5. Добавить зависимости в `requirements.txt`

```
asyncpg>=0.29.0
cryptography>=41.0.0
```

## Финальный контракт

- `app/db_client.py` создан, использует пул соединений.
- `indexer_worker.py` читает все параметры из PostgreSQL, per‑vault чанкинг работает.
- Метаданные чанков содержат `world_id`, `category`, `campaign_id` для файлов в подпапках миров.
- `binding_manager.py` пока не удалён (будет в Spec-03b), но его вызовы заменены на `db_client`.
- При ошибке расшифровки или отсутствии модели статус vault становится `"error"`.

## Критерии приёмки

- [ ] `rag-indexer` запускается без `config.yaml` (есть `DATABASE_URL` и `ENCRYPTION_KEY` в env).
- [ ] `IndexerDBClient.get_platform_settings()` возвращает корректные типы (int, bool и т.д.).
- [ ] `indexer_worker` использует per‑vault `chunk_size`, если он задан, иначе глобальный.
- [ ] При недоступной БД задача индексации завершается с логом `"Indexing task aborted"`.
- [ ] Файл `worlds/forgotten_realms/pantheon.md` → в метаданных чанка `world_id = "forgotten_realms"`, `category = "pantheon"`, `campaign_id` отсутствует.
- [ ] Файл `worlds/forgotten_realms/campaigns/curse_of_strahd/act1.md` → `campaign_id = "curse_of_strahd"`.
- [ ] После успешной индексации `vaults.chunk_count` увеличивается на количество чанков.
- [ ] При ошибке расшифровки API-ключа `binding_status = "error"`.
