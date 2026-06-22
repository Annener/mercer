# rag-backend: Слой сервисов (`app/services/`)

## Обзор

12 файлов сервисного слоя. Все зависимости направлены внутрь (providers → services → DAL).  
Никаких HTTP-роутеров здесь нет — только бизнес-логика.

---

## Карта файлов

| Файл | Размер | Назначение |
|---|---|---|
| `retrieval.py` | ~30 KB | Векторный / гибридный поиск + reranker |
| `pipeline_executor.py` | ~14 KB | DAG-runner пайплайна со стримингом |
| `settings_service.py` | ~23 KB | CRUD настроек, провайдеров, моделей |
| `pipeline_dag.py` | ~7 KB | Чистый DAG-движок (без HTTP/DB) |
| `pipeline_router.py` | ~8 KB | LLM-маршрутизатор → выбор пайплайна |
| `pipeline_service.py` | ~7 KB | CRUD пайплайнов в БД |
| `domain_service.py` | ~9 KB | CRUD доменов, промптов, кларификационных полей |
| `planner.py` | ~7 KB | Предварительное планирование запроса |
| `clarification_fsm.py` | ~5 KB | FSM сбора уточнений от пользователя |
| `query_rewriter.py` | ~5 KB | LLM-переформулировка поисковых запросов |
| `prompt_pack.py` | ~5 KB | Загрузка/форматирование промптов |
| `vault_config_service.py` | ~3 KB | Настройки Vault (embedding-модель и т.д.) |

---

## retrieval.py — Сердце RAG

### Публичный API

```python
async def retrieve(query, vault_id, *, document_ids, top_k, strategy, config, db) -> list[SearchHit]
async def retrieve_multi_vault(query, vault_ids, *, document_ids, top_k, strategy, config, db) -> list[SearchHit]
async def rerank_hits(query, hits, db) -> list[SearchHit]
def format_context(hits, role=None) -> str
def format_context_with_role(hits, role) -> str          # алиас, для обратной совместимости
async def delete_document_chunks(document_id, vault_id)
async def get_allowed_tag_ids(domain_id, campaign_id, db) -> set[str]
async def get_document_ids_by_tags(tag_ids, domain_id, db) -> list[str]
```

### Стратегии поиска

| Стратегия | Логика |
|---|---|
| `"hybrid"` | vector search + FTS → **RRF merge** (дефолт) |
| `"semantic"` | только vector search |
| `"none"` | возвращает `[]` без запроса к LanceDB |

**RRF (Reciprocal Rank Fusion):**  
`score = 1/(k+rank_vector) + 1/(k+rank_text)`, где k=60.  
Дедупликация по `chunk_id`. Vector-версия хита имеет приоритет.

### Фильтрация по документам

```
document_ids = None   → поиск по всему vault (без фильтра)
document_ids = []     → немедленный возврат [] (кампания без тегов)
document_ids = [...]  → LanceDB filter {"document_id": {"$in": [...]}}
```

> ⚠️ Страховочный пост-фильтр: если LanceDB вернул hits вне `document_ids` (маппинг-баг в storage API) — они вырезаются с `WARNING`.

### Embedding-провайдеры

Приоритет резолюции:  
1. `_embedding_model` (прямая передача из `retrieve_multi_vault`)  
2. `config: AppConfig`  
3. `db` → `settings_service.get_active_embedding_config()`

Поддерживаемые провайдеры: `"ollama"` (POST `/api/embeddings`) и `"openai_compatible"` (POST `/embeddings`).  
Retry с экспоненциальным backoff: `2^attempt` секунд, `model.max_retries` попыток.

### Reranker

Поддерживаемые провайдеры:

| Провайдер | Механизм |
|---|---|
| `ollama` | Генеративный yes/no через `/api/generate`. Semaphore ограничивает параллелизм (env `RERANK_OLLAMA_CONCURRENCY=1`). Парсит `<think>...</think>` Qwen3-Reranker. |
| `openai_compatible / cohere / jina` | POST `/rerank` → поле `relevance_score` или `score` |

Если reranker не активен (`enabled=False`) — хиты возвращаются без изменений.

### format_context()

Формирует пронумерованный контекст `[1] текст\n\n[2] текст...` для LLM.  
Нумерация документов строго соответствует нумерации карточек источников на фронтенде.  
С параметром `role` оборачивает в `=== role ===\n...`.  
При пустом `hits` без `role` возвращает заглушку на русском.

---

## pipeline_dag.py — Чистый DAG-движок

**Нет** зависимостей от DB, HTTP или FastAPI.

```python
build_dag(steps)              -> dict[str, list[str]]         # граф смежности
topological_sort(steps)       -> list[list[str]]              # уровни Кана
detect_cycles(steps)          -> list[str] | None             # DFS
validate_dag(steps)           -> list[str]                    # список ошибок
get_execution_levels(steps)   -> list[list[PipelineStep]]     # объекты шагов по уровням
```

**Топологическая сортировка (Кан):** возвращает `list[list[step_id]]` — шаги одного уровня  
могут выполняться параллельно. При цикле → пустой список.

**Ребро A→B**: шаг B зависит от A (в `B.after_step_ids` содержится `A`).

---

## pipeline_executor.py — DAG Runner

```python
class PipelineExecutor:
    async def run_stream(ctx) -> AsyncIterator[dict]
    async def resume_from_validation(ctx, validated_step_id) -> AsyncIterator[dict]
```

### Типы событий (SSE-чанки)

| `type` | Описание |
|---|---|
| `pipeline_selected` | пайплайн выбран, передаёт `pipeline_id` |
| `step_complete` | шаг завершён (retrieval OK) |
| `step_skipped_no_docs` | шаг пропущен — нет документов |
| `step_error` | ошибка retrieval-шага |
| `validation_required` | пауза на validation-шаге, содержит `resume_token` |
| `token` | стриминговый токен LLM из `final_composition` |
| `pipeline_complete` | весь пайплайн завершён |
| `error` | критическая ошибка |

### Алгоритм выполнения

1. `get_execution_levels(ctx.steps)` → список уровней  
2. Одиночный шаг уровня — `_run_dag_step()`  
3. Несколько шагов уровня — `_run_parallel_level()` через `asyncio.gather()`  
   (каждый шаг получает отдельную DB-сессию из `session_factory`)  
4. После всех уровней — `_run_final_composition()` → LLM stream

### Validation-пауза

При встрече `step.type == "validation"`:
1. Генерируется `resume_token = secrets.token_urlsafe(32)`, TTL = 1 час  
2. В `Chat.pipeline_pause_state` сохраняется `context_snapshot` (полный дамп `PipelineExecutionContext`)  
3. Возвращается `validation_required` чанк — пайплайн останавливается  
4. При возобновлении: `resume_from_validation(ctx, validated_step_id)` — пропускает уровни до `validated_step_id`

### Промт-резолюция

`_resolve_prompt(template, ctx)` подставляет:
- `{query}` → `ctx.query`
- `{STEP_ID.result}` → результат шага
- `{STEP_ID.key}` → ключ из dict-результата

### Поисковый запрос для шага

Перед retrieval: `query_rewriter.rewrite_for_retrieval(ctx.query, step_prompt, provider)` —  
LLM комбинирует цель шага и запрос пользователя в оптимальный векторный запрос.

---

## pipeline_router.py — LLM-маршрутизатор

```python
class PipelineRouter:
    async def select(context, locked_pipeline_id, db, llm_provider) -> PipelineRead | None
```

### Логика выбора

1. **Locked pipeline** → возвращает напрямую без LLM (режим mode проверяется)  
2. Получить активные пайплайны домена → отфильтровать по `campaign_id`  
   - `mode=campaign` → пайплайны без `campaign_id` + пайплайны с совпадающим `campaign_id`  
   - `mode=general` → только пайплайны без `campaign_id`  
3. LLM-вызов: `provider.generate()` → ожидается JSON  
   ```json
   {"pipeline_id": "...", "confidence": 0.8, "reasoning": "..."}
   ```  
4. `confidence < 0.5` → возвращает `None` (chat.py переходит на plain RAG)

Промт-шаблон берётся из `domain_service.get_prompt(domain_id, "pipeline_router")` или дефолтный `PROMPT_TEMPLATE`.  
Использует последние 3 сообщения истории чата.  
Ошибки роутинга логируются в `AuditLog` как `pipeline_router_failure`.

---

## domain_service.py — Домены

```python
domain_service = DomainService()   # синглтон

await domain_service.get_domain(domain_id, db)                         -> DomainConfig
await domain_service.list_enabled(db)                                  -> list[DomainConfig]
await domain_service.create_domain(data, db)                           -> dict
await domain_service.update_domain(domain_id, data, db)                -> dict
await domain_service.delete_domain(domain_id, db)                      # guard: есть vault'ы?
await domain_service.update_prompts(domain_id, prompts, db)
await domain_service.update_clarification_fields(domain_id, fields, db)
domain_service.invalidate(domain_id)                                   # сброс in-memory кэша
```

**In-memory кэш** `_cache: dict[str, DomainConfig]`. Инвалидируется при любом изменении.  
Фаллбэк: если домен не найден → подтягивает домен `"default"`.  
**Защита от удаления**: нельзя удалить домен с vault'ами; нельзя удалить системный домен.

`DomainConfig` содержит:
- `prompts: dict[str, str]` — типы `system`, `clarification`, `planner`, `pipeline_router`
- `clarification_fields: list[dict]` — упорядочены по `display_order`

---

## planner.py — Планировщик запроса

```python
class Planner:
    async def decide(db, query, vault_id, domain_id, history) -> tuple[PlannerDecision, list[str]]
```

Вызывается до начала RAG. Определяет:

| Решение | Логика |
|---|---|
| `retrieval_strategy` | `"semantic"` если у vault/домена есть чанки, иначе `"none"` |
| `clarification_needed` | `True` если LLM нашёл `missing_fields` И `max_clarification_turns > 0` |
| `pipeline_invocations` | список пайплайнов из реестра для домена |

**LLM-роутер кларификации**: отправляет запрос + последние 6 сообщений истории в LLM,  
ожидает `{"missing_fields": ["field1", ...]}`. Фильтрует ответ — только поля  
разрешённые для данного домена (из `DomainClarificationField`).

---

## clarification_fsm.py — FSM уточнений

Состояния: `idle` → `collecting` → `complete` / `fallback`

```python
async def get_state(db, chat_id) -> ClarificationState
async def save_state(db, chat_id, state)
async def start_collecting(db, chat_id, missing_fields, prompt_pack) -> ClarificationState
def process_clarification_answer(state, user_message, max_turns, prompt_pack) -> ClarificationState
def idle_state() -> ClarificationState
def generate_next_question(missing_fields, collected, prompt_pack) -> str
```

**Экстракция значений** (`_extract_field_value`): regex-паттерны `"про X"`, `"это X"` + нормализация (strip пунктуации).  
**Переход в `fallback`**: когда `turn >= max_turns` но ещё есть `missing_fields`.

---

## query_rewriter.py — Переформулировка запросов

```python
query_rewriter = QueryRewriter()   # синглтон

await query_rewriter.rewrite(original_query, history, provider, domain_description) -> str
await query_rewriter.rewrite_for_retrieval(original_query, step_prompt, provider) -> str
```

| Метод | Когда используется | Промпт |
|---|---|---|
| `rewrite()` | chat-путь, при наличии истории | `REWRITE_PROMPT` — делает запрос самодостаточным (заменяет местоимения) |
| `rewrite_for_retrieval()` | pipeline step retrieval | `RETRIEVAL_REWRITE_PROMPT` — оптимизирует под векторный поиск |

Fallback: при любом исключении возвращает `original_query` (не ломает пайплайн).

---

## Главный поток запроса (chat-путь)

```
HTTP POST /chat/stream
    │
    ├─ Planner.decide()
    │       ├─ retrieval_strategy?
    │       └─ clarification_needed? → ClarificationFSM
    │
    ├─ [если clarification] → FSM.process_clarification_answer() → вернуть вопрос
    │
    ├─ QueryRewriter.rewrite()              ← история чата
    │
    ├─ PipelineRouter.select()             ← LLM выбирает пайплайн
    │
    ├─ [есть пайплайн] PipelineExecutor.run_stream()
    │       ├─ DAG levels (get_execution_levels)
    │       │     └─ per step: QueryRewriter.rewrite_for_retrieval() → retrieve() → format_context()
    │       ├─ [validation step] → пауза → resume_from_validation()
    │       └─ FinalComposition → LLM stream → SSE tokens
    │
    └─ [нет пайплайна] plain RAG
            ├─ get_allowed_tag_ids() → get_document_ids_by_tags()
            ├─ retrieve() / retrieve_multi_vault()
            ├─ rerank_hits()
            └─ format_context() → LLM stream
```

---

## Env-переменные сервисного слоя

| Переменная | Дефолт | Описание |
|---|---|---|
| `STORAGE_API_URL` | `http://db-api-server:8080` | URL storage API (LanceDB прокси) |
| `RERANK_OLLAMA_CONCURRENCY` | `1` | Параллелизм запросов к Ollama reranker |
| `RERANK_OLLAMA_NUM_PREDICT` | `32` | Лимит токенов ответа reranker |
| `DEFAULT_TOP_K` | `10` | Кол-во чанков из retrieval по умолчанию |
