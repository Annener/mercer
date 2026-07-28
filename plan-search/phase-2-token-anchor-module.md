# Фаза 2 — Новый модуль `token_anchor.py`

> **Перед началом выполнения:** прочитай `plan-search/concept.md` и убедись, что все изменения фазы соответствуют концепту.

## Цель

Создать новый модуль `rag-indexer/app/update_mode/token_anchor.py` — pure-функции без I/O, реализующие char-map алгоритм для нахождения raw-фрагмента, соответствующего нормализованному якорю.

## Контекст: зависимости

**Фаза 1 должна быть выполнена** — модуль `text_ops_utils.py` должен существовать.

Ключевые зависимости для импорта:
- `from parser.preprocessing.preprocessor import preprocess` (путь: `rag-indexer/parser/preprocessing/preprocessor.py`)
- `from app.update_mode.text_ops_utils import build_anchor_pattern`

### Функция `preprocess` (preprocessor.py)

Выполняет следующие шаги в порядке:
1. NFC-нормализация (`unicodedata.normalize("NFC", text)`)
2. Замена символов через `CHAR_MAP` (em-dash `\u2014` → `-`, soft hyphen `\u00AD` → `""`, неразрывный пробел `\u00A0` → ` `, и другие)
3. Удаление строк из одних цифр (`re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)`)
4. Склейка дефисного переноса: `re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", text)`
5. Шаг 4a: склейка дефиса+пробел: `re.sub(r"(\w+)-\s+(\w)", r"\1\2", text)`
6. Шаг 4b: Markdown-заголовки оборачиваются `\n\n`
7. Шаг 5: одинарный `\n` → пробел (с временным маркером `\u2400\u2400` для двойных)
8. Шаг 6: `[ \t]+` → один пробел, убираются пробелы перед `\n`
9. `.strip()`

## Задача

### Создать `rag-indexer/app/update_mode/token_anchor.py`

Модуль содержит **4 функции** в следующем порядке реализации:

#### 1. `build_char_map(raw: str, normalized: str) -> list[int]`

Строит карту `normalized_pos → raw_pos`.

**Алгоритм:** воспроизвести каждый шаг `preprocess()` через `re.finditer` **до** фактического применения замены, отслеживая смещение между raw и normalized.

Правила построения карты для каждого шага:

- **Шаг 1 (NFC):** итерировать оба текста одновременно; при обнаружении несовпадения длин (многосимвольный кластер → один символ) `raw_pos` смещается на длину исходного кластера, `norm_pos` — на 1.
- **Шаг 2 (CHAR_MAP, посимвольные замены):** один raw-символ → один или ноль norm-символов. Если символ удалён (soft hyphen `\u00AD` → `""`), `raw_pos` двигается вперёд без записи в `char_map`. Если символ заменён 1-к-1 (em-dash → дефис) — `char_map[norm_pos] = raw_pos`.
- **Шаг 3 (удаление строк из цифр):** перед `re.sub` использовать `re.finditer` чтобы найти матчи; символы совпавших диапазонов пропускаются (не пишутся в char_map).
- **Шаг 4 (дефисный перенос `(\w+)-\s*\n\s*(\w+)`):** перед `re.sub` — `re.finditer` по текущему raw. Для каждого match: символы `match.group(1)` → 1-к-1 в char_map; символы `"-\s*\n\s*"` между группами — пропущены; символы `match.group(2)` → 1-к-1 в char_map.
- **Шаг 4a (дефиса+пробел `(\w+)-\s+(\w)`):** аналогично шагу 4; символы `group(1)` → 1-к-1; символы `"-\s+"` — пропущены; символ `group(2)` → 1-к-1.
- **Шаг 4b (Markdown-заголовки):** заголовки оборачиваются `\n\n` с обеих сторон — вставляются новые символы в normalized. Учесть что `raw_pos` не смещается для добавленных `\n\n`, но `norm_pos` двигается вперёд.
- **Шаг 5 (одинарный `\n` → пробел):** 1-к-1 замена, `char_map[norm_pos] = raw_pos` для каждого `\n`.
- **Шаг 6 (`[ \t]+` → один пробел):** N raw-пробелов → 1 norm-пробел. `char_map[norm_pos] = raw_pos` первого пробела из группы.

**Гарантия:** `len(char_map) == len(normalized)`. `char_map` монотонно неубывает.

#### 2. `find_anchor_offset(anchor_value: str, normalized_text: str) -> tuple[int, int] | None`

- Использует `build_anchor_pattern(anchor_value)` из `text_ops_utils`
- Ищет первое совпадение через `pattern.search(normalized_text)`
- Возвращает `(match.start(), match.end())` или `None` если не найдено

#### 3. `extract_raw_fragment(raw: str, char_map: list[int], norm_start: int, norm_end: int) -> str`

- `raw_start = char_map[norm_start]`
- `raw_end = char_map[norm_end - 1] + 1`
- Возвращает `raw[raw_start:raw_end]`

#### 4. `resolve_anchor_in_raw(anchor_value: str, raw: str) -> str | None`

Публичная точка входа. Объединяет функции 1–3:

```
normalized_raw = preprocess(raw, source_hint="token_anchor")
char_map = build_char_map(raw, normalized_raw)
offset = find_anchor_offset(anchor_value, normalized_raw)
if offset is None:
    return None
return extract_raw_fragment(raw, char_map, *offset)
```

## Тесты

Создать `rag-indexer/tests/test_token_anchor.py` с unit-тестами для каждой функции.

Обязательные тестовые кейсы для `build_char_map` / `resolve_anchor_in_raw`:
- Em-dash: raw `"Кот — животное"` → anchor `"Кот - животное"` должен находить raw-фрагмент `"Кот — животное"`
- Перенос строки: raw `"задача А\nзадача Б"` → anchor `"задача А задача Б"` → raw-фрагмент `"задача А\nзадача Б"`
- Дефисный перенос (шаг 4): raw `"спо-\nсобность"` → anchor `"способность"` → raw-фрагмент `"спо-\nсобность"`
- Дефис+пробел (шаг 4a): raw `"выва- ливается"` → anchor `"вываливается"` → raw-фрагмент `"выва- ливается"`
- NFC: raw с составным `й` (U+0439 или NFD) → anchor с монолитным `й` → raw-фрагмент находится корректно
- Anchor not found: `find_anchor_offset` возвращает `None`
- Soft hyphen (CHAR_MAP `\u00AD` → `""`): символ удалён, char_map не ломается

## Требования

- Модуль `token_anchor.py` содержит **только pure-функции** — никаких I/O, никаких БД, никаких сетевых вызовов
- Импорт `preprocess` производится напрямую из `parser.preprocessing.preprocessor`
- Если `build_char_map` получает тексты с несоответствием длин (ошибка вычислений), не падать с IndexError — обработать gracefully (вернуть частичную карту или None)
- Все тесты Фазы 1 должны продолжать проходить
