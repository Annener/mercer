# Spec-04a: Retrieval and Pipeline Service

Перед выполнением прочитай `Spec-00-Architecture-Overview.md`, `Spec-02a` (сервисы), `Spec-03a` (индексация метаданных миров/кампаний).

**Зависит от:** `Spec-03a` (метаданные в чанках), `Spec-02a` (сервисы настроек и доменов).

**Цель:** Расширить `retrieval.py` поддержкой фильтрации по мирам/кампаниям/документам, создать `pipeline_service.py` для CRUD и версионирования пайплайнов.

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/app/services/retrieval.py` — текущая реализация поиска
- `rag-backend/app/db/models.py` — модели `Pipeline`, `World`, `Campaign`
- `shared_contracts/models.py` — возможно, потребуется добавить модели для pipeline

## Задачи

### 1. Расширить `services/retrieval.py`

**Новая сигнатура функции `retrieve`:**

```python
async def retrieve(
    query: str,
    vault_id: str,
    *,
    document_ids: list[str] | None = None,
    world_id: str | None = None,
    categories: list[str] | None = None,
    campaign_id: str | None = None,
    exclude_campaigns: list[str] | None = None,
    top_k: int | None = None,
) -> list[SearchHit]:
```

**Правила фильтрации (LanceDB `.where()`):**

- Все фильтры комбинируются через `AND`.
- Для `document_ids`: `metadata.document_id IN (?, ?, ...)`.
- Для `world_id`: `metadata.world_id = ?`.
- Для `categories`: `metadata.category IN (?, ?, ...)`.
- Для `campaign_id`: `metadata.campaign_id = ?`.
- Для `exclude_campaigns`: `metadata.campaign_id NOT IN (?, ?, ...)`.

**Важно:** Использовать **параметризованные запросы** с плейсхолдерами `?`, никогда не вставлять значения через f-строки. Пример:

```python
where_clause = ""
params = []
if document_ids:
    placeholders = ",".join(["?"] * len(document_ids))
    where_clause += f"metadata.document_id IN ({placeholders}) AND "
    params.extend(document_ids)
# ...
if where_clause:
    where_clause = where_clause.rstrip(" AND ")
    table.search(query).where(where_clause, params).limit(top_k or default_top_k)
```

- `top_k` если не передан — берётся из `settings_service.get("retrieval.top_k")`.
- Если фильтры не заданы — поведение идентично текущему (полный поиск по vault).

**Функция `retrieve_multi_vault`** — аналогично, принимает те же параметры и применяет их к каждому vault.

**Функция `format_context_with_role(hits: list[SearchHit], role: str) -> str`:**

- Группирует хиты по ролям (role передаётся как параметр, но группировка не требуется — функция просто форматирует все хиты с заголовком, соответствующим роли).
- Добавляет заголовок-разделитель в зависимости от `role`:
  - `methodology` → `=== МЕТОДОЛОГИЯ ===`
  - `lore` → `=== ЗНАНИЯ О МИРЕ ===`
  - `campaign_context` → `=== КОНТЕКСТ КАМПАНИИ ===`
  - `character_sheet` → `=== ЛИСТ ПЕРСОНАЖА ===`
  - `session_log` → `=== ЖУРНАЛ СЕССИИ ===`
  - `rules` → `=== ПРАВИЛА ===`
- Если `hits` пуст → возвращает пустую строку (без заголовка).
- Формат каждого хита: `[N]\n{text}\n---` (как в существующей `format_context`).

**Существующую `format_context` не трогать** — она остаётся для fallback Planner.

### 2. Создать `services/pipeline_service.py`

CRUD-сервис для управления пайплайнами. Все методы принимают `db: AsyncSession`.

**Методы:**

- `list_pipelines(domain_id: str | None = None, db: AsyncSession) -> list[PipelineRead]` — все версии, если `domain_id` указан — фильтр по домену.
- `get_active_pipelines(domain_id: str, db: AsyncSession) -> list[PipelineRead]` — только `is_active=True` для указанного домена.
- `get_pipeline(pipeline_id: str, version: str | None = None, db: AsyncSession) -> PipelineRead | None` — если `version` не указан, вернуть активную версию.
- `get_pipeline_by_uuid(uuid: str, db: AsyncSession) -> PipelineRead | None`.
- `create_pipeline(data: PipelineCreate, db: AsyncSession) -> PipelineRead` — валидация JSONB, версия `1.0.0`, `is_active=True`.
- `update_pipeline(pipeline_uuid: str, data: PipelineUpdate, db: AsyncSession) -> PipelineRead` — **всегда создаёт новую версию** (минорный инкремент), старую деактивирует.
- `deactivate_pipeline(pipeline_uuid: str, db: AsyncSession) -> None` — soft delete (`is_active=False`).
- `activate_pipeline(pipeline_uuid: str, db: AsyncSession) -> None` — активировать указанную версию, деактивировать все другие версии того же `pipeline_id`.

**Валидация JSONB `steps` и `final_composition`:**

- Для `steps`:
  - Каждый элемент должен содержать `order` (int, уникальный), `type` (book/world/campaign), `name` (str), `role` (один из списка), `system_prompt` (str).
  - Если `type == "book"` → обязательно поле `document_ids` (непустой массив строк).
  - Если `type == "world"` → обязательно `world_id` (str), опционально `categories` (массив строк).
  - Если `type == "campaign"` → обязательно `campaign_id` (str).
  - Опционально: `top_k` (int, >0).
- Для `final_composition`:
  - Обязательно поле `system_prompt` (str).
- При ошибке валидации бросать `ValueError` с понятным сообщением.

**Версионирование:**

- Формат `major.minor.patch`, всегда инкрементируется **patch** (последняя цифра).
- Пример: `1.0.0` → `1.0.1` → `1.0.2`.
- Мажорная версия всегда `1`, минорная всегда `0`.

**In‑memory кэш** (опционально): можно хранить активные пайплайны для быстрого доступа, с методом `invalidate(pipeline_id: str | None = None)`.

### 3. Обновить `shared_contracts/models.py`

Добавить Pydantic-модели (если ещё нет):

```python
class PipelineStep(BaseModel):
    order: int
    type: Literal["book", "world", "campaign"]
    name: str
    role: Literal["methodology", "lore", "campaign_context", "character_sheet", "session_log", "rules"]
    system_prompt: str
    top_k: int | None = None
    document_ids: list[str] | None = None
    world_id: str | None = None
    categories: list[str] | None = None
    campaign_id: str | None = None

class FinalComposition(BaseModel):
    system_prompt: str

class PipelineCreate(BaseModel):
    pipeline_id: str
    domain_id: str
    name: str
    description: str | None = None
    steps: list[PipelineStep]
    final_composition: FinalComposition
    is_active: bool = True

class PipelineUpdate(PipelineCreate):
    pass

class PipelineRead(BaseModel):
    id: str  # UUID
    pipeline_id: str
    domain_id: str
    version: str
    name: str
    description: str | None
    steps: list[PipelineStep]
    final_composition: FinalComposition
    is_active: bool
    created_at: datetime
```

## Финальный контракт

- `retrieval.retrieve()` поддерживает фильтрацию по `world_id`, `campaign_id`, `document_ids`, `categories`.
- `retrieval.format_context_with_role()` возвращает отформатированный контекст с заголовком роли.
- `pipeline_service.py` реализует полный CRUD с валидацией и версионированием.
- Модели данных добавлены в `shared_contracts`.

## Критерии приёмки

- [ ] `retrieve(world_id="forgotten_realms")` формирует параметризованный запрос к LanceDB (проверка логов или тест с моком).
- [ ] `retrieve(categories=["lore", "rules"])` корректно преобразует список в `IN (?, ?)`.
- [ ] `retrieve` с пустыми фильтрами возвращает те же результаты, что и раньше.
- [ ] `format_context_with_role([...], "lore")` возвращает строку, начинающуюся с `=== ЗНАНИЯ О МИРЕ ===`.
- [ ] `format_context_with_role([], "lore")` возвращает пустую строку.
- [ ] `pipeline_service.create_pipeline()` с валидным JSONB создаёт запись в БД с версией `1.0.0`.
- [ ] `pipeline_service.update_pipeline()` создаёт новую версию с инкрементом (`1.0.0` → `1.0.1`), старая версия `is_active=False`.
- [ ] `pipeline_service.update_pipeline()` с невалидным `steps` бросает `ValueError`.
- [ ] `pipeline_service.activate_pipeline()` деактивирует все другие версии того же `pipeline_id`.