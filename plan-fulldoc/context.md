# Контекст для реализации Full Document Mode

Этот файл содержит весь технический контекст, необходимый для реализации концепта. Читай его вместе с `plan.md` и `status.md`.

---

## Архитектура сервисов

```
rag-backend :8000  ←──→  rag-indexer :9000 (internal)
      │                        │
      │                   db-api-server :8080
      │                        │
      └──────→  rag-db (PostgreSQL :5432)
                redis :6379
                lancedb (volume /data/lancedb)
```

- **rag-backend** — главный API (FastAPI), единственный порт наружу. SPA-фронтенд (`app/static/`, ванильный JS).
- **rag-indexer** — асинхронный воркер индексации, недоступен снаружи.
- **db-api-server** — HTTP-обёртка над LanceDB.
- **pdf-sidecar** — внешний сервис парсинга, reranking, embedding (порт 8765, вне Docker).

---

## Ключевые файлы сервисного слоя (rag-backend/app/services/)

| Файл | Размер | Назначение |
|---|---|---|
| `retrieval.py` | ~30 KB | Векторный / гибридный поиск + reranker |
| `pipeline_executor.py` | ~14 KB | DAG-runner пайплайна со стримингом |
| `pipeline_dag.py` | ~7 KB | Чистый DAG-движок |
| `pipeline_router.py` | ~8 KB | LLM-маршрутизатор |
| `pipeline_service.py` | ~7 KB | CRUD пайплайнов |
| `prompt_pack.py` | ~5 KB | Загрузка/форматирование промптов |
| `query_rewriter.py` | ~5 KB | LLM-переформулировка запросов |
| `clarification_fsm.py` | ~5 KB | FSM сбора уточнений |

---

## Механика паузы пайплайна (существующая)

В `pipeline_executor.py` при встрече шага типа `validation`:
1. Генерируется `resume_token`, TTL = 1 час.
2. В `Chat.pipeline_pause_state` сохраняется `context_snapshot`.
3. Возвращается SSE-событие `validation_required`.
4. При возобновлении: `resume_from_validation(ctx, validated_step_id)`.

**Full Document Mode использует тот же механизм**, только с другим типом паузы (`full_document_selection`) и другим эндпоинтом возобновления.

---

## SSE-события pipeline_executor (существующие)

| `type` | Описание |
|---|---|
| `pipeline_selected` | пайплайн выбран |
| `step_complete` | шаг завершён |
| `step_skipped_no_docs` | нет документов |
| `step_error` | ошибка шага |
| `validation_required` | пауза на validation |
| `token` | токен LLM |
| `pipeline_complete` | завершено |
| `error` | критическая ошибка |

**Новое событие:** `full_document_selection_required` — пауза для выбора документов.

---

## Схема LanceDB (db-api-server)

Таблица: `vault_{vault_id}`

| Колонка | Тип | Примечание |
|---|---|---|
| `chunk_id` | str | `{document_id}_{chunk_index}` |
| `document_id` | str | — |
| `chunk_index` | int | **отдельная колонка**, не metadata |
| `text` | str | — |
| `vector` | list[float] | — |
| `metadata` | str | JSON-строка |

---

## Существующий API db-api-server (критически важный для нас)

```
GET /index/document/{document_id}/chunks?vault_id={vault_id}
```
Возвращает `ChunkRecord[]` **без вектора**, отсортированных по `chunk_index`. Именно этот эндпоинт используется для склейки полного текста документа.

```
DELETE /index/document/{document_id}?vault_id={vault_id}
GET /index/documents?vault_id={vault_id}
POST /index/search
POST /index/search/text
```

---

## Схема PostgreSQL (Chat)

```python
ChatRecord(ORMModel):
    id: str
    title: str
    domain_id: str
    campaign_id: str | None
    vault_id: str | None
    locked_pipeline_id: str | None
    pipeline_versions: dict | None
    pipeline_pause_state: dict | None    # JSON, используется для паузы
    pending_pipeline_confirm: str | None
    created_at: datetime
    updated_at: datetime
    # --- ДОБАВИТЬ В ЭТАПЕ 1 ---
    # full_document_mode_enabled: bool
    # sent_full_document_ids: list[str]
```

---

## Схема PostgreSQL (Document)

```python
DocumentRead(ORMModel):
    id: str
    vault_id: str
    source_path: str
    title: str
    md5: str
    mtime: datetime
    status: str
    indexed_at: datetime | None
    created_at: datetime
    # --- ДОБАВИТЬ В ЭТАПЕ 1 ---
    # char_count: int | None
    # chunk_count: int | None
    # estimated_tokens: int | None
```

---

## Схема SearchHit (из retrieval.py)

```python
class SearchHit:
    chunk_id: str
    document_id: str       # <-- ключевое поле для группировки
    vault_id: str
    text: str
    score: float
    metadata: dict
```

---

## Новый тип: DocumentCandidate (добавить в shared_contracts/models.py)

```python
class DocumentCandidate(BaseModel):
    document_id: str
    title: str
    source_path: str
    char_count: int | None
    chunk_count: int | None
    estimated_tokens: int | None
    already_sent: bool  # document_id in chat.sent_full_document_ids
```

---

## Новый сервис: full_document_service.py

Расположение: `rag-backend/app/services/full_document_service.py`

### collect_document_candidates(hits, sent_full_document_ids, db)

```
Вход: list[SearchHit], list[str], AsyncSession
Выход: list[DocumentCandidate]

Логика:
1. Собрать уникальные document_id из hits
2. Для каждого document_id: SELECT из таблицы documents где id = document_id
3. Собрать DocumentCandidate с полями из Document (title, source_path, char_count, etc.)
4. already_sent = document_id in sent_full_document_ids
```

### reconstruct_full_text(document_id, vault_id, storage_api_url)

```
Вход: str, str, str
Выход: str

Логика:
1. GET {storage_api_url}/index/document/{document_id}/chunks?vault_id={vault_id}
2. Получить ChunkRecord[] (уже отсортированы по chunk_index)
3. Вернуть '\n\n'.join(chunk.text for chunk in chunks)
```

### assemble_hybrid_context(selected_doc_ids, full_texts, hits, candidates)

```
Вход: list[str], dict[str,str], list[SearchHit], list[DocumentCandidate]
Выход: str (готовый context для LLM)

Логика:
1. Секция полных документов:
   for doc_id in selected_doc_ids:
       "=== ПОЛНЫЙ ДОКУМЕНТ: {title} ===\n{full_texts[doc_id]}"
2. Секция чанков (только НЕ из selected_doc_ids):
   chunk_hits = [h for h in hits if h.document_id not in selected_doc_ids]
   Пронумеровать как [1], [2], ...
3. Склеить секции
```

---

## Изменения в pipeline_executor.py

### Точка вставки паузы

После метода, который завершает все retrieval-шаги DAG и до вызова `_run_final_composition()`, добавить:

```python
if ctx.chat.full_document_mode_enabled:
    candidates = await full_document_service.collect_document_candidates(
        hits=all_accumulated_hits,
        sent_full_document_ids=ctx.chat.sent_full_document_ids,
        db=db
    )
    if candidates:
        pause_state = {
            "step": "full_document_selection",
            "candidates": [c.model_dump() for c in candidates],
            "saved_hits": serialize_hits(all_accumulated_hits),
            "query": ctx.query,
            "pipeline_id": ctx.pipeline_id,
            "final_composition_template": ctx.pipeline.final_composition.template,
        }
        await save_pause_state(chat_id, pause_state, db)
        yield {"type": "full_document_selection_required", "candidates": [c.model_dump() for c in candidates]}
        return
```

### resume_from_full_doc_selection(chat_id, selected_document_ids, db)

```python
async def resume_from_full_doc_selection(
    self,
    chat_id: str,
    selected_document_ids: list[str],
    db: AsyncSession,
) -> AsyncIterator[dict]:
    # 1. Читаем pause_state из Chat
    # 2. Загружаем full texts для selected_document_ids
    #    (параллельно через asyncio.gather)
    # 3. Вызываем assemble_hybrid_context
    # 4. Обновляем chat.sent_full_document_ids (добавляем selected_document_ids)
    # 5. Очищаем pipeline_pause_state
    # 6. Вызываем _run_final_composition с новым контекстом
```

---

## Новые API-эндпоинты

### POST /api/chat/{chat_id}/full_document_confirm

```python
class FullDocumentConfirmRequest(BaseModel):
    selected_document_ids: list[str] = []

# Возвращает: StreamingResponse (SSE), как и /stream
# Логика:
# 1. Достать Chat по chat_id
# 2. Проверить pause_state["step"] == "full_document_selection"
# 3. Вернуть executor.resume_from_full_doc_selection(...)
```

### PATCH /api/chat/{chat_id} (расширение существующего)

```python
class ChatUpdateRequest(BaseModel):
    full_document_mode_enabled: bool | None = None
    # ... существующие поля
```

---

## Frontend (ванильный JS, app/static/)

### Тоглер

Добавить в область настроек чата (где уже есть другие настройки):
```html
<div class="setting-row">
  <label>
    <input type="checkbox" id="fullDocModeToggle">
    Разрешить отправку полных документов
  </label>
</div>
```

```javascript
// При изменении:
fetch(`/api/chat/${chatId}`, {
  method: 'PATCH',
  body: JSON.stringify({ full_document_mode_enabled: checked })
})
```

### Обработка SSE-события full_document_selection_required

```javascript
// В SSE-обработчике (где уже обрабатываются validation_required и token):
case 'full_document_selection_required':
  hideSpinner();
  showFullDocPanel(event.candidates);
  break;
```

### Панель выбора

```javascript
function showFullDocPanel(candidates) {
  // Рендерим список DocumentCandidate
  // Для каждого: checkbox + title + estimated_tokens + badge "уже загружен"
  // Внизу: суммарный счётчик токенов (обновляется при изменении чекбоксов)
  // Кнопки: "Продолжить с выбранными" и "Продолжить без полных документов"
}

async function confirmFullDocSelection() {
  const selected = getCheckedDocumentIds();
  const response = await fetch(`/api/chat/${chatId}/full_document_confirm`, {
    method: 'POST',
    body: JSON.stringify({ selected_document_ids: selected })
  });
  // Обрабатываем как SSE-стрим
  handleSSEStream(response);
}
```

---

## Соглашения проекта

- **ORM**: SQLAlchemy async, `session: AsyncSession`
- **Схемы**: Pydantic v2, `ORMModel` для чтения из ORM (`from_attributes=True`)
- **Ключи**: `domain_id`, `vault_id` — строки-идентификаторы, не UUID
- **Миграции**: Alembic, запускаются при старте (`run_migrations()` в `app/db/migrations.py`)
- **Стриминг**: SSE через `StreamingResponse` с `AsyncIterator[dict]`
- **Фронтенд**: ванильный JS, никаких фреймворков
- **Межсервисное взаимодействие**: HTTP через `httpx.AsyncClient`
- **Общие типы**: `shared_contracts/models.py` (используется и backend, и indexer)

---

## Что НЕ нужно делать

- Не запускать retrieval/rewriting во время ввода текста
- Не предлагать ВСЕ документы vault, только источники найденных чанков
- Не создавать отдельный background job или очередь
- Не менять существующий RAG-путь (full doc mode — только дополнение)
- Не хранить большие данные в Redis (pause state — в PostgreSQL Chat.pipeline_pause_state)
