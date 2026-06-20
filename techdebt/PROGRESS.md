# Трекер прогресса по техдолгу

Обновляй этот файл после каждого закрытого техдолга.

| # | Название | Приор | Статус | Коммит | Примечание |
|---|---|---|---|---|---|
| TD-01 | Ghost-синглтон PipelineRouter | 🔴 | ✅ Готово | ec70fa6 | Удалена 1 строка, без side effects |
| TD-02 | API-ключ через os.environ | 🔴 | ✅ Готово | — | — |
| TD-03 | LLMRAGPlanner мёртвый код | 🟡 | ✅ Готово | b9d6c8e | Удалён класс + 2 импорта, добавлены тесты |
| TD-04 | format_prompt deprecated | 🟡 | ✅ Готово | 003cf36 | Сценарий B: уточнён комментарий, проставлен TODO |
| TD-05 | decide() дублирует select() | 🟡 | ✅ Готово | 1eaf053 | Удалёны decide() + _chat_history(), 3 импорта |
| TD-06 | Пустая дир app/planners/ | 🟡 | ✅ Готово | 83d3773 | Удалён пустой __init__.py, директория убрана |
| TD-07 | Дубликация format_context | 🟠 | ✅ Готово | 99c3e2e | format_context(role=None) + тонкая обёртка format_context_with_role |
| TD-08 | async без await _default_top_k | 🟠 | ✅ Готово | e23f953 | Удалена async-функция, заменена модульной константой _DEFAULT_TOP_K |
| TD-09 | Дубликация _transaction() | 🟠 | ✅ Готово | cb189bf..02d1228 | Вынесено в app/db/utils.py::transactional(); удалено из 2 сервисов (16 вызовов) |
| TD-10 | Двойная фильтрация в retrieve() | 🟠 | ✅ Готово | a530cec | Убран x10 overfetch; постфильтр оставлен как leak-detector + metadata fallback |
| TD-11 | Мелкие замечания (батч) | 🟢 | ✅ Готово | 7569998 | A: import re на уровень модуля; B: N/A; C: комментарий TTL→API-слой; D: комментарий осознанного дублирования |

## Статусы

| Иконка | Смысл |
|---|---|
| ⬜ Не начато | - |
| 🔄 В процессе | Анализ или работа ведётся |
| ⏸️ Ожидает | Зависит от другой задачи |
| ✅ Готово | Коммит в main |
| ❌ Отменено | Решено иначе / не актуально |

## Журнал изменений

После закрытия каждого техдолга — записывай здесь краткую выжимку.

### TD-01

**Что было:** в конце `rag-backend/app/services/pipeline_router.py` сидела строка `pipeline_router = PipelineRouter.__new__(PipelineRouter)`. Она создавала экземпляр класса в обход `__init__`, тем самым `self.db = None` и остальные атрибуты не инициализированы. При любом обращении к синглтону — `AttributeError` в рантайме.

**Что сделано:** синглтон не использовался нигде (проверено поиском по кодовой базе). `chat.py` правильно инстанцирует `PipelineRouter(db)` локально. Строка удалена.

**SHA:** `ec70fa6` | **Side effects:** нет.

### TD-02
_—— заполнить после исправления —_

### TD-03

**Что было:** в `rag-backend/app/services/planner.py` жил мёртвый класс `LLMRAGPlanner` — LLM-декомпозитор запросов, который нигде не импортировался и не использовался. Аналогичная логика уже живёт в `query_rewriter.py`. Вместе с классом тянулись два неиспользуемых импорта (`get_generation_provider`, `GenerationProviderUnavailableError`).

**Что сделано:** удалены класс `LLMRAGPlanner` (~45 строк) и оба импорта. До изменений добавлены unit-тесты на `Planner` (8 тестов) + тест на отсутствие `LLMRAGPlanner` после удаления.

**SHA:** `b9d6c8e` | **Side effects:** нет.

### TD-04

**Что было:** функция `format_prompt` помечена DEPRECATED с размытым комментарием «будет удалён после Этапа 8». Анализ показал: функция не является мёртвым кодом — её активно использует `clarification_fsm.generate_next_question` с плейсхолдерами `{missing_fields}` / `{collected_fields}`, несовместимыми с `resolve_step_vars` (паттерн `{STEP_ID.accessor}`).

**Что сделано:** Сценарий B. В `prompt_pack.py` размытый комментарий заменён на конкретный: кто блокирует удаление, какие плейсхолдеры надо переименовать. В `clarification_fsm.py` добавлен `# TODO(TD-04)` на месте вызова.

**SHA:** `003cf36` (prompt_pack.py), `088258c` (clarification_fsm.py) | **Side effects:** нет.

### TD-05

**Что было:** метод `decide()` в `PipelineRouter` дублировал логику `select()` — тот же `PROMPT_TEMPLATE`, та же фильтрация пайплайнов, тот же LLM-вызов. Разница: `decide()` принимал `Chat` ORM и сам ходил в БД за историей (через `_chat_history()`), не имел фильтрации по campaign_id. Ни одного вызова в продакшн-коде не найдено.

**Что сделано:** Сценарий A. Удалены `decide()` (~40 строк) и `_chat_history()` (~8 строк). Убраны неиспользуемые импорты: `sqlalchemy.select`, `Chat`, `Message`.

**SHA:** `1eaf053` | **Side effects:** нет.

### TD-06

**Что было:** директория `app/planners/` содержала только пустой `__init__.py`. Ни одного импорта `from app.planners` нигде не найдено. `Planner` живёт в `app/services/planner.py` и переезжать не собирается.

**Что сделано:** Сценарий A. Удалён `__init__.py`, директория убрана Git-ом.

**SHA:** `83d3773` | **Side effects:** нет.

### TD-07

**Что было:** `format_context(hits)` и `format_context_with_role(hits, role)` в `retrieval.py` полностью дублировали логику построения нумерованных блоков (`source_index`, `numbered`, цикл `blocks`). Единственная разница — наличие заголовка `=== {role} ===` и поведение при пустом `hits` (заглушка vs пустая строка). При изменении формата контекста нужно было редактировать два места.

**Что сделано:** Объединены в одну функцию `format_context(hits, role=None)` с опциональным параметром. `format_context_with_role` стала однострочной обёрткой `return format_context(hits, role=role)`. Публичные сигнатуры обеих функций сохранены, поведение не изменилось. Добавлен раздел-разделитель `# Context formatting` для читаемости.

**SHA:** `99c3e2e` | **Side effects:** нет.

### TD-08

**Что было:** `async def _default_top_k() -> int` в `retrieval.py` — функция без единого `await`, вызывалась через `await _default_top_k()` в двух местах. Создавала корутину ради простого `os.getenv()`.

**Что сделано:** функция удалена, заменена модульной константой `_DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "10"))`. Вычисляется один раз при импорте. Оба `await _default_top_k()` заменены на `_DEFAULT_TOP_K`.

**SHA:** `e23f953` | **Side effects:** нет.

### TD-09

**Что было:** `@asynccontextmanager async def _transaction(self, db: AsyncSession)` — метод, скопированный дословно в `SettingsService` и `DomainService`. Итого 16 вызовов (`self._transaction(db)`) и две идентичные реализации. Любое изменение логики транзакций (savepoint, логирование) требовало правки в двух местах.

**Что сделано:** создан `rag-backend/app/db/utils.py` с публичной функцией `transactional(db: AsyncSession)`. Оба сервиса переключены на `from app.db.utils import transactional`, приватные методы `_transaction` удалены. Неиспользуемые импорты `asynccontextmanager` и `AsyncIterator` убраны из обоих сервисов.

**SHA:** `cb189bf` (utils.py), `d614a6d` (settings_service.py), `02d1228` (domain_service.py) | **Side effects:** нет. Alembic не затронут.

### TD-10

**Что было:** `retrieve()` применял фильтрацию по `document_ids` дважды: сначала через `filter_expr` в `_vector_search()` (на стороне LanceDB), затем повторно в Python после merge результатов. При этом включался `search_top_k = effective_top_k * 10`, а лог `post-filter applied` выглядел так, будто LanceDB-фильтр ненадёжен по умолчанию.

**Что сделано:** доверие к LanceDB сделано явным: `search_top_k` теперь всегда равен `effective_top_k`, x10 overfetch убран. Постфильтр оставлен только как защитный leak-detector и metadata fallback для edge case, когда `document_id` приходит только в `metadata`. Вводящий в заблуждение лог заменён на warning о реальной утечке фильтра (`filter leak`) — он теперь сигнализирует о возможной проблеме storage API, а не о штатном поведении.

**SHA:** `a530cec` | **Side effects:** нет. Alembic не затронут.

### TD-11

**Что было:** четыре мелких замечания в разных файлах.
- **11-A:** `import re` находился внутри тела функции `_score_from_response_text` в `retrieval.py` — нарушение конвенций, мешает статическому анализу (ruff/mypy).
- **11-B:** задача описывала f-string в `logger.*` в `planner.py` — при проверке файл уже использовал корректное `%s`-форматирование. N/A.
- **11-C:** константа `_VALIDATION_TTL` в `pipeline_executor.py` помечена комментарием «по концепту». `expires_at` записывается в `pipeline_pause_state`, но TTL не проверяется в самом executor. Это **сознательное архитектурное решение**: проверка принадлежит API-слою (`pipeline_resume` endpoint), не executor-у.
- **11-D:** `rag-backend/app/logging_config.py` и `rag-indexer/logging_config.py` — файлы с одинаковым SHA (`a3742b1d`). Вынос в `shared_contracts` потребовал бы изменения точки входа indexer. Решение: оставить дублирование, добавить явный комментарий с инструкцией синхронизировать оба файла при изменениях.

**Что сделано:**
- `retrieval.py`: `import re` перенесён на уровень модуля (после `import os`).
- `pipeline_executor.py`: комментарий к `_VALIDATION_TTL` расширен — явно зафиксировано, что TTL-check в API-слое, а не здесь.
- `rag-indexer/logging_config.py`: добавлен заголовочный комментарий об осознанном дублировании и требовании синхронной правки.

**SHA:** `7569998` | **Side effects:** нет. Alembic не затронут.
