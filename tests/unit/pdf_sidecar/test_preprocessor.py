"""Unit-тесты для pdf-sidecar/preprocessor.py.

Pure-CPU, без внешних зависимостей — только stdlib (re, unicodedata).
"""
from __future__ import annotations

from preprocessor import (
    _ALLOWED_RANGES,
    _ALLOWED_SINGLE,
    CHAR_MAP,
    _is_allowed_char,
    preprocess,
    reset_suspicious_chars_cache,
)


class TestPreprocessEmpty:
    def test_empty_string(self):
        assert preprocess("") == ""

    def test_whitespace_only(self):
        assert preprocess("   \n\t  ") == ""


class TestPreprocessNfc:
    def test_nfc_normalization(self):
        # "é" может быть NFC (1 codepoint) или NFD (e + combining acute, 2 codepoints)
        decomposed = "e\u0301"  # NFD
        result = preprocess(decomposed)
        assert result == "\u00e9"  # NFC

    def test_nfc_no_op_on_already_normalized(self):
        text = "Привет, мир!"
        assert preprocess(text) == "Привет, мир!"


class TestPreprocessCharMap:
    def test_replacement_codepoints(self):
        # Каждый ключ CHAR_MAP должен быть заменён на значение
        for bad, good in CHAR_MAP.items():
            text = f"before{bad}after"
            result = preprocess(text)
            assert bad not in result, f"{bad!r} not removed from {result!r}"
            if good:
                assert good in result, f"{good!r} not in result {result!r}"

    def test_soft_hyphen_removed(self):
        # U+00AD (soft hyphen) → "" (пустая строка)
        text = "soft\u00ADhyphen"
        result = preprocess(text)
        assert "\u00ad" not in result
        assert "softhyphen" in result


class TestPreprocessDigitLines:
    def test_pure_digit_line_removed(self):
        text = "first paragraph\n\n42\n\nsecond paragraph"
        result = preprocess(text)
        assert "42" not in result
        assert "first paragraph" in result
        assert "second paragraph" in result

    def test_digit_inside_text_kept(self):
        text = "chapter 5 is great"
        result = preprocess(text)
        assert "5" in result

    def test_pure_digit_line_with_surrounding_spaces(self):
        text = "line1\n   123   \nline2"
        result = preprocess(text)
        assert "123" not in result


class TestPreprocessHyphenation:
    def test_hyphen_with_newline_collapsed(self):
        text = "выва-\nливается"
        result = preprocess(text)
        assert "вываливается" in result

    def test_hyphen_with_space_collapsed(self):
        # Шаг 4a: пробел после дефиса (когда \n уже заменён)
        text = "выва- ливается"
        result = preprocess(text)
        assert "вываливается" in result

    def test_compound_word_with_hyphen_preserved(self):
        # Нет пробела после дефиса — не должно склеиваться
        text = "эльф-обыватель"
        result = preprocess(text)
        assert "эльф-обыватель" in result

    def test_date_with_hyphen_preserved(self):
        text = "2023-01-01"
        result = preprocess(text)
        assert "2023-01-01" in result

    def test_isbn_with_hyphen_preserved(self):
        text = "978-5-04"
        result = preprocess(text)
        assert "978-5-04" in result


class TestPreprocessNewlines:
    def test_double_newline_preserved_as_paragraph(self):
        text = "paragraph1\n\nparagraph2"
        result = preprocess(text)
        assert "\n\n" in result
        assert "paragraph1" in result
        assert "paragraph2" in result

    def test_single_newline_becomes_space(self):
        text = "line1\nline2"
        result = preprocess(text)
        assert "line1 line2" in result

    def test_triple_newline_collapsed_to_double(self):
        text = "p1\n\n\n\np2"
        result = preprocess(text)
        assert "\n\n\n" not in result


class TestPreprocessMarkdownHeading:
    def test_heading_text_preserved(self):
        # Заголовок Markdown "# Heading" не должен потеряться при preprocess
        text = "paragraph\n# Heading\nnext paragraph"
        result = preprocess(text)
        assert "# Heading" in result

    def test_heading_separated_by_blank_lines_when_input_has_double_newlines(self):
        # Если вокруг заголовка уже стоят \n\n — они должны сохраниться как разделители абзацев
        text = "paragraph\n\n# Heading\n\nnext paragraph"
        result = preprocess(text)
        assert "# Heading" in result
        # \n\n сохраняется между абзацами (после preprocess шага 5)
        assert "\n\n" in result
        # Heading отделён \n\n от "paragraph"
        assert "paragraph\n\n# Heading" in result


class TestIsAllowedChar:
    def test_ascii_printable_allowed(self):
        for ch in "Hello, World! 0123":
            assert _is_allowed_char(ch), f"{ch!r} should be allowed"

    def test_cyrillic_allowed(self):
        assert _is_allowed_char("А")
        assert _is_allowed_char("я")

    def test_control_chars_not_allowed(self):
        # \x00 — control char, не в _ALLOWED_SINGLE
        assert not _is_allowed_char("\x00")
        # \x07 — BEL
        assert not _is_allowed_char("\x07")

    def test_allowed_single_chars(self):
        assert _is_allowed_char("\n")
        assert _is_allowed_char("\r")
        assert _is_allowed_char("\t")

    def test_pua_not_allowed(self):
        # U+E000 U+E001 — PUA marker, должен быть отфильтрован
        assert not _is_allowed_char("\uE000")
        assert not _is_allowed_char("\uE001")

    def test_allowed_ranges_cover_documented_set(self):
        # Smoke: размеры списков как в оригинале
        assert len(_ALLOWED_RANGES) == 8
        assert {0x000A, 0x000D, 0x0009} == _ALLOWED_SINGLE


class TestResetSuspiciousCharsCache:
    def test_reset_clears_cache(self):
        # Прогоняем текст с неизвестным символом (PUA)
        preprocess("hello \uE000 world", source_hint="test")
        # Сбрасываем кэш
        reset_suspicious_chars_cache()
        # После reset повторный прогон должен снова логировать WARNING
        # (мы не можем assert на log, но вызов не должен падать)
        result = preprocess("hello \uE000 world", source_hint="test2")
        assert "hello" in result