
# Pipeline System Redesign — Общий концепт изменений

> Статус: утверждён | Следующий шаг: детализированный план изменений

Этот документ — **точка входа** для всей работы по переработке механизма пайплайнов в Mercer. На его основе будут создаваться:
- детализированный план изменений по файлам и задачам
- лог выполненных работ
- промпт-файл для копирования в контекст при реализации

---

## Почему переделываем

Текущий механизм пайплайнов поддерживает только строго последовательное выполнение шагов с числовым `order`. Это не позволяет запускать независимые шаги параллельно, именовать результаты шагов, обращаться к ним из последующих шагов, и останавливать выполнение на промежуточной проверке.

---

## Что меняется — обзор

1. **DAG-модель выполнения** вместо числовой последовательности: шаги образуют граф зависимостей через `after_step_ids`, независимые шаги одного уровня запускаются параллельно.
2. **Именованные шаги** (`step_id`) и **переменные результатов** — результат любого шага доступен в последующих через `{STEP_ID.result}` и `{STEP_ID.key}`.
3. **Новый тип шага — `validation`**: пайплайн приостанавливается, показывает промежуточный результат пользователю, ждёт его ответа или отмены.
4. **Подтверждение запуска**: каждый запуск пайплайна требует явного подтверждения пользователя через карточку в чате.
5. **Ломающие изменения в `FinalComposition`**: переменные `{context}` и `{collected_fields}` удаляются; вместо них — только `{STEP_ID.result}` / `{STEP_ID.key}`.
6. **Удаление рудиментов**: `type="final"`, `is_final`, числовой `order` убираются из кода и схем.

---

## 1. Новая модель шага — `PipelineStep`

### Текущая схема

```python
class PipelineStep(BaseModel):
    order: int
    type: Literal["retrieval", "final"]
    name: str
    system_prompt: str
    top_k: int | None
    tag_ids: list[str]
    is_final: bool          # рудимент, дублирует type="final"
    role: str | None
```

### Новая схема

```python
class PipelineStep(BaseModel):
    step_id: str                          # user-defined slug, e.g. "analyze", "classify"
    type: Literal["retrieval", "validation"]
    name: str                             # отображаемое название
    system_prompt: str                    # поддерживает {STEP_ID.result}, {STEP_ID.key}, {query}
    after_step_ids: list[str]             # [] = стартовый шаг

    # --- только для type=retrieval ---
    top_k: int | None
    tag_ids: list[str]
    role: str | None
    output_format: Literal["text", "json"] = "text"

    # --- только для type=validation ---
    validation_prompt: str | None         # что показать пользователю; поддерживает {STEP_ID.result}
    options: list[str] | None             # варианты выбора (опционально)
```

### Что изменилось и почему

| Поле | Было | Стало | Причина |
|---|---|---|---|
| `order: int` | Числовой порядок | — (удалено) | Порядок определяется графом `after_step_ids` |
| `step_id: str` | — | Пользовательский slug | Адресация результатов через переменные |
| `after_step_ids: list[str]` | — | Список ID предшественников | DAG-зависимости |
| `type` | `"retrieval"`, `"final"` | `"retrieval"`, `"validation"` | `"final"` — рудимент, удаляется |
| `is_final: bool` | Deprecated-поле | — (удалено) | Рудимент |
| `output_format` | — | `"text"` / `"json"` | JSON-ответы доступны по ключам |
| `validation_prompt` | — | Строка с переменными | Контент для показа пользователю при паузе |
| `options` | — | `list[str]` или `None` | Варианты выбора при валидации |

### Правила валидации схемы

- `step_id` уникален в рамках одного пайплайна
- `after_step_ids` не может содержать собственный `step_id` (self-loop запрещён)
- Поля `top_k`, `tag_ids`, `role`, `output_format` — только для `type=retrieval`
- Поля `validation_prompt`, `options` — только для `type=validation`
- `{STEP_ID.result}` в `system_prompt` допустим только если `STEP_ID` является предком в DAG
- `type=validation` без потомков (кроме `FinalComposition`) — ошибка при сохранении

---

## 2. FinalComposition — удаление устаревших переменных

`FinalComposition` остаётся отдельным объектом, не входит в `steps`.

```python
class FinalComposition(BaseModel):
    system_prompt: str
    # Поддерживаемые переменные:
    #   {STEP_ID.result}   — полный текстовый результат шага
    #   {STEP_ID.key}      — ключ из JSON-результата шага
    #   {query}            — запрос пользователя
    #
    # УДАЛЕНЫ (ломающее изменение):
    #   {context}          — заменить на явные {STEP_ID.result}
    #   {collected_fields} — если нужны — передать через validation-шаг
```

### Пример промпта после изменений

```
На основе анализа документов:

Классификация запроса: {classify.category}
Детальный анализ: {analyze.result}
Применимые правила: {rules.result}

Сформируй финальный ответ пользователю на запрос: {query}
```

### Миграция существующих пайплайнов

1. `{context}` → заменить на перечисление `{STEP_ID.result}` по всем шагам пайплайна
2. `{collected_fields}` → удалить из промптов, записать warning в лог миграции
3. `order: N` → `after_step_ids = [step_id шага с order=N-1]`; шаг `order=0` → `after_step_ids = []`
4. `type="final"` → удалить; `is_final` → удалить

---

## 3. Переменные результатов шагов

### Синтаксис

| Выражение | Смысл | Условие |
|---|---|---|
| `{STEP_ID.result}` | Полный текстовый результат шага | Всегда |
| `{STEP_ID.key}` | Значение ключа из JSON-результата | `output_format=json` |
| `{query}` | Запрос пользователя | Всегда |

### Логика разворачивания в `prompt_pack.py`

- `PipelineExecutionContext.step_results: dict[str, Any]` — накапливается по мере выполнения шагов
- `output_format=text` → `step_results[step_id] = "строка"`
- `output_format=json` → `step_results[step_id] = dict` после `json.loads()`; при неудаче — fallback к тексту, подробная запись в лог с исходным текстом
- `resolve_step_vars(template, step_results)` — regex-проход перед `str.format_map()`:
  - `{STEP_ID.result}` + строка → подставить строку
  - `{STEP_ID.result}` + dict → `json.dumps(dict)`
  - `{STEP_ID.key}` + dict → `dict[key]`
  - Не найден — оставить как есть, warning в лог

---

## 4. DAG-модель выполнения

### Правила графа

- Шаги с `after_step_ids = []` — стартовые (идут от виртуального узла "Начало")
- Граф ациклический (DAG); циклы проверяются DFS при сохранении пайплайна
- `FinalComposition` запускается когда все конечные шаги завершены

### Алгоритм исполнения

```
1. Построить граф зависимостей из after_step_ids
2. Топологическая сортировка (алгоритм Кана)
3. Определить уровни выполнения:
   Уровень 0: after_step_ids == []
   Уровень N: все предки завершены
4. Для каждого уровня:
   - Несколько шагов → asyncio.gather() с независимыми DB-сессиями
   - Один шаг → обычный await
5. Встречен type=validation → пауза (раздел 5)
6. Все шаги завершены → FinalComposition
```

### Параллельность и DB-сессии

Параллельные шаги не разделяют async SQLAlchemy-сессию. Каждый получает независимую сессию через `async_sessionmaker`.

### Пример DAG

```
[● Начало]
    ├──► [analyze]      after_step_ids: []
    └──► [classify]     after_step_ids: []
              │    │
              └──┬─┘
         [summarize]    after_step_ids: ["analyze", "classify"]
              │
         [👤 review]    after_step_ids: ["summarize"]   type=validation
              │
      [■ FinalComposition]
```

---

## 5. Шаг-валидация (human-in-the-loop)

### Концепт

Шаг `type=validation` приостанавливает пайплайн, показывает промежуточный результат пользователю и ждёт реакции:
- Замечание / уточнение → продолжить с этим текстом в `step_results`
- Выбор варианта из `options` → продолжить с выбором
- **Прервать выполнение** → пайплайн отменяется, состояние удаляется

**Таймаут:** 1 час. После истечения — пайплайн отменяется, состояние удаляется.

### Поток — пауза

```
1. Executor доходит до type=validation
2. Формирует контент: validation_prompt + подстановка {STEP_ID.result}
3. Сохраняет в chats.pipeline_pause_state (JSONB):
   {
     "status": "awaiting_validation",
     "paused_at_step_id": "review",
     "step_results": {...},
     "resume_token": "<uuid>",
     "expires_at": "<now + 1h>"
   }
4. Отправляет SSE-чанк, завершает текущий поток:
   {
     "type": "validation_required",
     "content": "...",
     "options": [...] | null,
     "resume_token": "...",
     "step_name": "..."
   }
5. Frontend рендерит inline-карточку в ленте чата:
   [текст / варианты выбора] + [поле ввода] + [Продолжить] [Прервать пайплайн]
```

### Поток — продолжение / отмена

```
POST /api/chat/{chat_id}/pipeline_resume
Body: { resume_token: str, user_feedback: str | null, cancelled: bool }

cancelled=true  → удалить pipeline_pause_state из БД
               → ответить: "Выполнение пайплайна прервано"

cancelled=false → восстановить контекст из pipeline_pause_state
               → step_results["_validation_{step_id}"] = user_feedback
               → удалить pipeline_pause_state из БД
               → продолжить executor со следующего шага
```

### Переменная результата validation-шага

```
{review.result}  →  текст ответа пользователя
```

### SSE-чанки

| `type` | Ключи |
|---|---|
| `validation_required` | `content`, `options`, `resume_token`, `step_name` |
| `pipeline_resumed` | `step_name`, `user_feedback_preview` |
| `pipeline_cancelled` | `step_name` |

---

## 6. Подтверждение запуска пайплайна

Каждый запуск пайплайна требует явного подтверждения. Единый алгоритм для всех пайплайнов.

### Поток

```
1. PipelineRouter.select() → пайплайн выбран
2. Сохраняет в chats.pending_pipeline_confirm (JSONB):
   {
     "pipeline_id": "...",
     "pipeline_name": "...",
     "reasoning": "...",
     "confirm_token": "<uuid>",
     "expires_at": "<now + 5min>"
   }
3. SSE-чанк:
   {
     "type": "pipeline_confirm_required",
     "pipeline_name": "...",
     "reasoning": "...",
     "confirm_token": "..."
   }
4. Frontend: inline-карточка в чате
   [название пайплайна + reasoning] + [Запустить] [Отменить]

confirmed=true  → POST /pipeline_confirm → удалить pending_pipeline_confirm → запустить executor
confirmed=false → POST /pipeline_confirm → удалить pending_pipeline_confirm → plain RAG fallback
```

---

## 7. UI конструктора пайплайнов

Визуальный DAG-редактор на **Vis.js Network** (layout: `hierarchical`, direction: `UD`).

### Структура экрана

```
┌─────────────────────────────────────────────────────┐
│  [+ Добавить шаг]  [Сохранить]  [Валидировать DAG]  │
├────────────────────────────┬────────────────────────┤
│  Canvas (Vis.js)           │  Боковая панель         │
│                            │  (при выборе шага)      │
│  [● Начало]                │                         │
│     ├── [analyze]          │  step_id:  [analyze]    │
│     └── [classify]         │  type:     retrieval ▼  │
│           └── [summarize]  │  name:     [.......]    │
│                 └── [👤]   │  prompt:   [.......]    │
│                       │    │  tags:     [+добавить]  │
│           [■ Final]        │  top_k:    [5]          │
│                            │  output:   text ▼       │
│                            │  [+ Дочерний шаг]       │
│                            │  [Удалить шаг]          │
└────────────────────────────┴────────────────────────┘
```

### Цветовая кодировка узлов

| Тип | Цвет |
|---|---|
| `retrieval` | Синий |
| `validation` | Оранжевый |
| `FinalComposition` | Фиолетовый (фиксированный, неудаляемый) |
| `● Начало` | Серый (виртуальный, фиксированный) |

---

## 8. Изменения в кодовой базе

### Изменить существующие файлы

| Файл | Что меняется |
|---|---|
| `shared_contracts/models.py` | Новая схема `PipelineStep`; удалить `order`, `is_final`, `type="final"`; добавить `step_id`, `after_step_ids`, `type="validation"`, `output_format`, `validation_prompt`, `options` |
| `rag-backend/app/services/pipeline_executor.py` | DAG-выполнение, `asyncio.gather` с независимыми сессиями, `step_results`, validation-пауза, resume, отмена |
| `rag-backend/app/services/prompt_pack.py` | Добавить `resolve_step_vars()`; удалить `{context}` и `{collected_fields}` |
| `rag-backend/app/api/chat.py` | `pipeline_confirm_required` перед запуском; обработка confirm/fallback и resume/cancel |
| `rag-backend/app/db/models.py` | JSONB-поля `pipeline_pause_state`, `pending_pipeline_confirm` в таблице `chats` |
| `rag-backend/app/static/` | UI конструктора (Vis.js); inline-карточки confirm и validation в ленте чата |

### Добавить новые файлы

| Файл | Назначение |
|---|---|
| `rag-backend/app/services/pipeline_dag.py` | Построение DAG, топологическая сортировка (алгоритм Кана), DFS-проверка циклов, определение уровней параллельности |
| `rag-backend/app/api/pipeline_resume.py` | Endpoints: `POST /pipeline_resume`, `POST /pipeline_confirm` |

### Миграции БД

1. JSONB-поля `pipeline_pause_state`, `pending_pipeline_confirm` → таблица `chats`
2. Схема `steps` → таблица `pipelines` (новый формат `PipelineStep`)
3. Скрипт миграции данных существующих пайплайнов (конвертация `order` → `after_step_ids`, замена `{context}`, удаление рудиментов)

---

## 9. Принятые решения

| Вопрос | Решение |
|---|---|
| Таймаут validation-паузы | 1 час; после — пайплайн отменяется, состояние удаляется |
| Параллельные шаги и DB-сессии | Независимая async-сессия через `async_sessionmaker` на каждый шаг |
| Подтверждение запуска | Каждый запуск любого пайплайна — обязательное подтверждение |
| JSON fallback при невалидном JSON | Fallback к тексту; в лог — подробная запись с исходным текстом |
| Отображение validation в чате | Inline-карточка в ленте чата |
| Отмена во время валидации | Кнопка "Прервать пайплайн"; `cancelled=true` в resume-запросе |
| Очистка состояния | `pipeline_pause_state` удаляется сразу после обработки resume или cancel |
| `{context}` / `{collected_fields}` | Удаляются (ломающее изменение), миграционный скрипт |
