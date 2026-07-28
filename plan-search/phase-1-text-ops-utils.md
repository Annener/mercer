# Фаза 1 — Общий утилитный модуль `text_ops_utils.py`

> **Перед началом выполнения:** прочитай `plan-search/concept.md` и убедись, что все изменения фазы соответствуют концепту.

## Цель

Вынести приватную функцию `_build_anchor_pattern` из `text_ops.py` в новый публичный утилитный модуль `text_ops_utils.py`. Это необходимо, чтобы `token_anchor.py` (Фаза 2) мог использовать её без импорта приватных символов из чужого модуля.

## Контекст: текущее состояние

**Файл:** `rag-indexer/app/update_mode/text_ops.py`

Функция `_build_anchor_pattern(anchor_text: str) -> re.Pattern[str]` определена как приватная. Она строит regex, который толерантен к любым пробельным символам между словами. Используется в `_replace_unique_text()` для fuzzy-поиска якорного текста.

Текущая реализация:
```python
def _build_anchor_pattern(anchor_text: str) -> re.Pattern[str]:
    tokens = re.split(r"\s+", anchor_text.strip())
    tokens = [t for t in tokens if t]
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    return re.compile(pattern, re.DOTALL)
```

## Задача

### 1. Создать новый файл `rag-indexer/app/update_mode/text_ops_utils.py`

- Содержит одну публичную функцию: `build_anchor_pattern(anchor_value: str) -> re.Pattern[str]`
- Функция является публичным аналогом `_build_anchor_pattern` из `text_ops.py`
- Логика идентична текущей реализации в `text_ops.py` — не менять поведение
- Модуль содержит только stdlib импорты (`re`)
- Добавить docstring: функция строит whitespace-tolerant regex для поиска `anchor_value` в тексте

### 2. Изменить `rag-indexer/app/update_mode/text_ops.py`

- Удалить определение `_build_anchor_pattern` из файла
- Добавить импорт в начало файла:
  ```python
  from app.update_mode.text_ops_utils import build_anchor_pattern as _build_anchor_pattern
  ```
- Все внутренние вызовы `_build_anchor_pattern(...)` остаются без изменений — псевдоним `_build_anchor_pattern` сохраняет совместимость
- Никакой другой логики в `text_ops.py` не менять

## Требования

- Поведение `_replace_unique_text()` и всего остального кода `text_ops.py` **не должно измениться**
- Все существующие тесты `rag-indexer/tests/` должны проходить без изменений
- Новый файл `text_ops_utils.py` должен находиться в `rag-indexer/app/update_mode/`
- Импорт в `text_ops.py` использует псевдоним `as _build_anchor_pattern` — внутри файла функция используется под тем же именем

## Проверка

После реализации убедиться:
- `python -c "from app.update_mode.text_ops import apply_op"` — без ошибок
- `python -c "from app.update_mode.text_ops_utils import build_anchor_pattern"` — без ошибок
- Запустить существующие тесты: `pytest rag-indexer/tests/ -x -q` — все проходят
