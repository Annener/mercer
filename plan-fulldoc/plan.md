# План реализации: Full Document Mode

> **Концепт:** `plan-fulldoc/concept.md`  
> **Статус:** `plan-fulldoc/status.md`  
> **Промпт для продолжения:** `plan-fulldoc/prompt.md`

---

## Предварительные выводы по коду репозитория

Перед реализацией важно зафиксировать, что уже есть и что нужно добавить:

### Уже готово (переиспользуем)

| Что | Где | Как используем |
|---|---|---|
| `pipeline_pause_state` / `pending_pipeline_confirm` в `Chat` | PostgreSQL + `ChatRecord` | Паузу FullDoc вешаем на этот же механизм, добавляем новый `step` тип |
| `resume_from_validation()` в `PipelineExecutor` | `services/pipeline_executor.py` | По аналогии делаем `resume_from_full_doc_selection()` |
| `GET /index/document/{document_id}/chunks` | `db-api-server` | Готовый эндпоинт для получения всех чанков документа, отсортированных по `chunk_index` |
| `chunk_index` как отдельная колонка LanceDB | `db-api-server/storage/lancedb_store.py` | Сортировка при склейке текста гарантирована без metadata |
| `ChunkRecord` без вектора в ответе `/chunks` | `db-api-server` | Чистая склейка текста без лишних данных |
| `document_id` у каждого `SearchHit` | `retrieval.py` | Группировка хитов по документу тривиальна |
| `format_context()` в `retrieval.py` | `services/retrieval.py` | Нужно расширить для hybrid-контекста (full docs + chunks) |
| Ванильный JS фронтенд с SSE-стримингом | `rag-backend/app/static/` | Добавляем новые UI-компоненты туда же |

### Нужно добавить

| Что | Где |
|---|---|
| `full_document_mode_enabled: bool` в `Chat` | Alembic-миграция |
| `sent_full_document_ids: list[str]` в `Chat` | Alembic-миграция |
| `char_count`, `chunk_count`, `estimated_tokens` в `Document` | Alembic-миграция |
| Запись size-полей при финализации индексации | `rag-indexer/indexer_worker.py` |
| `FullDocumentService` | `rag-backend/app/services/full_document_service.py` (новый файл) |
| Новый step-тип `full_document_selection` в пайплайне | `services/pipeline_executor.py` |
| `POST /api/chat/{chat_id}/full_document_confirm` | `rag-backend/app/api/chat/` |
| `PATCH /api/chat/{chat_id}` расширить флагом | `rag-backend/app/api/chat/` |
| `DocumentCandidate` схема | `shared_contracts/models.py` |
| UI: тоглер + промежуточная панель выбора | `rag-backend/app/static/` |

---

## Этапы реализации

---

### Этап 1 — Alembic-миграции: новые поля в Chat и Document

**Цель:** Добавить поля `full_document_mode_enabled` и `sent_full_document_ids` в таблицу `Chat`, а также `char_count`, `chunk_count`, `estimated_tokens` в таблицу `Document`.

**Файлы для изменения:**
- `rag-backend/migrations/` — новая ревизия Alembic
- ORM-модель `Chat` (найти в `rag-backend/app/db/models.py` или аналогичном файле)
- ORM-модель `Document`
- `shared_contracts/models.py` — расширить `ChatRecord` и `DocumentRead`

**Детали:**

```python
# В таблице chats:
full_document_mode_enabled = Column(Boolean, default=False, nullable=False, server_default='false')
sent_full_document_ids = Column(JSON, default=list, nullable=False, server_default='[]')

# В таблице documents:
char_count = Column(Integer, nullable=True)
chunk_count = Column(Integer, nullable=True)
estimated_tokens = Column(Integer, nullable=True)
```

**Контракты (shared_contracts/models.py):**

```python
# Расширить ChatRecord:
full_document_mode_enabled: bool = False
sent_full_document_ids: list[str] = []

# Расширить DocumentRead:
char_count: int | None = None
chunk_count: int | None = None
estimated_tokens: int | None = None
```

**Критерий завершения:** Миграция применяется без ошибок, поля доступны через ORM.

---

### Этап 2 — Indexer: запись size-метаданных документа

**Цель:** При финализации индексации документа записывать `char_count`, `chunk_count`, `estimated_tokens` в PostgreSQL.

**Файлы для изменения:**
- `rag-indexer/indexer_worker.py` — в месте, где документ помечается как `done`
- `rag-indexer/app/db_client.py` — добавить метод обновления size-полей

**Детали:**

В `indexer_worker.py` перед или при вызове обновления статуса документа:
```python
total_chars = sum(len(chunk.text) for chunk in chunks)
total_chunks = len(chunks)
estimated_tokens = total_chars // 4  # грубая оценка

await db_client.update_document_size(
    document_id=document_id,
    char_count=total_chars,
    chunk_count=total_chunks,
    estimated_tokens=estimated_tokens
)
```

В `db_client.py` — новый HTTP-запрос к rag-backend (или прямой UPDATE через SQLAlchemy, если indexer имеет прямой доступ к БД — уточнить по коду).

**Критерий завершения:** После переиндексации документы имеют заполненные size-поля в БД.

---

### Этап 3 — FullDocumentService: сбор кандидатов и склейка текста

**Цель:** Новый сервис `full_document_service.py` с тремя функциями.

**Файл:** `rag-backend/app/services/full_document_service.py` (новый)

**Содержимое:**

```python
# shared_contracts/models.py — добавить:
class DocumentCandidate(BaseModel):
    document_id: str
    title: str
    source_path: str
    char_count: int | None
    chunk_count: int | None
    estimated_tokens: int | None
    already_sent: bool  # был ли отправлен полностью в этом чате


# full_document_service.py:
async def collect_document_candidates(
    hits: list[SearchHit],
    sent_full_document_ids: list[str],
    db: AsyncSession,
) -> list[DocumentCandidate]:
    """
    Группирует хиты по document_id.
    Для каждого уникального document_id достаёт Document из PostgreSQL.
    Возвращает список DocumentCandidate с метаданными.
    """

async def reconstruct_full_text(
    document_id: str,
    vault_id: str,
    storage_api_url: str,
) -> str:
    """
    GET /index/document/{document_id}/chunks?vault_id={vault_id}
    Сортировка по chunk_index (уже отсортированы сервером).
    Склейка: '\n\n'.join(chunk.text for chunk in chunks)
    """

def assemble_hybrid_context(
    selected_doc_ids: list[str],
    full_texts: dict[str, str],  # document_id → full text
    hits: list[SearchHit],       # все хиты из retrieval
) -> str:
    """
    selected_doc_ids → секция [ПОЛНЫЙ ДОКУМЕНТ: title]\ntext
    остальные хиты (document_id NOT IN selected_doc_ids) → обычная нумерация [1]...
    Гарантирует отсутствие дублей.
    """
```

**Критерий завершения:** Юнит-тест или ручная проверка склейки чанков в текст.

---

### Этап 4 — PipelineExecutor: новый шаг full_document_selection

**Цель:** Добавить в `pipeline_executor.py` логику паузы и возобновления для full document mode.

**Файлы для изменения:**
- `rag-backend/app/services/pipeline_executor.py`

**Детали:**

В `run_stream()` после завершения всех retrieval-шагов (до `_run_final_composition`):

```python
# Псевдокод:
if chat.full_document_mode_enabled:
    candidates = await collect_document_candidates(all_hits, chat.sent_full_document_ids, db)
    if candidates:
        # Сохранить pause state
        pause_state = {
            "step": "full_document_selection",
            "candidates": [c.model_dump() for c in candidates],
            "saved_hits": [h.model_dump() for h in all_hits],
            "query": ctx.query,
            "pipeline_id": ctx.pipeline_id,
        }
        await save_pipeline_pause_state(chat_id, pause_state, db)
        yield {"type": "full_document_selection_required", "candidates": [c.model_dump() for c in candidates]}
        return  # пауза

# Новый метод:
async def resume_from_full_doc_selection(
    chat_id: str,
    selected_document_ids: list[str],
    db: AsyncSession,
) -> AsyncIterator[dict]:
    # Восстановить pause state
    # Загрузить full texts для selected_document_ids
    # Собрать hybrid context
    # Обновить sent_full_document_ids в Chat
    # Запустить _run_final_composition с новым контекстом
```

**Новое SSE-событие:**
```json
{"type": "full_document_selection_required", "candidates": [...]}
```

**Критерий завершения:** При включённом режиме pipeline останавливается и возобновляется корректно.

---

### Этап 5 — API: новые и расширенные эндпоинты

**Цель:** Добавить endpoint подтверждения выбора и расширить PATCH чата.

**Файлы для изменения:**
- `rag-backend/app/api/chat/` (найти роутер чата)

**Новые эндпоинты:**

```
POST /api/chat/{chat_id}/full_document_confirm
Body: {"selected_document_ids": ["doc1", "doc2"]}
Ответ: SSE-стрим (как /stream)

PATCH /api/chat/{chat_id}/settings  (или расширить существующий PATCH)
Body: {"full_document_mode_enabled": true}
```

**Логика `full_document_confirm`:**
1. Прочитать `pipeline_pause_state` из Chat
2. Проверить `step == "full_document_selection"`
3. Вызвать `pipeline_executor.resume_from_full_doc_selection(chat_id, selected_document_ids, db)`
4. Вернуть SSE-стрим генерации

**Критерий завершения:** `curl`-тест — отправить confirm с пустым списком (только чанки) и с документами.

---

### Этап 6 — Frontend: тоглер и панель выбора документов

**Цель:** Добавить UI для управления режимом и выбора документов.

**Файлы для изменения:**
- `rag-backend/app/static/` — ванильный JS

**Компонент 1 — Тоглер в настройках чата:**
```html
<label class="toggle">
  <input type="checkbox" id="fullDocMode" onchange="toggleFullDocMode(this.checked)">
  <span>Разрешить отправку полных документов</span>
</label>
```
При изменении: `PATCH /api/chat/{id}/settings`.

**Компонент 2 — Промежуточная панель (рендерится при получении `full_document_selection_required`):**
```html
<div class="fulldoc-panel">
  <p>Найдены релевантные документы. Выберите, какие отправить в модель целиком:</p>
  
  <!-- Для каждого кандидата: -->
  <div class="doc-item">
    <input type="checkbox" value="{document_id}">
    <span class="doc-title">{title}</span>
    <span class="doc-size">~{estimated_tokens} токенов</span>
    <span class="doc-badge already-sent" [если already_sent]>уже загружен</span>
  </div>
  
  <!-- Итоговый счётчик -->
  <div class="fulldoc-total">Выбрано: ~N токенов</div>
  
  <!-- Кнопки -->
  <button onclick="confirmFullDocSelection()">Продолжить с выбранными</button>
  <button onclick="skipFullDocSelection()">Продолжить без полных документов</button>
</div>
```

**JS-логика:**
- При получении `full_document_selection_required` в SSE-потоке — скрыть спиннер, показать панель
- При нажатии `Продолжить` — `POST /api/chat/{id}/full_document_confirm` с выбранными IDs
- При нажатии `Продолжить без полных документов` — `POST /api/chat/{id}/full_document_confirm` с пустым списком
- Обновлять суммарный счётчик токенов при изменении чекбоксов

**Критерий завершения:** Полный пользовательский сценарий работает end-to-end в браузере.

---

## Порядок этапов и зависимости

```
Этап 1 (миграции)
    │
    ├──→ Этап 2 (indexer, независим, только нужна новая колонка)
    │
    └──→ Этап 3 (FullDocumentService)
              │
              └──→ Этап 4 (PipelineExecutor)
                        │
                        └──→ Этап 5 (API)
                                  │
                                  └──→ Этап 6 (Frontend)
```

Этапы 1 и 2 можно делать параллельно после создания миграции. Этап 3 требует только завершения Этапа 1 (контракты).
