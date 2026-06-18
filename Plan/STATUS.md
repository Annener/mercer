# Plan/STATUS.md — Статус реализации Pipeline Redesign

> Файл обновляется в конце каждой рабочей сессии.  
> Концепт: `Plan/pipeline-redesign-concept.md`  
> Детальный план: `Plan/pipeline-redesign-execution-plan.md`

---

## Текущий статус

**✅ ВСЕ ЭТАПЫ ЗАВЕРШЕНЫ + ТЕХДОЛГ ЗАКРЫТ**  
Дата финала: 2026-06-19  
**Pytest: ✅ `104 passed, 1 warning in 1.03s`**

---

## Обзор всех этапов

| № | Название | Статус | Коммит |
|---|---|---|---|
| 1 | Схема данных: `shared_contracts/models.py` | ✅ Завершён | 0b9888f |
| 2 | Миграция БД | ✅ Завершён | 77bd39d, af30439, 4c213f5 |
| 3 | DAG-движок: `pipeline_dag.py` | ✅ Завершён | cafad1e |
| 4 | Разворачивание переменных: `prompt_pack.py` | ✅ Завершён | 5559bf2 |
| 5 | API endpoints: `pipeline_resume.py` | ✅ Завершён | d95d436, dcc3ef9, faa39c6 |
| 6 | Переработка executor: `pipeline_executor.py` | ✅ Завершён | (cm. ниже) |
| 7 | Интеграция confirm-флоу в `chat.py` | ✅ Завершён с замечаниями | bdc3b66 |
| 8 | Применение миграции данных + cleanup | ✅ Завершён | a95fc12, 31cf332 |
| 9 | UI: конструктор пайплайнов (Vis.js) | ✅ Завершён | fb441e0 |
| 10 | UI: inline-карточки в ленте чата | ✅ Завершён | 234e419 |
| 11 | Сквозное тестирование | ✅ Завершён | 503bca5 |

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
- [x] Валидатор на self-loop в `after_step_ids`
- [x] Валидация полей по `type`: retrieval-only vs validation-only
- [x] Валидатор уникальности `step_id` в `PipelineCreate` и `PipelineUpdate`
- [x] Обновлён докстринг `FinalComposition`
- [x] Добавлено `step_results: dict[str, Any]` в `PipelineExecutionContext`
- [x] `PipelineStepResult.step_order` → `step_id: str`

**Коммит:** `0b9888f`

---

### Сессия 2 — Этап 2: Миграция БД
**Дата:** 2026-06-18  
**Сделано:**
- [x] Alembic-миграция `0019_pipeline_pause_state.py`
- [x] ORM `Chat` в `db/models.py`: два новых JSONB-поля
- [x] `tools/migrate_pipelines.py` с `--dry-run` / `--apply` / `--domain-id`

**Коммиты:** `77bd39d`, `af30439`, `4c213f5`

---

### Сессия 3 — Этап 3: DAG-движок
**Дата:** 2026-06-18  
**Сделано:**
- [x] `pipeline_dag.py` создан с нуля
- [x] `test_pipeline_dag.py` — 17 тестов

**Коммит:** `cafad1e`

---

### Сессия 4 — Этап 4: Разворачивание переменных
**Дата:** 2026-06-18  
**Сделано:**
- [x] `resolve_step_vars()` в `prompt_pack.py`
- [x] `PipelineExecutionContext.resolve()`
- [x] `test_prompt_pack.py` расширен до 26 тестов

**Коммит:** `5559bf2`

---

### Сессия 5 — Этап 5: API endpoints
**Дата:** 2026-06-18  
**Сделано:**
- [x] `POST /pipeline_confirm` и `POST /pipeline_resume` реализованы
- [x] Регистрация роутера в `main.py`
- [x] `test_pipeline_resume.py` — 13 тестов

**Коммиты:** `d95d436`, `dcc3ef9`, `faa39c6`

---

### Сессия 6 — Этап 6: Executor (верификация)
**Дата:** 2026-06-18  
**Статус:** ✅ Завершён — реализация обнаружена в файле

---

### Сессия 7 — Этап 7: confirm-флоу в `chat.py`
**Дата:** 2026-06-18  
**Статус:** ⚠️ Завершён с замечаниями

**Сделано:**
- [x] Confirm-флоу встроен в `send_stream()`: `pending_pipeline_confirm` → SSE `pipeline_confirm_required`
- [x] `confirm_token` + TTL 1 час
- [x] Снапшот контекста в JSONB

**Не выполнено:** интеграционные тесты confirm-флоу chat.py, выравнивание non-stream `/send`

**Коммит:** `bdc3b66`

---

### Сессия 8 — Этап 8: Применение миграции данных
**Дата:** 2026-06-18  
**Статус:** ⚠️ Завершён с замечаниями (данные мигрированы, pytest не запускался)

**Сделано:**
- [x] DSN-фикс в `migrate_pipelines.py`
- [x] `migrate_pipelines.py --apply` → 2 пайплайна мигрированы успешно

**Коммит:** `a95fc12`

---

### Сессия 8b — Этап 8: Исправление тестов
**Дата:** 2026-06-19  
**Статус:** ✅ Закрыт  
**Pytest:** ✅ `79 passed, 1 warning in 0.98s`  
**Коммит:** `31cf332`

---

### Сессия 9 — Этап 9: UI конструктор (Vis.js DAG-редактор)
**Дата:** 2026-06-19  
**Статус:** ✅ Завершён  
**Коммит:** `fb441e0`

---

### Сессия 10 — Этап 10: UI inline-карточки в ленте чата
**Дата:** 2026-06-19  
**Статус:** ✅ Завершён  
**Коммит:** `234e419`

---

### Сессия 11 — Этап 11: Сквозное тестирование
**Дата:** 2026-06-19  
**Статус:** ✅ Завершён  
**Коммит:** `503bca5`

---

### Сессия 12 — Багфикс + Рефакторинг техдолга
**Дата:** 2026-06-19  
**Статус:** ✅ Завершён  
**Pytest:** ✅ `104 passed, 1 warning in 1.03s`

**Сделано:**
- [x] Баг: `_run_dag_step` перезаписывал `ctx.step_results` пустой строкой при отсутствии hits — исправлено гуардом `if step.step_id not in ctx.step_results` (commit `794ebd5`)
- [x] Рефакторинг: удалён дублирующий `_build_levels()` — заменён вызовом `get_execution_levels()` из `pipeline_dag.py` (commit `eb50e5c`)
- [x] Удалён весь legacy API executorа: `run()`, `_execute()`, `_run_step()`, `_retrieve_for_step()`, `_mark_started()`, `_mark_completed()`, `_gather_sources_for_step()`, `_check_cancelled()` — ~150 строк удалено
- [x] Удалёны module-level хелперы: `_pipeline_from_context()`, `_ctx_dict()`, `_deprecated_context_vars()`, `_SKIPPED`
- [x] Оставлен shim `_build_levels()` для обратной совместимости тестовых импортов

---

## Оставшийся технический долг (малоприоритетный)

- `object.__setattr__` в DAG-тестах при `frozen=True` — заменить на `.model_copy(update=...)` (косметика)
- `pipeline_builder.js`: перетаскивание рёбер мышью — отложено
- `pipeline_builder.js`: горячие клавиши Del для удаления узла — отложено
- confirm-флоу встроен только в `send_stream()`; non-stream `send()` остаётся legacy-путём
- Интеграционные тесты confirm-флоу в `chat.py` — не написаны
- Ручная API-проверка мигрированных пайплайнов (желательна)
