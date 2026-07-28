# Фаза 4 — Диагностические логи в resolver.py

> **Перед началом выполнения:** прочитай `plan-search/concept.md` и убедись, что все изменения фазы соответствуют концепту.

## Цель

Удостовериться что все диагностические логи в `resolver.py` добавлены корректно и полноценно описывают работу fallback-механизма. Фаза 3 уже добавляет основные логи, эта фаза — финальная проверка и дополнение.

**Фаза 3 должна быть выполнена** перед этой фазой.

## Контекст

После Фазы 3 в `resolver.py` в fallback-блоке должны быть следующие логи:
1. WARNING перед fallback: `"direct anchor search failed"`
2. INFO при успехе fallback: `"token-anchor fallback succeeded"`
3. WARNING при ambiguous: `"token-anchor fallback: raw_fragment is ambiguous"`
4. WARNING при повторном не найден: `"token-anchor fallback also failed"`

## Задача

### Проверить и дополнить логи в resolver.py

Удостовериться что каждый из 4 сценариев логируется:

**Сценарий A — прямой поиск провалился, fallback запускается:**
```
log.warning(
    "_resolve_one: direct anchor search failed for anchor=%r, trying token-anchor fallback",
    anchor_val[:80],
)
```

**Сценарий B — fallback нашёл raw_fragment:**
```
log.info(
    "_resolve_one: token-anchor fallback succeeded, raw_fragment=%r",
    raw_fragment[:80],
)
```

**Сценарий C — raw_fragment найден, но неоднозначен:**
```
log.warning(
    "_resolve_one: token-anchor fallback: raw_fragment is ambiguous for anchor=%r",
    anchor_val[:80],
)
```

**Сценарий D — fallback тоже не нашёл якорь:**
```
log.warning(
    "_resolve_one: token-anchor fallback also failed for anchor=%r",
    anchor_val[:80],
)
```

**Сценарий E — fallback не применяется (операция не в списке или пустой anchor):**  
Логировать не нужно — стандартная обработка `anchor_not_found`.

### Проверить формат: первые 80 символов

Во всех логах якорь и raw_fragment обрезаются до **80 символов** (`[:80]`). Это необходимо чтобы не заспамить лог при длинных якорях.

### Проверить уровни логирования

| Событие | Уровень |
|---|---|
| Fallback запускается | WARNING |
| Fallback успешен | INFO |
| raw_fragment ambiguous | WARNING |
| Fallback тоже провалился | WARNING |

## Требования

- Не добавлять новых логов в `token_anchor.py` — эта фаза касается только `resolver.py`
- Не менять логику `_resolve_one()` — только убедиться что логи расставлены верно
- Все тесты Фаз 1–3 должны продолжать проходить
- Запустить полный тест-сьют: `pytest rag-indexer/tests/ -x -q`

## Финальная проверка плана

После Фазы 4 — финальная проверка всего изменения:

1. Убедиться что новые файлы созданы:
   - `rag-indexer/app/update_mode/text_ops_utils.py`
   - `rag-indexer/app/update_mode/token_anchor.py`

2. Убедиться что изменённые файлы корректны:
   - `rag-indexer/app/update_mode/text_ops.py` — импортирует `build_anchor_pattern` из `text_ops_utils`
   - `rag-indexer/app/update_mode/resolver.py` — содержит `_build_pending_change()` и fallback-блок

3. Убедиться что НЕ изменённые файлы не тронуты:
   - `rag-indexer/parser/preprocessing/preprocessor.py`
   - `shared_contracts/models.py`
   - `rag-indexer/app/update_mode/applier.py`

4. Запустить полный тест-сьют и убедиться что все тесты проходят.
