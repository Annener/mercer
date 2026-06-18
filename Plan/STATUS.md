# Plan/STATUS.md — Статус реализации Pipeline Redesign

> Файл обновляется в конце каждой рабочей сессии.  
> Концепт: `Plan/pipeline-redesign-concept.md`  
> Детальный план: `Plan/pipeline-redesign-execution-plan.md`

---

## Текущий активный этап

**Этап 4 — Разворачивание переменных: `prompt_pack.py`**  
Статус: 🔲 Не начат

---

## Обзор всех этапов

| № | Название | Статус | Коммит |
|---|---|---|---|
| 1 | Схема данных: `shared_contracts/models.py` | ✅ Завершён | 0b9888f |
| 2 | Миграция БД | ✅ Завершён | 77bd39d, af30439, 4c213f5 |
| 3 | DAG-движок: `pipeline_dag.py` | ✅ Завершён | cafad1e |
| 4 | Разворачивание переменных: `prompt_pack.py` | 🔲 Не начат | — |
| 5 | API endpoints: `pipeline_resume.py` | 🔲 Не начат | — |
| 6 | Переработка executor: `pipeline_executor.py` | 🔲 Не начат | — |
| 7 | Интеграция confirm-флоу в `chat.py` | 🔲 Не начат | — |
| 8 | Применение миграции данных | 🔲 Не начат | — |
| 9 | UI: конструктор пайплайнов (Vis.js) | 🔲 Не начат | — |
| 10 | UI: inline-карточки в ленте чата | 🔲 Не начат | — |
| 11 | Сквозное тестирование | 🔲 Не начат | — |

**Легенда:** 🔲 Не начат | 🔄 В процессе | ✅ Завершён | ⚠️ Завершён с замечаниями

---

## Лог сессий

### Сессия 0 — Инициализация плана
**Дата:** 2026-06-15  
**Сделано:**
- Создан `Plan/pipeline-redesign-execution-plan.md` — детализированный план на 11 этапов
- Создан `Plan/STATUS.md` (этот файл) — служебный трекер
- Создан `Plan/pipeline-redesign-prompt.md` — промт для копирования в новые чаты

---

### Сессия 1 — Этап 1: Схема данных
**Дата:** 2026-06-18  
**Сделано:**
- [x] Удалены `order`, `is_final`, `type="final"` из `PipelineStep`
- [x] Добавлены `step_id`, `after_step_ids`, `output_format`, `validation_prompt`, `options`
- [x] Добавлен `type="validation"` в `PipelineStep`
- [x] Валидатор на self-loop в `after_step_ids` (`@model_validator` на `PipelineStep`)
- [x] Валидация полей по `type`: retrieval-only vs validation-only
- [x] Валидатор уникальности `step_id` в `PipelineCreate` и `PipelineUpdate`
- [x] Обновлён докстринг `FinalComposition` (новые переменные, удалённые)
- [x] Добавлено `step_results: dict[str, Any]` в `PipelineExecutionContext`
- [x] `PipelineStepResult.step_order` → `step_id: str`

**Коммит:** `0b9888f7c2f57e354199229885b81359f42edbde`

**Pytest:** Не запускались локально в этой сессии (CI на GitHub). Ожидаемые сломающие изменения:
- Любой код, создающий `PipelineStep` с `order`/`is_final` — падёт с `ValidationError`
- Любой код, обращающийся к `PipelineStepResult.step_order` — `AttributeError`
- `pipeline_executor.py` (ещё не переписан) использует `step.order` и `step.is_final` — упадёт при запуске

---

### Сессия 2 — Этап 2: Миграция БД
**Дата:** 2026-06-18  
**Сделано:**
- [x] Alembic-миграция `0019_pipeline_pause_state.py`:
  - Добавлена колонка `pipeline_pause_state JSONB NULL` в `chats`
  - Добавлена колонка `pending_pipeline_confirm JSONB NULL` в `chats`
  - `down_revision = "0018"`, `revision = "0019"`
  - `downgrade()` через `drop_column`
- [x] ORM `Chat` в `db/models.py`: добавлены два `Mapped[dict | None]` поля с комментариями по структуре JSONB
- [x] `tools/migrate_pipelines.py`:
  - `--dry-run` — печатает diff без записи, exit 1 если есть что мигрировать
  - `--apply` — применяет изменения в БД
  - `--domain-id` — фильтр по домену
  - Миграция: `order`-сортировка шагов, генерация `step_id = "step_N"`, построение `after_step_ids` цепочкой
  - Шаг `type=="final"` извлекается из `steps[]` и переносится в `final_composition.system_prompt`

**Коммиты:**
- `77bd39d` — Alembic-миграция 0019
- `af30439` — ORM Chat (два новых JSONB-поля)
- `4c213f5` — `tools/migrate_pipelines.py`

**Pytest / dry-run:**
- `alembic upgrade head` и `migrate_pipelines.py --dry-run` запускаются вручную на Этапе 8
- Pytest: не запускались в этой сессии (требуется живой БД)

---

### Сессия 3 — Этап 3: DAG-движок
**Дата:** 2026-06-18  
**Сделано:**
- [x] `rag-backend/app/services/pipeline_dag.py` создан с нуля
  - `build_dag(steps)` — строит `{step_id: [children]}`
  - `topological_sort(steps)` — алгоритм Кана, возвращает `list[list[str]]` уровней
  - `detect_cycles(steps)` — DFS с трёхцветной маркировкой, возвращает список step_id цикла или None
  - `validate_dag(steps)` — агрегирует ошибки: отсутствие стартового шага, ссылки на несуществующие step_id, цикл, validation без потомков
  - `get_execution_levels(steps)` — возвращает `list[list[PipelineStep]]` для executor; при цикле бросает `ValueError`
- [x] `rag-backend/app/tests/__init__.py` создан
- [x] `rag-backend/app/tests/test_pipeline_dag.py` создан:
  - `TestBuildDag`: linear chain, parallel branches, unknown parent ignored
  - `TestTopologicalSort`: linear, parallel level, diamond, cycle returns empty
  - `TestDetectCycles`: no cycle, direct cycle, self-loop via validator
  - `TestValidateDag`: valid linear, no start step, missing after_step_id, cycle detected, validation without children, validation with children OK
  - `TestGetExecutionLevels`: linear levels, parallel same level, cycle raises ValueError, validation in levels

**Коммит:** `cafad1e13f5a314e2682f2cefd4d5b320187f2bf`

**Pytest:** Не запускались в этой сессии (нет live-окружения). Тесты написаны без зависимостей от БД/HTTP.  
Запуск: `cd rag-backend && pytest app/tests/test_pipeline_dag.py -v`

**Замечено, не трогали:**
- `shared_contracts/models.py` уже содержит `step_results: dict[str, Any]` (из Этапа 1) — `get_execution_levels` работает с ним напрямую через атрибуты объекта
- Тест `test_self_loop_via_validator` ожидает `ValidationError` при `after_step_ids=["a"]` для шага с `step_id="a"` — зависит от наличия `@model_validator` из Этапа 1
- `object.__setattr__` использован в тестах для обхода Pydantic frozen/validator при симуляции цикла — если модель не `model_config = ConfigDict(frozen=True)`, можно использовать `.model_copy(update=...)`

---

## Детали этапов (заполняется по мере выполнения)

### Этап 1 — Схема данных ✅
Все пункты выполнены. См. лог сессии 1.

---

### Этап 2 — Миграция БД ✅
Все пункты выполнены. См. лог сессии 2.

---

### Этап 3 — DAG-движок ✅
Все пункты выполнены. См. лог сессии 3.

---

### Этап 4 — Переменные промптов
- [ ] `resolve_step_vars(template, step_results)`
- [ ] `PipelineExecutionContext` dataclass
- [ ] Удалить/задепрекейтить логику `{context}`, `{collected_fields}`
- [ ] Unit-тесты

**Коммит:** _заполнить_

---

### Этап 5 — API endpoints
- [ ] `POST /pipeline_confirm`
- [ ] `POST /pipeline_resume`
- [ ] Регистрация роутера в `main.py`
- [ ] Интеграционные тесты

**Коммит:** _заполнить_

---

### Этап 6 — Executor
- [ ] Импорт DAG-движка и ExecutionContext
- [ ] DAG-based основной цикл с уровнями
- [ ] `asyncio.gather()` для параллельных шагов
- [ ] Validation-пауза: сохранение `pipeline_pause_state`, SSE-чанк
- [ ] `resume_from_validation()`
- [ ] Удалить `order`, `is_final`, `{context}`

**Коммит:** _заполнить_

---

### Этап 7 — chat.py confirm-флоу
- [ ] После `PipelineRouter.select()` → сохранить `pending_pipeline_confirm`
- [ ] Отправить SSE `pipeline_confirm_required`
- [ ] Проверить plain RAG fallback
- [ ] Проверить locked-pipeline режим

**Коммит:** _заполнить_

---

### Этап 8 — Применение миграций
- [ ] `alembic upgrade head`
- [ ] `migrate_pipelines.py --dry-run` → проверить вывод
- [ ] `migrate_pipelines.py --apply` → проверить записи в БД
- [ ] `pytest --tb=short` → все зелёные
- [ ] Ручная проверка пайплайнов через API

**Pytest результат:** _заполнить_

---

### Этап 9 — UI конструктор
- [ ] Vis.js Network CDN
- [ ] Рендер графа, hierarchical layout
- [ ] Цветовая кодировка
- [ ] Боковая панель редактирования
- [ ] Добавить/удалить шаг
- [ ] Валидировать DAG
- [ ] Сохранить пайплайн

**Коммит:** _заполнить_

---

### Этап 10 — UI карточки в чате
- [ ] `pipeline_confirm_required` → confirm-карточка
- [ ] `validation_required` → validation-карточка
- [ ] `pipeline_resumed` / `pipeline_cancelled` → статусные строки

**Коммит:** _заполнить_

---

### Этап 11 — Сквозное тестирование
- [ ] Интеграционный тест: параллельные шаги + validation + FinalComposition
- [ ] Сценарий отмены на confirm-этапе
- [ ] Сценарий отмены на validation-этапе
- [ ] Тест таймаута validation
- [ ] Мигрированные пайплайны работают корректно
- [ ] `pytest` — все зелёные

**Финальный статус:** 🔲

---

## Замечания и технический долг

- `pipeline_executor.py` использует старые поля `step.order`, `step.is_final` — не трогали, будет переписан в Этапе 6
- `prompt_pack.py` использует `{context}` и `{collected_fields}` — не трогали, будет переписан в Этапе 4
- `chat.py` не имеет `pipeline_confirm_required` флоу — Этап 7
- `collected_fields` в `PipelineExecutionContext` удален (был в старом контексте документации, но не был в коде — замечено)
- `pipeline_pause_state` / `pending_pipeline_confirm` добавлены в ORM, но ещё не используются в коде — будут задействованы в Этапах 6 и 7
- Тесты DAG-движка используют `object.__setattr__` для симуляции цикла (обход Pydantic self-loop validator из Этапа 1). Если в будущем модель станет `frozen=True`, заменить на `.model_copy(update=...)`
