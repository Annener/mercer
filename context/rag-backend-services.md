# rag-backend: Слой сервисов (`app/services/`)

## Обзор

13 файлов сервисного слоя. Все зависимости направлены внутрь (providers → services → DAL).  
Никаких HTTP-роутеров здесь нет — только бизнес-логика.

---

## Карта файлов

| Файл | Размер | Назначение |
|---|---|---|
| `retrieval.py` | ~32 KB | Векторный / гибридный поиск + reranker |
| `pipeline_executor.py` | ~31 KB | DAG-runner пайплайна со стримингом + full_document_selection |
| `settings_service.py` | ~23 KB | CRUD настроек, провайдеров, моделей |
| `full_document_service.py` | ~10 KB | Сборка полных текстов документов + гибридный контекст |
| `pipeline_dag.py` | ~7 KB | Чистый DAG-движок (без HTTP/DB) |
| `pipeline_router.py` | ~8 KB | LLM-маршрутизатор → выбор пайплайна |
| `pipeline_service.py` | ~7 KB | CRUD пайплайнов в БД |
| `domain_service.py` | ~9 KB | CRUD доменов, промптов, кларификационных полей |
| `planner.py` | ~7 KB | Предварительное планирование запроса |
| `clarification_fsm.py` | ~5 KB | FSM сбора уточнений от пользователя |
| `query_rewriter.py` | ~7 KB | LLM-переформулировка поисковых запросов |
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

## full_document_service.py — Полные документы (Full Document Mode)

**Stage 3 Full Document Mode.** Позволяет пользователю запросить отправку полного текста документа в LLM вместо набора чанков.

### Константы

```python
FULL_DOC_TOKEN_LIMIT = 32_000  # максимум токенов для полного документа
```

### Публичный API

```python
async def collect_document_candidates(hits, sent_full_document_ids, db) -> list[DocumentCandidate]
async def reconstruct_full_text(document_id, vault_id, db_api_url) -> str | None
def assemble_hybrid_context(selected_doc_ids, full_texts, hits, candidates) -> str
```

#### `collect_document_candidates()`
1. Дедуплицирует `document_id` из хитов (порядок первого появления)
2. Загружает `Document`-записи из БД одним IN-запросом
3. Фильтрует документы без `char_count`/`estimated_tokens` (size-метаданные обязательны)
4. Фильтрует документы `> FULL_DOC_TOKEN_LIMIT` токенов
5. Помечает `already_sent` по списку `sent_full_document_ids`

#### `reconstruct_full_text()`
Запрашивает чанки через:
```
GET {db_api_url}/index/document/{document_id}/chunks?vault_id={vault_id}
→ {"chunks": [{chunk_id, document_id, vault_id, text, metadata: {chunk_index: N}, ...}]}
```
Сортирует по `metadata.chunk_index`, склеивает через `\n`.

#### `assemble_hybrid_context()`
Формат секции полного документа:
```
[FULL DOCUMENT: {title}]
{full_text}
[END DOCUMENT]
```
Формат остаточных чанков (из документов без полного текста):
```
[CHUNK from {title}]
{chunk_text}
```

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
    async def resume_from_full_doc_selection(chat_id, selected_document_ids, db) -> AsyncIterator[dict]
```

### Типы событий (SSE-чанки)

| `type` | Описание |
|---|---|
| `pipeline_selected` | пайплайн выбран, передаёт `pipeline_id` |
| `step_complete` | шаг завершён (retrieval OK) |
| `step_skipped_no_docs` | шаг пропущен — нет документов |
| `step_error` | ошибка retrieval-шага |
| `validation_required` | пауза на validation-шаге, содержит `resume_token` |
| `full_document_selection_required` | пауза Full Document Mode, содержит список `candidates` |
| `token` | стриминговый токен LLM из `final_composition` |
| `pipeline_complete` | весь пайплайн завершён |
| `step_status` | информационный статус шага (отображается в UI) |
| `error` | критическая ошибка |

### Алгоритм выполнения

1. `get_execution_levels(ctx.steps)` → список уровней  
2. Одиночный шаг уровня — `_run_dag_step()`  
3. Несколько шагов уровня — `_run_parallel_level()` через `asyncio.gather()`  
   (каждый шаг получает отдельную DB-сессию из `session_factory`)  
4. После всех уровней → `_maybe_pause_for_full_doc()` — проверка Full Document Mode  
5. Если пауза не нужна → `_run_final_composition()` → LLM stream

### Validation-пауза

При встрече `step.type == "validation"`:
1. Генерируется `resume_token = secrets.token_urlsafe(32)`, TTL = 1 час  
2. В `Chat.pipeline_pause_state` сохраняется `context_snapshot` (полный дамп `PipelineExecutionContext`)  
3. Возвращается `validation_required` чанк — пайплайн останавливается  
4. При возобновлении: `resume_from_validation(ctx, validated_step_id)` — пропускает уровни до `validated_step_id`

### Full Document Mode — пауза перед финальной композицией

После выполнения всех DAG-шагов, если `Chat.full_document_mode_enabled = True`:

1. `_maybe_pause_for_full_doc()` собирает все накопленные `SearchHit` из `ctx.step_results` (ключи `_hits_*`)
2. Вызывает `collect_document_candidates()` — фильтрует документы по размеру и уже отправленным
3. Если есть кандидаты → сохраняет `pipeline_pause_state` со `step="full_document_selection"` и возвращает `full_document_selection_required`
4. Пользователь выбирает документы → вызывается `resume_from_full_doc_selection()`

### `resume_from_full_doc_selection()`

Два варианта ветки по наличию `pipeline_id` в `context_snapshot`:
- **plain-fallback** (нет `pipeline_id`): загружает полные тексты → собирает гибридный контекст → вызывает LLM напрямую → сохраняет `Message`
- **pipeline** (есть `pipeline_id`): восстанавливает `PipelineExecutionContext` → записывает hybrid context в `step_results` retrieval-шагов → запускает `_run_final_composition()`

Параллельная загрузка полных текстов через `asyncio.gather()`.  
`vault_id` для документа берётся из `hit.metadata["vault_id"]` или fallback на первый vault из контекста.

После успешной загрузки обновляет `Chat.sent_full_document_ids` и очищает `Chat.pipeline_pause_state`.

### Промт-резолюция

`_resolve_prompt(template, ctx)` подставляет:
- `{query}` → `ctx.original_query` если есть, иначе `ctx.query` (полный пользовательский запрос, до QueryRewriter)
- `{STEP_ID.result}` → результат шага
- `{STEP_ID.key}` → ключ из dict-результата
- Ключи начинающиеся с `_` (внутренние, например `_hits_*`) игнорируются

### Накопление хитов

Каждый retrieval-шаг сохраняет сырые `SearchHit` в `ctx.step_results` под ключом  
`_hits_{step_id}` — для последующего использования в `_maybe_pause_for_full_doc()`.  
Публичный хелпер: `_collect_all_hits(ctx) -> list[SearchHit]` — дедуплицирует по `chunk_id`.

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
    │       │                  + накапливает hits в ctx.step_results["_hits_{step_id}"]
    │       ├─ [validation step] → пауза → resume_from_validation()
    │       ├─ _maybe_pause_for_full_doc() — если full_document_mode_enabled
    │       │     └─ [кандидаты есть] → full_document_selection_required → resume_from_full_doc_selection()
    │       └─ FinalComposition → LLM stream → SSE tokens
    │
    └─ [нет пайплайна] plain RAG
            ├─ get_allowed_tag_ids() → get_document_ids_by_tags()
            ├─ retrieve() / retrieve_multi_vault()
            ├─ rerank_hits()
            ├─ [full_document_mode_enabled] → full_document_selection_required
            │     └─ resume_from_full_doc_selection() (plain-fallback ветка)
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
