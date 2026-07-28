"""Token-Map Anchoring — pure-функции char-map алгоритма.

Модуль реализует построение карты ``normalized_pos -> raw_pos`` (char_map)
и использует её для нахождения точного raw-фрагмента, соответствующего
нормализованному якорю, сгенерированному LLM.

Public API
----------
build_char_map(raw, normalized) -> list[int]
find_anchor_offset(anchor_value, normalized_text) -> tuple[int, int] | None
extract_raw_fragment(raw, char_map, norm_start, norm_end) -> str
resolve_anchor_in_raw(anchor_value, raw) -> str | None

Все функции pure (без I/O, без БД, без сетевых вызовов).
"""
from __future__ import annotations

import logging
import re
import unicodedata

from parser.preprocessing.preprocessor import CHAR_MAP, _HEADING_FULL_LINE_RE, preprocess
from app.update_mode.text_ops_utils import build_anchor_pattern

log = logging.getLogger(__name__)


def build_char_map(raw: str, normalized: str) -> list[int]:
    """Построить карту ``normalized_pos -> raw_pos``.

    Воспроизводит каждый шаг ``preprocess()`` через ``re.finditer`` **до**
    фактического применения замены, отслеживая смещение между raw и
    normalized.

    Parameters
    ----------
    raw:
        Исходный текст файла (без нормализации).
    normalized:
        Результат ``preprocess(raw)``.

    Returns
    -------
    list[int]
        ``char_map[i]`` — позиция i-го символа normalized в raw-строке.
        ``len(char_map) == len(normalized)``. Монотонно неубывает.
        При несовпадении длин возвращает частичную карту без IndexError.
    """
    # current_text и current_offsets движутся синхронно через каждый шаг
    current_text: str = raw
    current_offsets: list[int] = list(range(len(raw)))

    # ------------------------------------------------------------------
    # Шаг 1: NFC-нормализация
    # ------------------------------------------------------------------
    new_text = unicodedata.normalize("NFC", current_text)
    if new_text != current_text:
        new_offsets: list[int] = []
        ri = 0
        ni = 0
        while ni < len(new_text) and ri < len(current_text):
            if new_text[ni] == current_text[ri]:
                new_offsets.append(current_offsets[ri])
                ri += 1
                ni += 1
            else:
                # NFC может склеить несколько code-unit в один символ
                found = False
                for span in range(2, min(5, len(current_text) - ri + 1)):
                    combined = unicodedata.normalize("NFC", current_text[ri : ri + span])
                    if new_text[ni : ni + len(combined)] == combined:
                        first_raw = current_offsets[ri]
                        for _ in range(len(combined)):
                            new_offsets.append(first_raw)
                        ri += span
                        ni += len(combined)
                        found = True
                        break
                if not found:
                    new_offsets.append(current_offsets[ri])
                    ri += 1
                    ni += 1
        current_offsets = new_offsets
        current_text = new_text

    # ------------------------------------------------------------------
    # Шаг 2: CHAR_MAP (посимвольные замены / удаления)
    # ------------------------------------------------------------------
    new_text = ""
    new_offsets = []
    for i, ch in enumerate(current_text):
        if ch in CHAR_MAP:
            replacement = CHAR_MAP[ch]
            if replacement:          # замена 1-к-1
                new_text += replacement
                new_offsets.append(current_offsets[i])
            # иначе soft hyphen — символ удалён, позиция пропускается
        else:
            new_text += ch
            new_offsets.append(current_offsets[i])
    current_text = new_text
    current_offsets = new_offsets

    # ------------------------------------------------------------------
    # Шаг 3: удаление строк из одних цифр
    # ------------------------------------------------------------------
    _pattern3 = re.compile(r"^\s*\d+\s*$", re.MULTILINE)
    new_text = ""
    new_offsets = []
    last = 0
    for m in _pattern3.finditer(current_text):
        for i in range(last, m.start()):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        last = m.end()  # skip matched region
    for i in range(last, len(current_text)):
        new_text += current_text[i]
        new_offsets.append(current_offsets[i])
    current_text = new_text
    current_offsets = new_offsets

    # ------------------------------------------------------------------
    # Шаг 4: склейка дефисного переноса (\w+)-\s*\n\s*(\w+) -> \1\2
    # ------------------------------------------------------------------
    _pattern4 = re.compile(r"(\w+)-\s*\n\s*(\w+)")
    new_text = ""
    new_offsets = []
    last = 0
    for m in _pattern4.finditer(current_text):
        for i in range(last, m.start()):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        # group(1) — 1-к-1
        g1s, g1e = m.span(1)
        for i in range(g1s, g1e):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        # дефис + \s*\n\s* — пропускаем
        # group(2) — 1-к-1
        g2s, g2e = m.span(2)
        for i in range(g2s, g2e):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        last = m.end()
    for i in range(last, len(current_text)):
        new_text += current_text[i]
        new_offsets.append(current_offsets[i])
    current_text = new_text
    current_offsets = new_offsets

    # ------------------------------------------------------------------
    # Шаг 4a: склейка дефиса+пробел (\w+)-\s+(\w) -> \1\2
    # ------------------------------------------------------------------
    _pattern4a = re.compile(r"(\w+)-\s+(\w)")
    new_text = ""
    new_offsets = []
    last = 0
    for m in _pattern4a.finditer(current_text):
        for i in range(last, m.start()):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        g1s, g1e = m.span(1)
        for i in range(g1s, g1e):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        # дефис + \s+ — пропускаем
        g2s, g2e = m.span(2)
        for i in range(g2s, g2e):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        last = m.end()
    for i in range(last, len(current_text)):
        new_text += current_text[i]
        new_offsets.append(current_offsets[i])
    current_text = new_text
    current_offsets = new_offsets

    # ------------------------------------------------------------------
    # Шаг 4b: оборачивание Markdown-заголовков в \n\n
    # Вставляемые символы \n\n не имеют raw-позиции — используем
    # позицию первого / последнего символа заголовка.
    # ------------------------------------------------------------------
    new_text = ""
    new_offsets = []
    last = 0
    for m in _HEADING_FULL_LINE_RE.finditer(current_text):
        for i in range(last, m.start()):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        first_raw = current_offsets[m.start()] if m.start() < len(current_offsets) else 0
        last_raw = current_offsets[m.end() - 1] if m.end() - 1 < len(current_offsets) else 0
        # prepend \n\n
        new_text += "\n\n"
        new_offsets.extend([first_raw, first_raw])
        # heading 1-к-1
        for i in range(m.start(), m.end()):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        # append \n\n
        new_text += "\n\n"
        new_offsets.extend([last_raw, last_raw])
        last = m.end()
    for i in range(last, len(current_text)):
        new_text += current_text[i]
        new_offsets.append(current_offsets[i])
    current_text = new_text
    current_offsets = new_offsets

    # убираем тройные+ \n, появившиеся после шага 4b
    current_text, current_offsets = _collapse_excess_newlines(current_text, current_offsets)

    # ------------------------------------------------------------------
    # Шаг 5: одинарный \n → пробел (через маркер \u2400\u2400)
    # ------------------------------------------------------------------
    _MARKER = "\u2400\u2400"
    # 5a: \n\n → маркер (2-к-2)
    new_text = ""
    new_offsets = []
    i = 0
    while i < len(current_text):
        if current_text[i : i + 2] == "\n\n":
            new_text += _MARKER
            new_offsets.append(current_offsets[i])
            new_offsets.append(current_offsets[i + 1])
            i += 2
        else:
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
            i += 1
    current_text = new_text
    current_offsets = new_offsets

    # 5b: одинарный \n → пробел (1-к-1)
    new_text = ""
    new_offsets = []
    for i, ch in enumerate(current_text):
        new_text += " " if ch == "\n" else ch
        new_offsets.append(current_offsets[i])
    current_text = new_text
    current_offsets = new_offsets

    # 5c: маркер → \n\n (2-к-2)
    new_text = ""
    new_offsets = []
    i = 0
    while i < len(current_text):
        if current_text[i : i + 2] == _MARKER:
            new_text += "\n\n"
            new_offsets.append(current_offsets[i])
            new_offsets.append(current_offsets[i + 1])
            i += 2
        else:
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
            i += 1
    current_text = new_text
    current_offsets = new_offsets

    # ------------------------------------------------------------------
    # Шаг 6: [ \t]+ → один пробел (N-к-1)
    # ------------------------------------------------------------------
    _pattern6 = re.compile(r"[ \t]+")
    new_text = ""
    new_offsets = []
    last = 0
    for m in _pattern6.finditer(current_text):
        for i in range(last, m.start()):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        new_text += " "
        new_offsets.append(current_offsets[m.start()])
        last = m.end()
    for i in range(last, len(current_text)):
        new_text += current_text[i]
        new_offsets.append(current_offsets[i])
    current_text = new_text
    current_offsets = new_offsets

    # пробелы перед \n — удаляем пробелы, оставляем \n
    _pattern6b = re.compile(r" +\n")
    new_text = ""
    new_offsets = []
    last = 0
    for m in _pattern6b.finditer(current_text):
        for i in range(last, m.start()):
            new_text += current_text[i]
            new_offsets.append(current_offsets[i])
        nl_pos = m.end() - 1
        new_text += "\n"
        new_offsets.append(current_offsets[nl_pos])
        last = m.end()
    for i in range(last, len(current_text)):
        new_text += current_text[i]
        new_offsets.append(current_offsets[i])
    current_text = new_text
    current_offsets = new_offsets

    # 3+ \n → 2
    current_text, current_offsets = _collapse_excess_newlines(current_text, current_offsets)

    # ------------------------------------------------------------------
    # .strip(): убираем ведущие/хвостовые пробелы
    # ------------------------------------------------------------------
    stripped = current_text.strip()
    if not stripped:
        return []
    strip_start = len(current_text) - len(current_text.lstrip())
    strip_end = strip_start + len(stripped)
    final_offsets = current_offsets[strip_start:strip_end]

    if len(final_offsets) != len(normalized):
        log.warning(
            "build_char_map: length mismatch — char_map=%d, normalized=%d; "
            "returning partial map",
            len(final_offsets),
            len(normalized),
        )
        # возвращаем минимально-корректную частичную карту
        min_len = min(len(final_offsets), len(normalized))
        return final_offsets[:min_len]

    return final_offsets


def _collapse_excess_newlines(
    text: str, offsets: list[int]
) -> tuple[str, list[int]]:
    """Вспомогательная функция: заменяет 3+ \\n → 2 \\n, синхронно обновляя offsets."""
    pattern = re.compile(r"\n{3,}")
    new_text = ""
    new_offsets: list[int] = []
    last = 0
    for m in pattern.finditer(text):
        for i in range(last, m.start()):
            new_text += text[i]
            new_offsets.append(offsets[i])
        for i in range(m.start(), min(m.start() + 2, m.end())):
            new_text += text[i]
            new_offsets.append(offsets[i])
        last = m.end()
    for i in range(last, len(text)):
        new_text += text[i]
        new_offsets.append(offsets[i])
    return new_text, new_offsets


def find_anchor_offset(
    anchor_value: str, normalized_text: str
) -> tuple[int, int] | None:
    """Найти позицию anchor_value в normalized_text.

    Parameters
    ----------
    anchor_value:
        Строка якоря (нормализованный текст от LLM).
    normalized_text:
        Нормализованный текст документа (результат ``preprocess(raw)``).

    Returns
    -------
    tuple[int, int] | None
        ``(match.start(), match.end())`` первого совпадения, или ``None``.
    """
    pattern = build_anchor_pattern(anchor_value)
    m = pattern.search(normalized_text)
    if m is None:
        return None
    return m.start(), m.end()


def extract_raw_fragment(
    raw: str,
    char_map: list[int],
    norm_start: int,
    norm_end: int,
) -> str:
    """Извлечь raw-фрагмент по границам normalized-позиций.

    Parameters
    ----------
    raw:
        Исходный (не нормализованный) текст файла.
    char_map:
        Карта, построенная функцией :func:`build_char_map`.
    norm_start:
        Начальная позиция в normalized-тексте (включительно).
    norm_end:
        Конечная позиция в normalized-тексте (не включительно).

    Returns
    -------
    str
        Фрагмент исходного raw-текста, соответствующий [norm_start, norm_end).
    """
    raw_start = char_map[norm_start]
    raw_end = char_map[norm_end - 1] + 1
    return raw[raw_start:raw_end]


def resolve_anchor_in_raw(anchor_value: str, raw: str) -> str | None:
    """Публичная точка входа: найти raw-фрагмент для нормализованного якоря.

    Объединяет :func:`build_char_map`, :func:`find_anchor_offset` и
    :func:`extract_raw_fragment` в единый пайплайн.

    Parameters
    ----------
    anchor_value:
        Значение якоря в нормализованном виде (как видел LLM).
    raw:
        Исходный текст файла (сырой, с диска).

    Returns
    -------
    str | None
        Raw-фрагмент, соответствующий якорю, или ``None`` если якорь
        не найден в нормализованном тексте.
    """
    normalized_raw = preprocess(raw, source_hint="token_anchor")
    char_map = build_char_map(raw, normalized_raw)
    offset = find_anchor_offset(anchor_value, normalized_raw)
    if offset is None:
        log.debug(
            "resolve_anchor_in_raw: anchor not found in normalized text "
            "(anchor_value=%r)",
            anchor_value[:80],
        )
        return None
    norm_start, norm_end = offset
    return extract_raw_fragment(raw, char_map, norm_start, norm_end)
