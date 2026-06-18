# Mercer Pipeline Redesign — Детализированный план реализации

> Репозиторий: https://github.com/Annener/mercer  
> Концепт: `Plan/pipeline-redesign-concept.md`  
> Статус: см. `Plan/STATUS.md`

---

## Образ конечного результата

После выполнения всех этапов:

- Пайплайны выполняются как **DAG** (направленный ациклический граф): независимые шаги запускаются параллельно через `asyncio.gather`, порядок определяется `after_step_ids`, а не числовым `order`.
- Существует **тип шага `validation`** — human-in-the-loop пауза: пайплайн останавливается, отправляет SSE-карточку во фронтенд, ждёт ответа пользователя (таймаут 1 час).
- **Каждый запуск пайплайна** требует явного подтверждения через inline-карточку в чате.
- В `FinalComposition` и `system_prompt` работают переменные `{STEP_ID.result}` и `{STEP_ID.key}` — переменные `{context}` и `{collected_fields}` удалены.
- Конструктор пайплайнов в UI переработан: **визуальный DAG-редактор** на Vis.js Network.
- Все существующие пайплайны **мигрированы** на новый формат.

---

## Структура этапов

Каждый этап — отдельная сессия чата. Этапы атомарны: каждый оставляет кодовую базу в рабочем (или явно сломанном с пометкой) состоянии и фиксирует результат в `Plan/STATUS.md`.

---

## Этап 1 — Схема данных: `shared_contracts/models.py`

**Контекст для чата:** `context/00_index.md`, `context/04_pipelines.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Переписать Pydantic-модель `PipelineStep`. Это основа, от которой зависят все последующие этапы.

**Задачи:**
1. Удалить поля `order: int`, `is_final: bool`, `type="final"` из `PipelineStep`.
2. Добавить поля: `step_id: str`, `after_step_ids: list[str]`, `type: Literal["retrieval", "validation"]`, `output_format: Literal["text", "json"] = "text"`, `validation_prompt: str | None`, `options: list[str] | None`.
3. Добавить валидаторы (`@model_validator`):
   - `step_id` уникален в рамках пайплайна (проверяется на уровне `Pipeline`-модели).
   - `after_step_ids` не содержит собственный `step_id`.
   - Поля `top_k`, `tag_ids`, `role`, `output_format` — только для `type=retrieval`.
   - Поля `validation_prompt`, `options` — только для `type=validation`.
4. Обновить `FinalComposition`: убрать упоминание `{context}` и `{collected_fields}` из docstring/комментариев, добавить документирующий комментарий с поддерживаемыми переменными.
5. Обновить `Pipeline`-модель: убрать `order`-based сортировку, добавить валидатор уникальности `step_id`.
6. Запустить существующие тесты (`pytest`), зафиксировать какие упали.

**Результат:** Обновлённый `shared_contracts/models.py`, список сломанных тестов.

---

## Этап 2 — Миграция БД

**Контекст для чата:** `context/00_index.md`, `context/06_db_models.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Добавить JSONB-поля в таблицу `chats` и обновить схему хранения шагов в `pipelines`.

**Задачи:**
1. Создать Alembic-миграцию: добавить `pipeline_pause_state JSONB NULL` в таблицу `chats`.
2. Создать Alembic-миграцию: добавить `pending_pipeline_confirm JSONB NULL` в таблицу `chats`.
3. Обновить ORM-модель `Chat` в `rag-backend/app/db/models.py`: добавить два новых поля.
4. Написать **скрипт миграции данных** `tools/migrate_pipelines.py`:
   - Читает все записи из таблицы `pipelines`.
   - Конвертирует `order: N` → `after_step_ids = [step_id шага с order=N-1]`; `order=0` → `after_step_ids = []`.
   - Генерирует `step_id` из `name` (slug: lowercase, заменить пробелы на `_`).
   - Удаляет `is_final`, `type="final"`.
   - Заменяет `{context}` на перечисление `{STEP_ID.result}` по всем шагам пайплайна.
   - Удаляет `{collected_fields}` из промптов (пишет warning в лог).
   - Сохраняет результат в `pipelines.steps` (dry-run по умолчанию, `--apply` для записи).
5. Запустить скрипт в dry-run, зафиксировать вывод в `Plan/STATUS.md`.

**Результат:** Alembic-миграции, обновлённый ORM, скрипт `tools/migrate_pipelines.py`.

---

## Этап 3 — DAG-движок: `pipeline_dag.py`

**Контекст для чата:** `context/00_index.md`, `context/04_pipelines.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Создать отдельный модуль `rag-backend/app/services/pipeline_dag.py` с чистой DAG-логикой без зависимостей от БД или HTTP.

**Задачи:**
1. Функция `build_dag(steps: list[PipelineStep]) -> dict[str, list[str]]` — строит словарь `{step_id: [children]}`.
2. Функция `topological_sort(steps) -> list[list[str]]` — топологическая сортировка алгоритмом Кана, возвращает уровни параллельности (список списков `step_id`).
3. Функция `detect_cycles(steps) -> list[str] | None` — DFS-проверка циклов, возвращает цикл если есть.
4. Функция `validate_dag(steps) -> list[str]` — агрегирует все ошибки графа: циклы, несуществующие `after_step_ids`, нет стартового шага, validation без потомков.
5. Функция `get_execution_levels(steps) -> list[list[PipelineStep]]` — полная функция для executor: возвращает уровни с объектами шагов.
6. Написать unit-тесты в `tests/test_pipeline_dag.py`: линейный граф, параллельные ветки, граф с validation, обнаружение цикла, граф с diamond-зависимостью.

**Результат:** `pipeline_dag.py` + `tests/test_pipeline_dag.py`, все тесты зелёные.

---

## Этап 4 — Разворачивание переменных: `prompt_pack.py`

**Контекст для чата:** `context/00_index.md`, `context/07_rag_runtime.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Добавить функцию `resolve_step_vars()` и убрать старую логику `{context}` / `{collected_fields}`.

**Задачи:**
1. Добавить функцию `resolve_step_vars(template: str, step_results: dict[str, Any]) -> str`:
   - Regex-проход по шаблону: ищет `{STEP_ID.result}` и `{STEP_ID.key}`.
   - `{STEP_ID.result}` + строка → подставить строку.
   - `{STEP_ID.result}` + dict → `json.dumps(dict)`.
   - `{STEP_ID.key}` + dict → `dict[key]`, если ключ не найден — оставить placeholder, warning в лог.
   - Не найден STEP_ID — оставить как есть, warning в лог.
2. Расширить существующий `PipelineExecutionContext(BaseModel)` в `shared_contracts/models.py`:
   - Добавить поле `step_results: dict[str, Any] = Field(default_factory=dict)`.
   - Добавить метод `resolve(self, template: str) -> str` — делегирует в `resolve_step_vars(template, self.step_results)`.
   - **Не создавать новый класс** — `PipelineExecutionContext` уже существует как Pydantic BaseModel с полями `chat_id`, `query`, `pipeline_id` и др. Расширяем его.
   - Важно: выполнять этот шаг **после** Этапа 1, чтобы `model_dump()` / `model_validate()` работали с актуальной схемой `PipelineStep`.
3. Удалить (или задепрекейтить с raise) старые функции формирования `{context}` и `{collected_fields}` в `pipeline_executor.py` (не в `prompt_pack.py` — там этой логики нет).
4. Написать unit-тесты: text-результат, json-результат по ключу, отсутствующий step_id, отсутствующий ключ, `{query}`.

**Результат:** Обновлённый `prompt_pack.py` + расширенный `PipelineExecutionContext` в `models.py` + тесты.

---

## Этап 5 — API endpoints: `pipeline_resume.py`

**Контекст для чата:** `context/00_index.md`, `context/03_api_endpoints.md`, `context/06_db_models.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Создать два новых FastAPI-эндпоинта.

**Задачи:**
1. Создать `rag-backend/app/api/pipeline_resume.py`.
2. `POST /api/chat/{chat_id}/pipeline_confirm`:
   - Body: `{ confirm_token: str, confirmed: bool }`.
   - `confirmed=true`: проверить токен и `expires_at` в `chats.pending_pipeline_confirm`, запустить executor, вернуть SSE-стрим.
   - `confirmed=false`: очистить `pending_pipeline_confirm`, вернуть plain RAG fallback SSE-стрим.
   - Если токен просрочен: вернуть ошибку `410 Gone`.
3. `POST /api/chat/{chat_id}/pipeline_resume`:
   - Body: `{ resume_token: str, user_feedback: str | null, cancelled: bool }`.
   - `cancelled=true`: очистить `pipeline_pause_state`, отправить SSE-чанк `pipeline_cancelled`.
   - `cancelled=false`: восстановить контекст, добавить `step_results["_validation_{step_id}"] = user_feedback`, очистить `pipeline_pause_state`, продолжить executor (SSE-стрим).
   - Если токен просрочен: вернуть `410 Gone`.
4. Зарегистрировать роутер в `main.py`.
5. Написать интеграционные тесты (с mock DB).

**Результат:** `pipeline_resume.py` + регистрация + тесты.

---

## Этап 6 — Переработка executor: `pipeline_executor.py`

**Контекст для чата:** `context/00_index.md`, `context/04_pipelines.md`, `context/07_rag_runtime.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Заменить линейный executor на DAG-based с поддержкой параллельности и validation-пауз. Самый сложный этап.

**Задачи:**
1. Импортировать `get_execution_levels()` из `pipeline_dag.py` и `PipelineExecutionContext` из `shared_contracts/models.py`.
2. Переписать основной цикл: итерировать по уровням из `get_execution_levels()`.
3. Для уровня с несколькими шагами — `asyncio.gather()`, каждый шаг получает независимую `async_sessionmaker`-сессию.
4. Для одного шага — обычный `await`.
5. При встрече `type=validation`:
   - Вычислить `validation_prompt` через `ctx.resolve()`.
   - Сохранить `pipeline_pause_state` в БД (JSONB): `ctx.model_dump()` → JSONB.
   - Отправить SSE-чанк `{ "type": "validation_required", ... }`.
   - Завершить текущий стрим.
6. Метод `resume_from_validation(chat_id, resume_token, user_feedback)`:
   - Восстановить контекст: `PipelineExecutionContext.model_validate(pipeline_pause_state)`.
   - Продолжить с уровня после validation.
7. Убрать все ссылки на `order`, `is_final`, `type="final"`.
8. Убрать старую логику сборки `{context}` и `{collected_fields}` — использовать `ctx.resolve()`.

**Результат:** Переписанный `pipeline_executor.py`.

---

## Этап 7 — Интеграция confirm-флоу в `chat.py`

**Контекст для чата:** `context/00_index.md`, `context/03_api_endpoints.md`, `context/07_rag_runtime.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Встроить обязательное подтверждение запуска пайплайна перед executor.

**Задачи:**
1. После `PipelineRouter.select()`: вместо немедленного запуска executor — сохранить `pending_pipeline_confirm` в БД.
2. Отправить SSE-чанк `pipeline_confirm_required` с `pipeline_name`, `reasoning`, `confirm_token`.
3. Завершить стрим — ответ на запрос временно не приходит.
4. Логика продолжения — делегируется в `POST /pipeline_confirm` (Этап 5).
5. Убедиться что plain RAG fallback (при `confirmed=false`) корректно проходит через старый путь без executor.
6. Проверить locked-pipeline режим: при `chat.locked_pipeline_id` confirm тоже требуется.

**Результат:** Обновлённый `chat.py`, интеграционные тесты confirm-флоу.

---

## Этап 8 — Применение миграции данных

**Контекст для чата:** `context/00_index.md`, `context/06_db_models.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Применить Alembic-миграции и скрипт конвертации пайплайнов на тестовом окружении.

**Задачи:**
1. `alembic upgrade head` — применить миграции из Этапа 2.
2. Запустить `tools/migrate_pipelines.py --dry-run`, проверить вывод.
3. Запустить `tools/migrate_pipelines.py --apply`, проверить записи в БД.
4. Запустить полный `pytest`, зафиксировать результаты в `Plan/STATUS.md`.
5. Вручную проверить несколько пайплайнов через API: получить JSON через `GET /api/pipelines/{id}`, убедиться что структура новая.
6. Проверить что старые тесты с `order` / `is_final` удалены или обновлены.

**Результат:** Применённые миграции, все тесты зелёные (или зафиксированные исключения).

---

## Этап 9 — UI: конструктор пайплайнов (Vis.js)

**Контекст для чата:** `context/00_index.md`, `context/01_overview.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Переработать UI конструктора пайплайнов в `rag-backend/app/static/`.

**Задачи:**
1. Подключить Vis.js Network через CDN.
2. Реализовать рендер графа: `hierarchical` layout, direction `UD`.
3. Цветовая кодировка: retrieval=синий, validation=оранжевый, FinalComposition=фиолетовый, Start=серый.
4. Клик по узлу — открыть боковую панель с формой редактирования шага (поля согласно новой схеме).
5. Кнопка «+ Добавить шаг» — добавляет новый retrieval-шаг, соединяет с выбранным родителем.
6. Кнопка «+ Дочерний шаг» в боковой панели.
7. Кнопка «Удалить шаг» в боковой панели (запрещена для Start и FinalComposition).
8. Кнопка «Валидировать DAG» — вызывает `validate_dag()` через API, показывает ошибки.
9. Кнопка «Сохранить» — `PUT /api/pipelines/{id}` с новым JSON.
10. FinalComposition — фиксированный узел, редактируется в боковой панели (только `system_prompt`).

**Результат:** Обновлённый UI конструктора.

---

## Этап 10 — UI: inline-карточки в ленте чата

**Контекст для чата:** `context/00_index.md`, `context/03_api_endpoints.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Реализовать рендер SSE-чанков `pipeline_confirm_required` и `validation_required` во фронтенде.

**Задачи:**
1. В SSE-обработчике чата: распознать `type: "pipeline_confirm_required"`.
2. Рендерить confirm-карточку: название пайплайна, reasoning, кнопки «Запустить» / «Отменить».
3. «Запустить» → `POST /pipeline_confirm` с `confirmed=true`, продолжить стрим в той же ленте.
4. «Отменить» → `POST /pipeline_confirm` с `confirmed=false`, показать plain-ответ.
5. Распознать `type: "validation_required"`.
6. Рендерить validation-карточку: текст `content`, кнопки из `options` (если есть), поле ввода, кнопки «Продолжить» / «Прервать пайплайн».
7. «Продолжить» → `POST /pipeline_resume` с `cancelled=false`, продолжить стрим.
8. «Прервать» → `POST /pipeline_resume` с `cancelled=true`, показать сообщение об отмене.
9. Обработать `type: "pipeline_resumed"` и `type: "pipeline_cancelled"` — показать статусные строки в ленте.

**Результат:** Обновлённый JS-код чата.

---

## Этап 11 — Сквозное тестирование

**Контекст для чата:** `context/00_index.md`, `Plan/pipeline-redesign-concept.md`, `Plan/STATUS.md`

**Цель:** Проверить полный флоу end-to-end и устранить оставшиеся проблемы.

**Задачи:**
1. Написать интеграционный тест: создать пайплайн с двумя параллельными retrieval-шагами + validation + FinalComposition.
2. Запустить флоу: убедиться что confirm-карточка появляется, оба шага выполняются параллельно, validation-пауза работает корректно, FinalComposition использует `{STEP_ID.result}`.
3. Проверить сценарий отмены на confirm-этапе → plain RAG.
4. Проверить сценарий отмены на validation-этапе → `pipeline_cancelled`.
5. Проверить таймаут validation (тест с мокированием `expires_at = now - 1 second`).
6. Проверить что старые пайплайны (после миграции из Этапа 8) работают корректно.
7. Финальный `pytest --tb=short`, все тесты зелёные.
8. Обновить `Plan/STATUS.md`: статус = **DONE**.

**Результат:** Все тесты зелёные, система полностью функциональна.

---

## Правило для каждого этапа

В конце каждой рабочей сессии:
1. Зафиксировать изменения в git (`git commit`).
2. Обновить `Plan/STATUS.md` — отметить этап завершённым, записать что сделано и что осталось.
3. Если этап не завершён — зафиксировать ровно на каком шаге остановились.
