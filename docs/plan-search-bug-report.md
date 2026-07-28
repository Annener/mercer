# Bug Report: ветка `plan-search` — Token-Map Anchoring

> Сгенерировано по результатам code review ветки `plan-search`.  
> Основан на реальном анализе кода через GitHub API.  
> Каждый баг — самостоятельный шаг. Фиксить по порядку приоритета.

---

## Контекст задачи

LLM генерирует `anchor.value` из нормализованного текста (после `preprocess()`), а resolver ищет якорь в raw-файле на диске. Из-за трансформаций `preprocess()` (newline→space, em-dash→дефис, дефисные переносы, мягкий дефис, NFC) прямой поиск падает с `AnchorNotFoundError`.

Решение реализовано через построение char-map (`normalized_pos → raw_pos`), поиск якоря в нормализованном тексте, извлечение raw-фрагмента и повторный `apply_op` с ним.

### Затронутые файлы

| Файл | Статус |
|------|--------|
| `rag-indexer/app/update_mode/text_ops_utils.py` | НОВЫЙ |
| `rag-indexer/app/update_mode/text_ops.py` | ИЗМЕНЁН |
| `rag-indexer/app/update_mode/token_anchor.py` | НОВЫЙ |
| `rag-indexer/app/update_mode/resolver.py` | ИЗМЕНЁН |
| `rag-indexer/parser/preprocessing/preprocessor.py` | ИСТОЧНИК ИСТИНЫ (не менять без сверки) |
| `rag-indexer/tests/test_token_anchor.py` | ТЕСТЫ unit |
| `rag-indexer/tests/test_token_anchor_fallback.py` | ТЕСТЫ integration |

---

## Статус Фазы 1 (text_ops_utils.py + text_ops.py)

**✅ Полностью корректно.** Все пункты спецификации выполнены:

- `text_ops_utils.py` — только `import re` из stdlib.
- `build_anchor_pattern` публичная, логика идентична оригинальной `_build_anchor_pattern`.
- `text_ops.py` — `def _build_anchor_pattern` удалена, импорт: `from app.update_mode.text_ops_utils import build_anchor_pattern as _build_anchor_pattern`.
- Все вызовы `_build_anchor_pattern(...)` внутри `text_ops.py` не изменены.
- Никакая другая логика `text_ops.py` не тронута.

---

## 🔴 БАГ 1 — Шаг 3 `build_char_map`: `\n` после строки-из-цифр не удаляется

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `build_char_map`, шаг 3  
**Серьёзность:** Критично — гарантированный length mismatch → `None` → fallback всегда падает для документов с нумерацией строк

### Описание

Паттерн `re.compile(r"^\s*\d+\s*$", re.MULTILINE)` с флагом `re.MULTILINE` в Python: `$` совпадает **перед** `\n`, но **не захватывает** `\n`. Т.е. `m.end()` указывает на позицию `\n`, а не после неё.

Код делает `last = m.end()` — в результате символ `\n` (сразу после цифровой строки) остаётся в `current_text`. Тем временем `preprocess()` удаляет строку целиком вместе с переносом через `re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)`.

**Воспроизводящий кейс:**
```python
raw = "Глава\n42\nТекст"
# preprocess() → "Глава\nТекст" → "Глава Текст"  (len=11)
# build_char_map после шага 3: "Глава\n\nТекст"  (лишний \n)
# → после шага 5b: "Глава  Текст"  (два пробела, len=12)
# → length mismatch 12 != 11 → build_char_map вернёт None
```

### Что нужно знать для фикса

Нужно также пропускать `\n` после совпадения, если он есть. В шаге 3 заменить:

```python
last = m.end()
```

на:

```python
end = m.end()
if end < len(current_text) and current_text[end] == "\n":
    end += 1
last = end
```

Альтернатива — использовать паттерн `r"^\s*\d+\s*\n"` (без `re.MULTILINE` для `$`), но тогда нужно проверить, что `preprocess()` использует именно такой вариант, а не `re.MULTILINE`.

---

## 🔴 БАГ 2 — `preprocess(raw, source_hint=...)` — параметр не верифицирован

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `resolve_anchor_in_raw`  
**Серьёзность:** Критично — `TypeError` в runtime при первом же fallback-вызове, если сигнатура не совпадает

### Описание

В `resolve_anchor_in_raw` вызов:

```python
normalized_raw = preprocess(raw, source_hint="token_anchor")
```

Параметр `source_hint` используется как именованный. Если `preprocess()` в `preprocessor.py` не имеет этого параметра (или он называется иначе), при первом же вызове будет `TypeError: preprocess() got an unexpected keyword argument 'source_hint'`.

Весь fallback-механизм станет нерабочим, причём ошибка будет маскирована: в `_resolve_one` вызов `resolve_anchor_in_raw` не обёрнут в try/except TypeError, поэтому исключение всплывёт до `resolve_changes`, где поймается общим `except Exception` и запишется как `internal_error`.

### Что нужно знать для фикса

Открыть `preprocessor.py` и проверить сигнатуру функции `preprocess()`:

- Если параметра `source_hint` нет — убрать его из вызова: `preprocess(raw)`.
- Если есть — оставить как есть.
- Если параметр есть, но называется иначе — исправить имя.

Независимо от результата: добавить тест в `test_token_anchor.py`, который вызывает `resolve_anchor_in_raw(...)` и проверяет, что `TypeError` не бросается (smoke test на сигнатуру).

---

## 🔴 БАГ 3 — Маркер `CHAR_MAP_MARKER` не верифицирован против `preprocessor.py`

**Файл:** `rag-indexer/app/update_mode/text_ops_utils.py` (константа `CHAR_MAP_MARKER = "\uE000\uE001"`)  
**Серьёзность:** Критично — при расхождении маркеров `\n\n` в документах не восстанавливаются → length mismatch для всех документов с заголовками или двойными переносами

### Описание

В шаге 5 `build_char_map` используется маркер `_MARKER = CHAR_MAP_MARKER = "\uE000\uE001"` (PUA-символы) для временного сохранения `\n\n` перед заменой одинарных `\n → пробел`.

Вся логика шага 5 (`5a: \n\n → маркер`, `5b: \n → пробел`, `5c: маркер → \n\n`) **должна воспроизводить** точно такой же шаг в `preprocess()`. Если `preprocess()` использует другой маркер (например, оригинальный `\u2400\u2400`), то:

- `build_char_map` ищет `"\uE000\uE001"` в тексте на шаге 5c — не находит (маркер другой).
- Двойные переносы строк не восстанавливаются.
- Результат `current_text` после шага 5 отличается от `normalized` → length mismatch → `None`.

### Что нужно знать для фикса

1. Открыть `preprocessor.py` и найти переменную маркера в шаге 5 (замена `\n\n`).
2. Убедиться, что маркер в `preprocessor.py` — это тоже `"\uE000\uE001"`.
3. Если маркер другой (например, `"\u2400\u2400"`):
   - **Либо** обновить `preprocessor.py`, чтобы использовал `CHAR_MAP_MARKER` из `text_ops_utils.py` (импорт публичной константы — архитектурно чисто).
   - **Либо** изменить `CHAR_MAP_MARKER` в `text_ops_utils.py` на тот, что использует preprocessor.
4. Правило: маркер должен быть определён **в одном месте** и импортироваться из него. Сейчас `text_ops_utils.py` уже является кандидатом на роль источника истины — нужно только убедиться, что preprocessor его тоже использует.

---

## 🟡 БАГ 4 — `extract_raw_fragment`: неверный результат при `norm_end == norm_start`

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `extract_raw_fragment`  
**Серьёзность:** Средняя — `find_anchor_offset` не вернёт `norm_start == norm_end` в нормальной работе, но функция не защищена от этого edge case

### Описание

Текущая реализация:

```python
raw_start = char_map[norm_start]
raw_end = char_map[norm_end - 1] + 1
```

При `norm_end == norm_start` (пустой диапазон): `char_map[norm_end - 1]` = `char_map[norm_start - 1]` — это позиция символа **перед** началом якоря. Функция вернёт `raw[char_map[norm_start - 1] : char_map[norm_start - 1] + 1]` — один символ перед якорем вместо пустой строки. При `norm_start == 0` будет `char_map[-1]` — последний элемент списка (Python не падает, но возвращает мусор).

Пустой якорь `build_anchor_pattern("")` компилирует паттерн `""`, который сматчит позицию 0 с `m.start() == m.end() == 0` — это реальный путь к `norm_start == norm_end == 0`.

### Что нужно знать для фикса

Добавить guard в начало `extract_raw_fragment`:

```python
if norm_start >= norm_end:
    return ""
```

Дополнительно: в `resolver.py` guard `exc.anchor_value.strip()` (Баг 5) предотвращает пустой якорь на уровне выше, но `extract_raw_fragment` должна быть защищена независимо.

---

## 🟡 БАГ 5 — Паттерны шагов 4 и 4a не верифицированы против `preprocessor.py`

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, шаги 4 и 4a  
**Серьёзность:** Средняя — при расхождении паттернов часть трансформаций не будет отражена в char_map

### Описание

В `token_anchor.py`:
- Шаг 4: `re.compile(r"(\w+)-\s*\n\s*(\w+)")`
- Шаг 4a: `re.compile(r"(\w+)-\s+(\w)")`

Эти паттерны должны быть **идентичны** паттернам в `preprocessor.py`. Если preprocessor использует, например, `r"(\w)-\n(\w)"` (без `\s*`) или добавляет флаг `re.UNICODE` — поведение разойдётся. Вхождения дефисных переносов будут не замечены в `build_char_map` → length mismatch или неверная позиция.

Отдельный риск для шага 4a: если `preprocess()` применяет шаги 4 и 4a в одном `re.sub` через `|` (альтернацию), то порядок применения иной — шаг 4 в `token_anchor.py` может создать новые совпадения для шага 4a, которых не было в оригинале.

### Что нужно знать для фикса

1. Открыть `preprocessor.py` и найти строки, соответствующие шагам 4 и 4a.
2. Скопировать паттерны **дословно** в `token_anchor.py`.
3. Проверить: применяются ли шаги 4 и 4a в preprocessor **последовательно** (два отдельных `re.sub`) или через один `re.sub` с `|`. В `token_anchor.py` они идут последовательно — это должно совпадать.
4. Если preprocessor применяет их в одном sub — переписать шаги 4/4a в `build_char_map` соответственно.

---

## 🟡 БАГ 6 — Заголовок в начале файла: лишний `\n\n` при prepend

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, шаг 4b  
**Серьёзность:** Средняя — для документов, начинающихся с Markdown-заголовка, length mismatch

### Описание

В шаге 4b для каждого заголовка добавляется `\n\n` до и после:

```python
new_text += "\n\n"   # prepend
# ... тело заголовка ...
new_text += "\n\n"   # append
```

Если заголовок стоит в позиции 0 (начало файла), prepend `\n\n` добавляется безусловно. В `preprocess()` нужно проверить: добавляется ли `\n\n` перед заголовком, если он стоит в начале текста. Если preprocessor пропускает prepend для первого заголовка (т.к. перед ним нечего отделять), то `build_char_map` добавит 2 лишних символа → length mismatch.

### Что нужно знать для фикса

1. Открыть `preprocessor.py`, найти шаг с обёрткой заголовков в `\n\n`.
2. Проверить: есть ли там условие вроде `if m.start() > 0` для prepend?
3. Если есть — добавить аналогичное условие в шаг 4b `token_anchor.py`:
   ```python
   if m.start() > 0:
       new_text += "\n\n"
       new_offsets.extend([first_raw, first_raw])
   ```
4. Если preprocessor добавляет `\n\n` безусловно — оставить как есть.

---

## 🟡 БАГ 7 — Пробельный якорь проходит fallback-guard в `resolver.py`

**Файл:** `rag-indexer/app/update_mode/resolver.py`, функция `_resolve_one`  
**Серьёзность:** Низкая — редкий кейс, но ведёт к ложному match

### Описание

Guard активации fallback:

```python
if intent.operation in _FALLBACK_OPS and exc.anchor_value.strip():
```

Это уже корректно — `exc.anchor_value.strip()` используется. Баг отсутствует. ✅

> Данный пункт оставлен для протокола: в предыдущей версии отчёта здесь был указан баг с `exc.anchor_value` (без `.strip()`). В реальном коде `.strip()` уже применяется.

---

## 🟡 БАГ 8 — Мёртвый код: структура `except ContentTooLargeError` в fallback-блоке

**Файл:** `rag-indexer/app/update_mode/resolver.py`, функция `_resolve_one`  
**Серьёзность:** Низкая — не влияет на логику, но создаёт путаницу при чтении кода

### Описание

В fallback-блоке после `apply_op(...)` структура обработки `ContentTooLargeError` правильная: `try/except ContentTooLargeError` обёртывает только `_build_pending_change`. `apply_op` не бросает `ContentTooLargeError`. Баг в текущем коде **отсутствует** — рефактор через `_build_pending_change` уже устранил проблему.

> Данный пункт оставлен для протокола: описанный в концепте «внешний except ContentTooLargeError вокруг apply_op» в реальном коде не присутствует — он уже убран. ✅

---

## 🟢 Тесты — статус

| Файл | Статус |
|------|--------|
| `test_token_anchor.py` | ✅ Существует (8.9 KB) |
| `test_token_anchor_fallback.py` | ✅ Существует (7.9 KB) |
| Моки в fallback-тестах | ✅ `_lookup_document`, `resolve_vault_root`, `resolve_file_path`, `read_original_utf8` |
| `test_fallback_ambiguous_raw_fragment` проверяет `error_code == "anchor_ambiguous"` | ✅ Строгий assert (не `in (...)`) |

### ⚠️ Слабое место в тесте 4 (`test_fallback_ambiguous_raw_fragment`)

`raw` содержит `"задача А задача Б"` дважды **без нормализационных трансформаций** (пробелы уже стоят, не `\n`). Значит прямой `apply_op` тоже упадёт с `AnchorAmbiguousError` — без захода в fallback. Тест проверяет общий путь ambiguous, но не проверяет именно fallback-ветку с рассинхроном нормализации. Для полного покрытия нужен тест где `raw` содержит трансформируемые символы (например, em-dash в паттерне который встречается дважды).

---

## Порядок исправления

| # | Баг | Файл | Приоритет |
|---|-----|------|-----------|
| 1 | `\n` после строки-из-цифр не удаляется в шаге 3 | `token_anchor.py` | 🔴 Сначала |
| 2 | Верифицировать сигнатуру `preprocess()` на `source_hint` | `token_anchor.py` / `preprocessor.py` | 🔴 Сначала |
| 3 | Верифицировать и синхронизировать `CHAR_MAP_MARKER` с preprocessor | `text_ops_utils.py` / `preprocessor.py` | 🔴 Сначала |
| 4 | Верифицировать паттерны шагов 4/4a против preprocessor | `token_anchor.py` / `preprocessor.py` | 🟡 Второй проход |
| 5 | Верифицировать prepend `\n\n` для заголовка в начале файла | `token_anchor.py` / `preprocessor.py` | 🟡 Второй проход |
| 6 | Guard в `extract_raw_fragment` при `norm_end == norm_start` | `token_anchor.py` | 🟡 Второй проход |
| 7 | Улучшить тест 4 fallback: добавить кейс с реальной нормализацией | `test_token_anchor_fallback.py` | 🟢 Последний |

---

## Инварианты для проверки после всех фиксов

```python
# Инвариант 1: длина char_map всегда совпадает с длиной normalized
raw = "Любой текст"
assert len(build_char_map(raw, preprocess(raw))) == len(preprocess(raw))

# Инвариант 2: em-dash
assert resolve_anchor_in_raw("Кот - животное", "Кот \u2014 животное") == "Кот \u2014 животное"

# Инвариант 3: newline→space
assert resolve_anchor_in_raw("задача А задача Б", "задача А\nзадача Б") == "задача А\nзадача Б"

# Инвариант 4: документ с нумерацией строк (Баг 1)
raw = "Глава\n42\nТекст"
result = build_char_map(raw, preprocess(raw))
assert result is not None  # не было бы до фикса

# Инвариант 5: все unit-тесты проходят
# pytest rag-indexer/tests/test_token_anchor.py
# pytest rag-indexer/tests/test_token_anchor_fallback.py
```
