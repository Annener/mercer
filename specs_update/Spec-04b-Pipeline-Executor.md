# Spec-04b: Pipeline Executor

Перед выполнением прочитай `Spec-00-Architecture-Overview.md`, `Spec-04a` (retrieval и pipeline_service).

**Зависит от:** `Spec-04a` (функции `retrieve`, `format_context_with_role`, сервис пайплайнов).

**Цель:** Создать `pipeline_executor.py` — асинхронный генератор, который выполняет мультишаговый пайплайн, генерирует SSE-события (прогресс, токены, источники) и поддерживает отмену через `request`.

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/app/services/retrieval.py` (уже расширен фильтрацией)
- `rag-backend/app/services/pipeline_service.py` (модели пайплайнов)
- `rag-backend/app/services/settings_service.py` (для top_k по умолчанию)
- `rag-backend/app/services/prompt_pack.py` (форматирование промптов с переменными `{context}`, `{collected_fields}`)

## Задачи

### 1. Создать `services/pipeline_executor.py`

Класс `PipelineExecutor` с методом `run`, который является асинхронным генератором (возвращает `AsyncGenerator[dict[str, Any], None]`).

**Сигнатура:**

```python
class PipelineExecutor:
    async def run(
        self,
        pipeline: PipelineRead,          # объект пайплайна из БД
        query: str,                      # исходный запрос пользователя
        chat_context: dict,              # { "chat_id": ..., "collected_fields": ..., "history": [...] }
        db: AsyncSession,
        request: Request | None = None,  # FastAPI Request для проверки отмены
    ) -> AsyncGenerator[dict[str, Any], None]:
        ...
```

**Параметры chat_context:**
- `chat_id` — UUID чата (нужен для обновления `pipeline_versions`)
- `collected_fields` — словарь с собранными полями уточнения (если есть)
- `history` — список последних сообщений (для роутера, но executor может игнорировать)

### 2. Логика выполнения

**Шаг 1. Проверка отмены перед началом**

Если `request` передан и `await request.is_disconnected()` → `asyncio.CancelledError`.

**Шаг 2. Обновление `chats.pipeline_versions` (до выполнения)**

```python
# Установка started_at
started_at = datetime.utcnow().isoformat()
await db.execute(
    update(Chat)
    .where(Chat.id == chat_context["chat_id"])
    .values(pipeline_versions=func.jsonb_set(
        func.coalesce(Chat.pipeline_versions, '{}'::jsonb),
        '{last_used}',
        func.to_jsonb({
            "pipeline_id": pipeline.pipeline_id,
            "version": pipeline.version,
            "started_at": started_at
        })
    ))
)
await db.commit()
```

**Шаг 3. Отправка события `pipeline_selected` (первое SSE)**

```python
yield {
    "type": "pipeline_selected",
    "pipeline_id": pipeline.pipeline_id,
    "pipeline_name": pipeline.name,
    "reasoning": "executing pipeline",
    "mode": "auto"  # или "lock" — будет передано извне
}
```

**Шаг 4. Выполнение шагов пайплайна**

- Получить `steps = sorted(pipeline.steps, key=lambda s: s.order)`
- `total_steps = len(steps)`
- Для каждого шага с индексом `i` (начиная с 1):

  **4a. Прогресс:**
  ```python
  yield {"type": "progress", "step": i, "total": total_steps, "step_name": step.name}
  ```

  **4b. Проверка отмены:** если `request` и разорвано → `CancelledError`.

  **4c. Сбор контекста через `retrieve()`:**

  - Определить `top_k = step.top_k or settings_service.get("retrieval.top_k")`
  - В зависимости от `step.type`:
    - `book`: `hits = await retrieve(query, vault_id, document_ids=step.document_ids, top_k=top_k)`
    - `world`: `hits = await retrieve(query, vault_id, world_id=step.world_id, categories=step.categories, top_k=top_k)`
    - `campaign`: `hits = await retrieve(query, vault_id, campaign_id=step.campaign_id, top_k=top_k)`

  - Примечание: `vault_id` должен быть определён из контекста чата (пока не реализовано — будет передаваться в executor отдельным параметром или в `chat_context`; добавим `chat_context["vault_id"]`). Для простоты в этом Spec будем считать, что `chat_context` содержит `vault_id`.

  **4d. Форматирование контекста:** `context_block = format_context_with_role(hits, step.role)`

  **4e. Вызов LLM для шага:**

  - Промпт: `step.system_prompt` с подстановкой `{context}` → `format_prompt(step.system_prompt, {"context": context_block})`
  - Вызвать `generate()` (не стриминг, т.к. результаты промежуточных шагов не показываются пользователю, но `partial_result` сохраняется).
  - `partial_result = await llm.generate(prompt, ...)`

  **4f. Проверка отмены после вызова LLM.**

  **4g. Сохранить результат шага** в список `partial_results`.

  **4h. Отправить событие `step_done`:**
  ```python
  yield {
      "type": "step_done",
      "step": i,
      "step_name": step.name,
      "partial_length": len(partial_result)
  }
  ```

**Шаг 5. Финальная композиция**

- Объединить все `partial_results` с разделителем `"\n\n---\n\n"`.
- Подставить в `pipeline.final_composition.system_prompt` переменные:
  - `{context}` → объединённый текст
  - `{collected_fields}` → JSON-строка или пусто, если нет
- Вызвать `generate_stream()` для финального промпта.

**Шаг 6. Стриминг токенов**

```python
async for token in llm.generate_stream(prompt):
    if request and await request.is_disconnected():
        raise asyncio.CancelledError
    yield {"type": "token", "content": token}
```

**Шаг 7. Источники (sources)**

После окончания стрима собрать все хиты по шагам в формат `step_groups` (см. Spec-00, раздел 7.1):

```python
step_groups = []
for i, step in enumerate(steps, start=1):
    # hits для этого шага должны быть сохранены в список `step_hits_list`
    step_groups.append({
        "step": i,
        "step_name": step.name,
        "sources": [
            {"path": hit.metadata.get("source_path"), "page": hit.metadata.get("page_number"), "vault_id": hit.metadata.get("vault_id")}
            for hit in step_hits_list[i-1]
        ]
    })
yield {"type": "sources", "grouped_by_step": True, "step_groups": step_groups}
```

**Шаг 8. Обновление `pipeline_versions` (после успеха)**

```python
await db.execute(
    update(Chat)
    .where(Chat.id == chat_context["chat_id"])
    .values(pipeline_versions=func.jsonb_set(
        Chat.pipeline_versions,
        '{last_used,completed_at}',
        func.to_jsonb(datetime.utcnow().isoformat())
    ))
)
await db.commit()
```

**Обработка ошибок:**

- Если на любом шаге возникает исключение (ошибка LLM, ошибка retrieval), нужно отправить событие `{"type": "error", "message": str(exc)}` и завершить генератор. Не обновлять `completed_at` в `pipeline_versions`.
- При `CancelledError` — просто завершить генератор (без отправки error, можно отправить `[DONE]` или ничего).

### 3. Вспомогательные методы

- `_check_cancelled(request)` — статический метод для проверки.
- `_gather_sources_for_step(hits)` — преобразование хитов в формат sources.

### 4. Подготовка к интеграции в `chat.py`

В `chat.py` нужно будет:
- Получить объект пайплайна через `pipeline_service`.
- Создать `chat_context = {"chat_id": chat.id, "vault_id": chat.vault_id, "collected_fields": collected, "history": [...]}`.
- Вызвать `executor.run(pipeline, query, chat_context, db, request=request)` и пробросить события.

Это будет сделано в Spec-04c.

## Финальный контракт

- `pipeline_executor.py` создан, класс `PipelineExecutor` с методом `run` — асинхронный генератор.
- Поддерживает отмену через `request.is_disconnected()`.
- Отправляет SSE-события: `pipeline_selected`, `progress`, `step_done`, `token`, `sources`, `error`.
- Обновляет `chats.pipeline_versions` (started_at до выполнения, completed_at после).
- При ошибке или отмене не обновляет `completed_at`.

## Критерии приёмки

- [ ] Код компилируется без ошибок.
- [ ] `executor.run()` — генератор, yield события в правильном порядке.
- [ ] При `request.is_disconnected()` во время выполнения поднимается `CancelledError` и генератор завершается.
- [ ] Шаги пайплайна используют `retrieve()` с правильными параметрами фильтрации.
- [ `format_context_with_role` вызывается с ролью шага.
- [ ] `partial_results` объединяются с разделителем.
- [ ] Финальный промпт использует `{context}` и `{collected_fields}`.
- [ ] `sources` группируются по шагам в соответствии со Spec-00.
- [ ] `pipeline_versions` обновляется в БД (started_at до, completed_at после).