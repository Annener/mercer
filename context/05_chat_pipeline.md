# 05 — Chat API, shared_contracts, Pipeline Router & Executor

> Шаг 5 из 5. Покрывает: `api/chat.py`, `shared_contracts/models.py`,
> `services/pipeline_router.py`, `services/pipeline_executor.py`.
> Читать после `04_infra.md`.

---

## Содержание

1. [shared_contracts/models.py — ключевые типы](#1-shared_contractsmodelspy)
2. [api/chat.py — структура и эндпоинты](#2-apichatpy)
3. [Жизненный цикл сообщения (send / send_stream)](#3-жизненный-цикл-сообщения)
4. [PipelineRouter — логика выбора пайплайна](#4-pipelinerouter)
5. [PipelineExecutor — логика исполнения](#5-pipelineexecutor)
6. [Ключевые нюансы и исправленные баги](#6-ключевые-нюансы-и-баги)

---

## 1. shared_contracts/models.py

Файл содержит **все Pydantic-контракты**, которыми обмениваются сервисы.
Отдельного комментария заслуживают модели, связанные с чатом и пайплайном.

### ORMModel — базовый класс

```python
class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode='before')
    @classmethod
    def _coerce_uuid_fields(cls, data):
        ...
```

- `from_attributes=True` — разрешает создавать модель из ORM-объекта.
- `_coerce_uuid_fields` — автоматически конвертирует `uuid.UUID` → `str` для str-полей.
- **Пропускает list-поля** (relationships): `getattr` на ленивый relationship в async-контексте
  вызывает `MissingGreenlet`. Поэтому `tags`, `chats` и т.п. подставляются **вручную** в роуте.

### Главные типы цепочки чат → пайплайн

| Модель | Назначение | Ключевые поля |
|---|---|---|
| `CreateChatRequest` | Тело POST /chat/create | `domain_id: str \| None`, `vault_id`, `campaign_id` |
| `CreateChatResponse` | Ответ /chat/create | `chat_id`, `title` |
| `SendMessageRequest` | Тело POST /send и /send_stream | `content: str`, `stream: bool = True` |
| `ChatMessage` | Одно сообщение в истории | `message_id`, `role`, `content`, `created_at`, `pipeline_id` |
| `ChatRecord` | ORM → JSON чат | `id`, `title`, `vault_id`, `domain_id`, `campaign_id`, даты |
| `PipelineStep` | Один шаг пайплайна | `order`, `type` (retrieval/final), `name`, `system_prompt`, `top_k`, `tag_ids`, `is_final` |
| `FinalComposition` | Финальный промпт пайплайна | `system_prompt` |
| `PipelineRead` | Полное описание пайплайна (ORM→JSON) | `pipeline_id`, `domain_id`, `campaign_id`, `version`, `steps`, `final_composition` |
| `PipelineExecutionContext` | Контекст запуска пайплайна | см. ниже |
| `PipelineResult` | Результат (non-stream) | `final_answer`, `steps`, `error` |

### PipelineExecutionContext — центральный объект

```python
class PipelineExecutionContext(BaseModel):
    chat_id: str
    message_id: str
    query: str
    domain_id: str | None = None
    campaign_id: str | None = None
    vault_ids: list[str] = Field(default_factory=list)
    vault_id: str | None = None          # deprecated back-compat
    # Заполняются ПОСЛЕ pipeline_router.select():
    pipeline_id: str | None = None
    pipeline_version: str | None = None
    steps: list[PipelineStep] | None = None
    final_composition: FinalComposition | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_strategy: str | None = None
    confidence: float | None = None
    reasoning: str | None = None
    mode: str | None = None
```

**Важно**: объект создаётся ДО выбора пайплайна — поля `pipeline_id`, `steps`,
`final_composition` в момент создания `None`. `PipelineRouter.select()` дописывает их
напрямую (мутирует объект). `PipelineExecutor` обязан проверить что они заполнены.

### Дублирование CreateChatRequest

В репозитории **два** определения `CreateChatRequest`:
- `shared_contracts/models.py` — `domain_id: str | None = None` (опциональный, back-compat)
- `api/chat.py` — `domain_id: str` (обязательный, локальное переопределение)

ФастAPI при парсинге тела запроса использует **локальный** класс из `chat.py` (он объявлен в том
же файле и импортируется раньше). Если `domain_id` не передан — 422. Это намеренный инвариант
(комментарий `# A05 fix`).

---

## 2. api/chat.py — структура и эндпоинты

### Инициализация на уровне модуля

```python
router = APIRouter(prefix="/chat", tags=["chat"])
config_for_vault = VaultConfigService()   # синглтон-like объект для vault-конфига
```

`VaultConfigService` читается один раз при импорте — не per-request. Содержит `.vaults` —
словарь `vault_id → VaultConfigEntry`. Используется в `send_message` и `send_message_stream`
для формирования `vault_ids` по `domain_id`.

### Список эндпоинтов

| Метод | Путь | Описание |
|---|---|---|
| POST | `/chat/create` | Создать чат. Принимает `domain_id` (обязательный), `vault_id`, `campaign_id`. |
| GET | `/chat/list` | Список чатов. Фильтр `?domain_id=`. N+1 fix: vault_enabled через кеш. |
| GET | `/chat/{chat_id}/history` | История + метаданные чата. |
| POST | `/chat/{chat_id}/rename` | Переименовать чат. |
| DELETE | `/chat/{chat_id}` | Удалить чат (204). |
| POST | `/chat/{chat_id}/lock_pipeline` | Зафиксировать пайплайн для чата. |
| POST | `/chat/{chat_id}/send` | Отправить сообщение (non-stream). |
| POST | `/chat/{chat_id}/send_stream` | Отправить сообщение (SSE stream). |
| POST | `/chat/{chat_id}/clarify` | Принять ответы на уточняющие вопросы. |

### Создание чата (POST /chat/create)

```python
chat = Chat(
    title="New Chat",
    vault_id=req.vault_id,
    domain_id=req.domain_id,
    campaign_id=campaign_uuid,
    pipeline_versions=await _pipeline_versions(request),
)
db.add(chat)
await db.flush()                                     # генерируем chat.id без commit
db.add(ClarificationStateRow(chat_id=chat.id, stage="idle"))  # FSM-запись сразу
await _audit(db, "chat.create", ...)
await db.commit()
```

- `ClarificationStateRow` создаётся вместе с чатом (один `flush` + один `commit`).
- `_pipeline_versions(request)` — читает заголовки `X-Pipeline-*` для трассировки.
- `campaign_id` парсится в `uuid.UUID`; невалидный формат → 422.

### Список чатов — N+1 fix (GET /chat/list)

Старый код вызывал `await _vault_enabled(db, vault_id)` для каждого чата в list comprehension.
Fix:

```python
unique_vault_ids = {c.vault_id for c in chats if c.vault_id}
vault_enabled_cache = {None: False}
if unique_vault_ids:
    retrieval_enabled = await settings_service.get("retrieval.enabled", db)  # один запрос
    for vid in unique_vault_ids:
        vault_enabled_cache[vid] = retrieval_enabled
```

---

## 3. Жизненный цикл сообщения

### send (non-stream) — POST `/{chat_id}/send`

```
1. _get_chat_or_404(chat_id)               — проверить чат
2. Message(role="user") → db.flush()       — сохранить запрос пользователя
3. _domain_id_for_chat()                   — определить domain_id (chat → campaign fallback)
4. vault_ids из VaultConfigService         — enabled Vaults домена
5. retrieval_strategy                      — "semantic" если vault + enabled, иначе "none"
6. PipelineExecutionContext(...)           — создать без pipeline_id/steps
7. PipelineRouter(db).select(context)      — выбрать пайплайн (мутирует context)
8. history (limit 20) → context.history   — добавить историю
9. PipelineExecutor(db).run(context)       — запустить, получить _ExecutionResult
10. Message(role="assistant") → db.commit  — сохранить ответ
11. _auto_title() если title == "New Chat" — автозаголовок
12. return MessageResponse(content, message_id)
```

### send_stream (SSE) — POST `/{chat_id}/send_stream`

Шаги 1-8 — **идентичны** non-stream. Разница начинается с шага 9:

```python
async def event_stream() -> AsyncIterator[str]:
    executor = PipelineExecutor(db)
    full_answer = ""
    async for chunk in executor.run_stream(context):
        if chunk.get("type") == "delta":
            chunk = {**chunk, "type": "token"}      # нормализация delta→token
        data = json.dumps(chunk, ensure_ascii=False)
        yield f"data: {data}\n\n"
        if chunk.get("type") == "token":
            full_answer += chunk.get("content", "")
    # После стрима — сохранить сообщение:
    if full_answer:
        db.add(Message(role="assistant", content=full_answer, ...))
        await db.commit()
    yield "data: [DONE]\n\n"

return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**SSE-формат чанков** от executor:

| type | Поля | Когда |
|---|---|---|
| `pipeline_selected` | `pipeline_id`, `pipeline_name`, `reasoning`, `mode` | Начало |
| `progress` | `step`, `total`, `step_name` | Перед каждым шагом |
| `step_done` | `step`, `step_name`, `partial_length` | После шага (есть хиты) |
| `step_skipped_no_docs` | `step`, `step_name` | Шаг пропущен (нет документов) |
| `token` | `content` | Финальный стрим токенов |
| `sources` | `step_groups[{step, step_name, sources}]` | После финального LLM |
| `error` | `message` | Ошибка |

**Нюанс**: если `chunk.type == "delta"` (старый формат от некоторых LLM), роут нормализует
его в `"token"`. Фронтенд должен обрабатывать только `"token"`.

### _domain_id_for_chat — приоритет

```python
async def _domain_id_for_chat(chat, db):
    if chat.domain_id:                         # 1. прямое поле чата
        return chat.domain_id
    if chat.campaign_id:                       # 2. через кампанию
        campaign = await db.get(Campaign, chat.campaign_id)
        if campaign and campaign.domain_id:
            return campaign.domain_id
    return None                                # 3. нет домена
```

Результат: `domain_id = await _domain_id_for_chat(chat, db) or chat.domain_id`.
Back-compat: если в чате нет `domain_id`, но есть `campaign_id`, domain берётся из кампании.

---

## 4. PipelineRouter

Файл: `services/pipeline_router.py`.

### Принцип работы

```
select(context, locked_pipeline_id)
  ↓
  Если locked_pipeline_id:
    → pipeline_service.get_pipeline(locked_pipeline_id)
    → mode-проверка (campaign pipeline не течёт в general mode)
    → return pipeline  (confidence=1.0, reasoning="locked by user")
  ↓
  Иначе:
    → pipeline_service.get_active_pipelines(domain_id)
    → фильтр по mode (general / campaign)
    → LLM: prompt с JSON-ответом {pipeline_id, confidence, reasoning}
    → confidence < 0.5 → return None
    → return selected pipeline
```

### Промпт маршрутизатора

```python
PROMPT_TEMPLATE = """
Ты — маршрутизатор запросов для домена "{domain_id}".
Доступные pipelines: {pipelines_list}
Query: "{query}"
История (3 посл.): {chat_history}
Верни ТОЛЬКО JSON: {"pipeline_id": "...", "confidence": 0.0-1.0, "reasoning": "..."}
"""
```

Промпт можно переопределить через доменный промпт типа `pipeline_router`
(`domain_service.get_prompt(domain_id, "pipeline_router", db)`).

### Фильтрация кандидатов по режиму

```python
if campaign_id:
    # campaign mode: campaign-specific + general (fallback)
    candidates = [p for p in all_pipelines
                  if p.campaign_id is None or str(p.campaign_id) == campaign_uuid]
else:
    # general mode: только общие пайплайны домена
    candidates = [p for p in all_pipelines if p.campaign_id is None]
```

### Mode-validation для locked pipeline

| Ситуация | Поведение |
|---|---|---|
| Locked — campaign-specific, mode=general | WARNING + игнорируем lock, переходим к LLM-выбору |
| Locked — general, mode=campaign | Разрешаем (fallback) |
| Locked — совпадает с режимом | Используем без вопросов |

### Legacy: decide()

Старый метод `decide(query, chat, db)` принимает ORM-объект `Chat` напрямую.
Оставлен для обратной совместимости (тесты). В production chat.py использует `select()`.

### BUG-1 fix

```python
def __init__(self, db: AsyncSession) -> None:
    self.db = db  # BUG-1: раньше db не сохранялся, select() падал без явной передачи db
```

### Singleton-заглушка

```python
pipeline_router = PipelineRouter.__new__(PipelineRouter)
```

`__new__` без `__init__` — объект без `self.db`. Используется только если нужен
импорт самого класса (не инстанца) в других модулях. Не использовать для реальных вызовов.

---

## 5. PipelineExecutor

Файл: `services/pipeline_executor.py`.

### Структура класса

```
PipelineExecutor
  __init__(db)                          — сохраняет db
  run(context)         → _ExecutionResult    — non-stream, /send
  run_stream(context)  → AsyncIterator[dict] — SSE, /send_stream
  _execute(pipeline, query, chat_context, db, request)
                       → AsyncGenerator     — общий генератор
  _run_step(index, step, query, ctx, db, provider)
                       → (index, step, hits, partial|_SKIPPED)
  _retrieve_for_step(query, step, ctx, db)
                       → list[SearchHit]
  _check_cancelled(request)
  _mark_started / _mark_completed(ctx, db)
  _gather_sources_for_step(hits)
```

### _execute — главный генератор (упрощённо)

```python
1. yield {type: "pipeline_selected", ...}
2. steps = sorted(pipeline.steps, key=lambda s: s.order)
3. provider = settings_service.get_active_provider()
4. yield {type: "progress", ...} для каждого шага
5. tasks = [_run_step(i, step, ...) for i, step in enumerate(steps)]
6. step_results = await asyncio.gather(*tasks)   # параллельно!
7. for index, step, hits, partial in step_results:
       if partial is _SKIPPED: yield {type: "step_skipped_no_docs"}
       else: yield {type: "step_done"}
8. combined_context = "\n\n---\n\n".join(filter(None, partial_results))
9. final_prompt = format_prompt(pipeline.final_composition.system_prompt, {context, collected_fields})
10. async for token in provider.generate_stream([system, user]):
        yield {type: "token", content: token}
11. yield {type: "sources", step_groups: [...]}
12. _mark_completed()
```

**Ключевое**: шаги ретривала и промежуточных LLM-запросов выполняются
`asyncio.gather` — **параллельно**. Финальный `generate_stream` — стримится.

### _run_step — один шаг пайплайна

```python
hits = await _retrieve_for_step(query, step, chat_context, db)
if not hits:
    return index, step, hits, _SKIPPED          # sentinel, не строка

context_block = format_context_with_role(hits, step.role)
prompt = format_prompt(step.system_prompt, {context: context_block, query: query})
partial = await provider.generate([system, user])  # не стрим — полный ответ
return index, step, hits, partial
```

### _retrieve_for_step — логика ретривала

```
1. top_k = step.top_k или retrieval.top_k из settings
2. vault_ids = chat_context["vault_ids"]   (не legacy vault_id!)
3. Если step.tag_ids:
   - get_allowed_tag_ids(domain_id, campaign_id, db)
   - intersect с step.tag_ids
   - get_document_ids_by_tags(effective_tag_ids, domain_id, db)
   - если document_ids == [] → return []  (пропуск шага)
4. Если нет vault_ids → return [] (WARNING)
5. len(vault_ids) == 1 → retrieve()
   len(vault_ids) > 1  → retrieve_multi_vault()
```

### _pipeline_from_context — восстановление PipelineRead

```python
def _pipeline_from_context(context: PipelineExecutionContext) -> PipelineRead:
    return PipelineRead(
        id="",                                    # stub
        pipeline_id=context.pipeline_id,
        domain_id=context.domain_id or "default",
        version=context.pipeline_version or "0",
        name=context.pipeline_id or "unknown",
        steps=context.steps or [],
        final_composition=context.final_composition,
        campaign_id=context.campaign_id,
    )
```

Нужен, т.к. `_execute` принимает `PipelineRead`, а не `PipelineExecutionContext`.
`id=""` — заглушка (PK не нужен на этапе исполнения).

### BUG-2 fix

```python
def __init__(self, db: AsyncSession) -> None:
    self.db = db  # BUG-2: раньше db брался из context, но его там нет
```

### _SKIPPED sentinel

```python
_SKIPPED = object()
```

Используется вместо пустой строки или None, чтобы различать «шаг вернул пустую строку»
и «шаг был пропущен». В `_execute` проверяется `if partial is _SKIPPED`.

---

## 6. Ключевые нюансы и баги

### N-01 — два CreateChatRequest

В `chat.py` объявлен **локальный** `CreateChatRequest` с `domain_id: str` (обязательным).
В `shared_contracts` — `domain_id: str | None`. FastAPI использует локальный.
Если фронтенд передаёт `domain_id: null` — 422 (а не тихий `None`).

### N-02 — stream: bool в SendMessageRequest

```python
class SendMessageRequest(BaseModel):
    content: str
    stream: bool = True
```

Поле `stream` существует в модели — не вызывает ошибку валидации.
Эндпоинты `/send` и `/send_stream` различаются **путём**, а не этим полем.
Фронтенд маршрутизирует сам (api.js выбирает нужный URL).

### N-03 — параллельные шаги пайплайна

Все шаги (retrieval + intermediate LLM) выполняются `asyncio.gather` — **одновременно**.
Если шаги зависят друг от друга (выход одного → вход другого) — это **не поддерживается**
текущей архитектурой. Шаги независимы по дизайну.

### N-04 — confidence < 0.5 → None

Если LLM вернул пайплайн с `confidence < 0.5` — `PipelineRouter.select()` возвращает `None`.
В `chat.py` это приводит к 503:
```python
if pipeline is None:
    raise HTTPException(503, "No active pipeline found for this domain")
```

### N-05 — _mark_started/completed мутируют pipeline_versions

```python
# В chat.pipeline_versions хранится JSON:
{"last_used": {"pipeline_id": "...", "version": "...", "started_at": "...", "completed_at": "..."}}
```

Два `db.commit()` на одно сообщение: при старте и при завершении. При stream — ещё один после
сохранения assistant-сообщения. Итого до 3 commit на одно send_stream.

### N-06 — singleton-заглушки

```python
pipeline_router = PipelineRouter.__new__(PipelineRouter)
pipeline_executor = PipelineExecutor.__new__(PipelineExecutor)
```

Оба созданы через `__new__` без вызова `__init__` → нет `self.db`. Это **заглушки**
для случаев когда модуль импортируется, но реальные экземпляры создаются в `chat.py`:
```python
pipeline_router = PipelineRouter(db)
executor = PipelineExecutor(db)
```

### N-07 — auto-title

```python
def _auto_title(query: str) -> str:
    cleaned = re.sub(r"[^\w\s\u0400-\u04ff]", " ", query).strip()
    words = cleaned.split()
    if len(words) > 7:
        cleaned = " ".join(words[:7])
    return cleaned[:255]
```

Оставляет кириллицу (`\u0400-\u04ff`), обрезает до 7 слов или 255 символов.
Вызывается только если `chat.title == "New Chat"` — идемпотентен.

### N-08 — ClarificationStateRow создаётся при создании чата

FSM-запись `stage="idle"` добавляется сразу при `POST /chat/create`.
Это гарантирует что `/clarify` всегда найдёт запись в БД (нет lazy-init).

### N-09 — vault_ids vs vault_id

В `PipelineExecutionContext` два поля:
- `vault_ids: list[str]` — **актуальный**, все enabled Vault домена
- `vault_id: str | None` — **deprecated**, legacy single-vault

В `_retrieve_for_step` используется только `vault_ids`. `vault_id` в context
передаётся для back-compat, но в реальном ретривале игнорируется.

### N-10 — format_prompt

```python
from app.services.prompt_pack import format_prompt
```

Простой helper: `system_prompt.format(**kwargs)` с защитой от KeyError.
В финальном шаге передаёт `{context, collected_fields}`, в step-промптах — `{context, query}`.

---

## Схема потока данных (полная)

```
Browser
  POST /chat/{id}/send_stream
  body: {content: "..."}
         ↓
FastAPI chat.py
  1. _get_chat_or_404()
  2. Message(user) → flush
  3. _domain_id_for_chat()     → domain_id
  4. VaultConfigService        → vault_ids
  5. PipelineExecutionContext(query, domain_id, vault_ids, ...)
         ↓
  PipelineRouter(db).select(context)
    → domain_service.get_prompt("pipeline_router")  [опц.]
    → pipeline_service.get_active_pipelines(domain_id)
    → filter по mode
    → provider.generate([system_prompt, query]) → JSON
    → context.pipeline_id = ...
    → context.steps = ...
    → context.final_composition = ...
         ↓
  context.history = last 20 messages
         ↓
  StreamingResponse(event_stream())
    → PipelineExecutor(db).run_stream(context)
      → asyncio.gather([_run_step x N])
          → _retrieve_for_step()    → retrieve_multi_vault()
          → provider.generate()     → partial answer
      → format_prompt(final_composition)
      → provider.generate_stream()  → token chunks
      → yield {type: "token", content}
      → yield {type: "sources", ...}
    → Message(assistant) → commit
    → yield "data: [DONE]"
         ↓
Browser: накапливает токены
```
