"""Unit-тесты для модуля token_anchor (Фаза 2, Token-Map Anchoring).

Запуск:
    pytest rag-indexer/tests/test_token_anchor.py -v
"""
from __future__ import annotations

import unicodedata

from app.update_mode.token_anchor import (
    build_char_map,
    extract_raw_fragment,
    find_anchor_offset,
    resolve_anchor_in_raw,
)
from parser.preprocessing.preprocessor import preprocess

# ---------------------------------------------------------------------------
# Вспомогательная функция: строим нормализованный текст теми же шагами
# что и preprocess(), чтобы тест не зависел от конкретной реализации
# ---------------------------------------------------------------------------

def _norm(raw: str) -> str:
    """Нормализовать raw через preprocess."""
    return preprocess(raw, source_hint="test")


# ---------------------------------------------------------------------------
# build_char_map — длина и монотонность
# ---------------------------------------------------------------------------

class TestBuildCharMapProperties:
    """Свойства char_map: len == len(normalized), монотонно неубывает."""

    def test_length_equals_normalized(self) -> None:
        """len(char_map) == len(normalized) для типичного текста."""
        raw = "Кот — животное"
        norm = _norm(raw)
        cmap = build_char_map(raw, norm)
        assert len(cmap) == len(norm)

    def test_monotone_nondecreasing(self) -> None:
        """char_map монотонно неубывает."""
        raw = "задача А\nзадача Б"
        norm = _norm(raw)
        cmap = build_char_map(raw, norm)
        for i in range(1, len(cmap)):
            assert cmap[i] >= cmap[i - 1], (
                f"Нарушена монотонность: cmap[{i}]={cmap[i]} < cmap[{i-1}]={cmap[i-1]}"
            )

    def test_empty_string(self) -> None:
        """Пустой raw → пустая карта."""
        assert build_char_map("", "") == []

    def test_no_transformations(self) -> None:
        """Текст без трансформаций — char_map тождественная."""
        raw = "hello world"
        norm = _norm(raw)
        cmap = build_char_map(raw, norm)
        assert len(cmap) == len(norm)
        # позиции должны совпадать с индексами
        for i, raw_pos in enumerate(cmap):
            assert raw[raw_pos] == norm[i]


# ---------------------------------------------------------------------------
# resolve_anchor_in_raw — основные тестовые кейсы из фазы
# ---------------------------------------------------------------------------

class TestResolveAnchorInRaw:
    """Функциональные тесты: raw-фрагмент найден корректно."""

    def test_em_dash(self) -> None:
        """Em-dash: raw 'Кот — животное' → anchor 'Кот - животное' → raw-фрагмент 'Кот — животное'."""
        raw = "Кот \u2014 животное"
        anchor = "Кот - животное"
        fragment = resolve_anchor_in_raw(anchor, raw)
        assert fragment is not None
        assert fragment == raw

    def test_newline_becomes_space(self) -> None:
        """Перенос строки: raw 'задача А\nзадача Б' → anchor 'задача А задача Б'."""
        raw = "задача А\nзадача Б"
        anchor = "задача А задача Б"
        fragment = resolve_anchor_in_raw(anchor, raw)
        assert fragment is not None
        assert fragment == raw

    def test_hyphen_line_break_step4(self) -> None:
        """Дефисный перенос (шаг 4): 'спо-\nсобность' → anchor 'способность'."""
        raw = "спо-\nсобность"
        anchor = "способность"
        fragment = resolve_anchor_in_raw(anchor, raw)
        assert fragment is not None
        assert fragment == raw

    def test_hyphen_space_step4a(self) -> None:
        """Дефис+пробел (шаг 4a): 'выва- ливается' → anchor 'вываливается'."""
        raw = "выва- ливается"
        anchor = "вываливается"
        fragment = resolve_anchor_in_raw(anchor, raw)
        assert fragment is not None
        assert fragment == raw

    def test_nfc_normalization(self) -> None:
        """NFC: raw с NFD-й → anchor с NFC-й → фрагмент найден корректно."""
        # NFD: й = и (U+0438) + краткая (U+0306)
        raw_nfd = "\u0438\u0306" + "огурт"  # NFD-й + огурт
        anchor_nfc = unicodedata.normalize("NFC", raw_nfd)  # монолитный й + огурт
        fragment = resolve_anchor_in_raw(anchor_nfc, raw_nfd)
        assert fragment is not None
        # нормализованная форма anchor должна совпадать с NFC фрагмента
        assert unicodedata.normalize("NFC", fragment) == anchor_nfc

    def test_anchor_not_found_returns_none(self) -> None:
        """Якорь не найден → None."""
        raw = "обычный текст"
        anchor = "этого нет в документе совсем"
        result = resolve_anchor_in_raw(anchor, raw)
        assert result is None

    def test_soft_hyphen_removed(self) -> None:
        """Soft hyphen (U+00AD) удаляется; char_map не ломается."""
        # soft hyphen внутри слова
        raw = "со\u00ADвет"
        anchor = "совет"  # после удаления мягкого переноса
        fragment = resolve_anchor_in_raw(anchor, raw)
        assert fragment is not None
        assert "совет" in unicodedata.normalize("NFC", fragment)

    def test_partial_anchor_in_long_text(self) -> None:
        """Якорь совпадает с частью длинного документа."""
        raw = "Введение.\nОсновная часть:\nпункт первый\nпункт второй.\nЗаключение."
        anchor = "пункт первый пункт второй"
        fragment = resolve_anchor_in_raw(anchor, raw)
        assert fragment is not None
        assert "пункт первый" in fragment
        assert "пункт второй" in fragment


# ---------------------------------------------------------------------------
# find_anchor_offset
# ---------------------------------------------------------------------------

class TestFindAnchorOffset:
    """Тесты find_anchor_offset."""

    def test_returns_correct_span(self) -> None:
        """find_anchor_offset возвращает корректный span."""
        normalized = "один два три"
        anchor = "два три"
        result = find_anchor_offset(anchor, normalized)
        assert result is not None
        start, end = result
        assert normalized[start:end] == "два три"

    def test_returns_none_when_not_found(self) -> None:
        """find_anchor_offset возвращает None если якорь не найден."""
        result = find_anchor_offset("нет такого", "совсем другой текст")
        assert result is None

    def test_whitespace_tolerant(self) -> None:
        """find_anchor_offset использует whitespace-tolerant паттерн."""
        # build_anchor_pattern объединяет слова через \s+
        result = find_anchor_offset("один два", "один   два")
        assert result is not None


# ---------------------------------------------------------------------------
# extract_raw_fragment
# ---------------------------------------------------------------------------

class TestExtractRawFragment:
    """Тесты extract_raw_fragment."""

    def test_basic_extraction(self) -> None:
        """extract_raw_fragment возвращает правильный срез raw."""
        raw = "hello world"
        norm = _norm(raw)
        cmap = build_char_map(raw, norm)
        # найдём 'world' в norm
        start = norm.index("world")
        end = start + len("world")
        fragment = extract_raw_fragment(raw, cmap, start, end)
        assert fragment == "world"

    def test_em_dash_extraction(self) -> None:
        """extract_raw_fragment корректно возвращает em-dash фрагмент."""
        raw = "A \u2014 B"
        norm = _norm(raw)
        cmap = build_char_map(raw, norm)
        start = norm.index("A")
        end = norm.index("B") + 1
        fragment = extract_raw_fragment(raw, cmap, start, end)
        assert "\u2014" in fragment
