# Mercer — Индексер (rag-indexer)

> **Проход 5 из N.**
> Сервис `rag-indexer` (порт `9000`). Точка входа — `run_indexing()` в `indexer_worker.py`.
> Отвечает за сканирование Vault, парсинг файлов, чанкинг, эмбеддинг и запись в LanceDB.

---

## Структура директорий

```
rag-indexer/
├── indexer_worker.py          # Главная точка входа — оркестратор всего процесса
├── config.py                  # EmbeddingModelConfig и платформенные настройки
├── config_loader.py           # Загрузка конфига из env/файла
├── logging_config.py          # Настройка логирования
├── requirements.txt
├── Dockerfile
├── api/                       # FastAPI-приложение indexer (tasks API)
│   └── ...
├── app/
│   └── db_client.py           # IndexerDBClient — HTTP-клиент к rag-backend PostgreSQL
├── embedding/
│   ├── base_provider.py       # Абстрактный EmbeddingProvider
│   ├── ollama_provider.py     # Провайдер Ollama
│   └── openai_provider.py     # Провайдер OpenAI-compatible
├── parser/
│   ├── chunking/
│   │   ├── generic_chunker.py      # Основной чанкер (sliding window + Markdown-заголовки)
│   │   ├── entity_chunker.py       # Entity-aware чанкер
│   │   └── embedding_enricher.py   # Обогащение текста для эмбеддинга
│   ├── parsing/
│   │   ├── pdf_parser.py      # Парсинг PDF (sidecar + fallback pdfminer)
│   │   └── md_parser.py       # Парсинг Markdown
│   ├── preprocessing/
│   │   ├── preprocessor.py    # Очистка текста чанка
│   │   └── pdf_page_merger.py # Склейка страниц PDF, маркеры страниц
│   ├── scanning/
│   │   └── vault_scanner.py   # Сканирование директории vault
│   └── state/
│       └── state_manager.py   # Менеджер состояния задачи (JSON-файлы)
└── storage/
    └── storage_client.py      # HTTP-клиент к db-api-server (LanceDB)
```

---

## Полный поток индексации (`run_indexing`)

```
run_indexing(task_id, vault_id, force_reindex, db_client, is_cancelled, broadcast)
  │
  ├─► 1. Получить настройки платформы (db_client.get_platform_settings())
  ├─► 2. Проверить vault: enabled + embedding_model_id
  ├─► 3. Получить EmbeddingModel, расшифровать API-ключ
  ├─► 4. Создать EmbeddingProvider (ollama / openai_compatible)
  ├─► 5. update_vault_binding_status(vault_id, "indexing")
  ├─► 6. scan_vault("/data/vaults/{vault_id}") → list[FileInfo]
  ├─► 7. create_state(task_id, vault_id, files_info)
  │
  └─► 8. Для каждого файла:
        ├─ is_cancelled? → _cancel_task()
        ├─ get_document_by_path()
        │   ├─ None → create_document()        (новый файл)
        │   ├─ md5==md5 && mtime==mtime && status=="indexed"
        │   │       → SKIP (файл не изменился)
        │   └─ иначе → _delete_chunks_from_lancedb() + update_document_status("pending")
        │
        └─► _process_file(...)
              ├─ parsing    → _parse_file_with_progress()
              ├─ chunking   → chunk_text() / chunk_with_entities()
              ├─ preprocess → preprocess() на каждый чанк
              ├─ PDF?       → _assign_page_numbers_and_headers()
              ├─ enrichment → build_embedding_text()
              ├─ embedding  → _embed_chunks() → list[vector]
              ├─ upsert     → storage_client.upsert_with_retry(UpsertRequest)
              └─ update_document_status("indexed")

  ├─► 9. mark_task_done(task_id)
  ├─► 10. update_vault_binding_status(vault_id, "bound")
  ├─► 11. save_last_successful_state(final_state)
  └─► 12. broadcast WSTaskCompleteMessage
```

### Статусы `binding_status` Vault

| Статус | Когда |
|---|---|
| `unbound` | Vault создан, не проиндексирован |
| `indexing` | Задача запущена |
| `bound` | Успешно завершено |
| `error` | Ошибка на любом этапе |

### Условия пропуска файла

Файл **пропускается** (не переиндексируется), если одновременно:
- `force_reindex = False`
- `doc.md5 == текущий md5`
- `doc.mtime == текущий mtime`
- `doc.status == "indexed"`

При `force_reindex = True` — **все файлы** переиндексируются.

---

## Парсинг (`parser/parsing/`)

### PDF (`pdf_parser.py`)

| Режим | Условие | Описание |
|---|---|---|
| **Sidecar** | По умолчанию | HTTP-запрос к `pdf_sidecar` (отдельный контейнер), возвращает страницы + заголовки |
| **Fallback (pdfminer)** | `fallback_to_pdfminer=True` + sidecar недоступен | Локальный парсинг через `pdfminer.six` |

Настройки из `platform_settings`:
- `pdf_sidecar.url`
- `pdf_sidecar.timeout_seconds`
- `pdf_sidecar.fallback_to_pdfminer`

**Результат PDF-парсинга:**
```python
{
  "pages": [{"text": "...", "page_number": 1}, ...],
  "headings": [{"text": "Глава 1", "level": 1, "page": 1}, ...]
}
```

Для PDF после парсинга вызывается `merge_pdf_pages()` — склейка страниц в единый текст с маркерами страниц `«§PAGE:N§»`, которые затем снимаются `strip_page_markers()`.

### Markdown (`md_parser.py`)

Возвращает:
```python
{
  "text": "...",   # Полный текст файла
  "metadata": {}   # Метаданные из frontmatter (если есть)
}
```

---

## Чанкинг (`parser/chunking/`)

### `generic_chunker.py` — `chunk_text()`

**Алгоритм:**
1. Разделить текст по Markdown-заголовкам (`^#{1,6}\s+.+$`)
2. Каждая секция (заголовок + контент) обрабатывается отдельно
3. Если секция `<= chunk_size` слов → сохранить целиком
4. Если секция `> chunk_size` слов → скользящее окно с шагом `chunk_size - overlap`

**Параметры:**

| Параметр | По умолчанию | Источник |
|---|---|---|
| `chunk_size` | `1600` слов | `vault.chunk_size` → `platform_settings["chunking.chunk_size"]` |
| `overlap` | `64` слов | `vault.overlap` → `platform_settings["chunking.overlap"]` |

**Метаданные чанка:**
```python
{
  "word_start": int,    # Абсолютная позиция начала (слова)
  "word_end": int,      # Абсолютная позиция конца
  "source_path": str,   # Относительный путь файла
  "checksum": str,      # MD5 файла
  "extension": str,     # ".pdf" / ".md"
  "domain_id": str,
  # После assign:
  "page_number": int,   # PDF only
  "headers": dict,      # Заголовки раздела/подраздела
  "source_hint": str,   # "{path}:chunk_{idx}"
  "embedding_text": str # Обогащённый текст для эмбеддинга
}
```

### `entity_chunker.py` — `chunk_with_entities()`

Entity-aware режим (включается через `vault.entity_aware_mode` или `platform_settings["chunking.entity_aware_mode"]`).

Разбивает текст с учётом **именованных сущностей** (NER) — сущности не разрываются границами чанков. Возвращает `(chunks, entities)`.

---

## Обогащение эмбеддинга (`embedding_enricher.py`)

### `build_embedding_text()`

Формирует строку, которая **подаётся в модель эмбеддинга** (не хранится как основной текст чанка):

```
Документ: vault/path/file.pdf
Раздел: Глава 2
Подраздел: Салон Фэла
Тип: lore
[текст чанка]
```

Поля:
- `Документ:` — `source_path`
- `Раздел:` — `headers.section` или `headers.h1` или `headers.h2`
- `Подраздел:` — `headers.subsection` или `headers.h3/h4` (если != секции)
- `Тип:` — `metadata.content_type` (если задан)

Хранится в `metadata.embedding_text` для отладки.

### `extract_markdown_headers()`

Извлекает первый Markdown-заголовок из начала чанка. Возвращает:
```python
{"h1": "Title", "section": "Title"}      # для H1/H2
{"h3": "Sub", "subsection": "Sub"}       # для H3
{}                                         # нет заголовка
```

---

## Эмбеддинг (`_embed_chunks`)

Чанки эмбеддируются **по одному** (не батч) через `provider.embed([text])`.

**Прогресс:** каждые 10 чанков (или последний) отправляет WS-сообщение.

**Провайдеры:**

| Тип | Класс | Настройки |
|---|---|---|
| `ollama` | `OllamaEmbeddingProvider` | `base_url`, `model_name`, `dimensions`, `timeout`, `max_retries` |
| `openai_compatible` | `OpenAICompatibleProvider` | + `api_key` (расшифровывается из `encrypted_api_key`) |

**Ошибка:** пустой вектор от провайдера → `ValueError` → файл помечается `error`, rollback загруженных чанков.

---

## Запись в LanceDB (`storage/storage_client.py`)

### `upsert_with_retry(UpsertRequest)`

```python
class UpsertRequest(BaseModel):
    vault_id: str
    chunks: list[UpsertChunk]

class UpsertChunk(BaseModel):
    document_id: str    # UUID из PostgreSQL documents.id
    chunk_index: int
    text: str
    vector: list[float]
    metadata: dict
```

- POST к `db-api-server /index/upsert`
- При `response.status == "partial"` → исключение (частичная ошибка)
- `chunk_id` в LanceDB = `{document_id}_{chunk_index}`

### `delete_document(document_id, vault_id)`

DELETE к `db-api-server /index/document/{document_id}` — удаляет все чанки документа перед переиндексацией.

---

## WebSocket-события (`broadcast`)

Все события передаются через `broadcast(task_id, message_dict)`.

| Тип сообщения | Когда | Ключевые поля |
|---|---|---|
| `WSFileChunkProgressMessage` | Прогресс обработки файла | `task_id`, `file_path`, `stage`, `chunks_total`, `chunks_processed`, `error` |
| `WSTaskCompleteMessage` | Задача завершена | `task_id`, `files_total`, `files_indexed` |
| `WSTaskCancelledMessage` | Задача отменена | `task_id` |

**Стадии (`stage`) для файла:**
`parsing` → `chunking` → `indexing` → `done` / `empty` / `error`

---

## Состояние задачи (`parser/state/state_manager.py`)

Состояние хранится как JSON-файл (не в PostgreSQL). Используется для:
- Пропуска неизменённых файлов при повторном запуске
- Восстановления после сбоя
- Трекинга `chunk_ids` по файлу

**Ключевые функции:**

| Функция | Описание |
|---|---|
| `create_state(task_id, vault_id, files)` | Создать начальное состояние |
| `load_state(task_id)` | Загрузить текущее состояние |
| `load_last_successful_state(vault_id)` | Загрузить последнее успешное (для skip-логики) |
| `save_last_successful_state(state)` | Сохранить после успешного завершения |
| `update_file_status(task_id, path, status, pct, ...)` | Обновить статус файла |
| `mark_task_done(task_id, error?)` | Завершить задачу |
| `mark_task_cancelled(task_id)` | Отметить как отменённую |

### `IndexState` / `FileIndexState` (shared_contracts)

```python
class FileIndexState(BaseModel):
    status: str             # "done" / "error" / "empty" / "indexing" / ...
    progress_pct: int
    chunk_ids: list[str]    # "{document_id}_{chunk_index}"
    chunks_total: int
    chunks_processed: int
    checksum_md5: str | None
    error: str | None

class IndexState(BaseModel):
    task_id: str
    vault_id: str
    status: str
    files: dict[str, FileIndexState]  # key = relative_path
    created_at: datetime
    completed_at: datetime | None
    error: str | None
```

---

## Настройки индексера (из `platform_settings`)

| Ключ | Описание |
|---|---|
| `chunking.chunk_size` | Размер чанка в словах (default: 1600) |
| `chunking.overlap` | Перекрытие чанков в словах (default: 64) |
| `chunking.entity_aware_mode` | Включить entity-aware чанкер (bool) |
| `pdf_sidecar.url` | URL PDF-sidecar контейнера |
| `pdf_sidecar.timeout_seconds` | Таймаут парсинга PDF |
| `pdf_sidecar.fallback_to_pdfminer` | Использовать pdfminer при сбое sidecar |

Настройки Vault (`vault.chunk_size`, `vault.overlap`, `vault.entity_aware_mode`) **переопределяют** глобальные `platform_settings`.

---

## IndexerDBClient (`app/db_client.py`)

HTTP-клиент к `rag-backend` (PostgreSQL через его API). Используется индексером для:

| Метод | Описание |
|---|---|
| `get_platform_settings()` | Получить все platform_settings |
| `get_vault(vault_id)` | Получить метаданные vault |
| `get_embedding_model(model_id)` | Получить конфиг embedding-модели |
| `get_document_by_path(vault_id, path)` | Найти документ по пути |
| `create_document(vault_id, path, md5, mtime)` | Создать запись документа |
| `update_document_status(doc_id, status, ...)` | Обновить статус документа |
| `update_vault_binding_status(vault_id, status)` | Обновить статус vault |
| `update_vault_chunk_count(vault_id, count)` | Обновить счётчик чанков |
| `decrypt_api_key(encrypted)` | Расшифровать API-ключ модели |

---

## Rollback при ошибке

При сбое во время индексации файла:
1. Файл помечается `error` в state
2. Все уже загруженные `document_ids` (`uploaded_document_ids`) удаляются из LanceDB
3. `vault.binding_status` → `"error"`
4. Исключение пробрасывается наверх

---

## Важные нюансы

- **`document_id` в LanceDB = UUID из `documents.id` PostgreSQL** — не хешированный slug. Связь между PostgreSQL и LanceDB поддерживается через этот UUID.
- **Парсинг PDF** запускается в `asyncio.to_thread` с heartbeat-таймером каждые 3 секунды — проверяет отмену и рассылает прогресс.
- **Чанки эмбеддируются по одному** (не батчем) — особенность текущей реализации, учитывать при оптимизации.
- **`entity_aware_mode`** доступен на уровне vault — можно включить точечно для конкретного vault.
- **`vault_scanner`** сканирует `/data/vaults/{vault_id}` — директория монтируется через Docker volume.
- Поддерживаемые расширения: `.pdf`, `.md`. Остальные вызывают `ValueError`.
