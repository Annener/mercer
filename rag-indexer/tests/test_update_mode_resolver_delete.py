"""Tests for delete operations in rag-indexer/app/update_mode/resolver.py

All tests are pure unit tests on the in-memory helpers:
  _delete_section, _delete_unique_text, _heading_level,
  _collapse_consecutive_blank_lines, _AnchorAmbiguousError.

No DB, no filesystem, no Docker required.

Test matrix:
  _heading_level             — H1-H6 recognised; non-headings return None
  _collapse_blank_lines      — 3+ blanks collapsed to 2
  _delete_section
    ✓ H2 section removed, sibling H2 untouched
    ✓ H2 body (list items) fully removed
    ✓ nested H3 removed, parent H2 survives
    ✓ anchor_not_found → returns None
    ✓ anchor_ambiguous → raises _AnchorAmbiguousError
    ✓ only section in file → empty string (not error)
    ✓ no 3+ consecutive blank lines after removal
    ✓ anchor supplied with/without leading '#' both match
  _delete_unique_text
    ✓ list item removed, siblings untouched
    ✓ line count decreases by 1
    ✓ anchor_not_found → returns None
    ✓ anchor_ambiguous → raises _AnchorAmbiguousError
    ✓ only line in file → empty string (not error)
    ✓ no 3+ consecutive blank lines after removal
    ✓ leading/trailing whitespace stripped in fragment match
"""
from __future__ import annotations

import pytest

from app.update_mode.resolver import (
    _AnchorAmbiguousError,
    _collapse_consecutive_blank_lines,
    _delete_section,
    _delete_unique_text,
    _heading_level,
)


# ---------------------------------------------------------------------------
# _heading_level
# ---------------------------------------------------------------------------

class TestHeadingLevel:
    def test_h1(self):
        assert _heading_level("# Title\n") == 1

    def test_h2(self):
        assert _heading_level("## Section\n") == 2

    def test_h3(self):
        assert _heading_level("### Sub\n") == 3

    def test_h6(self):
        assert _heading_level("###### Deep\n") == 6

    def test_not_a_heading_plain(self):
        assert _heading_level("plain text\n") is None

    def test_not_a_heading_hash_no_space(self):
        # '#hashtag' is not a CommonMark ATX heading
        assert _heading_level("#hashtag\n") is None

    def test_empty_line(self):
        assert _heading_level("\n") is None

    def test_heading_no_trailing_newline(self):
        assert _heading_level("## Title") == 2


# ---------------------------------------------------------------------------
# _collapse_consecutive_blank_lines
# ---------------------------------------------------------------------------

class TestCollapseBlankLines:
    def test_no_blanks_unchanged(self):
        lines = ["line1\n", "line2\n"]
        assert _collapse_consecutive_blank_lines(lines) == lines

    def test_two_blanks_unchanged(self):
        lines = ["a\n", "\n", "\n", "b\n"]
        assert _collapse_consecutive_blank_lines(lines) == lines

    def test_three_blanks_collapsed_to_two(self):
        lines = ["a\n", "\n", "\n", "\n", "b\n"]
        result = _collapse_consecutive_blank_lines(lines)
        assert result == ["a\n", "\n", "\n", "b\n"]

    def test_five_blanks_collapsed_to_two(self):
        lines = ["a\n"] + ["\n"] * 5 + ["b\n"]
        result = _collapse_consecutive_blank_lines(lines)
        blank_count = sum(1 for l in result if l.strip() == "")
        assert blank_count == 2


# ---------------------------------------------------------------------------
# _delete_section
# ---------------------------------------------------------------------------

_DOC_MULTIHEADING = """\
# Задачи на неделю

## Административное

- [x] Оплатить интернет
- [ ] Сходить к Ивану

## Встречи

### Встреча с Иваном (пятница)

Обсудить детали проекта.
"""


class TestDeleteSection:
    def test_delete_h2_leaves_sibling_h2(self):
        result = _delete_section(_DOC_MULTIHEADING, "## Административное")
        assert result is not None
        assert "Административное" not in result
        assert "Задачи на неделю" in result
        assert "Встречи" in result

    def test_delete_h2_removes_body(self):
        result = _delete_section(_DOC_MULTIHEADING, "Административное")  # without ##
        assert result is not None
        assert "Оплатить интернет" not in result
        assert "Сходить к Ивану" not in result

    def test_delete_h3_nested_leaves_parent_h2(self):
        result = _delete_section(_DOC_MULTIHEADING, "### Встреча с Иваном (пятница)")
        assert result is not None
        assert "Встреча с Иваном" not in result
        assert "Обсудить детали" not in result
        assert "Встречи" in result

    def test_anchor_not_found_returns_none(self):
        result = _delete_section(_DOC_MULTIHEADING, "## Несуществующий раздел")
        assert result is None

    def test_anchor_ambiguous_raises(self):
        doc = "## Одинаковый\nТекст 1\n\n## Одинаковый\nТекст 2\n"
        with pytest.raises(_AnchorAmbiguousError):
            _delete_section(doc, "Одинаковый")

    def test_only_section_returns_empty_string(self):
        doc = "## Единственный раздел\n\nКакой-то текст.\n"
        result = _delete_section(doc, "Единственный раздел")
        assert result is not None
        assert result.strip() == ""

    def test_no_triple_blank_lines_after_removal(self):
        doc = "# Док\n\n## Удалить\n\nТекст.\n\n## Остаться\n\nЧто-то.\n"
        result = _delete_section(doc, "Удалить")
        assert result is not None
        assert "\n\n\n" not in result

    def test_anchor_matches_with_or_without_hashes(self):
        """Both '## Summary' and 'Summary' as anchor should match."""
        doc = "# Doc\n\n## Summary\nbody\n\n## Other\nstuff\n"
        r1 = _delete_section(doc, "## Summary")
        r2 = _delete_section(doc, "Summary")
        assert r1 is not None
        assert r2 is not None
        assert r1 == r2


# ---------------------------------------------------------------------------
# _delete_unique_text
# ---------------------------------------------------------------------------

_DOC_TASKS = """\
# Задачи

- [x] Оплатить интернет
- [ ] Сходить к Ивану
- [ ] Записаться к врачу
"""


class TestDeleteUniqueText:
    def test_delete_list_item_leaves_siblings(self):
        result = _delete_unique_text(_DOC_TASKS, "- [ ] Сходить к Ивану")
        assert result is not None
        assert "Сходить к Ивану" not in result
        assert "Оплатить интернет" in result
        assert "Записаться к врачу" in result

    def test_delete_decreases_line_count_by_one(self):
        lines_before = _DOC_TASKS.splitlines()
        result = _delete_unique_text(_DOC_TASKS, "- [ ] Сходить к Ивану")
        assert result is not None
        assert len(result.splitlines()) == len(lines_before) - 1

    def test_anchor_not_found_returns_none(self):
        result = _delete_unique_text(_DOC_TASKS, "- [ ] Несуществующая задача")
        assert result is None

    def test_anchor_ambiguous_raises(self):
        doc = "- [ ] Дубль\n- [ ] Дубль\n"
        with pytest.raises(_AnchorAmbiguousError):
            _delete_unique_text(doc, "- [ ] Дубль")

    def test_only_line_returns_empty_string(self):
        doc = "- [ ] Единственная задача\n"
        result = _delete_unique_text(doc, "- [ ] Единственная задача")
        assert result is not None
        assert result.strip() == ""

    def test_no_triple_blank_lines_after_removal(self):
        doc = "# Док\n\n\n- [ ] Удалить\n\n\nЧто-то.\n"
        result = _delete_unique_text(doc, "- [ ] Удалить")
        assert result is not None
        assert "\n\n\n" not in result

    def test_strips_whitespace_in_fragment_for_match(self):
        """Fragment match is strip()-based; leading/trailing spaces are ignored."""
        result = _delete_unique_text(_DOC_TASKS, "  - [ ] Сходить к Ивану  ")
        assert result is not None
        assert "Сходить к Ивану" not in result
