# db-api-server

## Назначение

HTTP-сервис (FastAPI) — хранилище векторных чанков на базе LanceDB.
Предоставляет единый API для upsert, векторного поиска, полнотекстового поиска
и управления документами внутри изолированных пространств (`vault`).
Работает как отдельный контейнер, вызывается из `rag-indexer` и `rag-backend`.

**Точка входа:** `python main.py` или uvicorn  
**Порт по умолчанию:** `8080`  
**Конфиг:** `/app/config.yaml` (YAML, маппится через Docker volume)

---

## Файловая структура

```
db-api-server/
├── main.py              — FastAPI-приложение, lifespan, /health
├── config.py            — Pydantic-модели конфигурации (StorageAppConfig)
├── config_loader.py     — Загрузка YAML-конфига → StorageAppConfig
├── logging_config.py    — Настройка логирования
├── requirements.txt     — Python-зависимости (fastapi, uvicorn, lancedb, pyyaml)
├── Dockerfile           — Образ сервиса
├── api/
│   └── index.py         — APIRouter /index — все эндпоинты
└── storage/
    └── lancedb_store.py — Класс LanceDBStore, вся логика работы с LanceDB
```

---

## Конфигурация

Файл `/app/config.yaml` читается при старте через `config_loader.get_storage_config()`.

**Pydantic-модель `StorageAppConfig`:**
```yaml
lancedb:
  data_path: /data/lancedb   # путь к директории базы LanceDB
  cache_size_mb: 256
host: 0.0.0.0
port: 8080
log_level: INFO
```

---

## Концепция Vault

Каждый `vault_id` — это изолированная таблица в LanceDB с именем `vault_{sanitized_id}`.
Вектора внутри vault обязаны иметь одинаковую размерность. Размерность определяется
при первом upsert и кешируется в `_vault_dimensions`. При несовпадении чанк отклоняется
с `partial` статусом.

**Именование таблицы:** `vault_id` → символы вне `[a-zA-Z0-9_]` заменяются на `_`, крайние `_` обрезаются.

**Схема колонок таблицы:**

| Колонка | Тип | Описание |
|---|---|---|
| `chunk_id` | `str` | `{document_id}_{chunk_index}` |
| `document_id` | `str` | Идентификатор документа |
| `chunk_index` | `int` | Порядковый номер чанка в документе |
| `text` | `str` | Текст чанка (индексируется FTS) |
| `vector` | `list[float]` | Вектор эмбеддинга |
| `metadata` | `str` | JSON-строка произвольных метаданных |

---

## HTTP API

Все эндпоинты смонтированы с префиксом `/index` (тег `index`).

### `GET /health`
Проверка работоспособности.
```json
{"status": "ok", "service": "db-api-server"}
```

---

### `POST /index/upsert`
Запись чанков в vault. Операция выполняется в отдельном потоке
(`asyncio.to_thread`) чтобы не блокировать event loop — для большого PDF
(1000+ чанков) вставка может занимать несколько минут.

**Тело запроса (`UpsertRequest`):**
```json
{
  "vault_id": "my_vault",
  "chunks": [
    {
      "document_id": "doc_001",
      "chunk_index": 0,
      "text": "текст чанка",
      "vector": [0.1, 0.2, ...],
      "metadata": {"source_path": "file.pdf", "checksum": "abc123"}
    }
  ]
}
```

**Ответ (`UpsertResponse`):**
```json
{
  "status": "ok",          // "ok" | "partial"
  "upserted_count": 42,
  "failed_indices": [],    // индексы чанков с ошибкой размерности
  "error_details": []
}
```

**Логика upsert** — операция реализована как delete + add:
1. Для каждого чанка вычисляется `chunk_id = {document_id}_{chunk_index}`
2. Существующие строки с теми же `chunk_id` удаляются
3. Новые строки добавляются через `table.add()`

Это гарантирует идемпотентность — повторный upsert того же документа
корректно заменяет старые чанки без дубликатов.

---

### `POST /index/search`
Векторный поиск по vault.

**Тело запроса (`SearchRequest`):**
```json
{
  "vault_id": "my_vault",
  "vector": [0.1, 0.2, ...],
  "top_k": 10,
  "score_threshold": 0.7,
  "filter": {"document_id": "doc_001"}
}
```

**Ответ (`SearchResponse`):**
```json
{
  "results": [
    {
      "chunk_id": "doc_001_0",
      "document_id": "doc_001",
      "text": "текст чанка",
      "metadata": {...},
      "score": 0.92
    }
  ]
}
```

**Вычисление score:** `score = 1.0 - _distance` (LanceDB возвращает L2-дистанцию).

**Фильтрация:** если указан `filter`, при поиске извлекается `top_k * 10` кандидатов,
затем они фильтруются in-memory через `_matches_filter()`. Поддерживаемые операторы:
- `{"field": value}` — прямое равенство
- `{"field": {"$eq": value}}` — явное равенство
- `{"field": {"$in": [v1, v2]}}` — принадлежность списку

Колонки таблицы (`document_id`, `chunk_id` и др.) имеют приоритет над `metadata`
при поиске по ключу фильтра.

---

### `POST /index/search/text`
Полнотекстовый поиск (FTS) по vault.

**Тело запроса:**
```json
{
  "vault_id": "my_vault",
  "query_text": "поисковый запрос",
  "limit": 20
}
```

Использует `table.search(query_text, query_type="fts")`. При ошибке (FTS-индекс
не построен) — автоматический фоллбэк на substring match по всем строкам.
Все результаты FTS возвращаются с `score=1.0`.

---

### `DELETE /index/document/{document_id}`
Удаление всех чанков документа из vault.

Query-параметр: `vault_id` (обязательный).

```json
{"status": "ok", "deleted_count": 15}
```

Реализовано через `table.delete(f"document_id = '{escaped_id}'")`. 
`deleted_count` вычисляется как разница `count_rows()` до и после удаления.

---

### `GET /index/documents`
Список документов в vault с пагинацией.

Query-параметры: `vault_id` (обязательный), `limit` (1–500, default 100),
`offset` (default 0), `order_by` (default `"document_id"`).

**Ответ (`DocumentsResponse`):**
```json
{
  "documents": [
    {
      "document_id": "doc_001",
      "vault_id": "my_vault",
      "source_path": "path/to/file.pdf",
      "checksum": "abc123",
      "metadata": {...},
      "chunk_count": 42
    }
  ]
}
```

`source_path` берётся из metadata (ключи `source_path`, затем `source`, затем `document_id`).
Агрегирование: все строки читаются в память через `to_arrow().to_pylist()`,
дедуплицируются по `document_id`, сортируются и нарезаются по offset/limit.

---

### `GET /index/document/{document_id}/chunks`
Все чанки конкретного документа. Query-параметр: `vault_id`.

Возвращает `ChunkRecord[]` (без поля `vector`), отсортированных по `chunk_index`.

---

### `DELETE /index/vault/{vault_id}`
Полное удаление vault (таблицы LanceDB).

```json
{"status": "ok", "deleted_count": 150}
```

Использует `db.drop_table()`, инвалидирует кеш `_vault_dimensions`.

---

## LanceDB Store (`storage/lancedb_store.py`)

Класс `LanceDBStore` — единственный объект работы с базой. Создаётся один раз
в `lifespan` хуке и хранится в `app.state.store`.

### Инициализация и FTS-индексы

`connect()` вызывается при старте:
1. Создаёт директорию `data_path` если не существует
2. Подключается к LanceDB: `lancedb.connect(data_path)`
3. Вызывает `build_fts_indexes()` — пересоздаёт FTS-индекс (`create_fts_index("text", replace=True)`)
   на каждой существующей таблице `vault_*`

FTS-индекс также создаётся при первом upsert в новую таблицу (`_get_or_create_table`).
Ошибка построения FTS — не фатальна, логируется как WARNING.

### Кеш размерностей

`_vault_dimensions: dict[str, int]` — in-memory кеш ожидаемых размерностей векторов
по `vault_id`. Заполняется при первом upsert или при первом обращении к существующей таблице
(читается из `table.head(1)`). Инвалидируется при `delete_vault()`.

---

## Shared Contracts (используемые типы)

Из `shared_contracts.models` сервис использует только LanceDB-специфичные контракты:

| Тип | Описание |
|---|---|
| `UpsertChunk` | Один чанк: `document_id`, `chunk_index`, `text`, `vector`, `metadata` |
| `UpsertRequest` | `vault_id` + `chunks: list[UpsertChunk]` |
| `UpsertResponse` | `status`, `upserted_count`, `failed_indices`, `error_details` |
| `SearchRequest` | `vault_id`, `vector`, `top_k`, `score_threshold`, `filter` |
| `SearchResponse` | `results: list[SearchHit]` |
| `SearchHit` | `chunk_id`, `document_id`, `text`, `metadata`, `score` |
| `DocumentRecord` | Агрегат по документу: `document_id`, `vault_id`, `source_path`, `checksum`, `chunk_count` |
| `ChunkRecord` | Чанк без вектора: `chunk_id`, `document_id`, `vault_id`, `text`, `metadata` |

---

## Жизненный цикл (Lifespan)

```
startup:
  1. setup_logging("storage")
  2. get_storage_config() → app.state.config
  3. LanceDBStore(data_path) → app.state.store
  4. store.connect() → lancedb.connect() + build_fts_indexes()

shutdown:
  (логирование "Service stopped.")
```

Доступ к store из роутов — через хелпер `_store(request)`,
который читает `request.app.state.store` и возвращает 503 если store не инициализирован.

---

## Интеграция с Mercer

| Вызывающий компонент | Операция | Описание |
|---|---|---|
| `rag-indexer` | `POST /index/upsert` | Запись проиндексированных чанков |
| `rag-indexer` | `DELETE /index/document/{id}` | Удаление чанков при переиндексации |
| `rag-backend` | `POST /index/search` | Векторный поиск при обработке запроса |
| `rag-backend` | `POST /index/search/text` | FTS при BM25/hybrid поиске |
| `rag-backend` | `GET /index/documents` | Листинг документов через UI |

---

## Известные особенности

- **Нет поддержки транзакций** — delete+add в `_replace_rows` не атомарны. При падении
  в середине операции возможна частичная запись.
- **Агрегация в памяти** — `list_documents` и `get_document_chunks` читают весь vault
  в память через `to_arrow().to_pylist()`. При большом объёме может быть медленно.
- **FTS score всегда 1.0** — полнотекстовый поиск не возвращает релевантность от LanceDB,
  для ранжирования FTS-результатов используется `/rerank` в pdf-sidecar.
- **SQL-инъекция** защищена только через `_escape_sql_literal` (экранирует `'` → `''`)
  в `delete_document`. Все остальные параметры проходят через Pydantic-валидацию.
