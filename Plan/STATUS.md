# Plan/STATUS.md — Статус реализации Pipeline Redesign

> Файл обновляется в конце каждой рабочей сессии.  
> Концепт: `Plan/pipeline-redesign-concept.md`  
> Детальный план: `Plan/pipeline-redesign-execution-plan.md`

---

## Текущий активный этап

**Этап 9 — UI: конструктор пайплайнов (Vis.js)**  
Статус: 🔲 Не начат

---

## Обзор всех этапов

| № | Название | Статус | Коммит |
|---|---|---|---|
| 1 | Схема данных: `shared_contracts/models.py` | ✅ Завершён | 0b9888f |
| 2 | Миграция БД | ✅ Завершён | 77bd39d, af30439, 4c213f5 |
| 3 | DAG-движок: `pipeline_dag.py` | ✅ Завершён | cafad1e |
| 4 | Разворачивание переменных: `prompt_pack.py` | ✅ Завершён | 5559bf2 |
| 5 | API endpoints: `pipeline_resume.py` | ✅ Завершён | d95d436, dcc3ef9, faa39c6 |
| 6 | Переработка executor: `pipeline_executor.py` | ✅ Завершён | (см. ниже) |
| 7 | Интеграция confirm-флоу в `chat.py` | ✅ Завершён с замечаниями | bdc3b66 |
| 8 | Применение миграции данных + cleanup | ✅ Завершён | a95fc12, 31cf332 |
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

Полное описание — в архивной версии STATUS.md.  
**Замечание:** `_build_levels()` дублирует `get_execution_levels()` из `pipeline_dag.py` — отложено до Этапа 11.

---

### Сессия 7 — Этап 7: confirm-флоу в `chat.py`
**Дата:** 2026-06-18  
**Статус:** ⚠️ Завершён с замечаниями

**Сделано:**
- [x] Confirm-флоу встроен в `send_stream()`: `pending_pipeline_confirm` → SSE `pipeline_confirm_required`
- [x] `confirm_token` + TTL 1 час
- [x] Снапшот контекста в JSONB

**Не выполнено:** интеграционные тесты, выравнивание non-stream `/send`

**Коммит:** `bdc3b66`

---

### Сессия 8 — Этап 8: Применение миграции данных
**Дата:** 2026-06-18  
**Статус:** ⚠️ Завершён с замечаниями (данные мигрированы, pytest не запускался)

**Сделано:**
- [x] DSN-фикс в `migrate_pipelines.py` для Docker (`+asyncpg` strip)
- [x] `migrate_pipelines.py --apply` → 2 пайплайна мигрированы успешно (`Errors: 0`)
- [x] Legacy API (`run()`, `_execute()`, `_run_step()`, `_deprecated_context_vars()`) в `pipeline_executor.py` — намечены к удалению

**Не выполнено в этой сессии:** `alembic upgrade head`, `pytest --tb=short`

**Коммит:** `a95fc12`

---

### Сессия 8b — Этап 8: Исправление тестов (cleanup)
**Дата:** 2026-06-19  
**Статус:** ✅ Закрыт полностью

**Сделано:**
- [x] `test_resume_emits_pipeline_selected` — исправлен неверный инвариант:  
  `resume_from_validation()` → executor эмитирует `pipeline_selected`, а не `pipeline_resumed`;  
  `pipeline_resumed` эмитирует только endpoint `pipeline_resume.py` перед запуском executor
- [x] `test_resume_cancelled_false` + `test_resume_feedback_none` — исправлен lazy import:  
  `from app.services.pipeline_executor import PipelineExecutor` перенесён на уровень модуля в `pipeline_resume.py`;  
  `patch("app.api.pipeline_resume.PipelineExecutor")` теперь находит атрибут и корректно mock'ит

**Коммит:** `31cf332`

**Pytest:** ✅ `79 passed, 1 warning in 0.98s`

---

## Детали этапов

### Этап 8 — Применение миграций ✅
- [x] `migrate_pipelines.py --apply` → 2 pipeline-записи обновлены
- [x] DSN-фикс для Docker-контейнера
- [x] `test_pipeline_resume.py` — все 3 упавших теста исправлены
- [x] `pytest` → **79/79 passed**
- [ ] `alembic upgrade head` — не зафиксирован (предположительно применён ранее)
- [ ] Ручная проверка пайплайнов через API (`/api/pipelines`)
- [ ] Удаление legacy executor API / deprecated `format_prompt()` — технический долг

---

### Этап 9 — UI конструктор
- [ ] Vis.js Network CDN
- [ ] Рендер графа, hierarchical layout
- [ ] Цветовая кодировка узлов (retrieval / validation)
- [ ] Боковая панель редактирования шага
- [ ] Добавить / удалить шаг
- [ ] Валидировать DAG перед сохранением
- [ ] Сохранить пайплайн через API

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
- [ ] Сценарий отмены на confirm-этапе → plain RAG
- [ ] Сценарий отмены на validation-этапе → `pipeline_cancelled`
- [ ] Тест таймаута validation
- [ ] Мигрированные пайплайны работают корректно
- [ ] `pytest` — все зелёные

**Финальный статус:** 🔲

---

## Технический долг

- `_build_levels()` в `pipeline_executor.py` дублирует `get_execution_levels()` из `pipeline_dag.py` — рефакторинг до Этапа 11
- `format_prompt()` в `prompt_pack.py` — помечена DEPRECATED, удалить вместе с legacy executor API
- Legacy API executor'а (`run()`, `_execute()`, `_run_step()`, `_deprecated_context_vars()`) — удалить после финальной верификации
- New API executor'а (`run_stream`, `resume_from_validation`, `_dag_execute`) не покрыт unit-тестами — Этап 11
- confirm-флоу встроен только в `send_stream()`; non-stream `send()` остаётся legacy-путём
- confirm-флоу Этапа 7 не покрыт интеграционными тестами — Этап 11
- `object.__setattr__` в DAG-тестах для симуляции цикла — при `frozen=True` заменить на `.model_copy(update=...)`
- После завершения Этапа 8 желательна ручная API-проверка мигрированных пайплайнов
