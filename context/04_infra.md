# Mercer — Шаг 4: Инфраструктура, провайдеры, DB-модели, конфигурация

> Файл описывает состояние **as is** на момент создания (июнь 2026).

---

## 1. `config.py` — AppConfig (Pydantic)

`AppConfig` — главная конфигурационная модель приложения. Передаётся в `chat.py` через `_ctx_dict` -> `context.config`.

### Структура

```python
class AppConfig(BaseModel):
    vaults: dict[str, VaultConfig]                    # vault_id -> VaultConfig
    embedding_models: dict[str, EmbeddingModelConfig] # model_id -> EmbeddingModelConfig
    generation_models: dict[str, GenerationModelConfig] # model_id -> GenerationModelConfig
    reranker: RerankerConfig = ...
    chat: ChatConfig = ...
    retrieval: RetrievalConfig = ...
    pipelines: PipelinesConfig = ...
    ui: UIConfig = ...
    validation_rules: dict[str, ValidationRuleRange] = {}
```

### Вношенные конфиги

| Класс | Ключевые поля |
|---|---|
| `VaultConfig` | `vault_id`, `domain_id`, `path`, `enabled=True` |
| `EmbeddingModelConfig` | `model_id`, `provider` (ollama/openai_compatible), `model_name`, `base_url`, `dimensions>0`, `enabled=True`, `timeout_seconds=30`, `max_retries=3` |
| `GenerationModelConfig` | `model_id`, `provider="openai_compatible"`, `base_url`, `api_key_env`, `enabled=True`, `timeout_seconds=60` |
| `RerankerConfig` | `enabled=False`, `provider?`, `base_url?`, `model_name?` |
| `ChatConfig` | `max_clarification_turns=3` [0..10], `stream_answers=True`, `auto_title=True` |
| `RetrievalConfig` | `enabled=True`, `top_k=10` [1..100], `reranker_enabled=False` |
| `PipelinesConfig` | `enabled=True`, `path="/app/pipelines"`, `reload_interval_seconds=2.0`, `debounce_seconds=2.0` |
| `UIConfig` | `db_management_enabled=True` |
| `ValidationRuleRange` | `min: float`, `max: float` |

**Важно:** `AppConfig` популяется в `chat.py` из `_build_config(settings_service, config_for_vault)` пер request.
`vaults` берётся из `VaultConfigService.vaults` — если не загружен, будет `{}` → `retrieval` пропадёт.
`embedding_models` и `generation_models` популяются из `settings_service.list_*_models(db)`.

---

## 2. `providers/generation/` — Генерация текста

### Иерархия

```
GenerationProvider (ABC)
    generate_stream(messages) -> AsyncIterator[str]
    generate(messages) -> str

OpenAICompatibleProvider(GenerationProvider)
    generate_stream / generate / generate_json

GenerationProviderUnavailableError(Exception)
StreamProviderError(Exception)
```

### `get_generation_provider(config=None) -> GenerationProvider`

```python
# providers/generation/__init__.py
def get_generation_provider(config=None):
    provider = settings_service.get_active_provider()  # sync, in-memory
    if provider is None:
        raise GenerationProviderUnavailableError("No active generation model configured")
    return provider
```

**Важно:** `config` параметр игнорируется. Провайдер берётся из `settings_service._active_provider`.

### `OpenAICompatibleProvider`

```python
OpenAICompatibleProvider(
    config: GenerationModelConfig,
    api_key: str,
    max_retries: int = 3,
)
```

**Идентификация:** `HTTP-Referer: http://mercer.local`, `X-Title: Mercer RAG` — для OpenRouter/ProxyAPI.

**URL endpoint:** `{config.base_url.rstrip('/')}/chat/completions`

#### `generate_stream(messages)`
- Ретрай: `max_retries` раз, backoff `2**attempt`
- `httpx.AsyncClient.stream(POST, ...)` → `aiter_lines()` → `_parse_stream_line(line)`
- `StreamProviderError` (finish_reason=error от OpenRouter) → ретрай
- Исчерпание ретраев → `GenerationProviderUnavailableError`

#### `generate(messages)`
- Та же политика ретраев
- `_parse_completion_response(response.json())` → str

#### `generate_json(messages, fallback?)`
- Инъецция: если есть system-сообщение — добавляет `\n\nIMPORTANT: Respond with valid JSON only.`, иначе препендирует json_system-сообщение
- `temperature=0.2`
- **НЕ использует** `response_format={"type": "json_object"}` — OpenRouter/DeepSeek падают с этим
- Снимает code-fences если модель добавила \`\`\`json
- если `fallback` задан и все ретраи исчерпаны → вернёт `fallback` (не бросает)

#### `_build_chat_payload`

```python
def _build_chat_payload(model_id, messages, *, stream, temperature=None):
    payload = {"model": model_id, "messages": messages, "stream": stream}
    if temperature is not None:
        payload["temperature"] = temperature
    return payload
```

#### `_parse_stream_line(line) -> str`
- `data: ` prefix + `[DONE]` sentinel
- `choices[0].finish_reason == "error"` → `raise StreamProviderError`
- `choices[0].delta.content` → str

#### `_parse_completion_response(payload) -> str`
- `payload["choices"][0]["message"]["content"]`
- `ValueError` если нет choices/message/content

---

## 3. `db/models.py` — ORM-модели

### Таблицы и PK

| Модель | Таблица | PK | Бизнес-ключ |
|---|---|---|---|
| `Domain` | `domains` | `domain_id` (str) | `domain_id` |
| `DomainPrompt` | `domain_prompts` | UUID `id` | `domain_id` + `prompt_type` |
| `DomainClarificationField` | `domain_clarification_fields` | UUID `id` | `domain_id` + `field_name` |
| `PlatformSetting` | `platform_settings` | `key` (str) | `key` |
| `GenerationModel` | `generation_models` | UUID `id` | `model_id` (str, UNIQUE) |
| `EmbeddingModel` | `embedding_models` | UUID `id` | `model_id` (str, UNIQUE) |
| `Vault` | `vaults` | UUID `id` | `vault_id` (str, UNIQUE) |
| `Tag` | `tags` | UUID `id` | (`name`, `domain_id`) UNIQUE |
| `Document` | `documents` | UUID `id` | `source_path` + `vault_id` |
| `DocumentLabel` | `document_labels` | (`document_id`, `tag_id`) | M2M |
| `Campaign` | `campaigns` | UUID `id` | — |
| `campaign_tags` | `campaign_tags` | (`campaign_id`, `tag_id`) | M2M Table |
| `Chat` | `chats` | UUID `id` | — |
| `Message` | `messages` | UUID `id` | — |
| `ClarificationState` | `clarification_states` | `chat_id` (UUID FK) | — |
| `AuditLog` | `audit_logs` | UUID `id` | — |
| `Pipeline` | `pipelines` | UUID `id` | (`pipeline_id`, `domain_id`, `version`) UNIQUE |
| `PipelineDecision` | `pipeline_decisions` | UUID `id` | — |

**Alias:** `ClarificationStateRow = ClarificationState` — для бэк-компата в `chat.py`.

### Ключевые колонки

#### `Domain`
- `domain_id: str` — реальный PK (без UUID, без `id`)
- `is_system`, `enabled`
- реляции: `prompts`, `clarification_fields`

#### `PlatformSetting`
- `key` (PK), `value` (TEXT), `value_type` (bool/int/float/str), `group_name`, `label`, `hint`
- Десериализацию делает `SettingsService.deserialize_value()`

#### `GenerationModel`
- `id` (UUID PK), `model_id` (str, UNIQUE) — **все операции через `model_id`, не `id`**
- `encrypted_api_key: str | None` — Fernet-шифрование
- `is_active: bool` — только одна модель активна в любой момент
- `enabled`: доступна ли в списках моделей

#### `Vault`
- `id` (UUID PK), `vault_id` (str, UNIQUE)
- `domain_id -> domains(ondelete=SET NULL)` — не CASCADE!
- `chunk_count` — обновляется db-api-server после индексации
- `binding_status: str` = "bound" / "unbound"
- `embedding_model_id: str | None` — slug, не UUID FK

#### `Tag`
- `domain_id -> domains(CASCADE)`, `campaign_id -> campaigns(SET NULL)`
- UNIQUE (`name`, `domain_id`)

#### `Document`
- `vault_id -> vaults.vault_id(CASCADE)` — FK по `vault_id`-строке, не UUID
- `status`: pending/indexed/error
- `md5`, `mtime` — дедупликация при переиндексации

#### `Campaign`
- `domain_id -> domains(CASCADE)`
- `system_prompt: str | None` — переопределяет доменный system prompt в чате
- реляции: `chats`, `tags` (viewonly, через `campaign_tags`)

#### `Chat`
- `domain_id: str NOT NULL` — **A01 fix** (не Optional!), `ondelete=CASCADE`
- `campaign_id: UUID | None -> campaigns(SET NULL)`
- `pipeline_versions: JSONB | None` — история `{"last_used": pipeline_id}`
- `locked_pipeline_id: str | None` — A03: зафиксированный пайплайн для чата
- `vault_id: str | None` — **устаревшее**, back-compat поле. Не используется в chat.py.
- реляции: `messages` (order_by created_at), `clarification_state` (uselist=False), `campaign`

#### `Message`
- `role`: "user" / "assistant" / "system"
- `pipeline_id: str | None` — какой пайплайн сгенерировал ответ

#### `ClarificationState` / `ClarificationStateRow`
- PK = `chat_id` (UUID FK, не surrogate)
- `missing_fields: JSONB | None`, `collected: JSONB | None`
- `stage`, `turn`, `next_question`

#### `Pipeline`
- UNIQUE (`pipeline_id`, `domain_id`, `version`)
- `steps: JSONB list` — list[PipelineStep]
- `final_composition: JSONB dict` — FinalComposition
- `is_active: bool` — активный / архивный

#### `AuditLog`
- Свободная структура: `action`, `entity_type`, `entity_id`, `details: JSONB`

---

## 4. `db/session.py` — Сессия БД

```python
DATABASE_URL = os.getenv("DATABASE_URL",
    "postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session  # FastAPI DI: Depends(get_db)

async def dispose_engine() -> None:
    await engine.dispose()  # вызывается в lifespan shutdown
```

**Важно:**
- `expire_on_commit=False` — объекты остаются пригодны после `commit()`
- `pool_pre_ping=True` — проверка соединения перед каждым запросом
- `SessionLocal` — используется в `lifespan` для инициализации (вручную), `get_db` — в `Depends()`
- БД: `postgresql+asyncpg`, хост `rag-db`, база `ragplatform`

---

## 5. `main.py` — Жизненный цикл приложения

### Lifespan

```
1. setup_logging("backend")
2. run_migrations()           # Alembic async
3. setup_logging("backend")  # повторный вызов (intentional?)
4. app.state.settings_service = settings_service
5. app.state.domain_service = domain_service
6. async with SessionLocal() as db:
       await settings_service.load_settings(db)         # кэш platform_settings
       await settings_service.load_active_provider(db)  # построить LLM-провайдер
   (ошибка -> logger.critical + sys.exit(1))
7. если get_active_provider() is None -> logger.warning (не exit!)
8. logger.info("Service started")
9. yield
10. dispose_engine()
```

### Роутеры

| Роутер | Префикс |
|---|---|
| `chat_router` | (from `app.api.chat`) |
| `config_router` | (from `app.api.config_api`) |
| `settings_router` | `/api/settings` |
| `db_management_router` | (from `app.api.db_management`) |

### Статика и HTML

```python
STATIC_DIR = Path(__file__).parent / "static"  # rag-backend/app/static/
app.mount("/static", StaticFiles(directory=STATIC_DIR))

GET / -> STATIC_DIR/index.html (FileResponse, Cache-Control: no-cache)
GET /health -> {"status": "ok", "service": "rag-backend"}
```

---

## 6. `logging_config.py` — Настройка логирования

`setup_logging(service_name)` настраивает формат: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. Уровень: `INFO` (умолчание). Отключает verbose-логи `httpx`, `httpcore`, `sqlalchemy.engine` (выше WARNING).

**Важно:** `setup_logging` вызывается **дважды** в lifespan (до и после `run_migrations`). Второй вызов переопределяет настройки после migration-логов uvicorn.

---

## 7. Ключевые нюансы инфра-слоя

1. **`AppConfig` всегда собирается per-request** в `_build_config()` — не хранится в app.state. Если нужна статичная конфигурация — через `settings_service`.

2. **`generation_models` в AppConfig** — популяется в chat.py, но реальный LLM-провайдер берётся из `settings_service._active_provider` (in-memory), не из AppConfig.

3. **`Domain.domain_id` = PK** — в таблице `domains` нет колонки `id`. При `SELECT` сортировке/фильтрации всегда использовать `Domain.domain_id`.

4. **`Vault.domain_id` = SET NULL** — если домен удалён, vault не удаляется. Надо проверять `enabled_for_domain` после удаления домена.

5. **`Chat.domain_id NOT NULL`** — A01 fix. Создание чата без domain_id → PG `NOT NULL violation` → 500 (Pydantic не поможет, ошибка на уровне DB).

6. **Шифрование API-ключей** — `GenerationModel.encrypted_api_key` и `EmbeddingModel.encrypted_api_key` хранятся зашифрованными. `ENCRYPTION_KEY` env var обязателен. Без него — `RuntimeError` при `decrypt_api_key()`.

7. **`Document.vault_id` FK = строка** — `ForeignKey("vaults.vault_id")`, не UUID. Индексируется по `vault_id`-строке.

8. **`generate_json` без `response_format`** — намеренно не используется для совместимости с DeepSeek/OpenRouter. Не добавляйте это поле без проверки провайдера.

9. **`sys.exit(1)` при ошибке загрузки settings** — lifespan крашает приложение. Отсутствие `is_active` модели — лог WARNING, но не exit.

10. **`StreamProviderError`** — внутренний exception в `openai_compatible.py`, не проксируется наружу. Вызывается внутри `generate_stream`, триггерит ретрай.
