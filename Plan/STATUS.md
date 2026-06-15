# Plan/STATUS.md — Статус реализации Pipeline Redesign

> Файл обновляется в конце каждой рабочей сессии.  
> Концепт: `Plan/pipeline-redesign-concept.md`  
> Детальный план: `Plan/pipeline-redesign-execution-plan.md`

---

## Текущий активный этап

**Этап 1 — Схема данных: `shared_contracts/models.py`**  
Статус: 🔲 Не начат

---

## Обзор всех этапов

| № | Название | Статус | Коммит |
|---|---|---|---|
| 1 | Схема данных: `shared_contracts/models.py` | 🔲 Не начат | — |
| 2 | Миграция БД | 🔲 Не начат | — |
| 3 | DAG-движок: `pipeline_dag.py` | 🔲 Не начат | — |
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

**Следующий шаг:** Начать Этап 1 — переписать `shared_contracts/models.py`

---

## Детали этапов (заполняется по мере выполнения)

### Этап 1 — Схема данных
- [ ] Удалить `order`, `is_final`, `type="final"` из `PipelineStep`
- [ ] Добавить `step_id`, `after_step_ids`, `output_format`, `validation_prompt`, `options`
- [ ] Валидаторы: уникальность step_id, no self-loop, field restrictions по type
- [ ] Обновить `FinalComposition` (документирующий комментарий)
- [ ] Обновить `Pipeline`-модель (валидатор уникальности step_id)
- [ ] Запустить pytest, зафиксировать упавшие тесты

**Упавшие тесты после этапа:** _заполнить_  
**Коммит:** _заполнить_

---

### Этап 2 — Миграция БД
- [ ] Alembic-миграция: `pipeline_pause_state JSONB NULL` в `chats`
- [ ] Alembic-миграция: `pending_pipeline_confirm JSONB NULL` в `chats`
- [ ] Обновить ORM `Chat` в `db/models.py`
- [ ] Написать `tools/migrate_pipelines.py` (dry-run + --apply)
- [ ] Запустить dry-run, зафиксировать вывод

**Коммит:** _заполнить_

---

### Этап 3 — DAG-движок
- [ ] `build_dag()`
- [ ] `topological_sort()` → уровни параллельности
- [ ] `detect_cycles()` DFS
- [ ] `validate_dag()` агрегация ошибок
- [ ] `get_execution_levels()`
- [ ] Unit-тесты: линейный, параллельный, diamond, цикл, validation

**Все тесты зелёные:** _да/нет_  
**Коммит:** _заполнить_

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

_Записывать здесь всё замеченное но не исправленное в текущем этапе:_

- (пусто)
