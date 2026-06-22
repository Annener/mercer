# RAG Pipeline — Индексация и Ретривал

## Индексация документов

### Жизненный цикл файла

```
Файл в /data/vaults/{vault_id}/
    │
    ▼
Watchdog (rag-indexer) — обнаруживает изменение по md5/mtime
    │
    ▼
IndexerWorker.run_indexing_task()
    │
    ├─ PDF? → запрос к pdf-sidecar HTTP API → получение текста
    ├─ TXT/MD → прямое чтение
    │
    ▼
Parser — разбивка на чанки (chunk_size, overlap из настроек Vault)
    │
    ├─ entity_aware_mode=True → извлечение сущностей (NER)
    │
    ▼
EmbeddingProvider (ollama | openai_compatible)
    │  base_url берётся из EmbeddingModel в PostgreSQL
    │  Кэш эмбеддингов: /app/cache/embeddings/
    │
    ▼
StorageClient → db-api-server → LanceDB
    │  Сохраняет: chunk_id, document_id, vault_id, text, vector, metadata
    │
    ▼
RedisStateManager — обновляет IndexState (статус файлов)
    │
    ▼
PostgreSQL Document.status = "done"
```

### Ключевые файлы индексатора

| Файл | Роль |
|---|---|
| `rag-indexer/indexer_worker.py` | Основной воркер, оркестрирует весь процесс |
| `rag-indexer/app/main.py` | FastAPI app, watchdog, управление задачами |
| `rag-indexer/app/db_client.py` | HTTP-клиент к PostgreSQL через rag-backend |
| `rag-indexer/embedding/` | Провайдеры эмбеддингов |
| `rag-indexer/storage/storage_client.py` | HTTP-клиент к db-api-server |
| `rag-indexer/parser/` | Парсеры документов |
| `pdf-sidecar/parser.py` | Тяжёлый PDF-парсер (39KB, внешний процесс) |
| `pdf-sidecar/reranker.py` | Реранкер результатов |

## Ретривал (поиск)

### Файл: `rag-backend/app/services/retrieval.py` (~30KB, ключевой файл)

Поддерживает несколько стратегий поиска:
- **Semantic search** — векторный поиск по эмбеддингам в LanceDB
- **BM25 / Full-text search** — полнотекстовый поиск в LanceDB
- **Hybrid** — комбинация semantic + BM25 с RRF (Reciprocal Rank Fusion)
- **Entity-aware** — фильтрация/расширение по извлечённым сущностям

После поиска:
1. **Reranking** — через pdf-sidecar reranker или RerankModel (если активна)
2. **Дедупликация** чанков
3. Формирование контекста для LLM

## Обработка запроса в чате

```
POST /api/chat/{chat_id}/message
    │
    ▼
ClarificationFSM — проверка, достаточно ли данных для запроса
    │  если нет → генерирует уточняющий вопрос и возвращает его
    │
    ▼
QueryRewriter — перефразировка запроса для лучшего ретривала
    │  использует историю чата + активную GenerationModel
    │
    ▼
PipelineRouter — выбор нужного пайплайна
    │  LLM-роутер: анализирует запрос и выбирает pipeline_id
    │  или locked_pipeline_id если зафиксирован в Chat
    │  решение записывается в PipelineDecision
    │
    ▼
Planner — если пайплайн многошаговый, строит план выполнения
    │
    ▼
PipelineDAG + PipelineExecutor — выполняет шаги пайплайна
    │  Шаги могут включать: retrieval, generation, validation, tools
    │  Пауза на validation-шаге → pipeline_pause_state в Chat
    │  Ожидание подтверждения → pending_pipeline_confirm в Chat
    │
    ▼
PromptPack — собирает финальный промпт
    │  system_prompt из домена + campaign.system_prompt + контекст
    │
    ▼
GenerationModel (openai_compatible) → стриминг ответа
    │
    ▼
Message сохраняется в PostgreSQL
```

## Embedding Provider

**Файлы**: `rag-indexer/embedding/`

| Провайдер | Файл | Особенности |
|---|---|---|
| Ollama | `ollama_provider.py` | Локальный, /api/embeddings |
| OpenAI-compatible | `openai_provider.py` | Любой совместимый API |

- Базовый класс: `base_provider.py` — абстрактный `EmbeddingProvider`
- Кэш: `cache.py` — файловый кэш эмбеддингов по хэшу текста
- Фабрика: `embedding/__init__.py` — `get_provider(model: EmbeddingModel)`

## LanceDB (db-api-server)

**Файл**: `db-api-server/storage/lancedb_store.py` (~14KB)

- Одна БД, таблицы по vault_id
- Схема записи: `chunk_id`, `document_id`, `vault_id`, `text`, `vector`, `metadata` (JSON)
- Поиск: `search_chunks()` — принимает query_vector + фильтры
- BM25: `search_bm25()` — полнотекстовый поиск по `text` полю
- VaultBinding: фиксирует `embedding_model_id` + `expected_dimensions` для таблицы
- Нельзя изменить dimensions у уже созданной таблицы (LanceDB ограничение)

## IndexState (Redis)

Структура `shared_contracts/models.py`:
```python
IndexState:
  task_id: str
  vault_id: str
  status: "running" | "done" | "error" | "cancelled"
  files: dict[source_path, FileIndexState]

FileIndexState:
  checksum_md5: str
  status: pending | parsing | chunking | indexing | done | error | cancelled | empty
  chunks_total: int
  chunks_processed: int
  last_modified: datetime
```

Ключ в Redis: `indexer:state:{vault_id}`
