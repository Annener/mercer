# CONCEPT: Reranker Model Management

## Суть фичи

Сейчас параметры reranker'а хранятся как плоские ключи в таблице `platform_settings`
(`reranker.enabled`, `reranker.provider`, `reranker.base_url`, `reranker.model_name`).
Это неудобно: нельзя иметь несколько конфигураций, нет активации/деактивации,
нет проверки связи, нет единого UI.

**Цель:** вынести reranker в отдельную сущность — по аналогии с `EmbeddingModel` и
`GenerationModel`. Модель можно добавить, активировать/деактивировать, проверить
доступность. Активная reranker-модель автоматически применяется ко всем RAG-поискам.

## Конечный результат

- Вкладка «Reranker» в разделе настроек (рядом с Embedding / Generation моделями)
- Кнопка «Добавить модель» → модальное окно с полями
- Список добавленных моделей с кнопками: Активировать / Деактивировать / Проверить / Удалить
- Активная модель применяется в `retrieval.py` после поиска (переранжирование результатов)
- Неактивная — не применяется (поиск работает как раньше)

---

## Важный факт (найдено при аудите)

**Reranker в retrieval.py сейчас НЕ вызывается вообще.**
Функции `retrieve()` и `retrieve_multi_vault()` возвращают результаты без rerankinga,
несмотря на наличие ключей `reranker.*` в настройках. Реализация логики rerankinga —
обязательная часть этой задачи, не только UI.

---

## Архитектура: что и где меняется

### 1. База данных — новая таблица `rerank_models`

Файл: `rag-backend/app/db/models.py`

```python
class RerankModel(Base):
    __tablename__ = "rerank_models"

    id: UUID (PK, default=uuid4)
    model_id: str(128) UNIQUE NOT NULL      # slug, напр. "bge-reranker-v2"
    provider: str(64) NOT NULL              # "openai_compatible" | "cohere" | "jina"
    display_name: str(256) nullable
    base_url: str TEXT NOT NULL
    encrypted_api_key: str TEXT nullable
    timeout_seconds: int DEFAULT 30
    is_active: bool DEFAULT False           # только одна модель может быть активной
    enabled: bool DEFAULT True             # вкл/выкл без удаления (как в gen-моделях)
    created_at: datetime
    updated_at: datetime
```

Также нужна **миграция**: новый файл в `rag-backend/alembic/versions/` или в папке
`migrations/` (смотри как устроены существующие миграции в проекте).

Старые ключи `reranker.*` из `platform_settings` удалять НЕ сразу — сначала убедиться
что фронтенд их больше не читает.

### 2. settings_service.py

Файл: `rag-backend/app/services/settings_service.py`

Добавить методы по аналогии с embedding-моделями:

```python
async def list_rerank_models(db) -> list[dict]
async def create_rerank_model(data: dict, db) -> dict
async def update_rerank_model(model_id: str, data: dict, db) -> dict
async def delete_rerank_model(model_id: str, db) -> None
async def activate_rerank_model(model_id: str, db) -> dict
    # Деактивирует все остальные, активирует одну (как swap_provider для gen-моделей)
async def get_active_rerank_model(db) -> RerankModel | None
```

Вспомогательный приватный метод:
```python
@staticmethod
async def _get_rerank_model(model_id: str, db) -> RerankModel | None:
    result = await db.execute(select(RerankModel).where(RerankModel.model_id == model_id))
    return result.scalar_one_or_none()
```

### 3. API — новый файл rerank_models.py

Файл: `rag-backend/app/api/settings/rerank_models.py`

Эндпоинты:
```
GET    /settings/models/rerank                      → list_rerank_models
POST   /settings/models/rerank                      → create_rerank_model
PUT    /settings/models/rerank/{model_id:path}      → update_rerank_model
DELETE /settings/models/rerank/{model_id:path}      → delete_rerank_model
POST   /settings/models/rerank/{model_id:path}/activate  → activate
POST   /settings/models/rerank/{model_id:path}/deactivate → deactivate
POST   /settings/models/rerank/{model_id:path}/check     → проверка доступности
```

Паттерн — точная копия `emb_models.py`. Lookup по `model_id` (str), не по UUID PK.

### 4. Pydantic схемы

Файл: `rag-backend/app/api/settings/schemas.py`

Добавить в конец файла:
```python
class RerankModelCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    provider: str = "openai_compatible"
    display_name: str | None = None
    base_url: str
    api_key: str | None = None
    timeout_seconds: int = 30
    enabled: bool = True

class RerankModelUpdateRequest(BaseModel):
    provider: str | None = None
    display_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None
```

### 5. helpers.py — проверка reranker

Файл: `rag-backend/app/api/settings/helpers.py`

Добавить функцию `_check_reranker_provider(model: RerankModel) -> dict`:

```python
async def _check_reranker_provider(model: RerankModel) -> dict:
    """
    Отправляет тестовый rerank-запрос к провайдеру.
    Формат запроса: POST /rerank
    Body: {"model": model_id, "query": "test", "documents": ["doc one", "doc two"]}
    Ожидаемый ответ: список scores или results с полем relevance_score.
    Возвращает {"ok": True, "latency_ms": N} или бросает исключение.
    """
```

Поддерживаемые форматы:
- **OpenAI-compatible / Jina / BGE**: POST `/rerank`, body `{query, documents, model}`
- **Cohere**: POST `/rerank`, body `{query, documents, model}` — тот же формат

### 6. retrieval.py — реализация rerankinga

Файл: `rag-backend/app/services/retrieval.py`

Это **ключевое изменение**. Добавить функцию и встроить в пайплайн:

```python
async def rerank_hits(
    query: str,
    hits: list[SearchHit],
    db: AsyncSession,
) -> list[SearchHit]:
    """
    Переранжирует hits с помощью активной reranker-модели.
    Если активной модели нет или enabled=False — возвращает hits без изменений.
    """
    model = await settings_service.get_active_rerank_model(db)
    if model is None or not model.enabled or not model.is_active:
        return hits
    if not hits:
        return hits

    documents = [h.text for h in hits]
    api_key = settings_service.decrypt_api_key(model.encrypted_api_key) if model.encrypted_api_key else ""

    async with httpx.AsyncClient(
        timeout=model.timeout_seconds,
        headers={"Authorization": f"Bearer {api_key}"}
    ) as client:
        response = await client.post(
            f"{model.base_url.rstrip('/')}/rerank",
            json={"model": model.model_id, "query": query, "documents": documents},
        )
        response.raise_for_status()

    # Парсим scores — поддерживаем разные форматы провайдеров
    data = response.json()
    results = data.get("results") or data.get("data") or []
    scored = []
    for item in results:
        idx = item.get("index", item.get("corpus_id"))
        score = item.get("relevance_score") or item.get("score", 0.0)
        if idx is not None and idx < len(hits):
            scored.append((score, hits[idx]))

    if not scored:
        return hits

    scored.sort(key=lambda x: x[0], reverse=True)
    return [hit for _, hit in scored]
```

Встроить вызов в `retrieve_multi_vault()`:
```python
# После all_hits.sort(...) и result = all_hits[:effective_top_k]
if db is not None:
    result = await rerank_hits(query, result, db)
return result
```

**Важно:** `httpx` уже используется в `retrieval.py` для embedding-запросов, дополнительный
импорт не нужен. Если при чтении файла `import httpx` отсутствует — добавить в блок импортов.

### 7. __init__.py настроек — регистрация нового роутера

Файл: `rag-backend/app/api/settings/__init__.py`

Добавить импорт и подключение роутера `rerank_models.router`.

---

## UI: новая вкладка Reranker

### Расположение
Вкладка в настройках, рядом с «Embedding модели» и «Генеративные модели».

### Структура страницы
```
[Заголовок: Reranker модели]
[Кнопка: + Добавить модель]

┌─────────────────────────────────────────────────┐
│ bge-reranker-v2              [АКТИВНА] 🟢        │
│ http://localhost:8001         openai_compatible  │
│ [Деактивировать] [Проверить] [Удалить]           │
└─────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│ jina-reranker-v2             [неактивна] ⚪       │
│ https://api.jina.ai           openai_compatible  │
│ [Активировать] [Проверить] [Удалить]             │
└─────────────────────────────────────────────────┘
```

### Модальное окно «Добавить / Редактировать модель»
Поля:
- **model_id** (обязательное) — slug-идентификатор, напр. `bge-reranker-v2`
- **display_name** (опциональное) — человекочитаемое имя
- **provider** (select) — `openai_compatible` / `cohere` / `jina`
- **base_url** (обязательное) — URL API, напр. `http://localhost:8001`
- **api_key** (опциональное, тип password) — API ключ
- **timeout_seconds** (число, default 30)

### JS файл
Создать отдельный файл: `rag-backend/app/static/js/settings/tab-rerank-models.js`
По аналогии с существующими файлами:
- `rag-backend/app/static/js/settings/tab-emb-models.js`
- `rag-backend/app/static/js/settings/tab-gen-models.js`

---

## Что НЕ трогаем на первом этапе

- Ключи `reranker.*` в `platform_settings` — удалим только когда UI-вкладка готова
- Логику `pipeline_executor.py` — reranking встраивается в `retrieval.py`, не в executor
- Формат SSE-стрима — reranking прозрачен для пайплайна
