# Mercer — LanceDB / db-api-server

> **Проход 8 из N.**
> Отвечает на вопрос: «как устроено хранение и поиск векторов».
> Ключевые файлы:
> - `db-api-server/storage/lancedb_store.py` — вся логика хранилища
> - `db-api-server/api/index.py` — HTTP API
> - `db-api-server/config.py` — конфиг сервиса
> - `db-api-server/main.py` — точка входа FastAPI

---

## Архитектура сервиса

`db-api-server` — отдельный FastAPI-сервис (порт **8080**), изолированный от остальных.
Внутри Docker-сети `rag-net` к нему обращаются `rag-backend` и `rag-indexer`.
Наружу порт **не пробрасывается**.

LanceDB используется в **синхронном** режиме (локальный файловый движок).
Все synchronous-вызовы оборачиваются в `asyncio.to_thread()` в API-слое, чтобы не блокировать event loop.

---

## Схема таблиц LanceDB

Каждый vault хранится в **отдельной таблице** `vault_{sanitized_vault_id}`.

### Строка таблицы

| Колонка | Тип | Описание |
|---|---|---|
| `chunk_id` | `str` | `"{document_id}_{chunk_index}"` — уникальный идентификатор чанка |
| `document_id` | `str` | UUID документа (= `document_id` в PostgreSQL `documents`) |
| `chunk_index` | `int` | Индекс чанка внутри документа (0-based) |
| `text` | `str` | Текст чанка |
| `vector` | `list[float]` | Embedding-вектор (размерность фиксируется при первом upsert) |
| `metadata` | `str` | JSON-строка (см. ниже) |

### Поля `metadata` (JSON)

| Поле | Тип | Описание |
|---|---|---|
| `source_path` | str | Путь к исходному файлу |
| `page_number` | int \| null | Номер страницы (для PDF) |
| `headers` | list[str] | Заголовки секций (Markdown/DOCX) |
| `vault_id` | str | ID vault |
| `checksum` | str | MD5/SHA256 документа |
| `chunk_index` | int | Дублируется для удобства |
| `source` | str | Алиас `source_path` (legacy) |

### Именование таблиц

```python
def _table_name(vault_id: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", vault_id).strip("_")
    return f"vault_{sanitized}"
```

`vault_id` = UUID из PostgreSQL таблицы `vaults`. Дефисы UUID заменяются на `_`.

---

## HTTP API (`/index/*`)

Базовый путь: `http://db-api-server:8080/index/`

### POST `/index/upsert`

**Запрос:** `UpsertRequest`

```python
class UpsertRequest(BaseModel):
    vault_id: str
    chunks: list[ChunkRecord]
```

**`ChunkRecord`:**

```python
class ChunkRecord(BaseModel):
    chunk_id: str | None         # Вычисляется сервером: "{document_id}_{chunk_index}"
    document_id: str
    vault_id: str
    text: str
    vector: list[float]          # Обязателен при upsert
    metadata: dict
    summary: str | None
```

**Ответ:** `UpsertResponse`

```python
class UpsertResponse(BaseModel):
    status: str           # "ok" | "partial"
    upserted_count: int
    failed_indices: list[int] = []
    error_details: list[str] = []
```

**Поведение:**
- Upsert = delete by chunk_id + add. Это **идемпотентная** операция.
- Измерение вектора фиксируется при первом upsert vault. Несовпадение → чанк пропускается (попадает в `failed_indices`).
- При создании новой таблицы автоматически строится FTS-индекс по колонке `text`.
- Большой upsert (1000+ чанков) выполняется в `asyncio.to_thread()` — может занять несколько минут.

---

### POST `/index/search`

**Запрос:** `SearchRequest`

```python
class SearchRequest(BaseModel):
    vault_id: str
    vector: list[float]          # Embedding query-вектора
    top_k: int = 10
    score_threshold: float | None = None  # Минимальный score (0.0–1.0)
    filter: dict | None = None   # Фильтр по полям (см. ниже)
```

**Фильтр (`filter`):**

Поддерживаются операторы:
```json
{ "document_id": {"$in": ["uuid1", "uuid2"]} }
{ "document_id": {"$eq": "uuid1"} }
{ "document_id": "uuid1" }   // прямое сравнение
```

Поля из `row` (колонки таблицы) имеют приоритет над полями `metadata`.

**Алгоритм поиска:**
```
1. table.search(vector).limit(top_k * 10 если filter есть, иначе top_k)
2. score = 1.0 - _distance  (косинусное расстояние → косинусное сходство)
3. Отфильтровать score < score_threshold
4. Применить filter (post-filter, не natively в LanceDB)
5. Вернуть top_k результатов
```

**Ответ:** `SearchResponse`

```python
class SearchResponse(BaseModel):
    results: list[SearchHit] = []
```

**`SearchHit`:**

```python
class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    metadata: dict
    score: float    # 0.0–1.0 (выше = лучше)
```

> **Важно:** `SearchHit` в `db-api-server` имеет `chunk_id`, а в `rag-backend/services/retrieval.py` — нет поля `chunk_id`. Это разные контракты одного и того же класса — смотри `shared_contracts/models.py`.

---

### POST `/index/search/text`

Full-text search (FTS) по колонке `text`.

**Запрос:**
```python
class TextSearchRequest(BaseModel):
    vault_id: str
    query_text: str
    limit: int = 20  # max 200
```

**Поведение:**
- Использует LanceDB FTS-индекс (`query_type="fts"`).
- Fallback при ошибке FTS (индекс не готов) → substring match по всем строкам.
- Возвращает `score=1.0` для всех результатов (FTS не возвращает relevance score).

---

### DELETE `/index/document/{document_id}`

```
DELETE /index/document/{document_id}?vault_id={vault_id}
```

Удаляет все чанки документа из таблицы vault.

**Ответ:** `{"status": "ok", "deleted_count": N}`

---

### GET `/index/documents`

```
GET /index/documents?vault_id={vault_id}&limit=100&offset=0&order_by=document_id
```

Возвращает список **уникальных документов** (агрегирует по `document_id`).

**`DocumentRecord`:**
```python
class DocumentRecord(BaseModel):
    document_id: str
    vault_id: str
    source_path: str
    checksum: str
    metadata: dict
    chunk_count: int
```

**`order_by`:** `document_id` (default) | `chunk_count`

---

### GET `/index/document/{document_id}/chunks`

```
GET /index/document/{document_id}/chunks?vault_id={vault_id}
```

Возвращает все чанки документа, отсортированные по `chunk_index`.

**Важно:** поле `vector` в ответе = `None` (не возвращается для экономии трафика).

---

### DELETE `/index/vault/{vault_id}`

Полностью удаляет таблицу vault из LanceDB.

**Ответ:** `{"status": "ok", "deleted_count": N}`

---

## Как `rag-backend` вызывает `db-api-server`

В `rag-backend/app/services/retrieval.py`:

```python
# Шаги:
# 1. Получить embedding query через EmbeddingProvider
# 2. Отправить SearchRequest в db-api-server
# 3. Получить list[SearchHit]
# 4. (опционально) Rerank через RerankerProvider
# 5. Вернуть top_k hits
```

URL задаётся через env: `STORAGE_API_URL` (rag-backend) = `http://db-api-server:8080`.

---

## Конфигурация сервиса

**Файл:** `config/storage.config.yaml` (монтируется как `/app/config.yaml`)

```yaml
lancedb:
  data_path: /data/lancedb   # Путь к данным (монтируется как ./data/lancedb)
  cache_size_mb: 256
host: 0.0.0.0
port: 8080
log_level: INFO
```

**Монтирование данных:**
```
./data/lancedb  →  /data/lancedb  (внутри контейнера)
```

---

## FTS-индексы

- Строятся **при старте сервиса** (`build_fts_indexes()`) для всех существующих `vault_*` таблиц.
- Строятся автоматически при создании **новой** таблицы.
- При ошибке — предупреждение в лог, сервис продолжает работу.
- Fallback при поиске — substring match.

---

## Важные нюансы

- **Размерность вектора** фиксируется при первом upsert в vault (кэшируется в `_vault_dimensions`). Несовпадение при последующих upsert → частичная ошибка, не краш.
- **`chunk_id`** = `"{document_id}_{chunk_index}"` — составной ключ.
- **Upsert идемпотентен**: сначала удаляет старые chunk_id, затем добавляет новые.
- **Фильтрация** по `document_ids` — post-filter на Python-стороне (не нативный SQL), поэтому `limit` при наличии фильтра увеличивается до `top_k * 10`.
- **Синхронность**: все операции LanceDB синхронные, вызываются через `asyncio.to_thread()` в HTTP-слое.
- **`metadata` хранится как JSON-строка** в колонке, десериализуется при каждом чтении через `_decode_metadata()`.
