# 04 — Система пайплайнов (DAG)

## Концепция

Пайплайн — конфигурируемый граф обработки запроса пользователя:
1. **Pipeline Router** выбирает подходящий пайплайн для запроса (LLM-решение)
2. **Pipeline Executor** выполняет шаги DAG
3. **Final Composition** — финальный LLM-ответ на основе результатов шагов

## Типы шагов (`PipelineStep.type`)

### `retrieval`
- Делает векторный поиск в LanceDB
- Формирует контекст через LLM и возвращает ответ
- Поля: `top_k`, `tag_ids`, `role`, `output_format: text|json`
- Результат: строка или dict (при `output_format=json`)

### `validation`
- Задаёт вопрос пользователю и **ждёт ответа** (пауза DAG)
- Поля: `validation_prompt`, `options` (опциональный список вариантов)
- Пауза сохраняется в `Chat.pipeline_pause_state` (JSONB)
- Возобновление через `POST /pipeline_resume`

## Модель DAG (`pipeline_dag.py`)

```python
get_execution_levels(steps) -> list[list[PipelineStep]]
# Возвращает шаги, сгруппированные по уровням (топологическая сортировка)
# Шаги одного уровня могут выполняться параллельно
```

## Шаблоны переменных (`prompt_pack.py`)

В `system_prompt` шагов и `FinalComposition`:
- `{query}` — запрос пользователя
- `{STEP_ID.result}` — полный результат шага `STEP_ID` (строка)
- `{STEP_ID.key}` — поле `key` из JSON-результата шага (при `output_format=json`)

Разворачивание: `resolve_step_vars(template, step_results)` → `PipelineExecutionContext.resolve(template)`

## Confirm-флоу

Пайплайн может требовать подтверждения перед запуском:
1. Router выбирает пайплайн, Backend сохраняет в `Chat.pending_pipeline_confirm`
2. Frontend получает SSE-событие `pipeline_confirm_required`
3. Пользователь подтверждает → `POST /pipeline_confirm`
4. Пайплайн запускается

Подтверждение имеет `confirm_token` + TTL 1 час.

**Ограничение:** Confirm-флоу реализован только в `send_stream()`. Non-stream `/send` остаётся legacy-путём.

## API эндпоинты

```
POST /pipeline_confirm   # Подтверждение запуска пайплайна
POST /pipeline_resume    # Ответ на validation-шаг (возобновление DAG)
```

## Хранение пайплайнов

Два механизма:
1. **БД** (таблица `pipelines`) — управляемые через UI в `/db/ui`
2. **Hot-reload** из папки `/app/pipelines` — YAML/JSON файлы, перечитываются каждые 2s

## UI конструктор

Visual DAG-редактор на Vis.js в SPA:
- Drag-and-drop узлов (без drag рёбер — в техдолге)
- Создание шагов `retrieval` и `validation`
- Связи `after_step_ids`
- Горячие клавиши Del для узла — в техдолге

## Inline-карточки в чате

В ленте чата отображаются карточки хода выполнения пайплайна:
- Прогресс каждого шага
- Результаты retrieval
- Validation-запросы с вариантами ответов
- Итоговый ответ

## Ключевые файлы

```
rag-backend/app/services/
├── pipeline_dag.py       # Топологическая сортировка DAG
├── pipeline_executor.py  # Исполнение шагов
├── pipeline_router.py    # LLM-выбор пайплайна
├── pipeline_service.py   # CRUD операции
└── prompt_pack.py        # Разворачивание шаблонов

rag-backend/app/api/
├── pipeline_resume.py    # /pipeline_confirm + /pipeline_resume
└── chat.py               # SSE confirm_required, integration

shared_contracts/models.py # PipelineStep, PipelineExecutionContext...
```
