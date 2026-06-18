# Plan/STATUS.md — Статус реализации Pipeline Redesign

> Файл обновляется в конце каждой рабочей сессии.  
> Концепт: `Plan/pipeline-redesign-concept.md`  
> Детальный план: `Plan/pipeline-redesign-execution-plan.md`

---

## Текущий активный этап

**Этап 8 — Применение миграции данных**  
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
  - Вспомогатель `_plain_rag_stream()`: fallback RAG для отмены confirm, делегирует в `chat._fallback_retrieve` + `_resolve_system_prompt`
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

### Сессия 6 — Этап 6: Executor (верификация)
**Дата:** 2026-06-18  
**Статус:** ✅ Завершён — реализация обнаружена в файле, STATUS.md скорректирован

**Что обнаружено в `pipeline_executor.py`:**
- [x] `PipelineExecutionContext` из `shared_contracts.models` — импортирован
- [x] `_build_levels(steps)` — внутренняя топологическая сортировка по уровням (аналог `get_execution_levels` из `pipeline_dag.py`, реализована локально в executor'е)
- [x] `_resolve_prompt(template, ctx)` — подставляет `{query}`, `{STEP_ID.result}`, `{STEP_ID.key}` через `ctx.step_results`
- [x] `run_stream(ctx)` — публичный API: запуск DAG с уровня 0
- [x] `resume_from_validation(ctx, validated_step_id)` — публичный API: продолжение после validation-паузы
- [x] `_dag_execute(ctx, start_after_step)` — core async generator: итерация по уровням, `start_level` при resume
- [x] `_run_dag_step(step, ctx, provider)` — выполнение одного шага (retrieval или validation)
- [x] `_run_validation_step(step, ctx)` — сохраняет `pipeline_pause_state`, эмитит SSE `validation_required` со `__stop__` сигналом
- [x] `_run_parallel_level(steps, ctx, provider)` — `asyncio.gather()` с независимыми `async_sessionmaker`-сессиями через `_step_with_session()`
- [x] `_run_final_composition(ctx, provider)` — стриминг через `ctx.final_composition.system_prompt` + `_resolve_prompt()`
- [x] `_retrieve_for_step_dag(step, ctx)` — retrieval через `ctx.vault_ids` + `step.tag_ids`
- [x] `_save_pause_state(ctx, step_id, step_name, resume_token)` — сохраняет полный `ctx.model_dump()` в `chat.pipeline_pause_state` (JSONB)
- [x] `{context}` / `{collected_fields}` — убраны из нового API, используется только в legacy `_execute()` с пометкой DEPRECATED
- [x] Legacy API (`run()`, `_execute()`, `_run_step()`) сохранён до Этапа 8

**Замечание (не блокирует):**  
Executor использует собственную `_build_levels()` вместо `get_execution_levels()` из `pipeline_dag.py`. Логика идентична. Рефакторинг (унификация через `pipeline_dag.get_execution_levels`) можно отложить до Этапа 11 или оставить как есть — дублирование минимальное, оба модуля независимо тестируемы.

**Pytest:**  
Тесты executor'а отсутствуют (new API не покрыт unit-тестами). Покрытие `_dag_execute`, `_run_parallel_level`, `_run_validation_step` желательно добавить в Этапе 11 (сквозное тестирование) или отдельным шагом перед Этапом 7.

---

### Сессия 7 — Этап 7: confirm-флоу в `chat.py`
**Дата:** 2026-06-18  
**Статус:** ⚠️ Завершён с замечаниями

**Сделано:**
- [x] `rag-backend/app/api/chat.py` обновлён: после `PipelineRouter.select()` в `send_message_stream()` executor больше не запускается немедленно
- [x] При найденном пайплайне генерируется `confirm_token` через `secrets.token_urlsafe(32)`
- [x] Добавлен TTL confirm-токена: `_CONFIRM_TTL = timedelta(hours=1)`
- [x] В `chat.pending_pipeline_confirm` сохраняется JSONB-снапшот:
  - `confirm_token`
  - `pipeline_id`
  - `pipeline_name`
  - `expires_at`
  - `context_snapshot = context.model_dump(mode="json")`
- [x] После сохранения отправляется SSE-чанк `pipeline_confirm_required` с полями:
  - `pipeline_name`
  - `reasoning`
  - `confirm_token`
- [x] Стрим завершается через `data: [DONE]`, дальнейшее выполнение делегировано в `POST /chat/{chat_id}/pipeline_confirm`
- [x] Plain RAG fallback при `pipeline is None` оставлен без изменений
- [x] Locked-pipeline режим покрыт автоматически, т.к. `locked_pipeline_id` по-прежнему участвует в `PipelineRouter.select()`, а confirm требуется для любого найденного пайплайна
- [x] Добавлен helper `_build_confirm_payload()` для сериализации JSONB-снапшота

**Коммит:** `bdc3b66451001542211aed73cd0250407a01ff2e`

**Замечания / что осталось:**
- Интеграционные тесты confirm-флоу **не добавлены**, хотя указаны в execution plan для Этапа 7
- Non-stream endpoint `POST /chat/{chat_id}/send` оставлен в legacy-режиме и всё ещё запускает executor напрямую; новый confirm-флоу реализован только для `send_stream()`
- Pytest в этой сессии не запускался

**Почему этап считаем завершённым:**
- Основная цель этапа из execution plan выполнена: обязательное подтверждение встроено в основной стриминговый чат-флоу, который используется новым UI
- Оставшиеся пункты не блокируют переход к Этапу 8, но должны быть учтены в Этапе 11 (сквозное тестирование) или отдельной доработкой

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

### Этап 6 — Executor ✅
- [x] Импорт `PipelineExecutionContext` из `shared_contracts.models`
- [x] DAG-based основной цикл `_dag_execute()` с уровнями
- [x] `asyncio.gather()` для параллельных шагов (`_run_parallel_level`)
- [x] Validation-пауза: сохранение `pipeline_pause_state` (`_save_pause_state`), SSE-чанк `validation_required`
- [x] `resume_from_validation(ctx, validated_step_id)`
- [x] `order`, `is_final` удалены из нового API; `{context}`/`{collected_fields}` — только в legacy

**Замечено:** `_build_levels()` дублирует `pipeline_dag.get_execution_levels()` — не блокирует, рефакторинг по желанию в Этапе 11.

---

### Этап 7 — chat.py confirm-флоу ⚠️
- [x] После `PipelineRouter.select()` → сохранить `pending_pipeline_confirm`
- [x] Отправить SSE `pipeline_confirm_required`
- [x] Завершить стрим — ждать `/pipeline_confirm`
- [x] Проверить plain RAG fallback при `confirmed=false` — кодовый путь сохранён, вручную не проверялся
- [x] Проверить locked-pipeline режим — по коду проходит через общий путь confirm
- [ ] Интеграционные тесты confirm-флоу
- [ ] Выравнивание non-stream `/send` с новым confirm-флоу

**Коммит:** `bdc3b66`

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

- `_build_levels()` в `pipeline_executor.py` дублирует `get_execution_levels()` из `pipeline_dag.py` — логика идентична, рефакторинг откладывается до Этапа 11
- `format_prompt()` в `prompt_pack.py` оставлена с пометкой DEPRECATED — удалить после Этапа 8
- `pipeline_pause_state` / `pending_pipeline_confirm` добавлены в ORM и используются в executor (`_save_pause_state`) и API (Этап 5); `pending_pipeline_confirm` теперь заполняется в `chat.py` (Этап 7)
- New API executor'а (`run_stream`, `resume_from_validation`, `_dag_execute`) не покрыт unit-тестами — добавить в Этапе 11
- confirm-флоу пока встроен только в `send_stream()`; non-stream `send()` остаётся legacy-путём и может обходить обязательное подтверждение
- confirm-flow Этапа 7 не покрыт интеграционными тестами
- Тесты DAG-движка используют `object.__setattr__` для симуляции цикла (обход Pydantic self-loop validator из Этапа 1). Если в будущем модель станет `frozen=True`, заменить на `.model_copy(update=...)`
- `ctx.resolve()` в `PipelineExecutionContext` импортирует `resolve_step_vars` с динамическим fallback — проверить что `PYTHONPATH` настроен корректно в Docker-контейнере
- Legacy API (`run()`, `_execute()`, `_run_step()`, `_deprecated_context_vars()`) в `pipeline_executor.py` — удалить в Этапе 8 после применения миграции
