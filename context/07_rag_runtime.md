# Mercer — RAG Runtime: Полный поток запроса

> **Проход 7 из N.**
> Отвечает на вопрос: «что происходит после того, как пользователь отправил сообщение».
> Ключевые файлы:
> - `rag-backend/app/api/chat.py` — точка входа
> - `app/services/clarification_fsm.py` — FSM уточнения
> - `app/services/pipeline_router.py` — маршрутизация pipeline
> - `app/services/pipeline_executor.py` — выполнение pipeline
> - `app/services/retrieval.py` — поиск в LanceDB

---

## Общая схема потока

```
POST /api/chat/{chat_id}/send  (non-streaming)
GET  /api/chat/{chat_id}/send_stream  (SSE streaming)
         │
         ▼
   1. Загрузить Chat из PostgreSQL
         │
         ▼
   2. Clarification FSM
      ├─ stage=="idle"     → проверить недостающие поля
      ├─ stage=="collecting" → обработать ответ пользователя
      ├─ stage=="complete"  → продолжить
      └─ stage=="fallback"  → продолжить (без всех полей)
         │
         ▼
   3. Planner (если включён)
      └─ анализ query → plan (ShortAnswer/DetailedAnswer/...)
         │
         ▼
   4. PipelineRouter.select()
      ├─ locked_pipeline_id? → вернуть сразу
      ├─ LLM-роутинг по query+history
      └─ confidence < 0.5 или None → plain RAG fallback
         │
         ▼
   5. PipelineExecutor.run() / .run_stream()
      для каждого step пайплайна:
        a. _retrieve_for_step()   → list[SearchHit]
        b. format_context_with_role() → context_block
        c. provider.generate()   → partial_answer
      │
      ▼
   6. Final composition
      └─ combined_context = join(partial_results)
      └─ format_prompt(final_composition.system_prompt, {context, collected_fields})
      └─ provider.generate_stream() → tokens
         │
         ▼
   7. Ответ
      ├─ Сохранить Message(роль=assistant) в PostgreSQL
      └─ Вернуть sources[]
```

---

## 1. Точка входа: `POST /api/chat/{chat_id}/send`

**Файл:** `rag-backend/app/api/chat.py`

**Request body:**
```python
class SendMessageRequest(BaseModel):
    message: str
    domain_id: str | None = None
```

**Выполняемые действия:**
1. Загрузить `Chat` из PostgreSQL
2. Загрузить vault_ids домена (все enabled vaults с `domain_id` и `binding_status=="bound"`)
3. Сохранить `Message(role="user")` в PostgreSQL
4. Запустить Clarification FSM
5. Запустить Planner (если включён)
6. Запустить PipelineRouter → PipelineExecutor
7. Сохранить `Message(role="assistant")` в PostgreSQL
8. Вернуть `{answer, sources}`

**Streaming:** `GET /api/chat/{chat_id}/send_stream?message=...` — работает аналогично, но возвращает `EventSourceResponse` (WSE/SSE).

---

## 2. Clarification FSM (`clarification_fsm.py`)

### Стадии

```
idle
  │  (недостаёт полей)
  ▼
collecting
  │  (все поля собраны)
  ▼
complete ──────────────────► продолжить пайплайн
  │  (max_turns исчерпан)
  ▼
fallback ────────────────► продолжить пайплайн (частичные поля)
```

### Поля `ClarificationState`

```python
class ClarificationState(BaseModel):
    stage: str              # "idle" | "collecting" | "complete" | "fallback"
    missing_fields: list[str]  # Недостающие поля
    collected: dict[str, str]  # Собранные значения
    turn: int              # Номер хода
    next_question: str | None  # Следующий вопрос
```

### Логика в `chat.py`

- Поля домена — `DomainClarificationField` из PostgreSQL
- `missing_fields` = поля с `required=True`, ещё не собранные
- Если `stage == "collecting"` → ответ = `state.next_question`, пайплайн **не запускается**
- `max_turns` берётся из `platform_settings["clarification.max_turns"]`
- `_extract_field_value()` — regex-экстракция значения из сообщения. Если regex не срабатывает — берётся весь текст сообщения
- `collected_fields` из `ClarificationState.collected` передаётся в `PipelineExecutionContext` и далее в `final_composition` как `json.dumps(collected_fields)`

---

## 3. Planner (`services/planner.py`)

**Функция:** анализирует query через LLM и возвращает `plan` (напр. `ShortAnswer`, `DetailedAnswer`, `ListAnswer`). Используется для предварительной обработки запроса.

**Точка включения:** `platform_settings["planner.enabled"]` (bool).

**Использует:** `domain_prompts` с `prompt_type == "planner"`.

---

## 4. PipelineRouter (`services/pipeline_router.py`)

### `select(context, locked_pipeline_id)`

**Вход:** `PipelineExecutionContext` (c `domain_id`, `campaign_id`, `query`, `history`).

```
1. locked_pipeline_id есть?
   └─ Да → вернуть сразу, проверив совместимость режима
   └─ Нет → продолжить

2. Загрузить активные pipelines домена

3. Фильтрация по режиму:
   ├─ campaign_id есть → кандидаты = pipelines этой кампании + общие (campaign_id IS NULL)
   └─ нет → кандидаты = только общие (campaign_id IS NULL)

4. LLM-запрос:
   систем-промпт = domain_prompts["pipeline_router"] или PROMPT_TEMPLATE
   JSON ответ: {pipeline_id, confidence, reasoning}

5. confidence < 0.5 или None → вернуть None
   └─ chat.py перейдёт на plain RAG fallback
```

### Режимы (`mode`)

| Режим | Условие | Кандидаты |
|---|---|---|
| `general` | `campaign_id` нет | Только общие pipelines |
| `campaign` | `campaign_id` есть | Кампания + общие |
| `locked` | `locked_pipeline_id` | Любой pipeline |

### Сохраняемые данные

Решение роутера пишется в `pipeline_decisions` (через `chat.py`). Ошибка роутера → `audit_logs[action="pipeline_router_failure"]`.

---

## 5. PipelineExecutor (`services/pipeline_executor.py`)

### Три режима вызова

| Метод | Используется | Возвращает |
|---|---|---|
| `run(context)` | `/send` | `_ExecutionResult(final_answer, sources)` |
| `run_stream(context)` | `/send_stream` | `AsyncIterator[dict]` SSE-чанки |

### SSE-чанки (формат)

```python
{"type": "pipeline_selected", "pipeline_id": "...", "pipeline_name": "...", "reasoning": "...", "mode": "..."}
{"type": "progress",          "step": 1, "total": 2, "step_name": "..."}
{"type": "step_done",         "step": 1, "step_name": "...", "partial_length": 420}
{"type": "step_skipped_no_docs", "step": 1, "step_name": "..."}
{"type": "token",             "content": "..."}  # streaming tokens
{"type": "sources",           "grouped_by_step": true, "step_groups": [{"step": 1, "step_name": "...", "sources": [...]}]}
{"type": "error",             "message": "..."}
```

### Шаги `_execute()` детально

```
1. _mark_started()  → chat.pipeline_versions["last_used"] = {pipeline_id, started_at}
2. Сортировать steps по step.order
3. Получить active provider (settings_service.get_active_provider())
4. Для каждого step (последовательно, не asyncio.gather!):
   a. _retrieve_for_step() → list[SearchHit] (пусто = skip)
   b. format_context_with_role(hits, step.role)
   c. format_prompt(step.system_prompt, {context, query})
   d. provider.generate([system, user]) → partial_answer
5. combined_context = join(partial_answers, "\n\n---\n\n")
6. format_prompt(final_composition.system_prompt, {context, collected_fields})
7. provider.generate_stream([system, user]) → tokens
8. _mark_completed() → chat.pipeline_versions["last_used"]["completed_at"]
```

> **Важно:** шаги выполняются **последовательно** (SQLAlchemy async не допускает конкурентный доступ к одной сессии).

---

## 6. Retrieval (`services/retrieval.py`)

### Три функции

| Функция | Описание |
|---|---|
| `retrieve(query, vault_id, document_ids?, top_k?, db)` | Поиск в одном vault |
| `retrieve_multi_vault(query, vault_ids, document_ids?, top_k?, db)` | Поиск в нескольких vault, результаты объединяются и сортируются по score |
| `format_context_with_role(hits, role)` | Форматирует текстовый блок для промпта |

### Тег-скопинг

| Ситуация | Поведение |
|---|---|
| `step.tag_ids` заданы | Фильтр по документам с этими тегами |
| `step.tag_ids` нет, `campaign_id` есть | Фильтр по тегам кампании (через `get_allowed_tag_ids`) |
| оба пусты | Поиск по всему домену (нет фильтра `document_ids`) |
| `vault_ids` пусты | Шаг пропускается (warning + return []) |

### Параметры ретривала

| Параметр | Источник |
|---|---|
| `top_k` | `step.top_k` → `platform_settings["retrieval.top_k"]` |
| `score_threshold` | `platform_settings["retrieval.score_threshold"]` |

### `SearchHit` (результат поиска)

```python
class SearchHit(BaseModel):
    document_id: str
    chunk_index: int
    text: str
    score: float
    metadata: dict   # source_path, page_number, headers, vault_id, ...
```

### `format_context_with_role(hits, role)`

Формирует текстовый блок для промпта. `role` (из `PipelineStep`) влияет на заголовок блока (напр. `"lore"` → заголовок может быть `"Лор: "`).

---

## 7. Plain RAG Fallback

Если `PipelineRouter` вернул `None` — `chat.py` запускает простой RAG без pipeline:

```
1. retrieve() → hits
2. format_context_with_role(hits, role="default")
3. domain_prompts["system"] + context → system-prompt
4. provider.generate_stream() → ответ
```

---

## 8. `PipelineExecutionContext` (главный DTO)

```python
class PipelineExecutionContext(BaseModel):
    query: str
    chat_id: str | None
    domain_id: str | None
    campaign_id: str | None
    history: list[Message] | None       # последние N сообщений
    vault_ids: list[str] | None         # все bound vaults домена
    collected_fields: dict | None       # из ClarificationState.collected

    # Заполняет PipelineRouter:
    pipeline_id: str | None
    pipeline_version: str | None
    steps: list[PipelineStep] | None
    final_composition: FinalComposition | None
    confidence: float | None
    reasoning: str | None
    mode: str | None                    # "general" | "campaign" | "locked"
```

---

## 9. `PipelineStep` (JSONB-формат)

```python
class PipelineStep(BaseModel):
    order: int                # Порядок выполнения
    name: str                 # Название шага
    role: str                 # Роль для format_context_with_role()
    system_prompt: str        # Промпт шага (поддерживает {context}, {query})
    top_k: int | None         # top_k ретривала (иначе из platform_settings)
    tag_ids: list[str] | None # UUID-теги для скопинга
```

## 10. `FinalComposition` (JSONB-формат)

```python
class FinalComposition(BaseModel):
    system_prompt: str  # Систем-промпт финальной генерации
                        # Поддерживает {context}, {collected_fields}
```

---

## 11. Формат промптов (`prompt_pack.py`)

`format_prompt(template, variables)` — простая шаблонизация `str.format_map()`.

**Доступные переменные:**

| Переменная | Контекст |
|---|---|
| `{context}` | Отформатированные чанки из retrieval |
| `{query}` | Вопрос пользователя |
| `{collected_fields}` | JSON-строка собранных clarification-полей |
| `{missing_fields}` | В clarification-промпте |

---

## 12. SettingsService: ключевые ключи runtime

| Ключ | Тип | Описание |
|---|---|---|
| `retrieval.top_k` | int | Количество результатов ретривала |
| `retrieval.score_threshold` | float | Порог релевантности |
| `planner.enabled` | bool | Включить/отключить planner |
| `clarification.max_turns` | int | Макс ходов FSM уточнения |
| `clarification.enabled` | bool | Включить/отключить FSM |

`settings_service.get_active_provider()` — возвращает закешированный `GenerationProvider` для модели с `is_active=True`.

---

## 13. Сохранение сообщений

Перед запуском pipeline: `Message(role="user")` → PostgreSQL.  
После ответа: `Message(role="assistant", pipeline_id=selected.pipeline_id)` → PostgreSQL.  
Оба сохраняются **в `chat.py`**, а не внутри executor/router.

---

## 14. Важные нюансы

- **Последовательность шагов** обязательна — одна async SQLAlchemy-сессия разделяется между retrieval и executor.
- **`PipelineExecutor`** не создаёт instance через `__init__` — сервис инстанцируется через `__new__`, db регистрируется в `self.db` перед каждым запросом.
- **`final_composition.system_prompt`** получает `combined_context` (все частичные ответы шагов) + `collected_fields`.
- **Clarification** не блокирует pipeline — при `fallback` pipeline запускается с неполными `collected_fields`.
- **`chat.locked_pipeline_id`** — если задан, роутер пропускает LLM-выбор. Можно задать через `PATCH /api/chat/{chat_id}`.
- **`step.tag_ids`** изолирует шаг от контекста кампании — автор pipeline выбирает теги явно.
- **`sources`** в ответе — дедуплицированые `{path, page, vault_id}` по ключу `(path, page, vault_id)`, сгруппированы по шагу.
