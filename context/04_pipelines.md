# Mercer — Пайплайны

> **Проход 4 из N.**
> Файлы: `rag-backend/app/services/pipeline_router.py`, `pipeline_executor.py`, `pipeline_service.py`.

---

## Общая концепция

Пайплайн — это набор последовательных шагов обработки запроса пользователя, определённый администратором. Каждый шаг выполняет:
1. Извлечение чанков из LanceDB (тип `retrieval`)
2. LLM-генерацию частичного ответа по найденным чанкам

После всех шагов запускается **FinalComposition** — сборка итогового ответа через LLM с объединёнными результатами шагов.

---

## Структура данных

### `PipelineStep` (shared_contracts)

```python
class PipelineStep(BaseModel):
    order: int                  # Порядок выполнения
    type: Literal["retrieval", "final"]
    name: str                   # Название для UI и логов
    system_prompt: str          # Промпт LLM для шага
    top_k: int | None           # Переопределяет retrieval.top_k из настроек
    tag_ids: list[str]          # Фильтр по тегам (пустой = наследовать сценарий кампании)
    is_final: bool              # Deprecated-поле (final определяется через FinalComposition)
    role: str | None            # Метка роли для UI (напр. "rules", "examples")
```

### `FinalComposition` (shared_contracts)

```python
class FinalComposition(BaseModel):
    system_prompt: str   # Промпт финальной LLM-композиции
                         # Доступные подстановки: {context}, {collected_fields}
```

### `PipelineRead` (shared_contracts)

```python
class PipelineRead(ORMModel):
    id: str                     # UUID (internal PK)
    pipeline_id: str            # Строковый slug
    domain_id: str
    campaign_id: str | None     # None = общий пайплайн домена
    version: str                # "v1", "v2", ...
    name: str
    description: str | None
    steps: list[PipelineStep]   # Шаги из JSONB
    final_composition: FinalComposition
    is_active: bool
    created_at: datetime | None
```

### `PipelineExecutionContext` (shared_contracts)

Контекст, передаваемый через весь поток выполнения:

```python
class PipelineExecutionContext(BaseModel):
    chat_id: str
    message_id: str
    query: str                  # Переформулированный запрос (query rewriter)
    original_query: str         # Оригинальный запрос пользователя
    domain_id: str | None
    campaign_id: str | None
    vault_id: str | None        # Deprecated back-compat
    vault_ids: list[str]        # Список vault домена
    retrieval_strategy: str     # "hybrid", "none"
    history: list[ChatMessage]  # Последние 20 сообщений
    # Заполняется PipelineRouter:
    pipeline_id: str | None
    pipeline_version: str | None
    steps: list[PipelineStep] | None
    final_composition: FinalComposition | None
    confidence: float | None
    reasoning: str | None
    mode: str | None            # "general" или "campaign"
    collected_fields: dict      # Ответы clarification FSM
```

---

## PipelineRouter

**Файл:** `rag-backend/app/services/pipeline_router.py`

### Цель
Выбрать подходящий пайплайн для текущего запроса и домена.

### Главный метод: `select(context, locked_pipeline_id)`

```
1. locked_pipeline_id задан?
   ├── Да → загрузить pipeline из БД
   │       ├── Нашёл → проверить совместимость режима (campaign/general) → вернуть
   │       └── Не нашёл → warning + продолжить к LLM-роутингу
   └── Нет → продолжить

2. Загрузить активные пайплайны домена
   ├── Пустых нет → вернуть None

3. Фильтрация по режиму:
   ├── campaign_id есть → пайплайны этой кампании + общие домена
   └── Общий режим → только пайплайны без campaign_id

4. LLM-роутинг:
   ├── Загрузить промпт типа pipeline_router из domain_prompts
   ├── Если промпт пустой → использовать PROMPT_TEMPLATE
   ├── Отправить LLM-запрос с перечнем pipeline + запрос + история (3 посл.сообщ.)
   └── Ожидать JSON: {"pipeline_id": "...", "confidence": 0.0-1.0, "reasoning": "..."}

5. Проверка:
   ├── pipeline_id в списке кандидатов + confidence >= 0.5
   ├── Успех → заполнить context + вернуть PipelineRead
   └── Неудача → записать в audit_logs + вернуть None
```

### Режимы (`mode`)

| mode | Условие | Кандидаты |
|---|---|---|
| `general` | `campaign_id = null` | Только пайплайны с `campaign_id IS NULL` |
| `campaign` | `campaign_id` задан | Пайплайны этой кампании + общие домена |
| `locked` | `locked_pipeline_id` задан | Конкретный pipeline, без LLM-вызова |

### Порог `confidence`

| Значение | Поведение |
|---|---|
| `>= 0.7` | Высокая уверенность |
| `0.5 – 0.7` | Средняя уверенность |
| `< 0.5` | Отклонение, фоллбэк на plain RAG |

---

## PipelineExecutor

**Файл:** `rag-backend/app/services/pipeline_executor.py`

### Публичный API

| Метод | Используется в | Описание |
|---|---|---|
| `run(context)` | `chat.py /send` | Собирает все SSE-чанки внутренне, возвращает `_ExecutionResult` |
| `run_stream(context)` | `chat.py /send_stream` | Асинх-генератор SSE-диктов |

### Поток выполнения `_execute()`

```
1. Излучаем отмену (разрыв WebSocket = остановить)
2. Чанк: {"type": "pipeline_selected", "pipeline_id": ..., "reasoning": ...}
3. Чанк: по {"type": "progress", "step": N, "total": M} для каждого шага (анонс)
4. Выполнение шагов последовательно (!НЕ asyncio.gather — SQLAlchemy async)
   Для каждого шага:
     a. _retrieve_for_step(): LanceDB-поиск с применением tag-сценария
     b. Если хитов нет → _SKIPPED
     c. Если хиты есть → LLM.generate(system_prompt + контекст + query) → partial_result
5. Чанки по результатам:
   ├── {"type": "step_skipped_no_docs", ...}
   └── {"type": "step_done", "partial_length": N, ...}
6. FinalComposition:
   ├── Объединить partial_results через "\n\n---\n\n"
   ├── format_prompt(final_composition.system_prompt, {context, collected_fields})
   └── Стриминг: provider.generate_stream([system, user]) → {"type": "token", ...}
7. {"type": "sources", "grouped_by_step": true, "step_groups": [...]}
8. _mark_completed(): записать pipeline_versions.last_used.completed_at
```

### SSE-чанки (PipelineExecutor)

| `type` | Описание | Ключи |
|---|---|---|
| `pipeline_selected` | Пайплайн выбран | `pipeline_id`, `pipeline_name`, `reasoning`, `mode` |
| `progress` | Анонс о шагах | `step`, `total`, `step_name` |
| `step_done` | Шаг выполнен | `step`, `step_name`, `partial_length` |
| `step_skipped_no_docs` | Шаг пропущен | `step`, `step_name` |
| `token` | Токен ответа | `content` |
| `sources` | Источники | `grouped_by_step: true`, `step_groups: [{step, step_name, sources}]` |
| `error` | Ошибка | `message` |

### Теговая сценариев retrieval (_retrieve_for_step)

```
Шаг с tag_ids:
  └── get_document_ids_by_tags(step.tag_ids, domain_id)
       └── document_ids == [] → _SKIPPED

Шаг без tag_ids + campaign_id:
  └── get_allowed_tag_ids(domain_id, campaign_id)
       ├── Тегов нет → _SKIPPED
       └── get_document_ids_by_tags(tag_ids, domain_id)
            └── document_ids == [] → _SKIPPED

Шаг без tag_ids, без campaign_id:
  └── document_ids = None (весь домен)

Retrieve:
  ├── 1 vault  → retrieve(query, vault_id, document_ids, top_k)
  └── N vault → retrieve_multi_vault(query, vault_ids, document_ids, top_k)
```

---

## Цепочка обработки запроса (полная)

```
chat.py: POST /{chat_id}/send
  │
  ├─► 1. Сохранить user-сообщение (PostgreSQL)
  ├─► 2. Загрузить историю (20 сообщений)
  ├─► 3. QueryRewriter.rewrite() — LLM (если провайдер активен)
  ├─► 4. PipelineRouter.select()
  │        ├── Нашёл pipeline → [5a]
  │        └── Не нашёл → [5b]
  ├─► 5a. PipelineExecutor.run(context)
  │        └── Для каждого step:
  │              ├── _retrieve_for_step() → LanceDB
  │              └── LLM.generate() → partial
  │        └── FinalComposition → LLM.generate_stream() → final_answer
  └─► 5b. _plain_llm_reply()
           ├── _resolve_system_prompt() (campaign > domain)
           ├── _fallback_retrieve() → LanceDB
           └── provider.generate()
```

---

## Приоритет системного промпта

Порядок разрешения промпта (**от высшего к низшему**):

1. `campaign.system_prompt` — если кампания выбрана и имеет промпт
2. `domain_prompts[type=system].content` — общий системный промпт домена
3. Без промпта — если ни один не задан

Для промпта `pipeline_router`:
1. `domain_prompts[type=pipeline_router].content` (переопределяет поведение роутера)
2. `PROMPT_TEMPLATE` — встроенный шаблон

---

## PipelineService

**Файл:** `rag-backend/app/services/pipeline_service.py`

Слой доступа к таблице `pipelines`. Методы:

| Метод | Описание |
|---|---|
| `get_pipeline(pipeline_id, db)` | Получить пайплайн по `pipeline_id` (slug), возвращает последнюю версию |
| `get_active_pipelines(domain_id, db)` | Все `is_active=True` пайплайны домена |
| `create_pipeline(data, db)` | Создать пайплайн, авто-версийнирование (`v1`, `v2`, ...) |
| `update_pipeline(pipeline_id, data, db)` | Обновить, инкремент версии |
| `delete_pipeline(pipeline_id, db)` | Удалить с аудитом |

---

## format_prompt (prompt_pack.py)

**Файл:** `rag-backend/app/services/prompt_pack.py`

Подставновка переменных в шаблоне промпта.

```python
format_prompt(template: str, variables: dict) -> str
```

Доступные переменные в `system_prompt` шага:
- `{context}` — текст найденных чанков
- `{query}` — переформулированный запрос

Доступные переменные в `final_composition.system_prompt`:
- `{context}` — объединённые partial_results всех шагов
- `{collected_fields}` — JSON ответов FSM уточнения

---

## Важные нюансы и ограничения

- **Шаги выполняются последовательно**, не параллельно — SQLAlchemy async не допускает конкурентный доступ к одной сессии.
- **Шаг `_SKIPPED`** (пропущен) не передаётся в `final_composition` — его `partial` заменяется пустой строкой `""`.
- **`pipeline_versions.last_used`** в `chats` — записывается при старте и после завершения исполнения — для дебаггинга.
- **Отмена** (разрыв HTTP-соединения) вызывает `asyncio.CancelledError` — пайплайн чисто прерывается.
- **Фоллбэк** (plain RAG): срабатывает, когда пайплайнов нет или `confidence < 0.5`. Использует системный промпт кампании/домена и retrieval по всем Vault.
- Создавать пайплайны нужно через API, не вручную в БД — `pipeline_id` должен быть уникальным по `(pipeline_id, domain_id, version)`.
