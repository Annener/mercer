# Bug Report: ветка `plan-search` — Token-Map Anchoring

> Сгенерировано по результатам code review ветки `plan-search`.  
> Каждый баг — самостоятельный шаг. Фиксить по порядку приоритета.

---

## Контекст задачи

Решается проблема: LLM генерирует `anchor.value` из нормализованного текста (после `preprocess()`), а resolver ищет якорь в raw-файле на диске. Из-за трансформаций `preprocess()` (newline→space, em-dash→дефис, дефисные переносы, мягкий дефис, NFC) прямой поиск падает с `AnchorNotFoundError`.

Решение реализовано через построение char-map (`normalized_pos → raw_pos`), поиск якоря в нормализованном тексте, извлечение raw-фрагмента и повторный `apply_op` с ним.

### Затронутые файлы

| Файл | Статус |
|------|--------|
| `rag-indexer/app/update_mode/text_ops_utils.py` | НОВЫЙ |
| `rag-indexer/app/update_mode/text_ops.py` | ИЗМЕНЁН |
| `rag-indexer/app/update_mode/token_anchor.py` | НОВЫЙ |
| `rag-indexer/app/update_mode/resolver.py` | ИЗМЕНЁН |
| `rag-indexer/parser/preprocessing/preprocessor.py` | ИСТОЧНИК ИСТИНЫ (не менять) |
| `rag-indexer/tests/test_token_anchor.py` | ТЕСТЫ unit |
| `rag-indexer/tests/test_token_anchor_fallback.py` | ТЕСТЫ integration |

---

## 🔴 БАГ 1 — Импорт приватного символа `_HEADING_FULL_LINE_RE`

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`  
**Серьёзность:** Критично (нарушение архитектурного концепта + хрупкость)

### Описание

В строке импорта `token_anchor.py` среди прочего импортируется `_HEADING_FULL_LINE_RE` из `preprocessor.py`. Этот символ приватный (начинается с `_`). Концепт явно запрещает импорт приватных символов из чужих модулей.

Проблема: при переименовании или рефакторинге `_HEADING_FULL_LINE_RE` в `preprocessor.py` `token_anchor.py` сломается с `ImportError` без явного предупреждения на уровне публичного API.

### Что нужно знать для фикса

- `_HEADING_FULL_LINE_RE` в `preprocessor.py` — это `re.compile(r"^(#{1,6}\s[^\n]*)", re.MULTILINE)`. Паттерн матчит **всю строку** Markdown-заголовка от `#` до конца строки, без перехода на следующую.
- В `token_anchor.py` этот паттерн используется в шаге 4b `build_char_map` для обработки заголовков — логика шага 4b должна остаться **идентичной** preprocessor.py.
- Решение: объявить локальную переменную с тем же паттерном внутри `token_anchor.py`, не импортируя из preprocessor. Имя переменной может совпадать или отличаться — главное не импортировать приватный символ.
- Строку импорта `_HEADING_FULL_LINE_RE` из `preprocessor.py` нужно убрать.

---

## 🔴 БАГ 2 — Молчаливая частичная карта при рассинхроне длин

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `build_char_map`  
**Серьёзность:** Критично (ложные результаты без сигнала об ошибке)

### Описание

В конце `build_char_map` есть проверка `len(final_offsets) != len(normalized)`. При несовпадении функция логирует warning и возвращает **усечённую карту** (`final_offsets[:min_len]`) вместо того чтобы явно сигнализировать об ошибке.

Последствие: `extract_raw_fragment` получает карту, в которой позиции сдвинуты, и возвращает **неверный raw-фрагмент** без каких-либо признаков ошибки. `apply_op` применяет операцию к неверному фрагменту — тихая порча данных.

### Что нужно знать для фикса

- Рассинхрон длин `final_offsets` и `normalized` означает, что какой-то шаг в `build_char_map` воспроизводит `preprocess()` некорректно — это баг алгоритма, а не нормальная ситуация.
- При несовпадении длин нужно возвращать `None` из `build_char_map` (изменить возвращаемый тип на `list[int] | None`), и соответственно обрабатывать `None` в `resolve_anchor_in_raw`: логировать warning и возвращать `None` (якорь не найден через fallback).
- Альтернатива — бросать специальное исключение `CharMapSyncError`, но возврат `None` проще и согласован с тем, как `resolve_anchor_in_raw` уже обрабатывает случай "якорь не найден".
- Строку `return final_offsets[:min_len]` нужно заменить.
- Docstring функции нужно обновить: указать что при рассинхроне возвращается `None`.

---

## 🔴 БАГ 3 — Мёртвый код: внешний `except ContentTooLargeError` в fallback-блоке

**Файл:** `rag-indexer/app/update_mode/resolver.py`, функция `_resolve_one`  
**Серьёзность:** Средне (мёртвый код создаёт ложное ощущение защиты)

### Описание

В fallback-блоке (внутри `except AnchorNotFoundError`) вызов `apply_op(...)` обёрнут во внешний `try/except ContentTooLargeError`. Но `apply_op` **никогда** не бросает `ContentTooLargeError` — эту ошибку бросает только `_build_pending_change`. Внутренний `try/except ContentTooLargeError` вокруг `_build_pending_change` правильный. Внешний — никогда не срабатывает.

### Что нужно знать для фикса

- `ContentTooLargeError` определена в `resolver.py` и бросается исключительно из `_build_pending_change` при превышении `_MAX_CONTENT_BYTES = 10 MB`.
- `apply_op` из `text_ops.py` бросает только: `AnchorNotFoundError`, `AnchorAmbiguousError`, `UnsupportedOperationError`.
- В fallback-блоке структура должна быть: `apply_op` не в try/except ContentTooLargeError, а `_build_pending_change` — в try/except ContentTooLargeError.
- Нужно убрать внешний `try/except ContentTooLargeError` вокруг `apply_op` в fallback, оставив только внутренний вокруг `_build_pending_change`.
- Остальные except-ветки в fallback (`AnchorAmbiguousError`, `AnchorNotFoundError`) трогать не нужно.

---

## 🔴 БАГ 4 — Тест `test_fallback_ambiguous_raw_fragment` допускает лишний error_code

**Файл:** `rag-indexer/tests/test_token_anchor_fallback.py`  
**Серьёзность:** Средне (маскирует потенциальное несоответствие спецификации)

### Описание

Тест проверяет случай когда fallback находит raw_fragment, но он встречается в исходном тексте дважды. Assert написан как:
```
assert result.error_code in ("anchor_ambiguous", "anchor_not_unique")
```
Это допускает `anchor_not_unique` — код, который используется в **основном пути** для `AnchorAmbiguousError` при операциях `REPLACE_UNIQUE_TEXT`/`DELETE_UNIQUE_TEXT`. По концепту fallback при двойном совпадении raw_fragment должен возвращать именно `anchor_ambiguous`.

### Что нужно знать для фикса

- В `resolver.py` fallback-блок при `AnchorAmbiguousError` явно вызывает `return _fail("anchor_ambiguous", ...)` — это единственный возможный код в данной ветке.
- `anchor_not_unique` используется только в основном `except AnchorAmbiguousError` (не в fallback) для операций `REPLACE_UNIQUE_TEXT` и `DELETE_UNIQUE_TEXT`.
- Тест нужно ужесточить: assert должен проверять строго `== "anchor_ambiguous"`, без `in (...)`.
- Контекст теста: raw содержит фрагмент дважды, нормализованный якорь совпадает с raw (нет трансформаций), поэтому прямой `apply_op` тоже упадёт с `AnchorAmbiguousError` (или `AnchorNotFoundError` + fallback тоже найдёт дважды). Логику теста менять не нужно — только assert.

---

## 🟡 БАГ 5 — Пробельный якорь проходит guard-проверку в fallback

**Файл:** `rag-indexer/app/update_mode/resolver.py`, функция `_resolve_one`  
**Серьёзность:** Низко (редкий кейс, но ведёт к ложному match)

### Описание

В fallback-блоке проверка активации выглядит как `exc.anchor_value` (truthy check). Якорь из одних пробелов (`"   "`) — truthy строка, пройдёт проверку. `build_anchor_pattern` после внутреннего `.strip()` и фильтрации пустых токенов вернёт паттерн для пустой строки (`re.compile("", re.DOTALL)`), который сматчит позицию 0 любого текста. Результат: `raw_fragment = ""`, `apply_op` получит пустой anchor и либо не найдёт его, либо создаст нежелательное изменение.

### Что нужно знать для фикса

- `build_anchor_pattern` находится в `text_ops_utils.py` и при пустых токенах компилирует паттерн из пустой строки — это не баг самой функции, это ожидаемое поведение для пустого input.
- Guard в resolver нужно ужесточить: вместо `exc.anchor_value` использовать `exc.anchor_value.strip()`. Это безопасно — `str.strip()` не бросает исключений.
- Логику fallback при непустом якоре не менять.

---

## 🟡 БАГ 6 — Маркер `\u2400\u2400` не защищён от коллизии с содержимым документа

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `build_char_map`, шаг 5  
**Серьёзность:** Низко (реалистичный кейс для PDF с OCR-артефактами)

### Описание

В шаге 5 `build_char_map` использует `_MARKER = "\u2400\u2400"` как временный маркер для сохранения двойных переносов при замене одинарных `\n → пробел`. Этот же маркер используется в `preprocessor.py`. Символ U+2400 (`␀`) входит в диапазон `0x2000–0x206F` из `_ALLOWED_RANGES` preprocessor.py и **не фильтруется** как suspicious char. Если исходный документ содержит U+2400, маркер-детект на шаге 5c даст ложное срабатывание: часть обычного текста будет интерпретирована как маркер двойного переноса и заменена на `\n\n`.

### Что нужно знать для фикса

- Маркер должен быть таким символом, который гарантированно **не встречается** в исходных документах после шага 2 (CHAR_MAP).
- Хорошая альтернатива — Private Use Area Unicode: например `\uE000\uE001` (диапазон `0xE000–0xF8FF` — PUA, зарезервировано для частного использования, никогда не появляется в нормальных текстах). Эти символы не входят ни в один разрешённый диапазон `_ALLOWED_RANGES` и будут замечены `_detect_suspicious_chars`.
- Маркер нужно менять **синхронно** в обоих местах: в `token_anchor.py` (переменная `_MARKER`) и в `preprocessor.py` (три строки шага 5). Либо вынести маркер в `text_ops_utils.py` как публичную константу и импортировать из обоих мест — это предпочтительный вариант.
- Если принято решение не менять маркер сейчас, добавить `assert _MARKER not in current_text` перед шагом 5a в `build_char_map` для раннего обнаружения коллизии.

---

## 🟡 БАГ 7 — Нет защиты от многосимвольных значений в `CHAR_MAP`

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `build_char_map`, шаг 2  
**Серьёзность:** Низко (текущий `CHAR_MAP` безопасен, но нет guard на будущее)

### Описание

В шаге 2 `build_char_map` для каждого символа из `CHAR_MAP` добавляется **ровно одна** позиция в `new_offsets`, но `replacement` (значение из `CHAR_MAP`) может теоретически быть строкой длиннее 1 символа. Сейчас все значения в `CHAR_MAP` — `""`, `" "` или `"-"` (длина ≤ 1), поэтому баг не проявляется. Но при добавлении новой замены типа `"\r\n" → "\n"` или аббревиатуры `CHAR_MAP` рассинхронизируется без явной ошибки.

### Что нужно знать для фикса

- Добавить assert или raise в шаге 2 при обнаружении `len(replacement) > 1`:
  - Вариант мягкий: `assert len(replacement) <= 1` с поясняющим комментарием почему это требование существует.
  - Вариант строгий: поднимать `ValueError` с явным сообщением.
- Сам `CHAR_MAP` из `preprocessor.py` не менять — он источник истины.
- Проверку добавлять в `build_char_map` при итерации по символам в шаге 2.

---

## Порядок исправления

1. **БАГ 1** — убрать импорт `_HEADING_FULL_LINE_RE`, объявить локально
2. **БАГ 2** — заменить возврат частичной карты на `None`, обновить `resolve_anchor_in_raw`
3. **БАГ 3** — убрать мёртвый внешний `except ContentTooLargeError` в fallback
4. **БАГ 4** — ужесточить assert в тесте до `== "anchor_ambiguous"`
5. **БАГ 5** — заменить `exc.anchor_value` на `exc.anchor_value.strip()` в guard
6. **БАГ 6** — вынести `_MARKER` в `text_ops_utils.py`, использовать PUA-символ
7. **БАГ 7** — добавить assert/guard на длину replacement в шаге 2

---

## Инварианты для проверки после всех фиксов

- `len(build_char_map(raw, preprocess(raw))) == len(preprocess(raw))` — или `None` при рассинхроне.
- `resolve_anchor_in_raw("Кот - животное", "Кот \u2014 животное") == "Кот \u2014 животное"`
- `resolve_anchor_in_raw("задача А задача Б", "задача А\nзадача Б") == "задача А\nзадача Б"`
- Все 7 кейсов в `test_token_anchor.py` проходят.
- Все 4 теста в `test_token_anchor_fallback.py` проходят.
- `test_fallback_ambiguous_raw_fragment` проверяет строго `error_code == "anchor_ambiguous"`.
