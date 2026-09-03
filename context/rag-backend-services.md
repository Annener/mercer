# rag-backend: Слой сервисов (`app/services/`)

## Обзор

29 файлов сервисного слоя (`__init__.py` + 28 модулей). Все зависимости направлены внутрь (providers → services → DAL).  
Никаких HTTP-роутеров здесь нет — только бизнес-логика.

---

## Карта файлов

| Файл | Размер | Назначение |
|---|---|---|
| `retrieval.py` | ~34 KB | Векторный / гибридный поиск + reranker |
| `pipeline_executor.py` | ~40 KB | DAG-runner пайплайна со стримингом + full_document_selection + Campaign State injection |
| `settings_service.py` | ~23 KB | CRUD настроек, провайдеров, моделей, в т.ч. retrieval tool settings |
| `pipeline_dag.py` | ~7 KB | Чистый DAG-движок (без HTTP/DB) |
| `pipeline_router.py` | ~8 KB | LLM-маршрутизатор → выбор пайплайна |
| `pipeline_service.py` | ~7 KB | CRUD пайплайнов в БД |
| `domain_service.py` | ~9 KB | CRUD доменов, промптов, кларификационных полей |
| `planner.py` | ~7 KB | Предварительное планирование запроса |
| `clarification_fsm.py` | ~5 KB | FSM сбора уточнений от пользователя |
| `query_rewriter.py` | ~7 KB | LLM-переформулировка поисковых запросов |
| `prompt_pack.py` | ~5 KB | Загрузка/форматирование промптов |
| `vault_config_service.py` | ~3 KB | Настройки Vault (embedding-модель и т.д.) |
| `indexer_client.py` | ~6 KB | HTTP-клиент к rag-indexer (Update Mode resolve/apply) |
| `full_document_service.py` | ~12 KB | Сборка полных текстов документов + гибридный контекст |
| `campaign_state_service.py` | ~21 KB | CRUD конфигурации полей Campaign State + cascade purge (Stage 1) |
| `campaign_state_value_service.py` | ~35 KB | Versioned state + patch apply (Stage 2/5) |
| `campaign_state_compiler.py` | ~10 KB | Детерминированная компиляция Campaign State для prompt (Stage 6) |
| `effective_context.py` | ~11 KB | Runtime helper prompt assembly (Stage 6): compose_full_system_prompt, build_effective_context |
| `campaign_state_initial_service.py` | ~30 KB | Initial State proposal/apply (Stage 3) |
| `campaign_state_initial_store.py` | ~3 KB | Redis-сессии Initial State proposal |
| `campaign_state_stale_service.py` | ~16 KB | Вычисление potentially_stale (Stage 7) |
| `update_mode_executor.py` | ~50 KB | Оркестратор Campaign Update Mode + state_patch generation |
| `update_mode_store.py` | ~24 KB | Redis-сессии Update Mode review/apply с Lua-атомарностью |
| `agent_loop.py` | ~20 KB | Bounded LLM ↔ tool-cycle (Stage 8.4) |
| `search_knowledge_service.py` | ~8 KB | Host-side реализация `search_knowledge` tool (Stage 8.3) |
| `retrieval_tool_settings.py` | ~4 KB | Типизированный аксессор `retrieval.*` PlatformSettings (Stage 8.2) |

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
async def get_documents_by_tag(tag_id, db) -> list[Document]
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

> Страховочный пост-фильтр: если LanceDB вернул hits вне `document_ids` (маппинг-баг в storage API) — они вырезаются с `WARNING`.

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

### Diagnostic logs (Sprint 2)

В `retrieve()` (для каждого vault'а) пишется:

- `RETRIEVE_STAGES vault='...' strategy=hybrid vector_hits=N text_hits=M vector_top_cosine=0.xxxx` — ДО RRF-merge. Помогает диагностировать кросс-языковые случаи: при EN→RU `text_hits=0` потому что BM25 не находит пересечения; `vector_top_cosine` показывает реальную близость в bge-m3 (иначе RRF-скоры выглядят как `0.016` и непонятно, плохо это или нормально).
- `RERANK_HITS done: reranked N hits via model='...' rerank_top_score=0.xxxx` — score реранкера; низкий → вероятно нет релевантного материала.

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
5. Если пауза не нужна → `_run_final_composition()` → LLM stream.  
   В `compose_state_block_only()` подмешивается Campaign State блок после `_resolve_prompt(...)` (Stage 6).

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

### Накопление хитов и sources

Каждый retrieval-шаг сохраняет сырые `SearchHit` в `ctx.step_results` под ключом  
`_hits_{step_id}` — для последующего использования в `_maybe_pause_for_full_doc()` и для
формирования финального SSE `sources` event.  
Публичный хелпер: `_collect_all_hits(ctx) -> list[SearchHit]` — дедуплицирует по `chunk_id`.

Для шагов с `send_full_document=True`: дополнительно сохраняется
`_fulldoc_sources_{step_id} = list[Source]` (через `full_doc_hits_to_sources` —
одна запись на `document_id` с `source_kind="full_document"`).

После `_run_final_composition` (перед `pipeline_complete`) эмитится SSE event:

```json
{
  "type": "sources",
  "grouped_by_step": true,
  "step_groups": [
    {"step_id": "...", "step_name": "...", "sources": [{path, page?, vault_id?, document_id?, chunk_id?, source_kind, ...}]},
    ...
  ]
}
```

Сборка: `_collect_step_sources(ctx) -> list[SourceGroup]` — обходит все
`ctx.steps`, для каждого шага собирает источники из `_hits_*` и `_fulldoc_sources_*`,
дедуплицирует.

### Sources в Message (персистенция)

Resume-эндпоинты (`pipeline_resume.py::confirmed_stream`, `pipeline_resume.py::resume_stream`,
`_plain_rag_stream`, `fulldoc_confirm.py`, `pipeline_executor.py::resume_from_full_doc_selection`)
сохраняют `Message` с полем `sources` — JSONB список `MessageSource`.
Это позволяет восстановить блок «Источники» при reload чата.

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

## query_rewriter.py — Переформулировка запросов + кросс-языковой перевод (Sprint 2)

```python
query_rewriter = QueryRewriter()   # синглтон

# Stage 8.4 — переформулировка с учётом истории
await query_rewriter.rewrite(original_query, history, provider, domain_description) -> str

# Pipeline retrieval
await query_rewriter.rewrite_for_retrieval(original_query, step_prompt, provider) -> str

# Sprint 2 — кросс-языковой query expansion для prefill RAG
await query_rewriter.build_search_queries(
    original_query, provider, *, max_queries=4
) -> list[str]
# Возвращает [orig] для русского запроса
# Возвращает [orig, ru_translation] для английского (после LLM-перевода)
# При ошибке провайдера / пустом ответе / без provider — только [orig]
```

| Метод | Когда используется | Промпт / поведение |
|---|---|---|
| `rewrite()` | chat-путь, при наличии истории | `REWRITE_PROMPT` — делает запрос самодостаточным (заменяет местоимения) |
| `rewrite_for_retrieval()` | pipeline step retrieval | `RETRIEVAL_REWRITE_PROMPT` — оптимизирует под векторный поиск |
| `build_search_queries()` | **Sprint 2**: prefill RAG в `plain_stream` | Эвристика `is_cyrillic_query` (доля кириллицы ≥ 0.4); LLM-перевод `RU_TRANSLATE_PROMPT` для не-русских запросов. Dedup через `_normalise()` (lowercase + collapse whitespace). |

### Языковая детекция

```python
is_cyrillic_query(text: str, threshold: float = 0.4) -> bool
```

Считает долю кириллических букв в `text`. Если ≥ `threshold` — считается русским.
Позволяет смешанные запросы типа «Бехолдер Beholder» (7 кириллических / 8 латинских → ratio 0.467 → cyrillic).

Fallback: при любом исключении возвращает `original_query` (не ломает пайплайн).

---

## Campaign State — сервисы

### campaign_state_service.py — Field configuration (Stage 1)

CRUD-логика для `campaign_state_field_configs`:

```python
async def list_fields(campaign_id, db) -> list[CampaignStateFieldConfigRead]
async def create_field(campaign_id, data: CampaignStateFieldConfigCreate, db, *, actor) -> CampaignStateFieldConfigRead
async def update_field(field_id, data: CampaignStateFieldConfigUpdate, db, *, actor) -> CampaignStateFieldConfigRead
async def delete_field(field_id, db, *, actor) -> None
    # cascade-purge активной версии state: инкрементирует state_version,
    # пишет AuditLog action="campaign_state_field_cascade_purged"
async def reorder_fields(campaign_id, field_ids: list[str], db, *, actor) -> list[CampaignStateFieldConfigRead]
    # атомарная перестановка display_order; инкрементирует Campaign.config_version
```

Все мутации инкрементируют `Campaign.config_version`, чтобы клиенты могли видеть
несоответствие версии конфигурации в patch requests.

### campaign_state_value_service.py — Versioned state + patch (Stage 2/5)

```python
async def get_active_state(campaign_id, db) -> CampaignStateVersionRead | None
async def list_versions(campaign_id, db, limit, offset) -> list[CampaignStateVersionSummary]
async def get_version(campaign_id, state_version, db) -> CampaignStateVersionRead
async def apply_patch(campaign_id, patch: CampaignStatePatchRequest, db, *, actor) -> CampaignStatePatchResponse
    # fail-fast валидация; первая ошибка останавливает apply;
    # успешные операции применяются как одна новая версия (source_kind='patch')
async def create_initial_version(campaign_id, proposal: CampaignStateInitialProposal, db, *, actor) -> CampaignStateVersionRead
    # source_kind='initial', state_version=1, base_state_version=null
```

Удаление поля (Stage 4.1.1): `purge_field_from_active_version(...)` создаёт новую state-version, очищая
соответствующие `CampaignStateValue` / `CampaignStateListItem` строки в **активной** версии, и пишет AuditLog.

### campaign_state_compiler.py — Компилятор для prompt (Stage 6)

Детерминированный компилятор active версии Campaign State в текстовый блок
для prompt. Чистая функция, без БД/HTTP.

```python
from app.services.campaign_state_compiler import (
    compile_campaign_state,
    DEFAULT_TOKEN_BUDGET,
    default_token_counter,
    get_campaign_state_token_budget,
)

block = compile_campaign_state(
    version=active_state_version,        # CampaignStateVersionRead | None
    fields=enabled_fields_ordered,       # list[CampaignStateFieldConfigRead]
    budget_tokens=800,
)
# block.text         — текст для prompt ("" если state отсутствует)
# block.used_tokens  — оценка использованных токенов
# block.truncated_fields
# block.fields       — per-field метаданные для debug
```

Правила:

- порядок полей — `display_order ASC, key ASC`;
- budget ~800 токенов (ключ `chat.campaign_state_token_budget` в
  `settings_service.DEFAULTS`); поля исключаются целиком, не обрезаются;
- `single`: `"{label}: {text}"`;
- `list`: `"{label}:\n- {item}\n- {item}"; resolved=True → префикс `[x]`;
- empty-поля (single=None или list пуст) попадают в `empty_fields`,
  не в `truncated_fields`.

Эвристика токенов: `math.ceil(len(text) / 4)` — согласована с
`update_mode_executor.py`, `pipeline_executor.py`, `full_document_service.py`.

### effective_context.py — Re-export фасад (Phase 1)

> **Важно:** фактическая сборка контекста выполняется в `app/services/context_engine/assembly.py`.
> Этот модуль — re-export фасад для обратной совместимости с импортами до Phase 1.

```python
# Re-export из context_engine.assembly:
async def compose_full_system_prompt(
    campaign_id, domain_id, db,
    scene_state: dict | None = None,    # Sprint 1: inline scene-state
) -> str
async def compose_full_system_prompt_with_state(
    campaign_id, domain_id, db,
    scene_state: dict | None = None,    # Sprint 1
) -> tuple[str, CampaignStateCompiledBlock | None]
async def compose_state_block_only(campaign_id, db) -> str
async def build_effective_context(campaign_id, chat_id, domain_id, db, *, include_rag=False, rag_hits=None) -> EffectiveContextRead

# Внутри модуля (не из context_engine):
def append_tool_use_rules(prompt: str) -> str
def compose_scene_block(scene_state: dict | None) -> str        # Sprint 1 (Phase 2b: explicit + drift)
```

**Sprint 1 + Phase 2b**: `compose_scene_block` рендерит scene_state в два блока для system_prompt:
- `## Текущая сцена` — под-пространство `explicit` (от `update_scene_state` tool).
- `## Дрейф контекста (авто, может быть ошибочным)` — под-пространство `drift._hints` (от `DriftDetector`, max 8 hints в prompt).

Лимит 4KB; превышение обрезается с WARNING-меткой. Используется в `compose_full_system_prompt`
через параметр `scene_state`.

**Точки интеграции** `compose_full_system_prompt`:

- `app/api/chat.py::plain_stream` (SSE plain RAG fallback);
- `app/api/chat.py::_plain_llm_reply`;
- `app/api/pipeline_resume.py::_plain_rag_stream`;
- `app/services/pipeline_executor.py::PipelineExecutor.resume_from_full_doc_selection` (plain-fallback ветка).

**Sprint 2**: в `plain_stream` перед AgentLoop выполняется `_prefill_rag()` (см. `api/chat.py`).
Результат `[1]...[2]...` подмешивается в `system_prompt` через `format_context(hits)`.

`compose_state_block_only` используется в `PipelineExecutor._run_final_composition`
для добавления state-блока после `_resolve_prompt(...)` без вмешательства в шаблоны
с `{query}`/`{STEP_ID.*}`.

`build_effective_context` используется в debug endpoint
`GET /api/settings/campaigns/{id}/effective-context`.

`append_tool_use_rules` (Stage 8.6) добавляет к legacy-prompt правила вызова `search_knowledge`
(«используй evidence для фактов/лора, не выдумывай»). В Sprint 1 расширен секциями про
`update_scene_state` и `propose_context_update` (Sprint 3). Используется только в agent-loop
пути `plain_stream` (legacy single-shot retrieval не нуждается в этих правилах).

### Context Engine — Phase 1-5 (`app/services/context_engine/`)

Новый модуль, введённый в Phase 1. Ответственности: единая сборка контекста + фоновый drift detection + auto-draft campaign state.

#### `assembly.py` — единая точка сборки

```python
async def build_chat_context(
    campaign_id, domain_id, db,
    scene_state: dict | None = None,
    prefill_evidence: str | None = None,         # Phase 2b prefill RAG (опц.)
) -> str

async def build_chat_context_with_state(
    campaign_id, domain_id, db,
    scene_state: dict | None = None,
    prefill_evidence: str | None = None,
) -> tuple[str, CampaignStateCompiledBlock | None]

async def build_state_block_only(campaign_id, db) -> str
```

Используется во всех путях чат-turn-а (см. effective_context.py — обёртка).

#### `scene_memory.py` — два под-пространства scene_state

```python
def compose_scene_block(scene_state: dict | None) -> str
    # Рендерит explicit + drift hints в system_prompt блок

async def read_scene_state(chat_id, db) -> dict
    # Читает Chat.metadata_json["scene_state"] (default {})

async def merge_explicit(chat_id, patch: dict, db) -> dict
    # Хост-merge patch от update_scene_state tool в scene_state.explicit
    # value=None → удаляет ключ, иначе → присваивает

async def write_drift(chat_id, hints: list[dict], db) -> None
    # Записывает drift hints в scene_state.drift._hints
    # Только DriftDetector имеет право писать в drift

async def clear_drift(chat_id, db) -> None
    # Удаляет scene_state.drift (вызывается из accept/reject draft)
```

Ownership: `agent_loop.py` пишет в `explicit` через `merge_explicit`. `DriftDetector` пишет в `drift` через `write_drift`. Эти под-пространства **никогда не пересекаются** (см. комментарий в `agent_loop.py:567-570`).

#### `drift.py` — DriftDetector (малая локальная модель)

```python
class DriftDetector:
    def __init__(self, db_factory, redis_client): ...

    async def detect(self, chat_id: str) -> list[dict] | None
        # None = пропуск (нет chat.campaign_id, нет active state, нет active model)
        # [] = hints не найдены (или все ниже threshold)
        # list = hints записаны в scene_state.drift._hints

    # Читает:
    #   settings_service.get_active_drift_model(db)
    #   Message.last(N) для chat_id (N = platform_settings.drift.max_messages, default 10)
    #   compile_campaign_state(active version)
    # Провайдеры (по provider name):
    #   host_sidecar → HostSidecarDriftProvider → POST pdf-sidecar:8765/drift
    #   openai_compatible → OpenAICompatibleDriftProvider
```

#### `draft.py` — CampaignStateDrafter (большая модель)

```python
class CampaignStateDrafter:
    def __init__(self, db_factory, redis_client, generation_provider_factory): ...

    async def plan_draft(self, chat_id: str) -> dict | None
        # None = пропуск (нет chat.campaign_id, нет hints, generation failed)
        # dict = ContextDraft сохранён в Redis `draft:campaign:{cid}:chat:{chatid}` TTL 10800
```

Lifecycle:
1. Прочитать drift hints из `scene_state.drift._hints`.
2. `hash_hints(hints)` → `drift_hash` (sha256[:16]).
3. Если Redis draft существует и `drift_hash` совпадает → skip (нет изменений).
4. Получить active state + последние N сообщений.
5. Вызвать `provider.generate_json(system+user)` с system prompt:
   ```
   You are a Campaign State drafter. Allowed operations:
   - replace_single / clear_single
   - add_list_item / update_list_item / resolve_list_item / remove_list_item
   Output: {"state_patch": [...], "summary": "..."}.
   NO schema changes (create_field / update_field). NO file_changes.
   ```
6. Фильтрация ops по whitelist `_ALLOWED_OP_TYPES`.
7. `SETEX draft:campaign:{cid}:chat:{chatid} 10800 <json>`.

#### `loop.py` — DriftLoop (cooldown + idle scan)

```python
class DriftLoop:
    def __init__(self, detector: DriftDetector, redis: aioredis.Redis): ...

    async def trigger_for_chat(chat_id: str) -> None
        # Redis SETNX "drift:cooldown:{chat_id}" EX 30
        # Если уже acquired → skip
        # Иначе SADD "drift:dirty" {chat_id} + asyncio.create_task(_run_detect)

    async def run_idle_scan(self) -> None
        # Каждые 60 сек: SMEMBERS "drift:dirty" → trigger_for_chat для каждого
```

Trigger points (откуда вызывается `trigger_for_chat`):
- `app/api/chat.py:1130-1135` — после финального SSE event в `plain_stream`.
- `app/api/chat.py:1275-1290` — legacy single-shot путь.

Wiring (lifespan, `app/main.py:72-89`):
```python
drift_detector = DriftDetector(db_factory=SessionLocal, redis_client=redis_client)
drift_loop = DriftLoop(detector=drift_detector, redis=redis_client)
drafter = CampaignStateDrafter(...)
drift_loop.drafter = drafter
app.state.drift_loop = drift_loop
app.state.drafter = drafter
drift_loop._idle_task = asyncio.create_task(drift_loop.run_idle_scan())
```

### api/context_draft.py — Public API для draft

```python
GET    /api/chats/{chat_id}/context-draft
POST   /api/chats/{chat_id}/context-draft/accept
POST   /api/chats/{chat_id}/context-draft/reject
POST   /api/chats/{chat_id}/context-draft/check-files
```

Accept/reject/check-files пишут AuditLog и (для check-files) создают Update Mode session с `state_patch_context` (Phase 5).

### providers/drift/ — DriftProvider интерфейс

```python
# base.py
class DriftProvider(ABC):
    async def detect_drift(
        *, messages: list[dict], current_state: str, schema_hint: str | None
    ) -> list[dict]: ...

class DriftUnavailableError(Exception): ...
class DriftInvalidResponseError(Exception): ...

# host_sidecar.py (default)
class HostSidecarDriftProvider(DriftProvider):
    base_url: str       # http://host.docker.internal:8765
    model_name: str     # qvikhr-3-1.7b-instruct-noreasoning-q4_k_m
    timeout_seconds: int

# openai_compatible.py
class OpenAICompatibleDriftProvider(DriftProvider):
    base_url, model_name, api_key, timeout_seconds
```

CRUD drift-моделей встроен в `app/services/settings_service.py:395-470`, **не вынесен** в отдельный `drift_model_service.py` (см. отклонение от первоначального плана в `context/context-engine.md`).

### campaign_state_initial_service.py — Initial State (Stage 3)

```python
async def preview(campaign_id, document_ids: list[str], db) -> CampaignStateInitialProposalRead
    # Снимок DocumentSnapshot'ов + LLM-proposal + Redis-сессия (TTL 3h)
async def get_proposal(campaign_id, db) -> CampaignStateInitialProposalRead | None
async def apply(campaign_id, proposal_id, config_version, db, *, actor) -> CampaignStateVersionRead
    # 1.5: cascade-purge потерянных enabled-полей, если config изменился;
    #      пересоздание активной версии при изменении конфигурации полей;
    #      проверка source_snapshot (md5), иначе 409 source_snapshot_stale
```

Поддерживает `needs_clarification` (поле обязано содержать `clarification_question`) и `empty` статусы.
Только Markdown-документы кампании (никаких PDF).

### campaign_state_initial_store.py — Redis-сессия proposal

```python
SESSION_TTL_SECONDS = 3 * 60 * 60
key = f"campaign_state_initial:{campaign_id}"

async def save(campaign_id, proposal_read, redis)
async def load(campaign_id, redis) -> CampaignStateInitialProposalRead | None
async def delete(campaign_id, redis)
```

### campaign_state_stale_service.py — Potentially Stale (Stage 7)

```python
async def compute_stale_status(campaign_id, db) -> CampaignStateStaleStatus
    # На лету: для всех source_ref формата "file:<doc_id>:sha:<sha>" активной версии
    # проверяет Document.md5 и Document.status; возвращает список stale_documents.
async def record_transition(campaign_id, prev_stale, curr_stale, db, *, actor)
    # Пишет AuditLog при переходе false → true
```

`prev_stale` хранится в Redis-ключе `campaign:{id}:prev_stale`. Audit-лог пишется только на
переходе `false → true` — идемпотентно на повторных проверках.

---

## update_mode_executor.py — Campaign Update Mode

Основной оркестратор Update Mode. Каждый запуск: retrieval → LLM edit intents + state_patch → resolve.

```python
class UpdateModeExecutor:
    async def start(chat_id, redis, note, db) -> UpdateModeSession           # legacy: пользователь явно
    async def start_from_proposal(chat_id, redis, proposal, db) -> UpdateModeSession   # Sprint 3: model-driven
    async def get_session(chat_id, db) -> UpdateModeSession | None
    async def review(chat_id, decisions, db) -> UpdateModeSession
    async def apply(chat_id, apply_id, db) -> ApplyUpdateModeResponse
    async def cancel(chat_id, db) -> None
```

### Алгоритм `start()`

1. Сбор Markdown-документов кампании: `_get_campaign_tag_ids()` → `get_campaign_markdown_document_ids()`
2. `_build_context_documents()` — читает содержимое, ограничивает per-doc
3. `_generate_intents_and_state_patch()` — единый LLM-вызов возвращает `UpdateModeGenerationResult`
   с `intents`, `no_change_reason?`, `state_patch`, `state_patch_questions`
4. `_validate_state_patch_against_snapshot()` — проверяет соответствие `state_field_snapshot` активной кампании
5. `build_state_patch_entries()` — формирует `UpdateModeStatePatchEntry` (стабильный op_index, label, mode)
6. Resolve в indexer (`IndexerClient.resolve_update_mode`) — SHA-256, unified_diff, proposed_content
7. Сохраняет Redis-сессию через `update_mode_store`

### Алгоритм `start_from_proposal()` (Sprint 3)

Идентичен `start()` по шагам 1-7, но шаги 2-3 заменены на:
- принимает уже структурированный `ContextUpdateProposal` (от `propose_context_update` tool);
- `_validate_field_changes()` — валидирует schema-операции (regex key, mode immutability, conflict со snapshot);
- `_filter_state_patch_by_pending_field_changes()` — кросс-валидация: state_patch может ссылаться на field_key, создаваемый в этом же proposal;
- `build_field_change_entries()` — формирует `UpdateModeStateFieldChangeEntry` для каждой schema-операции.

### `apply()` (Sprint 3: трёхстадийный apply)

1. **Stage A — schema** (Sprint 3, новый): для принятых `field_change_decisions` вызывает `_apply_schema_changes()` —
   атомарное `create_field` / `update_field` через `campaign_state_field_service`. При failure →
   rollback созданных полей + abort всего apply (HTTP 422, audit `update_mode.apply_aborted_schema`).
2. **Stage B — state**: `apply_patch` через `campaign_state_value_service` (как раньше).
3. **Stage C — files**: CAS-проверка через `IndexerClient.apply_update_mode` (SHA-256 первого op).
4. AuditLog `update_mode.apply` с commit SHA, `state_patch_result` и `field_changes_result`.

Все ошибки — структурированные `error_code` (`file_modified`, `vault_lock_timeout`,
`apply_already_started`, `apply_id_payload_mismatch`, `apply_in_progress`,
`state_patch_conflict`, `schema_apply_failed` (Sprint 3) и др.).

---

## update_mode_store.py — Redis-сессии Update Mode

```python
SESSION_TTL_SECONDS = 3 * 60 * 60
key = f"update_mode:{chat_id}"

class UpdateModeStore:
    async def create_session(...)
    async def get_session(...)
    async def review_session(...,
                              accepted_change_ids, rejected_change_ids,
                              accepted_state_op_indexes, rejected_state_op_indexes,
                              edited_state_ops,
                              # Sprint 3:
                              accepted_field_op_indexes, rejected_field_op_indexes)
    async def begin_apply(apply_id)
    async def complete_apply(apply_id, apply_response, state_patch_result)
    async def cancel_session(...)
```

Атомарность достигается через Lua-скрипты:

| Lua | Назначение |
|---|---|
| `_REVIEW_LUA` | Атомарное обновление статуса change-ов + state_patch decisions (accepted/rejected indexes + edited text) + **Sprint 3**: field_change decisions (ARGV[7]/ARGV[8] для `accepted_field_op_indexes` / `rejected_field_op_indexes`) |
| `_APPLY_BEGIN_LUA` | Захват apply lock по apply_id; проверка payload fingerprint |
| `_APPLY_COMPLETE_LUA` | Перевод `in_progress → completed` с записью response |

`_LUA_FIX_ARRAYS()` — helper, перекодирующий пустые Lua-таблицы в `cjson.empty_array_mt`
для top-level list-полей сессии: `warnings`, `vault_ids`, `candidate_document_ids`,
`changes`, `state_patch_operations`, `state_field_snapshot`, **`state_field_change_operations`** (Sprint 3).

`_normalize_session_lists()` поддерживает те же list-поля в session payload, в т.ч.
`state_field_change_operations` (Sprint 3).

`_parse_review_result()` маппит error-строки Lua в типизированные исключения:
- `ERR:session_expired` → `SessionExpiredError`
- `ERR:unknown_state_op:N` → `UnknownStateOpIndexError`
- `ERR:state_op_review_conflict:N` → `StateOpReviewConflictError`
- **`ERR:unknown_field_change_op:N`** → `UnknownFieldChangeOpIndexError` (Sprint 3)
- **`ERR:field_change_review_conflict:N`** → `FieldChangeReviewConflictError` (Sprint 3)

---

## agent_loop.py — Bounded LLM ↔ tool cycle (Stage 8.4 + Sprint 1/3)

```python
SEARCH_KNOWLEDGE_TOOL: LLMToolDefinition       # tool-схема name="search_knowledge" (Stage 8.4)
UPDATE_SCENE_STATE_TOOL: LLMToolDefinition    # Sprint 1: name="update_scene_state"
PROPOSE_CONTEXT_UPDATE_TOOL: LLMToolDefinition  # Sprint 3: name="propose_context_update"
PROPOSAL_MIN_CONFIDENCE = 0.5                   # Sprint 3: min confidence для accept proposal

@dataclass(slots=True)
class AgentEvent:
    type: 'round_start' | 'tool_call' | 'tool_result' | 'token' | 'round_end' | 'final' | 'error'
    round: int = 0
    payload: dict = {}

class AgentLoop:
    async def run_stream(*,
                          provider, system_prompt, history, user_message,
                          domain_id, campaign_id, chat_id=None,
                          vault_ids, max_rounds, evidence_token_budget,
                          policy, db,
                          context_update_mode_enabled=False,    # Sprint 3
                          redis=None,                             # Sprint 3
                          audit: AuditContext) -> AsyncIterator[AgentEvent]
```

### Tools (Sprint 1 + Sprint 3)

`AgentLoop.run_stream` регистрирует до 3 tool definitions в `tools`:

- `SEARCH_KNOWLEDGE_TOOL` — всегда (Stage 8.4).
- `UPDATE_SCENE_STATE_TOOL` — всегда (Sprint 1).
- `PROPOSE_CONTEXT_UPDATE_TOOL` — только при `context_update_mode_enabled=True` AND `campaign_id is not None` AND `redis is not None` (Sprint 3).

### Контракт цикла (spec §12.2 + Sprint 1)

- Round 0 (`grounded`): `tool_choice='required'` (Sprint 1) — модель ОБЯЗАНА вызвать хотя бы один tool.
- Round 0 (`assistive`) или round N (1 ≤ N < max_rounds, кроме последнего grounded): `tool_choice='auto'`.
- Final round: `tool_choice='none'` — модель ОБЯЗАНА выдать текстовый ответ.
- Повторный нормализованный query → пустой tool_result с `note='duplicate_query'`.
- Если модель вернула только `tool_calls` без текста — продолжаем. Если есть текст — стримим и выходим.

### Tool execution (host-controlled)

- `search_knowledge` → `SearchKnowledgeService.run()` (см. ниже).
- `update_scene_state` → `_execute_update_scene_state(chat_id, patch, db)` — host мерджит patch в `Chat.metadata['scene_state']` и коммитит. **Без review, без audit.** `_SCENE_STATE_PATCH_MAX_KEYS = 16` (защита от спама).
- `propose_context_update` → `_execute_propose_context_update(chat_id, campaign_id, db, redis, proposal_dict)` — host валидирует (regex key, mode immutability, confidence ≥ 0.5) и создаёт Update Mode session через `UpdateModeExecutor.start_from_proposal()`. **С обязательным user review.**

### Sources flow (tool path)

Каждый `tool_result` event содержит в payload поле `sources: list[Source]` —
дедуплицированный список источников (`hits_to_sources` с `cap=MAX_SOURCES_PER_TOOL_RESULT=50`).
Чат-слой (`chat.py::plain_stream`) аккумулирует их в `all_sources: list[Source]`,
дедуплицирует и эмитит **один** финальный `sources` SSE event с
`grouped_by_step: false` после завершения `final` event'а.
Те же источники персистятся в `Message.sources` через `_save_partial_answer(sources=...)`.

`final` event содержит `rounds: list[AgentRoundResult]` где у каждого round
есть поле `sources: list[MessageSource]` (для audit).

`round_start` event payload: `{max_rounds, policy, phase, effective_grounded, tool_choice}`.
`phase` ∈ `"initial" | "followup" | "final"`:
- `initial` — round 0 + `tool_choice=required` (forced grounded: модель ОБЯЗАНА сначала позвать search_knowledge)
- `followup` — все промежуточные раунды (tool_choice=auto)
- `final` — последний раунд (tool_choice=none: модель должна дать ответ)
Чат-слой (`chat.py::plain_stream`) транслирует `phase` в человеко-читаемый
`step_status` («Ищу информацию в базе знаний…» / «Думаю над ответом…» / «Готовлю финальный ответ…»).

### Подключение в `chat.py` (Stage 8.5 + Sprint 2)

`plain_stream` имеет три ветки (Sprint 2):

1. **Prefill RAG** (Sprint 2): при `policy==grounded` и `campaign_id` — вызов `_prefill_rag()` ДО AgentLoop.
   `queries` берутся из `QueryRewriter.build_search_queries` (с RU-переводом при EN).
   Результат `[1]...[2]...` подмешивается в `system_prompt`. SSE event `prefill_rag` с `queries_used` + `has_evidence`.
2. **legacy**: `tool_enabled=False` → `provider.generate_stream()` без tool schema
   (правила вызова приклеиваются через `effective_context.append_tool_use_rules`)
3. **tool path**: `tool_enabled=True` → `AgentLoop.run_stream()` с
   `SEARCH_KNOWLEDGE_TOOL` (+ `UPDATE_SCENE_STATE_TOOL` + `PROPOSE_CONTEXT_UPDATE_TOOL` если `context_update_mode_enabled=True`),
   `RetrievalPolicy` и round-лимитом из `RetrievalToolSettings`.

SSE events новые (Sprint 1-3):
- `prefill_rag` — после prefill retrieval (queries_used, has_evidence)
- `context_update_proposal` — после успешного create Update Mode session (session_id, counts)

Audit-row `chat.agent_loop` пишется на каждом чат-турне tool-пути (Stage 8.7):
`payload` содержит `rounds`, `tool_calls_made`, `policy`.

---

## search_knowledge_service.py — `search_knowledge` host (Stage 8.3)

```python
search_knowledge_service = SearchKnowledgeService()   # синглтон

async def search(
    queries: list[str],
    reason: str,
    campaign_id: str | None,
    domain_id: str,
    db,
) -> SearchKnowledgeResult
```

### Алгоритм

1. Нормализация и дедупликация queries (`re.sub(r"\s+", " ", q).strip().lower()`)
2. Резолюция тегов активной кампании: `get_allowed_tag_ids(domain_id, campaign_id, db)`
3. Если `campaign_id` задан и тегов нет → возвращает `scope='empty'` (НЕ расширяется на домен — spec §12)
4. Если нет enabled-vault → `scope='no_vault'`
5. Параллельный запуск каждого query через `retrieve_multi_vault`
6. Merge + rerank + truncate to `evidence_token_budget`

Scope фиксируется хостом — модель не может расширить или сузить его.

---

## retrieval_tool_settings.py — Typed accessor (Stage 8.2)

```python
KEY_TOOL_ENABLED          = "retrieval.tool_enabled"
KEY_POLICY                = "retrieval.policy"
KEY_MAX_ROUNDS_GROUNDED   = "retrieval.max_rounds_chat"
KEY_MAX_ROUNDS_ASSISTIVE  = "retrieval.max_rounds_assistive"
KEY_EVIDENCE_TOKEN_BUDGET = "retrieval.evidence_token_budget"

@dataclass(slots=True, frozen=True)
class RetrievalToolSettings:
    tool_enabled: bool
    policy: RetrievalPolicy
    max_rounds_grounded: int
    max_rounds_assistive: int
    evidence_token_budget: int

    @property
    def max_rounds(self) -> int:  # round cap для активной policy

async def load_retrieval_tool_settings(db) -> RetrievalToolSettings
```

Безопасные дефолты, если PlatformSetting-строка удалена: `tool_enabled=True`,
`policy='grounded'`, `max_rounds_grounded=2`, `max_rounds_assistive=1`,
`evidence_token_budget=6000` (bumped в 0012 для grounded agent-assistant).

---

## settings_service.py, vault_config_service.py, prompt_pack.py

`settings_service.py` — единая точка CRUD platform settings, провайдеров, моделей,
включая `retrieval.*` ключи (Stage 8.2).

`vault_config_service.py` — read-cache `VaultConfig` (snapshot из БД для indexer):
содержит `embedding_model_id`, `chunk_size`, `git_author_*` и др.

`prompt_pack.py` — загрузка/форматирование доменных промптов; `resolve_step_vars(template, step_results)`
для подстановки `{STEP_ID.result}` и `{STEP_ID.key}` в `PipelineExecutionContext.resolve()`.

---

## Главный поток запроса (chat-путь)

```
HTTP POST /chat/send_stream
    │
    ├─ Planner.decide()
    │       ├─ retrieval_strategy?
    │       └─ clarification_needed? → ClarificationFSM
    │
    ├─ [если clarification] → FSM.process_clarification_answer() → вернуть вопрос
    │
    ├─ QueryRewriter.rewrite()              ← история чата
    │
    ├─ effective_context.compose_full_system_prompt() ← Stage 6: system_prompt + Campaign State
    │
    ├─ tool_enabled?
    │     ├─ False → legacy path:
    │     │     append_tool_use_rules(prompt)  ← Stage 8.6
    │     │     provider.generate_stream()
    │     │
    │     └─ True → tool path:
    │           AgentLoop.run_stream()
    │             ├─ provider.generate_stream_with_tools()   ← Stage 8.1
    │             │     Round 0..N-1: tool_choice='auto'
    │             │     Final round: tool_choice='none'
    │             ├─ [tool_calls] search_knowledge_service.search()
    │             │     dedupe → retrieve_multi_vault → rerank → truncate
    │             └─ AuditLog chat.agent_loop (Stage 8.7)
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
    │       └─ FinalComposition (+ Campaign State block через compose_state_block_only) → LLM stream
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