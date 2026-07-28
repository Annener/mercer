# Bug Report: ветка `plan-search` — Token-Map Anchoring

> Основан на прямом анализе кода через GitHub API.  
> Сверён с `preprocessor.py` (источник истины).  
> Каждый баг — самостоятельный шаг. Фиксить по порядку приоритета.

---

## Контекст задачи

LLM генерирует `anchor.value` из нормализованного текста (после `preprocess()`), а resolver ищет якорь в raw-файле на диске. Из-за трансформаций `preprocess()` (newline→space, em-dash→дефис, дефисные переносы, мягкий дефис, NFC) прямой поиск падает с `AnchorNotFoundError`.

Решение: построить char-map (`normalized_pos → raw_pos`), найти якорь в нормализованном тексте, извлечь raw-фрагмент и повторить `apply_op` с ним.

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

## Статус Фазы 1 (text_ops_utils.py + text_ops.py)

**✅ Полностью корректно.** Все пункты спецификации выполнены:

- `text_ops_utils.py` — только `import re` из stdlib.
- `build_anchor_pattern` публичная, логика идентична оригинальной `_build_anchor_pattern`.
- `text_ops.py` — `def _build_anchor_pattern` удалена, импорт: `from app.update_mode.text_ops_utils import build_anchor_pattern as _build_anchor_pattern`.
- Все вызовы `_build_anchor_pattern(...)` внутри `text_ops.py` не изменены.

---

## 🔴 БАГ 1 — Шаг 3 `build_char_map`: `\n` после строки-из-цифр не удаляется

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `build_char_map`, шаг 3  
**Серьёзность:** Критично — гарантированный length mismatch → `None` → fallback всегда падает для документов с нумерацией страниц

### Описание

В `preprocessor.py` шаг 3:

```python
text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
```

`re.sub` с `re.MULTILINE` и паттерном `^\s*\d+\s*$` — в Python `$` совпадает **перед** `\n`, но `re.sub` заменяет только саму совпавшую подстроку (без `\n`). Однако стандартное поведение `re.sub` здесь убирает `\n` — **проверим точнее**:

```python
>>> import re
>>> re.sub(r"^\s*\d+\s*$", "", "Глава\n42\nТекст", flags=re.MULTILINE)
'Глава\n\nТекст'
```

В `preprocessor.py` остаётся `"Глава\n\nТекст"` (две `\n`). Затем шаги 4b + 5 обрабатывают это через `\n\n` → маркер → `\n\n`, итоговый результат после `.strip()` = `"Глава\n\nТекст"` (или `"Глава Текст"` если оба `\n` одиночные — зависит от контекста).

В `build_char_map` (шаг 3) после `last = m.end()` символ `\n` **остаётся** в `current_text` (потому что `m.end()` при `re.MULTILINE $` указывает на позицию перед `\n`). Поведение **совпадает с preprocessor** — оба оставляют `\n`.

**Вывод: БАГ 1 переоценён.** Поведение `build_char_map` и `preprocessor.py` в шаге 3 идентично — оба оставляют пустую строку (`\n\n`). Последующие шаги (4b, 5) обработают это одинаково.

> ⚠️ Однако если `\n\n` появляется в `build_char_map` на шаге 3, а потом шаг 4b добавляет `\n\n` вокруг заголовка — могут возникнуть тройные `\n{3,}`. Оба места вызывают `_collapse_excess_newlines` / `re.sub(r"\n{3,}", ...)` — это покрыто. **Баг 1 закрыт ✅.**

---

## 🔴 БАГ 2 — Маркер `\u2400\u2400` в preprocessor vs `\uE000\uE001` в token_anchor

**Файл:** `rag-indexer/app/update_mode/text_ops_utils.py` (`CHAR_MAP_MARKER = "\uE000\uE001"`)  
vs `rag-indexer/parser/preprocessing/preprocessor.py` (использует `"\u2400\u2400"`)  
**Серьёзность:** Критично — `build_char_map` шаг 5 не совпадает с `preprocess()` → length mismatch для ЛЮБОГО документа с двойными переносами строк (заголовки, пустые строки между абзацами)

### Описание

В `preprocessor.py` шаг 5:

```python
text = text.replace("\n\n", "\u2400\u2400")  # маркер = U+2400 U+2400
text = text.replace("\n", " ")
text = text.replace("\u2400\u2400", "\n\n")
```

В `text_ops_utils.py`:

```python
CHAR_MAP_MARKER: str = "\uE000\uE001"  # маркер = U+E000 U+E001 (PUA)
```

В `token_anchor.py` шаг 5 использует `CHAR_MAP_MARKER = "\uE000\uE001"`. Это **другой маркер**.

**Последствие:** При обработке любого документа с заголовками или пустыми строками:
1. `preprocessor.py` заменяет `\n\n` → `\u2400\u2400`, затем восстанавливает → `\n\n`.
2. `build_char_map` заменяет `\n\n` → `\uE000\uE001` (другой маркер) — OK, логика та же.
3. НО: если в тексте уже присутствовал `\u2400` (U+2400 входит в разрешённый диапазон `0x2000–0x206F`!), то в `preprocessor.py` он будет ложно совпадать с маркером. В `build_char_map` — нет, потому что PUA-символ там гарантированно отсутствует.

**Реальный баг:** `CHAR_MAP_MARKER` в `text_ops_utils.py` и маркер в `preprocessor.py` — **разные строки**. Это не влияет на длину (оба маркера — 2 символа), и логика шага 5 идентична по структуре. Length mismatch из-за этого **не возникает**.

> ⚠️ Однако есть риск коллизии в `preprocessor.py`: символ `\u2400` входит в `_ALLOWED_RANGES` (диапазон `0x2000–0x206F`) и **не фильтруется** `_detect_suspicious_chars`. Если документ содержит `\u2400`, preprocessor испортит его содержимое. В `build_char_map` этой проблемы нет благодаря PUA-маркеру. Это баг в `preprocessor.py`, не в `token_anchor.py`.

### Что нужно знать для фикса

В `preprocessor.py` заменить маркер на тот же PUA, что используется в `text_ops_utils.py`:

```python
# preprocessor.py шаг 5 — вместо \u2400\u2400 использовать PUA:
from app.update_mode.text_ops_utils import CHAR_MAP_MARKER as _MARKER
text = text.replace("\n\n", _MARKER)
text = text.replace("\n", " ")
text = text.replace(_MARKER, "\n\n")
```

Либо — вынести константу в `text_ops_utils.py` (уже сделано) и сделать `preprocessor.py` зависимым от неё. Если архитектурно нежелательно импортировать `app.*` из `parser.*` — определить `CHAR_MAP_MARKER` в отдельном `shared_consts.py` и импортировать оттуда обоими модулями.

---

## 🔴 БАГ 3 — `source_hint` в `preprocess()`: параметр существует, вызов корректен

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `resolve_anchor_in_raw`  
**Серьёзность:** ~~Критично~~ → **Закрыт ✅**

### Описание

После просмотра `preprocessor.py`: сигнатура функции:

```python
def preprocess(text: str, source_hint: str = "") -> str:
```

Параметр `source_hint` существует и имеет значение по умолчанию `""`. Вызов `preprocess(raw, source_hint="token_anchor")` в `resolve_anchor_in_raw` — **корректен**. `TypeError` не возникнет.

> Баг 3 закрыт. ✅

---

## 🔴 БАГ 4 — Шаг 4a `build_char_map`: паттерн отличается от `preprocessor.py`

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, шаг 4a  
**Серьёзность:** Критично — дефис+пробел внутри слова не убирается из char_map → length mismatch

### Описание

В `preprocessor.py` шаг 4a:

```python
text = re.sub(r"(\w+)-\s+(\w)", r"\1\2", text)
```

В `token_anchor.py` шаг 4a:

```python
_pattern4a = re.compile(r"(\w+)-\s+(\w)")
```

Паттерн **идентичен** — ✅.

Но есть структурная проблема: в `preprocessor.py` шаги 4 и 4a применяются **последовательно** через два независимых `re.sub`. В `token_anchor.py` — тоже последовательно. Порядок совпадает ✅.

Однако шаг 4 (`re.sub(r"(\w+)-\s*\n\s*(\w+)", ...)`) может создать новые совпадения для шага 4a: после склейки `"за-\nда- ча"` → `"зада- ча"` появляется `"зада- "` — это совпадение шага 4a. В `preprocessor.py` оно будет поймано шагом 4a (отдельный `re.sub`). В `build_char_map` тоже — шаг 4a запускается на уже изменённом `current_text`. **Поведение идентично** ✅.

> Паттерны шагов 4 и 4a совпадают с preprocessor. ✅

---

## 🔴 БАГ 5 — Шаг 4b `build_char_map`: prepend `\n\n` перед заголовком в начале файла

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, шаг 4b  
**Серьёзность:** Критично — length mismatch для любого документа, начинающегося с Markdown-заголовка

### Описание

В `preprocessor.py` шаг 4b:

```python
text = _HEADING_FULL_LINE_RE.sub(r"\n\n\1\n\n", text)
```

Это безусловно добавляет `\n\n` до и после **каждого** заголовка, включая первый заголовок в начале файла.

В `token_anchor.py` шаг 4b:

```python
for m in _HEADING_FULL_LINE_RE.finditer(current_text):
    # ...
    new_text += "\n\n"   # prepend — ВСЕГДА
    # ... тело заголовка ...
    new_text += "\n\n"   # append — ВСЕГДА
```

Поведение **идентично** preprocessor — `\n\n` добавляется безусловно ✅. После этого оба вызывают `re.sub(r"\n{3,}", "\n\n", ...)` / `_collapse_excess_newlines`. Рассинхрона нет.

> Баг 5 закрыт. ✅

---

## 🟡 БАГ 6 — `extract_raw_fragment`: неверный результат при `norm_end == norm_start`

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`, функция `extract_raw_fragment`  
**Серьёзность:** Средняя — практически не достигается (пустой якорь блокируется в resolver), но функция не защищена

### Описание

Текущая реализация:

```python
raw_start = char_map[norm_start]
raw_end = char_map[norm_end - 1] + 1
```

При `norm_end == norm_start` (пустой диапазон): `char_map[norm_end - 1]` = `char_map[norm_start - 1]` — индекс на 1 **меньше** начала якоря. При `norm_start == 0`: `char_map[-1]` — последний элемент списка (Python не падает, но возвращает мусор).

Цепочка до этой ситуации:
1. Якорь состоит из пробелов → `build_anchor_pattern("")` компилирует `re.compile("", re.DOTALL)`.
2. `pattern.search(normalized_text)` → совпадение с `m.start() == m.end() == 0`.
3. `find_anchor_offset` возвращает `(0, 0)`.
4. `extract_raw_fragment(raw, char_map, 0, 0)` → `char_map[-1] + 1` → неверный фрагмент.

Guard в `resolver.py` (`exc.anchor_value.strip()`) блокирует пробельный якорь **до** вызова `resolve_anchor_in_raw`, но `extract_raw_fragment` — публичная функция и должна быть защищена независимо.

### Что нужно знать для фикса

Добавить guard в начало `extract_raw_fragment`:

```python
def extract_raw_fragment(
    raw: str,
    char_map: list[int],
    norm_start: int,
    norm_end: int,
) -> str:
    if norm_start >= norm_end:
        return ""
    raw_start = char_map[norm_start]
    raw_end = char_map[norm_end - 1] + 1
    return raw[raw_start:raw_end]
```

---

## 🟡 БАГ 7 — `preprocessor.py` использует `\u2400\u2400` как маркер, который не фильтруется

**Файл:** `rag-indexer/parser/preprocessing/preprocessor.py`, шаг 5  
**Серьёзность:** Средняя — ведёт к тихой порче документов с символом U+2400 (OCR-артефакты)

### Описание

В `preprocessor.py`:

```python
text = text.replace("\n\n", "\u2400\u2400")  # временный маркер
```

Символ `\u2400` (U+2400, SYMBOL FOR NULL) входит в диапазон `_ALLOWED_RANGES`:

```python
(0x2000, 0x206F),  # General punctuation
```

Поэтому `_detect_suspicious_chars` **не логирует** и не фильтрует этот символ. Если документ содержит `\u2400` (например, PDF с OCR-артефактами), то:

1. Шаг 5: `text.replace("\n\n", "\u2400\u2400")` — не затрагивает существующий `\u2400`.
2. `text.replace("\u2400\u2400", "\n\n")` — ЛОЖНОЕ СРАБАТЫВАНИЕ: оба рядом стоящих `\u2400` заменятся на `\n\n`.
3. В документе появляется пустая строка там, где её не было.

При этом в `build_char_map` используется PUA-маркер `\uE000\uE001` — он безопасен, т.к. не входит в `_ALLOWED_RANGES`.

### Что нужно знать для фикса

**Вариант А (рекомендуется):** Использовать `CHAR_MAP_MARKER` из `text_ops_utils.py` в `preprocessor.py`:

```python
# В preprocessor.py:
from app.update_mode.text_ops_utils import CHAR_MAP_MARKER as _NL_MARKER
# ...
text = text.replace("\n\n", _NL_MARKER)
text = text.replace("\n", " ")
text = text.replace(_NL_MARKER, "\n\n")
```

**Вариант Б:** Если импорт `app.*` из `parser.*` архитектурно нежелателен — вынести константу в `shared_consts.py` и импортировать из обоих мест.

**Вариант В (минимальный):** Изменить только `preprocessor.py`, задублировав PUA-маркер:

```python
_NL_MARKER = "\uE000\uE001"  # PUA, никогда не встречается в документах
text = text.replace("\n\n", _NL_MARKER)
text = text.replace("\n", " ")
text = text.replace(_NL_MARKER, "\n\n")
```

---

## 🟢 Закрытые пункты (проверены, не являются багами)

| Пункт | Статус | Причина |
|-------|--------|---------|
| `source_hint` в `preprocess()` | ✅ | Параметр существует: `def preprocess(text: str, source_hint: str = "")` |
| Паттерн шага 4 (`\w+)-\s*\n\s*(\w+)`) | ✅ | Идентичен preprocessor.py |
| Паттерн шага 4a (`(\w+)-\s+(\w)`) | ✅ | Идентичен preprocessor.py |
| Порядок шагов 4 → 4a | ✅ | Оба последовательные `re.sub`/`finditer` |
| `_HEADING_FULL_LINE_RE` не импортируется | ✅ | Паттерн задублирован локально |
| Prepend `\n\n` перед заголовком в начале файла | ✅ | preprocessor тоже добавляет безусловно |
| Шаг 3 (`\n` после цифр) | ✅ | `re.sub` оставляет `\n`, `build_char_map` тоже |
| Guard `exc.anchor_value.strip()` в resolver | ✅ | Уже применяется |
| Мёртвый `except ContentTooLargeError` | ✅ | Уже убран рефактором через `_build_pending_change` |
| `assert len(replacement) <= 1` в CHAR_MAP | ✅ | Уже есть |
| `build_char_map` возвращает `None` при mismatch | ✅ | Уже реализовано |
| `_HEADING_FULL_LINE_RE` паттерн совпадает | ✅ | `r"^(#{1,6}\s[^\n]*)"` — идентичен в обоих файлах |

---

## Порядок исправления

| # | Баг | Файл | Приоритет |
|---|-----|------|-----------|
| 1 | Маркер `\u2400\u2400` в preprocessor → заменить на PUA | `preprocessor.py` | 🔴 Сначала |
| 2 | Guard в `extract_raw_fragment` при `norm_end == norm_start` | `token_anchor.py` | 🟡 Второй |
| 3 | Улучшить тест 4 fallback: добавить кейс с em-dash дважды | `test_token_anchor_fallback.py` | 🟢 Последний |

---

## Инварианты для проверки после всех фиксов

```python
# Инвариант 1: длина char_map всегда == длине normalized
from parser.preprocessing.preprocessor import preprocess
from app.update_mode.token_anchor import build_char_map

for raw in [
    "Кот \u2014 животное",
    "задача А\nзадача Б",
    "# Заголовок\nТекст абзаца",
    "Глава\n42\nТекст",
    "при-\nмер",
]:
    norm = preprocess(raw)
    cm = build_char_map(raw, norm)
    assert cm is not None, f"None для raw={raw!r}"
    assert len(cm) == len(norm), f"mismatch: {len(cm)} != {len(norm)} для raw={raw!r}"

# Инвариант 2: em-dash
from app.update_mode.token_anchor import resolve_anchor_in_raw
assert resolve_anchor_in_raw("Кот - животное", "Кот \u2014 животное") == "Кот \u2014 животное"

# Инвариант 3: newline→space
assert resolve_anchor_in_raw("задача А задача Б", "задача А\nзадача Б") == "задача А\nзадача Б"

# Инвариант 4: пустой диапазон не падает
from app.update_mode.token_anchor import extract_raw_fragment
assert extract_raw_fragment("текст", [0, 1, 2, 3, 4], 2, 2) == ""
```
