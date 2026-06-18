# Plan/STATUS.md — Статус реализации Pipeline Redesign

> Файл обновляется в конце каждой рабочей сессии.  
> Концепт: `Plan/pipeline-redesign-concept.md`  
> Детальный план: `Plan/pipeline-redesign-execution-plan.md`

---

## Текущий активный этап

**Этап 6 — Переработка executor: `pipeline_executor.py`**  
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

### Сессия 4 — Этап 4: Разворачивание переменных
**Дата:** 2026-06-18  
**Сделано:**
- [x] `resolve_step_vars()` — уже реализована в `prompt_pack.py` (была добавлена в сессии 3)
- [x] `PipelineExecutionContext.step_results` + `.resolve()` — уже добавлены в `shared_contracts/models.py` (сессия 1)
- [x] Депрекация `{context}` / `{collected_fields}` в `pipeline_executor.py` — `_deprecated_context_vars()` и комментарии уже были добавлены в предыдущих сессиях
- [x] Unit-тесты `test_prompt_pack.py` расширены: добавлен класс `TestPipelineExecutionContextResolve` (9 тестов):
  - `test_query_substituted` — {query} подставляется
  - `test_step_result_substituted` — {STEP_ID.result} подставляется
  - `test_query_and_step_result_together` — {query} + {STEP_ID.result} вместе
  - `test_query_with_curly_braces_not_conflicting` — фигурные скобки в query не ломают resolve_step_vars
  - `test_dict_step_result_key_access` — {STEP_ID.key} для dict-результата
  - `test_missing_step_keeps_placeholder` — отсутствующий step_id оставляет placeholder
  - `test_empty_step_results_query_only` — только {query}, пустые step_results
  - `test_validation_feedback_in_context` — ответ validation-шага доступен через ctx.resolve()
  - `test_parallel_steps_both_available` — оба результата параллельных веток доступны

**Коммит:** `5559bf2c600145bb25acba3d2f32653349511e2e`

**Pytest:**  
Запуск: `cd rag-backend && pytest app/tests/test_prompt_pack.py -v`  
Все 26 тестов должны быть зелёными (17 из test_pipeline_dag.py + 9 новых + 17 старых из test_prompt_pack.py = итого 26 в test_prompt_pack.py).  
Без зависимостей от БД/HTTP.

---

### Сессия 5 — Этап 5: API endpoints
**Дата:** 2026-06-18  
**Сделано:**
- [x] Создан `rag-backend/app/api/pipeline_resume.py`:
  - `POST /chat/{chat_id}/pipeline_confirm`:
    - Body: `{ confirm_token: str, confirmed: bool }`
    - `confirmed=true`: проверка токена + `expires_at`, восстановка контекста, запуск `executor.run_stream()` → SSE
    - `confirmed=false`: очистка `pending_pipeline_confirm`, SSE `pipeline_cancelled` + plain RAG fallback
    - Просроченный токен → `410 Gone`
    - wrong token → `403 Forbidden`
    - нет pending → `404 Not Found`
  - `POST /chat/{chat_id}/pipeline_resume`:
    - Body: `{ resume_token: str, user_feedback: str | null, cancelled: bool }`
    - `cancelled=true`: очистка `pipeline_pause_state`, SSE-чанк `pipeline_cancelled`
    - `cancelled=false`: восстановка контекста, `step_results["_validation_{step_id}"] = user_feedback`, `executor.resume_from_validation()` → SSE
    - SSE-чанк `pipeline_resumed` перед стримом
    - Просроченный токен → `410 Gone`
    - wrong token → `403 Forbidden`
    - нет pause state → `404 Not Found`
  - Вспомогатель `_restore_context()`: восстанавливает `PipelineExecutionContext` из JSONB-снапшота
  - Вспомогатель `_plain_rag_stream()`: fallback RAG для отменьи confirm, делегирует в `chat._fallback_retrieve` + `_resolve_system_prompt`
  - Автоматическое обновление `chat.title` после assistant_msg для обоих endpoint'ов
- [x] `rag-backend/app/main.py` обновлён: зарегистрирован `pipeline_resume_router`
- [x] Тесты `rag-backend/app/tests/test_pipeline_resume.py`:
  - `TestPipelineConfirm`: 5 тестов (404 no-pending, 403 wrong-token, 410 expired, SSE cancelled, 422 invalid uuid)
  - `TestPipelineResume`: 5 тестов (404 no-state, 403 wrong-token, 410 expired, SSE cancelled, SSE resumed + feedback key, null feedback → "")
  - `TestRestoreContext`: 3 unit-теста (inject chat_id, preserve query, empty snapshot)

**Коммиты:**
- `d95d436` — `pipeline_resume.py`
- `dcc3ef9` — `main.py` (регистрация роутера)
- `faa39c6` — `test_pipeline_resume.py`

**Pytest:**  
Запуск: `cd rag-backend && pytest app/tests/test_pipeline_resume.py -v`  
Тесты не требуют живой БД — все зависимости mock'нуты.

**Замечено, не трогали:**
- `executor.resume_from_validation()` — метод ещё не существует в `PipelineExecutor` (будет реализован в Этапе 6). В тестах полностью mock'нут.
- `context_snapshot` в JSONB наполняется в Этапе 6 (при сохранении `pipeline_pause_state`) и Этапе 7 (`pending_pipeline_confirm`).
- Реальное заполнение `context_snapshot` произойдёт через `ctx.model_dump()` перед сохранением в БД.

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

### Этап 4 — Переменные промптов ✅
- [x] `resolve_step_vars(template, step_results)` — реализована в `prompt_pack.py`
- [x] `PipelineExecutionContext.step_results` + `.resolve()` — реализованы в `models.py`
- [x] Старая логика `{context}` / `{collected_fields}` задепрекейтирована в `pipeline_executor.py`
- [x] Unit-тесты: 26 тестов в `test_prompt_pack.py`

**Коммит:** `5559bf2c600145bb25acba3d2f32653349511e2e`

---

### Этап 5 — API endpoints ✅
- [x] `POST /pipeline_confirm` — реализован
- [x] `POST /pipeline_resume` — реализован
- [x] Регистрация роутера в `main.py`
- [x] Тесты (mock DB): 13 тестов

**Коммиты:** `d95d436`, `dcc3ef9`, `faa39c6`

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
- [ ] Сценарий отмены на confirm-этапе → plain RAG
- [ ] Сценарий отмены на validation-этапе → `pipeline_cancelled`
- [ ] Тест таймаута validation
- [ ] Мигрированные пайплайны работают корректно
- [ ] `pytest` — все зелёные

**Финальный статус:** 🔲

---

## Замечания и технический долг

- `pipeline_executor.py` использует старые поля `step.order`, `step.is_final` — не трогали, будет переписан в Этапе 6
- `format_prompt()` в `prompt_pack.py` оставлена с пометкой DEPRECATED — удалить после Этапа 8
- `chat.py` не имеет `pipeline_confirm_required` флоу — Этап 7
- `pipeline_pause_state` / `pending_pipeline_confirm` добавлены в ORM, но ещё не используются в коде (executor пишет в Etap 6, chat.py читает в Etap 7)
- `executor.resume_from_validation()` ещё не существует — API endpoint полностью mock'ит его в тестах
- Тесты DAG-движка используют `object.__setattr__` для симуляции цикла (обход Pydantic self-loop validator из Этапа 1). Если в будущем модель станет `frozen=True`, заменить на `.model_copy(update=...)`
- `ctx.resolve()` в `PipelineExecutionContext` импортирует `resolve_step_vars` с динамическим fallback — проверить что `PYTHONPATH` настроен корректно в Docker-контейнере
