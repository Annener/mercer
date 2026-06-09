# Mercer — Шаг 3: Слой сервисов

> Файл описывает состояние **as is** на момент создания (июнь 2026).

---

## 1. `settings_service.py` — Глобальный сервис настроек

**Синглтон:** `settings_service = SettingsService()` — module-level, один инстанс на весь процесс.

### Структура класса

```python
class SettingsService:
    _settings_cache: dict[str, Any]       # PlatformSetting key -> значение
    _setting_types: dict[str, str]         # key -> value_type (bool/int/float/str)
    _active_provider: GenerationProvider | None  # in-memory LLM-провайдер
    _provider_lock: asyncio.Lock           # атомарность swap
    _fernet: Fernet | None                 # ленивая инициализация
```

### DEFAULTS — значения по умолчанию

| Ключ | Значение |
|---|---|
| `retrieval.enabled` | `True` |
| `retrieval.top_k` | `10` |
| `retrieval.reranker_enabled` | `False` |
| `chunking.chunk_size` | `2000` |
| `chunking.overlap` | `64` |
| `chunking.entity_aware_mode` | `True` |
| `chat.max_clarification_turns` | `3` |
| `chat.stream_answers` | `True` |
| `chat.auto_title` | `True` |
| `reranker.enabled` | `False` |
| `reranker.provider/base_url/model_name` | `None` |
| `pdf_sidecar.url` | `http://host.docker.internal:8765` |
| `pdf_sidecar.timeout_seconds` | `180` |
| `pdf_sidecar.fallback_to_pdfminer` | `True` |

### Platform settings API

```python
await settings_service.load_settings(db)        # загрузить все PlatformSetting в кэш
await settings_service.get("retrieval.top_k", db)  # из кэша или из db
await settings_service.set(key, value, db)      # update + обновить кэш
await settings_service.reset_all(db)            # сброс к DEFAULTS
settings_service.invalidate(key)                # удалить из кэша
```

**Важно:** `get(key, db=None)` — если ключ не в кэше и `db=None` — бросает `KeyError`. `get` без db используется в `_default_top_k()` в `retrieval.py`.

### Активный LLM-провайдер

```python
await settings_service.load_active_provider(db)  # при старте приложения
await settings_service.swap_provider(model_id, db)  # после /activate
provider = settings_service.get_active_provider()   # sync, без db
```

**Важно:** `swap_provider` снимает `is_active=False` со всех моделей через `UPDATE GenerationModel SET is_active=False`, затем `model.is_active = True`. Использует `_get_generation_model(model_id, db)` (по строковому slug, не по UUID PK) — фикс E-CHK03.

### API-ключи: шифрование

```python
encrypted = settings_service.encrypt_api_key(plain_str)    # Fernet
plain = settings_service.decrypt_api_key(encrypted_str)
# Ключ: ENCRYPTION_KEY env var (обязателен). RuntimeError если не задан.
```

### GenerationModel CRUD (E-CHK03 fix: по model_id slug, не UUID PK)

```python
await settings_service.get_generation_model(model_id, db)
await settings_service.list_generation_models(db)
await settings_service.create_generation_model(data, db)
await settings_service.update_generation_model(model_id, data, db)
await settings_service.delete_generation_model(model_id, db)  # нельзя удалить is_active
await settings_service.activate_generation_model(model_id, db)  # -> swap_provider
```

### EmbeddingModel CRUD

```python
await settings_service.get_embedding_model(model_id, db)
await settings_service.list_embedding_models(db)
await settings_service.create_embedding_model(data, db)
await settings_service.update_embedding_model(model_id, data, db)
await settings_service.delete_embedding_model(model_id, db)
# Активации /activate нет — embedding привязывается через Vault.embedding_model_id
```

### `_transaction` context manager

```python
async with self._transaction(db):
    # если уже есть транзакция -> commit после, rollback при ошибке
    # иначе -> async with db.begin(): ...
```

### _build_generation_provider

Единственный поддерживаемый тип `provider = "openai_compatible"` → `OpenAICompatibleProvider`. Другой провайдер — `ValueError`.

---

## 2. `pipeline_router.py` — Маршрутизатор пайплайнов

**Синглтон:** `pipeline_router = PipelineRouter.__new__(PipelineRouter)` — создан через `__new__` (без `__init__`), db не задан на уровне модуля. В `chat.py` используется `PipelineRouter(db)` per-request.

### Основной метод: `select(context, locked_pipeline_id)`

```
1. locked_pipeline_id -> pipeline_service.get_pipeline(id, db)
   - заполняет context.pipeline_id/version/steps/final_composition
   - проверка mode-совместимости (кампанийный lock в general mode игнорируется)

2. активные пайплайны домена -> фильтрация по режиму:
   - campaign mode: campaign pipelines + глобальные (campaign_id IS NULL)
   - general mode: только глобальные

3. если candidates пусто -> return None

4. LLM-роутинг:
   - текст PROMPT_TEMPLATE (или domain prompt_type="pipeline_router")
   - запрос: [{role:system, content:full_prompt}, {role:user, content:query}]
   - ожидаем JSON: {pipeline_id, confidence, reasoning}
   - confidence < 0.5 -> None
   - pipeline_id не в candidates -> None + AuditLog
```

**Важно:** `provider = settings_service.get_active_provider()` — синхронный вызов, если `None` → router вернёт `None` (без исключения). `chat.py` преобразует None в 503.

### PROMPT_TEMPLATE роутера

Переменные: `{domain_id}`, `{pipelines_list}`, `{query}`, `{chat_history}`.
Ответ: `{"pipeline_id": "...", "confidence": 0.0-1.0, "reasoning": "..."}` или `{"pipeline_id": null, "confidence": 0.0, ...}`.

### Логирование ошибок

`_log_failure(query, response, available_pipelines, db)` → запись `AuditLog(action="pipeline_router_failure", ...)`.

### Legacy `decide(query, chat, db)` — устаревший метод

Использует Chat ORM напрямую, возвращает `tuple[PipelineRead | None, mode, confidence, reasoning]`. Новые вызовы используют `select()`. Тесты могут использовать `decide`.

---

## 3. `pipeline_executor.py` — Исполнитель пайплайнов

**Синглтон:** `pipeline_executor = PipelineExecutor.__new__(PipelineExecutor)` — аналогично router. В chat.py — `PipelineExecutor(db)` per-request.

### Публичный API

```python
result = await executor.run(context)          # -> _ExecutionResult(final_answer, sources)
async for chunk in executor.run_stream(context):  # -> AsyncIterator[dict]
    ...
```

### Внутренняя логика `_execute()` — асинх-генератор

```
1. pipeline_selected чанк
2. progress чанки (по одному на каждый шаг)
3. asyncio.gather(*[_run_step(...)]) — все шаги в параллеле!
4. step_done / step_skipped_no_docs чанки
5. final_composition.system_prompt -> LLM generate_stream
6. token чанки
7. sources чанк (сгруппированный по шагам)
8. _mark_completed
```

**Важно:** Шаги запускаются параллельно `asyncio.gather`. Если `final_composition is None` — `AttributeError` при обращении к `.system_prompt` — это приведёт к error-чанку (не к 500 из-за try/except в `_execute`).

### `_run_step(index, step, query, context, db, provider)`

```
1. _retrieve_for_step -> hits
2. hits = [] -> return _SKIPPED sentinel
3. format_context_with_role(hits, step.role)
4. format_prompt(step.system_prompt, {context, query})
5. provider.generate([system, user]) -> partial_answer
6. return (index, step, hits, partial)
```

### `_retrieve_for_step`

```
- top_k: step.top_k или settings_service.get("retrieval.top_k", db)
- vault_ids берётся из chat_context["vault_ids"]
- step.tag_ids -> get_allowed_tag_ids -> get_document_ids_by_tags
- vault_ids пусты -> return [] (шаг пропускается)
- len(vault_ids) == 1 -> retrieve(), иначе -> retrieve_multi_vault()
```

### `_pipeline_from_context` — восстановление PipelineRead из context

```python
PipelineRead(
    id="",                            # stub, UUID нет
    pipeline_id=context.pipeline_id,
    domain_id=context.domain_id or "default",
    version=context.pipeline_version or "0",
    name=context.pipeline_id or "unknown",
    steps=context.steps or [],
    final_composition=context.final_composition,
    campaign_id=context.campaign_id,
)
```

**Важно (BUG-3 fix):** `domain_id` обязателен для `PipelineRead`, поэтому `or "default"`.

### Жизненный цикл чата

- `_mark_started`: обновляет `chat.pipeline_versions["last_used"]` (по чату в DB)
- `_mark_completed`: добавляет `completed_at`

### `_gather_sources_for_step` — дедупликация источников

Key: `(source_path | document_id, page_number, vault_id)`. Дубликаты исключаются.

---

## 4. `retrieval.py` — Ретривал из LanceDB

**Внешний сервис:** `STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")`

### Основные функции

```python
await retrieve(query, vault_id, document_ids?, top_k?, strategy?, config?)
# document_ids=None -> без фильтра
# document_ids=[]   -> return [] (без запроса к LanceDB)
# document_ids=[...] -> фильтр {"document_id": {"$in": document_ids}}
# если strategy != "semantic" -> return []

await retrieve_multi_vault(query, vault_ids, document_ids?, top_k?, strategy?, config?)
# цикл по vault_ids, gather, sort by score desc, [:top_k]
```

### Поток запроса к LanceDB

```
1. _select_embedding_model(config) -> первая enabled EmbeddingModelConfig
2. _embed_query(query, model) -> list[float]
   - ollama: POST {base_url}/api/embeddings
   - openai_compatible: POST {base_url}/embeddings
   - ретрайс: model.max_retries, backoff 2**attempt
3. POST {STORAGE_API_URL}/index/search (SearchRequest)
4. SearchResponse.model_validate -> results
5. фильтр по document_ids (post-filter)
6. results[:top_k]
```

**Важно:** `config` обязателен — `ValueError` если `None`. `config` предаётся из `chat_context["config"]` (популяется из `_ctx_dict(context)` — `getattr(context, "config", None)`). Если `context.config is None` — запрос пропадёт.

### Форматирование контекста

```python
format_context(hits)                           # нумерация [1], [2]... по источникам
format_context_with_role(hits, role)           # заголовок роли + [1]...
```

ROLE_HEADERS: `methodology`, `lore`, `campaign_context`, `character_sheet`, `session_log`, `rules`. Неизвестная роль → `=== {ROLE.UPPER()} ===`.

### Теговые фильтры

```python
await get_allowed_tag_ids(domain_id, campaign_id, db)
# campaign_id -> теги кампании + глобальные
# None -> только глобальные
# Инвариант: пустое множество = кампания есть, но тегов нет -> document_ids=[]

await get_document_ids_by_tags(tag_ids, domain_id, db)
# JOIN Document -> DocumentLabel -> Vault WHERE domain_id + enabled + status='indexed'
# OR-логика: хотя бы один тег
# пустой tag_ids -> return [] без запроса
```

### Удаление чанков

```python
await delete_document_chunks(document_id, vault_id)
# DELETE {STORAGE_API_URL}/index/documents/{id}?vault_id=...
# 200/204/404 -> ok, другое -> raise_for_status
# физический файл НЕ удаляется
```

---

## 5. `vault_config_service.py` — Кэш Vault-конфигурации

**Синглтон:** `config_for_vault = VaultConfigService()` — module-level в chat.py.

```python
await config_for_vault.refresh(db)        # полная перезагрузка
await config_for_vault.ensure_loaded(db)  # ленивая: только если не загружено
config_for_vault.get(vault_id)            # _VaultEntry | None
config_for_vault.enabled_for_domain(domain_id)  # list[_VaultEntry]
config_for_vault.vaults                   # dict[str, _VaultEntry] (может быть пустым!)
config_for_vault.invalidate()             # сброс: следующий ensure_loaded() перезагрузит
```

**_VaultEntry поля:**

| Поле | Тип | Описание |
|---|---|---|
| `vault_id` | str | business-key |
| `domain_id` | str\|None | привязка к домену |
| `enabled` | bool | активен ли vault |
| `embedding_model_id` | str\|None | привязка модели |
| `expected_dimensions` | int\|None | для LanceDB |
| `chunk_size`, `overlap` | int\|None | параметры нарезки |
| `entity_aware_mode` | bool\|None | режим нарезки |
| `binding_status` | str | "bound"/"unbound" |
| `chunk_count` | int | кол-во чанков в индексе |

**Важно:** В `chat.py` используется без `ensure_loaded` на каждом запросе. Если vaultы добавлены/изменены после старта — `vault_ids` будет пустым до рестарта или `refresh`. Сеттингс автоматически вызывает `refresh` после CRUD ваулта.

---

## 6. `clarification_fsm.py` — FSM уточнений

### Статусы (stage)

| `stage` | Описание |
|---|---|
| `"idle"` | Исходный, запрос можно выполнять |
| `"collecting"` | Добираем недостающие поля |
| `"complete"` | Все поля собраны, запрос готов |
| `"fallback"` | Лимит turns исчерпан, выполнить частичные данные |

### API

```python
state = await get_state(db, chat_id)         # -> ClarificationState (creates if missing)
await save_state(db, chat_id, state)         # flush (commit снаружи)

state = await start_collecting(db, chat_id, missing_fields, prompt_pack)
# stage="collecting", turn=0, next_question генерируется

new_state = process_clarification_answer(state, user_message, max_turns, prompt_pack)
# синхронный: извлекает поля из user_message (регексы "(про|o) X")
# missing_fields опустел -> complete, turn >= max_turns -> fallback
```

### FIELD_LABELS — локальные названия полей

```python
{
    "topic":   "тему или объект вопроса",
    "subject": "конкретный класс, расу, заклинание или предмет",
}
```

---

## 7. `planner.py` — Legacy-планировщик

**Статус:** не используется в `chat.py` (заменён `PipelineRouter`). Остался в кодовой базе для обратной совместимости / тестов.

`Planner.decide(db, query, vault_id, domain_id, history)` — определяет:
- `retrieval_strategy`: семантический / none (через Vault.chunk_count)
- `clarification_needed`: если `missing_fields` != []
- `pipeline_invocations`: из PipelineRegistry (устаревший)

`LLMRAGPlanner.decompose(query, domain_id)` — разбивает запрос на 1-3 подзапроса через LLM `generate_json`. Также не используется в текущем потоке.

**AMBIGUOUS_SUBJECTS** — слова-триггеры для `missing_fields` (класс, раса, заклинание -> "subject").

---

## 8. Ключевые нюансы слоя сервисов

1. **`settings_service.get_active_provider()`** — синх, если `None` — роутер вернёт None, executor бросит `RuntimeError("No active generation model")` — это error-чанк в SSE, но чат видит сообщение об ошибке. Через `/api/settings/models/generation/{id}/check` можно проверить доступность.
2. **`context.config`** — заполняется в `chat.py` из `AppConfig`. Если `None` — retrieval пропадёт с `ValueError`.
3. **Параллельные шаги** — `asyncio.gather` в executor. Зависимые по ответу шаги не поддерживаются, все стартуют одновременно.
4. **`_SKIPPED` sentinel** — если все шаги пропущены (нет попаданий), `combined_context = ""`, final LLM знает о этом.
5. **`vault_ids` пустый в context** — все шаги будут пропущены (`_retrieve_for_step` вернёт []). Итог: final LLM отвечает без контекста.
6. **`config_for_vault.vaults`** — может быть пустым если `ensure_loaded` / `refresh` не вызывался. В chat.py вызывается только `config_for_vault.vaults` без `ensure_loaded`.
7. **Шифрование ENCRYPTION_KEY** — если env-переменная не задана, `decrypt_api_key` бросит `RuntimeError` при первом вызове активной модели.
8. **Planner / LLMRAGPlanner** — не встроены в pipeline-поток. Используйте PipelineRouter для новых фич.
9. **`format_context` вс `format_context_with_role`** — в pipeline executor используется `with_role` (role-based). Без role -> `format_context` используется в других местах.
10. **`PipelineRouter.__new__`** — module-level `pipeline_router` без db. Никогда не используйте напрямую — всегда `PipelineRouter(db)` per-request.
