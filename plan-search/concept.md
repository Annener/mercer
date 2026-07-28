# Token-Map Anchoring — Концепт

## Суть проблемы

LLM генерирует `anchor.value` из **нормализованного текста** (`IndexedContextDocument.text`).
Resolver в `rag-indexer` ищет этот `anchor.value` в **сыром `.md` файле** с диска.

Из-за трансформаций в `preprocess()` текст якоря не совпадает с raw-файлом,
и `apply_op()` падает с `AnchorNotFoundError`.

### Трансформации-нарушители (preprocessor.py)

| Шаг `preprocess()` | Что ломается |
|---|---|
| Шаг 5: одинарный `\n` → пробел | `"задача А\nзадача Б"` → `"задача А задача Б"` |
| `' '.join(block)` в `SemanticChunker` | межстрочные переносы внутри секции → пробелы |
| Шаг 2 (CHAR_MAP): `\u2014` → `-` (em-dash) | `"Кот — животное"` → `"Кот - животное"` |
| Шаг 4: `"спо-\nсобность"` → `"способность"` | дефисный перенос склеивается |
| Шаг 4a: `"выва- ливается"` → `"вываливается"` | пробел после дефиса в конце слова |
| Шаг 1: NFC | составной `й` → монолитный `й` |
| Шаг 6: `[ \t]+` → один пробел | двойные пробелы схлопываются |

## Архитектурное решение

Вся логика token-mapping **остаётся в `rag-indexer`** — потому что:
1. `preprocess()` уже живёт в `rag-indexer/parser/preprocessing/preprocessor.py`
2. Raw-файл читается там же: `read_original_utf8(file_path)` в `resolver.py`
3. Не нужно передавать нормализованный текст через HTTP

`UpdateModeResolveRequest` **остаётся без изменений**. `rag-backend` ничего нового не передаёт.

## Схема решения: char-map

Построить карту `normalized_pos → raw_pos`, применяя каждый шаг `preprocess()` через `re.finditer` **до** применения замены — накапливая смещения.

```
char_map: list[int]  (len == len(normalized))
char_map[i] = позиция i-го символа normalized в raw-строке
```

Затем fallback в resolver:
1. Прямой поиск провалился → `AnchorNotFoundError`
2. Построить `normalized_raw = preprocess(raw)`
3. Построить `char_map = build_char_map(raw, normalized_raw)`
4. Найти `anchor.value` в `normalized_raw` → `(norm_start, norm_end)`
5. Извлечь `raw[char_map[norm_start] : char_map[norm_end-1]+1]` — это точный raw-фрагмент
6. Повторить `apply_op(text=original, anchor_value=raw_fragment, ...)`

## Затронутые файлы

| Файл | Тип изменения |
|---|---|
| `rag-indexer/app/update_mode/text_ops_utils.py` | **Новый файл** — публичная `build_anchor_pattern()` |
| `rag-indexer/app/update_mode/text_ops.py` | `_build_anchor_pattern` → import из `text_ops_utils` |
| `rag-indexer/app/update_mode/token_anchor.py` | **Новый файл** — pure-функции char-map (~150 строк) |
| `rag-indexer/app/update_mode/resolver.py` | `_build_pending_change()` helper + fallback-блок |

## Что НЕ меняется

- `shared_contracts/models.py` — `UpdateModeResolveRequest` без изменений
- `rag-backend/app/services/update_mode_executor.py` — без изменений
- `text_ops.py` — `apply_op()` без изменений, только `_build_anchor_pattern` переезжает
- `applier.py`, `UpdateModeSession`, frontend/review UI — без изменений
- `preprocess()` — используется как есть через import
- `SemanticChunker` — без изменений

## Риски и ограничения

1. **Файл изменился между индексацией и resolve** — char_map строится по текущей версии файла. Митигация: `expected_sha256` обнаружит конфликт при apply.
2. **Производительность** — O(n) по символам, вызывается только при fallback (после провала прямого поиска).
3. **Шаг 4 (regex с группами)** — самый сложный кейс для char_map: нужно явно сопоставить `match.span(1)` и `match.span(2)` с позициями в normalized, пропустив дефис и переносы.
4. **Заголовки с em-dash** — LLM видит нормализованный дефис, raw содержит em-dash. Token-anchor решает через char_map шага 2.
