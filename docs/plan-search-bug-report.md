# Bug Report: ветка `plan-search` — Token-Map Anchoring

> Только актуальные баги после сверки с `preprocessor.py`.

---

## Контекст

LLM генерирует `anchor.value` из нормализованного текста после `preprocess()`, а resolver применяет операцию к raw-тексту файла. Для bridge между normalized и raw добавлен char-map fallback: поиск по normalized, извлечение raw-фрагмента, повторный `apply_op`.

Проблемы ниже — только те, что реально остались после проверки кода.

---

## 🔴 БАГ 1 — Небезопасный маркер `"\u2400\u2400"` в `preprocessor.py`

**Файл:** `rag-indexer/parser/preprocessing/preprocessor.py`  
**Серьёзность:** Высокая

### Описание

В шаге 5 `preprocessor.py` используется временный маркер:

```python
text = text.replace("\n\n", "\u2400\u2400")
text = text.replace("\n", " ")
text = text.replace("\u2400\u2400", "\n\n")
```

Символ `\u2400` попадает в разрешённый диапазон `_ALLOWED_RANGES` (`0x2000–0x206F`) и не считается suspicious char. Если такой символ реально встретится в документе, возможна ложная замена содержимого на `\n\n`.

При этом в `token_anchor.py` / `text_ops_utils.py` уже используется безопасный PUA-маркер `"\uE000\uE001"`.

### Что нужно сделать

Привести `preprocessor.py` к тому же маркеру, что уже используется в `text_ops_utils.py`.

Предпочтительно:

```python
from app.update_mode.text_ops_utils import CHAR_MAP_MARKER as _NL_MARKER

text = text.replace("\n\n", _NL_MARKER)
text = text.replace("\n", " ")
text = text.replace(_NL_MARKER, "\n\n")
```

Если такой импорт архитектурно нежелателен — вынести маркер в общую публичную константу и импортировать из неё оба модуля.

---

## 🟡 БАГ 2 — `extract_raw_fragment` не защищена от пустого диапазона

**Файл:** `rag-indexer/app/update_mode/token_anchor.py`  
**Функция:** `extract_raw_fragment`  
**Серьёзность:** Средняя

### Описание

Сейчас логика такая:

```python
raw_start = char_map[norm_start]
raw_end = char_map[norm_end - 1] + 1
```

Если `norm_end == norm_start`, выражение `char_map[norm_end - 1]` обращается к предыдущему символу, а при `norm_start == 0` — вообще к последнему элементу списка через `char_map[-1]`. Это даёт неверный raw-фрагмент.

Да, в обычном пути пустой якорь уже отсекается выше через `exc.anchor_value.strip()`, но сама функция должна быть безопасной независимо от внешнего guard.

### Что нужно сделать

Добавить ранний выход:

```python
if norm_start >= norm_end:
    return ""
```

---

## 🟢 Тестовое улучшение

**Файл:** `rag-indexer/tests/test_token_anchor_fallback.py`

### Что улучшить

Добавить отдельный тест, который проверяет именно fallback-сценарий с реальной нормализацией, а не просто общий ambiguous-case. Например, кейс с `em-dash` или другим преобразованием `preprocess()`, где raw-фрагмент после fallback встречается дважды.

---

## Порядок исправления

1. Заменить маркер в `preprocessor.py` на безопасный общий.
2. Добавить guard в `extract_raw_fragment`.
3. Усилить fallback-тест реальным кейсом нормализации.
