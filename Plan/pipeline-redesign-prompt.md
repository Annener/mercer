# Промт для рабочей сессии — Mercer Pipeline Redesign

> Скопируй этот промт целиком в начало нового чата перед работой над очередным этапом.

---

## Контекст проекта

Ты работаешь над проектом **Mercer** — RAG-платформой (чат-ассистент) на Python/FastAPI/PostgreSQL/LanceDB/Docker.

Репозиторий: https://github.com/Annener/mercer

Мы реализуем переработку системы пайплайнов согласно утверждённому концепту.

---

## Конечная цель (держи в голове всегда)

После завершения всей работы пайплайны в Mercer должны работать как DAG (направленный ациклический граф):
- Независимые шаги запускаются **параллельно** через `asyncio.gather()`
- Порядок определяется полем `after_step_ids`, поля `order` и `is_final` не существуют
- Существует тип шага **`validation`** — human-in-the-loop пауза: пайплайн останавливается, отправляет inline-карточку во фронтенд, ждёт ответа пользователя (таймаут 1 час)
- **Каждый запуск** любого пайплайна требует явного подтверждения через inline-карточку в чате
- В промптах работают переменные `{STEP_ID.result}` и `{STEP_ID.key}` — переменные `{context}` и `{collected_fields}` удалены
- UI конструктора пайплайнов — визуальный DAG-редактор на **Vis.js Network**

---

## Ключевые файлы для чтения перед работой

Прочитай в начале сессии (из репозитория):

**Обязательно:**
- `context/00_index.md` — навигатор по всей документации
- `Plan/pipeline-redesign-concept.md` — полный утверждённый концепт (источник истины)
- `Plan/STATUS.md` — **текущий статус**: какой этап активен, что уже сделано

**По задаче этапа** (смотри в STATUS.md какой этап активен):
- Этап 1 → `context/04_pipelines.md`
- Этап 2 → `context/06_db_models.md`
- Этапы 3–4 → `context/04_pipelines.md` + `context/07_rag_runtime.md`
- Этап 5 → `context/03_api_endpoints.md` + `context/06_db_models.md`
- Этапы 6–7 → `context/04_pipelines.md` + `context/07_rag_runtime.md`
- Этап 8 → `context/06_db_models.md`
- Этапы 9–10 → `context/01_overview.md` + `context/03_api_endpoints.md`
- Этап 11 → все файлы по необходимости

---

## Твои обязанности в этой сессии

1. Прочитай `Plan/STATUS.md` — определи текущий активный этап и шаг.
2. Прочитай файлы контекста для этого этапа (список выше).
3. Выполни задачи этапа согласно детализированному плану (`Plan/pipeline-redesign-execution-plan.md`).
4. В конце сессии:
   - Зафиксируй изменения в git
   - **Обнови `Plan/STATUS.md`**: отметь этап/шаг завершённым, запиши что сделано, что осталось, какие тесты упали

---

## Принципы работы

- **Не выходи за рамки этапа**: если видишь что-то смежное — запиши в STATUS.md как "замечено, не трогали", не правь.
- **Каждое изменение обосновано концептом**: если непонятно — смотри `Plan/pipeline-redesign-concept.md`.
- **Тесты**: после каждого этапа запускай `pytest`, фиксируй результат в STATUS.md.
- **Ломающие изменения**: `{context}` и `{collected_fields}` удаляются только при наличии миграционного скрипта (Этап 2), не раньше.
- **Параллельность и сессии**: параллельные шаги **не** разделяют async SQLAlchemy-сессию — каждый получает независимую через `async_sessionmaker`.

---

## Быстрая справка по новой схеме PipelineStep

```python
class PipelineStep(BaseModel):
    step_id: str                          # user-defined slug, e.g. "analyze"
    type: Literal["retrieval", "validation"]
    name: str
    system_prompt: str                    # поддерживает {STEP_ID.result}, {STEP_ID.key}, {query}
    after_step_ids: list[str]             # [] = стартовый шаг

    # только для type=retrieval:
    top_k: int | None
    tag_ids: list[str]
    role: str | None
    output_format: Literal["text", "json"] = "text"

    # только для type=validation:
    validation_prompt: str | None
    options: list[str] | None
```

## Быстрая справка по SSE-чанкам

| type | ключи |
|---|---|
| `pipeline_confirm_required` | `pipeline_name`, `reasoning`, `confirm_token` |
| `validation_required` | `content`, `options`, `resume_token`, `step_name` |
| `pipeline_resumed` | `step_name`, `user_feedback_preview` |
| `pipeline_cancelled` | `step_name` |

## Новые endpoints

- `POST /api/chat/{chat_id}/pipeline_confirm` — подтверждение/отмена запуска
- `POST /api/chat/{chat_id}/pipeline_resume` — продолжение/отмена после validation

---

*Этот промт актуален для всех этапов. Статус выполнения — в `Plan/STATUS.md`.*
