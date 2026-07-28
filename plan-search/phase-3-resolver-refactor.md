# Фаза 3 — Рефакторинг resolver.py + fallback

> **Перед началом выполнения:** прочитай `plan-search/concept.md` и убедись, что все изменения фазы соответствуют концепту.

## Цель

Внести два изменения в `rag-indexer/app/update_mode/resolver.py`:
1. Вынести построение `ResolvedUpdateModeChange` в вспомогательную функцию `_build_pending_change()`
2. Добавить fallback через `token_anchor.resolve_anchor_in_raw` в блок `except AnchorNotFoundError`

**Фазы 1 и 2 должны быть выполнены** перед этой фазой.

## Контекст: текущее состояние resolver.py

Файл: `rag-indexer/app/update_mode/resolver.py`

Функция `_resolve_one()` в блоке UPDATE action:
1. Читает файл через `read_original_utf8(file_path)`
2. Вызывает `apply_op(text=original, op=intent.operation, anchor_value=..., content=intent.content)`
3. При `AnchorNotFoundError` — сразу возвращает `_fail("anchor_not_found", ...)`
4. При успехе — вручную строит `ResolvedUpdateModeChange` с `status=PENDING`

Проблема: логика построения `ResolvedUpdateModeChange` (проверка `_MAX_CONTENT_BYTES`, вызов `build_unified_diff`, заполнение полей) дублируется в основном пути и потребует дублирования в fallback-ветке.

## Задача

### Изменение 1: Вынести `_build_pending_change()`

Создать приватную helper-функцию `_build_pending_change(...)` в `resolver.py` (не async, чистая функция).

Функция принимает именованные аргументы:
- `intent: UpdateModeIntent`
- `original: str`
- `proposed: str`
- `file_path: Path`
- `vault_root: Path`
- `vault_id: str`
- `original_sha256: str`
- `resolve_order: int`

Функция:
- Кодирует `proposed` в UTF-8 и проверяет `> _MAX_CONTENT_BYTES` → если превышено, бросает `ContentTooLargeError` (нужно определить или использовать существующий Exception)
- Строит `rel_path = str(file_path.relative_to(vault_root))`
- Строит `unified_diff = build_unified_diff(original, proposed, rel_path)`
- Возвращает `ResolvedUpdateModeChange` со всеми полями, `status=UpdateModeChangeStatus.PENDING`

Заменить в основном пути `_resolve_one()` (после успешного `apply_op`) вызовом `_build_pending_change(...)` вместо ручного построения объекта. Поведение **не должно измениться**.

**Обработка `ContentTooLargeError`:** в `_resolve_one()` обернуть вызов `_build_pending_change` в `try/except ContentTooLargeError` → `return _fail("content_too_large", ...)`.

### Изменение 2: Добавить токен-anchor fallback

Добавить импорт в начало `resolver.py`:
```python
from app.update_mode.token_anchor import resolve_anchor_in_raw
```

В `_resolve_one()`, в блоке `except AnchorNotFoundError as exc:`, **перед** текущими строками с `return _fail(...)`, добавить fallback-логику:

**Условие применения fallback:** операция должна быть одной из:
- `UpdateModeOperation.REPLACE_UNIQUE_TEXT`
- `UpdateModeOperation.DELETE_UNIQUE_TEXT`
- `UpdateModeOperation.APPEND_AFTER_SECTION`
- `UpdateModeOperation.DELETE_SECTION`

И `exc.anchor_value` должен быть непустым.

**Логика fallback:**
1. Залогировать WARNING: `"direct anchor search failed for anchor=%r, trying token-anchor fallback"` (первые 80 символов якоря)
2. Вызвать `raw_fragment = resolve_anchor_in_raw(exc.anchor_value, original)`
3. Если `raw_fragment is not None`:
   - Залогировать INFO: `"token-anchor fallback succeeded, raw_fragment=%r"` (первые 80 символов)
   - Вызвать `apply_op(text=original, op=intent.operation, anchor_value=raw_fragment, content=intent.content)`
   - При успехе: вызвать `_build_pending_change(...)` и вернуть результат
   - При `ContentTooLargeError`: `return _fail("content_too_large", ...)`
   - При `AnchorAmbiguousError`: залогировать WARNING `"token-anchor fallback: raw_fragment is ambiguous"`, вернуть `_fail("anchor_ambiguous", f"anchor maps to ambiguous raw fragment: {exc.anchor_value!r}")`
   - При повторном `AnchorNotFoundError`: залогировать WARNING `"token-anchor fallback also failed"` — **продолжить** к оригинальной обработке ошибки (не return)
4. Если `raw_fragment is None`: продолжить к оригинальной обработке ошибки

После fallback-блока — оригинальные строки `return _fail(...)` остаются без изменений.

## Требования

- Основной happy-path `_resolve_one()` **не меняет поведения** — только рефактор через `_build_pending_change()`
- Fallback срабатывает **только при `AnchorNotFoundError`**, не при других ошибках
- `AnchorAmbiguousError` из fallback возвращается с кодом `"anchor_ambiguous"` — не поглощается
- Все существующие тесты `test_update_mode_resolver_delete.py` и `test_update_mode_fs_git.py` должны проходить без изменений
- Новый импорт `resolve_anchor_in_raw` добавляется в секцию импортов (не инлайн)

## Тесты

Добавить в `rag-indexer/tests/` новый файл `test_token_anchor_fallback.py` с integration-тестами:

- **Тест 1:** anchor с `\n`→пробел успешно резолвится через fallback. Raw-файл содержит `"задача А\nзадача Б"`, anchor_value = `"задача А задача Б"` — должен вернуть `PENDING`.
- **Тест 2:** anchor с em-dash успешно резолвится через fallback. Raw-файл содержит `"Кот — животное"`, anchor = `"Кот - животное"`.
- **Тест 3:** якорь не найден вообще — возвращает `RESOLUTION_FAILED` с кодом `"anchor_not_found"`.
- **Тест 4:** fallback находит raw_fragment, но он встречается дважды → `RESOLUTION_FAILED` с кодом `"anchor_ambiguous"`.

Тесты должны мокать `_lookup_document`, `resolve_vault_root`, `resolve_file_path`, `read_original_utf8` — не обращаться к реальной ФС или БД.
