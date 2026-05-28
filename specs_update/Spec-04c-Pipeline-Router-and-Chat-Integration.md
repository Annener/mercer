# Spec-04c: Pipeline Router and Chat Integration

Перед выполнением прочитай `Spec-00-Architecture-Overview.md`, `Spec-04a` (pipeline_service, retrieval), `Spec-04b` (pipeline_executor).

**Зависит от:** `Spec-04a`, `Spec-04b`, `Spec-02b` (API настроек частично), `Spec-02c` (эндпоинты для pipeline уже есть).

**Цель:** Создать `pipeline_router.py` для LLM-маршрутизации запросов, обновить `api/chat.py` для интеграции пайплайнов (маршрутизация, выполнение, SSE), добавить недостающие эндпоинты в `api/settings.py`.

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/app/services/pipeline_service.py`
- `rag-backend/app/services/pipeline_executor.py`
- `rag-backend/app/services/domain_service.py` (для получения промпта `pipeline_router`)
- `rag-backend/app/api/chat.py` — текущая логика отправки сообщений
- `rag-backend/app/api/settings.py` — добавить эндпоинты для pipelines

## Задачи

### 1. Создать `services/pipeline_router.py`

Класс `PipelineRouter` с методом `decide`.

**Сигнатура:**

```python
class PipelineRouter:
    def __init__(self, settings_service, domain_service, pipeline_service):
        ...

    async def decide(
        self,
        query: str,
        chat: Chat,          # ORM объект чата
        db: AsyncSession,
        llm_provider: GenerationProvider | None = None,
    ) -> tuple[PipelineRead | None, str | None, float | None, str | None]:
        """
        Возвращает (pipeline, mode, confidence, reasoning).
        Если пайплайн не выбран — все значения None.
        """
```

**Логика:**

**Приоритет 1: Зафиксированный пайплайн (locked_pipeline_id)**

- Если `chat.locked_pipeline_id` задан:
  - Найти активную версию пайплайна через `pipeline_service.get_pipeline(chat.locked_pipeline_id)` (активная версия по `pipeline_id`).
  - Если найден → вернуть `(pipeline, "lock", 1.0, "locked by user")`.
  - Если не найден → логировать `WARNING`, перейти к приоритету 2.

**Приоритет 2: Автоматический выбор через LLM**

- Получить активные пайплайны для домена чата: `pipelines = await pipeline_service.get_active_pipelines(chat.domain_id, db)`.
- Если список пуст → вернуть `(None, None, None, None)`.
- Загрузить промпт типа `pipeline_router` из домена: `prompt = await domain_service.get_prompt(chat.domain_id, "pipeline_router", db)`.
- Если `prompt` пуст или состоит только из пробелов — использовать дефолтный шаблон (см. ниже).
- Сформировать список пайплайнов в виде строк:
  ```
  1. id="plot_arc", name="Сюжетная арка", description="..."
  2. id="lore_lookup", name="Поиск лора", description="..."
  ```
- Получить историю чата (последние 3 сообщения) из БД.
- Вызвать LLM (если `llm_provider` не передан, взять из `settings_service.get_active_provider()`).
- Отправить системный промпт + запрос пользователя. Ожидать JSON.
- Распарсить ответ. Если JSON валидный, содержит `pipeline_id`, `confidence`, и `confidence >= 0.5`, и `pipeline_id` присутствует в списке доступных пайплайнов — вернуть выбранный пайплайн, режим `"auto"`, confidence и reasoning.
- Иначе вернуть `None`.

**Дефолтный PROMPT_TEMPLATE:**

```
Ты — маршрутизатор запросов для домена "{domain_id}".

Доступные pipelines:
{pipelines_list}

Query пользователя: "{query}"
История чата (последние 3 сообщения):
{chat_history}

Проанализируй запрос и выбери наиболее подходящий pipeline.
Верни ТОЛЬКО валидный JSON в формате:
{{"pipeline_id": "...", "confidence": 0.0-1.0, "reasoning": "..."}}

Правила:
- confidence >= 0.7 — высокая уверенность
- confidence 0.5-0.7 — средняя уверенность
- confidence < 0.5 — низкая уверенность (система отклонит выбор)
- Если ни один pipeline не подходит — верни {{"pipeline_id": null, "confidence": 0.0, "reasoning": "..."}}
```

**Логирование:** При ошибке парсинга или неверном `pipeline_id` записать в `audit_logs` событие с `action="pipeline_router_failure"`, `details={"query": query, "response": raw_output, "available_pipelines": [ids]}`.

### 2. Обновить `api/chat.py`

**Добавить импорты:** `PipelineRouter`, `PipelineExecutor`, `pipeline_service`.

**В обработчике `POST /chat/{id}/message`:**

1. Получить чат из БД (уже есть).
2. Получить `query` из тела запроса.
3. Вызвать `pipeline_router.decide(query, chat, db)`.
4. Если `pipeline` выбран:
   - Создать `chat_context = {"chat_id": chat.id, "vault_id": chat.vault_id, "collected_fields": collected (из FSM), "history": [...]}`.
   - Вызвать `executor.run(pipeline, query, chat_context, db, request=request)`.
   - Пробрасывать все события из генератора в SSE.
   - **Важно:** Первое событие `pipeline_selected` отправляется внутри executor. Ничего дополнительно отправлять не нужно.
   - После завершения генератора отправить `data: [DONE]`.
5. Если `pipeline` не выбран (None) — выполнить существующий путь через `Planner` (старый SSE формат). Не ломать обратную совместимость.

**Обновить `_run_pipelines` (если существует):** удалить старый код, заменить на вызов `PipelineExecutor`. Или просто удалить функцию, если она больше не используется.

**Добавить в `chat.py` импорт `settings_service` для получения `top_k` и т.д. (уже должно быть).**

### 3. Добавить недостающие эндпоинты в `api/settings.py` (если ещё нет)

Spec-02c уже должен был добавить эндпоинты для pipelines, но проверим:

- `GET /settings/pipelines?domain_id=...` — список пайплайнов (все версии).
- `POST /settings/pipelines` — создание.
- `PUT /settings/pipelines/{id}` — обновление (новая версия).
- `DELETE /settings/pipelines/{id}` — soft delete.
- `POST /settings/pipelines/{id}/activate` — активация версии.

Если их нет — реализовать согласно Spec-02c (задача 4). Использовать `pipeline_service` для всех операций.

**Важно:** Эндпоинт `PUT /settings/pipelines/{id}` должен принимать `id` как UUID строки (не `pipeline_id`). Обновление создаёт новую версию.

### 4. Обновить `api/settings.py` для миров и кампаний (уже должно быть)

Spec-02c задача 3 описывает эндпоинты для миров и кампаний. Проверить их наличие. Если нет — реализовать.

### 5. Аудит логов

Во всех изменяющих эндпоинтах `api/settings.py` (POST, PUT, DELETE для доменов, моделей, vault'ов, миров, пайплайнов) добавить запись в `audit_logs`. Использовать вспомогательную функцию `log_audit(action, entity_type, entity_id, details, db)`. Для `pipeline_router` ошибки тоже логировать.

## Финальный контракт

- `pipeline_router.py` реализует выбор пайплайна (locked или LLM).
- `api/chat.py` умеет маршрутизировать запросы в пайплайны и возвращать SSE‑события нового формата.
- Старый путь через Planner сохраняется как fallback.
- Все эндпоинты для пайплайнов, миров, кампаний доступны через API.
- Аудит логов работает.

## Критерии приёмки

- [ ] При `chat.locked_pipeline_id` и существующем пайплайне — выбор происходит без LLM, режим `"lock"`.
- [ ] При пустом `pipeline_router` промпте используется дефолтный шаблон.
- [ ] При выборе пайплайна LLM, `confidence < 0.5` или невалидный JSON — решение не принимается, используется Planner.
- [ ] В `audit_logs` появляются записи об ошибках роутинга.
- [ ] `POST /chat/{id}/message` с выбранным пайплайном возвращает SSE‑события в порядке: `pipeline_selected`, `progress`, `step_done`, `token`, `sources`, `[DONE]`.
- [ ] `POST /chat/{id}/message` без пайплайна возвращает старый формат (`token`, `sources`).
- [ ] `POST /settings/pipelines` создаёт запись с версией `1.0.0`.
- [ ] `PUT /settings/pipelines/{id}` создаёт новую версию с инкрементом (`1.0.0` → `1.0.1`), старая версия `is_active=False`.
- [ ] `DELETE /settings/pipelines/{id}` устанавливает `is_active=False` (soft delete).
