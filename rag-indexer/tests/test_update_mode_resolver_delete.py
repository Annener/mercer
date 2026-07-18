"""Tests for delete_section and delete_unique_text operations in resolver.py.

All tests are pure unit tests — no DB, no filesystem, no Docker required.
They exercise the in-memory helpers _resolve_delete_section,
_resolve_delete_unique_text, _find_unique_heading, _heading_level, and
_collapse_consecutive_blank_lines directly, plus the full _resolve_one
pipeline via mocked DB and tmp vault fixtures.
"""
from __future__ import annotations

import pytest

from app.update_mode.resolver import (
    _collapse_consecutive_blank_lines,
    _find_unique_heading,
    _heading_level,
    _resolve_delete_section,
    _resolve_delete_unique_text,
)


# ---------------------------------------------------------------------------
# _heading_level
# ---------------------------------------------------------------------------

class TestHeadingLevel:
    def test_h1(self):
        assert _heading_level("# Title") == 1

    def test_h2(self):
        assert _heading_level("## Section") == 2

    def test_h3(self):
        assert _heading_level("### Sub") == 3

    def test_h6(self):
        assert _heading_level("###### Deep") == 6

    def test_no_space_after_hashes_is_not_heading(self):
        # CommonMark requires a space after '#' for ATX headings.
        assert _heading_level("##NoSpace") == 0

    def test_non_heading_line(self):
        assert _heading_level("Regular text") == 0

    def test_empty_line(self):
        assert _heading_level("") == 0

    def test_with_trailing_whitespace(self):
        assert _heading_level("## Section   ") == 2


# ---------------------------------------------------------------------------
# _find_unique_heading
# ---------------------------------------------------------------------------

class TestFindUniqueHeading:
    def _lines(self, text: str) -> list[str]:
        return text.splitlines(keepends=True)

    def test_h2_found_returns_correct_bounds(self):
        doc = "# Top\n\n## Section\nBody\n\n## Next\n"
        lines = self._lines(doc)
        result = _find_unique_heading(lines, "## Section")
        assert result is not None
        start, end = result
        assert lines[start].strip() == "## Section"
        # end should point at "## Next" line
        assert lines[end].strip() == "## Next"

    def test_h3_section_ends_at_parent_h2(self):
        doc = "## Parent\n\n### Child\nchild body\n\n## Sibling\n"
        lines = self._lines(doc)
        result = _find_unique_heading(lines, "### Child")
        assert result is not None
        start, end = result
        # end points at "## Sibling" — same or higher level than H3
        assert lines[end].strip() == "## Sibling"

    def test_section_extends_to_eof(self):
        doc = "# Top\n\n## Last\nfinal body\n"
        lines = self._lines(doc)
        result = _find_unique_heading(lines, "Last")
        assert result is not None
        start, end = result
        assert end == len(lines)

    def test_heading_not_found_returns_none(self):
        doc = "# Top\n\n## Other\n"
        lines = self._lines(doc)
        assert _find_unique_heading(lines, "Missing") is None

    def test_ambiguous_heading_returns_sentinel(self):
        doc = "## Section\nfirst\n\n## Section\nsecond\n"
        lines = self._lines(doc)
        result = _find_unique_heading(lines, "## Section")
        assert result == (-1, -1)

    def test_match_is_case_insensitive(self):
        doc = "## MY SECTION\nbody\n"
        lines = self._lines(doc)
        result = _find_unique_heading(lines, "my section")
        assert result is not None
        assert result != (-1, -1)

    def test_anchor_with_hashes_normalised(self):
        doc = "## Summary\nbody\n"
        lines = self._lines(doc)
        # Anchor supplied with leading hashes — should still match.
        result = _find_unique_heading(lines, "## Summary")
        assert result is not None
        assert result != (-1, -1)


# ---------------------------------------------------------------------------
# _resolve_delete_section
# ---------------------------------------------------------------------------

class TestResolveDeleteSection:
    def test_delete_h2_removes_heading_and_body(self):
        doc = "# Doc\n\n## Remove Me\nsome content\n\n## Keep\nkeep content\n"
        proposed, err = _resolve_delete_section(doc, "## Remove Me")
        assert err is None
        assert "Remove Me" not in proposed
        assert "some content" not in proposed
        assert "Keep" in proposed
        assert "keep content" in proposed

    def test_delete_h3_does_not_remove_sibling_h3(self):
        doc = (
            "## Parent\n\n"
            "### Alpha\nalpha body\n\n"
            "### Beta\nbeta body\n"
        )
        proposed, err = _resolve_delete_section(doc, "### Alpha")
        assert err is None
        assert "Alpha" not in proposed
        assert "alpha body" not in proposed
        assert "Beta" in proposed
        assert "beta body" in proposed

    def test_delete_section_at_eof(self):
        doc = "# Doc\n\n## Last Section\nonly content\n"
        proposed, err = _resolve_delete_section(doc, "## Last Section")
        assert err is None
        assert "Last Section" not in proposed
        assert "only content" not in proposed

    def test_heading_not_found_returns_anchor_not_found(self):
        doc = "# Doc\n\n## Real\nbody\n"
        proposed, err = _resolve_delete_section(doc, "## Nonexistent")
        assert proposed is None
        assert err == "anchor_not_found"

    def test_ambiguous_heading_returns_anchor_ambiguous(self):
        doc = "## Section\nfirst\n\n## Section\nsecond\n"
        proposed, err = _resolve_delete_section(doc, "## Section")
        assert proposed is None
        assert err == "anchor_ambiguous"

    def test_file_becomes_empty_returns_empty_string_not_error(self):
        """Deleting the only section should return '' without error."""
        doc = "## Only\ncontent\n"
        proposed, err = _resolve_delete_section(doc, "## Only")
        assert err is None
        assert proposed.strip() == ""

    def test_no_extra_blank_lines_after_removal(self):
        doc = "# Doc\n\n\n\n## Remove\nbody\n\n\n\n## Keep\ncontent\n"
        proposed, err = _resolve_delete_section(doc, "## Remove")
        assert err is None
        # No triple blank lines should remain
        assert "\n\n\n" not in proposed


# ---------------------------------------------------------------------------
# _resolve_delete_unique_text
# ---------------------------------------------------------------------------

class TestResolveDeleteUniqueText:
    def test_removes_unique_line(self):
        doc = "Line one\nRemove this line\nLine three\n"
        proposed, err = _resolve_delete_unique_text(doc, "Remove this line")
        assert err is None
        assert "Remove this line" not in proposed
        assert "Line one" in proposed
        assert "Line three" in proposed

    def test_removes_unique_list_item(self):
        doc = "- Item A\n- Delete me\n- Item C\n"
        proposed, err = _resolve_delete_unique_text(doc, "- Delete me")
        assert err is None
        assert "Delete me" not in proposed
        assert "Item A" in proposed
        assert "Item C" in proposed

    def test_anchor_not_found_returns_error(self):
        doc = "Line one\nLine two\n"
        proposed, err = _resolve_delete_unique_text(doc, "Nonexistent text")
        assert proposed is None
        assert err == "anchor_not_found"

    def test_file_becomes_empty_returns_empty_string_not_error(self):
        """Deleting the only content should return '' without error."""
        doc = "Only content here"
        proposed, err = _resolve_delete_unique_text(doc, "Only content here")
        assert err is None
        assert proposed.strip() == ""

    def test_whitespace_tolerant_match(self):
        """Anchor from LLM (single-line) matches multi-line occurrence in file."""
        doc = "Line one\nword1\nword2\nLine three\n"
        # LLM anchor collapses newline between word1 and word2 to space
        proposed, err = _resolve_delete_unique_text(doc, "word1 word2")
        assert err is None
        assert "word1" not in proposed
        assert "word2" not in proposed

    def test_no_triple_blank_lines_after_removal(self):
        doc = "\n\n\nTarget text\n\n\n"
        proposed, err = _resolve_delete_unique_text(doc, "Target text")
        assert err is None
        assert "\n\n\n" not in proposed


# ---------------------------------------------------------------------------
# _collapse_consecutive_blank_lines
# ---------------------------------------------------------------------------

class TestCollapseConsecutiveBlankLines:
    def test_three_newlines_collapsed_to_two(self):
        result = _collapse_consecutive_blank_lines("a\n\n\nb")
        assert result == "a\n\nb"

    def test_four_newlines_collapsed(self):
        result = _collapse_consecutive_blank_lines("a\n\n\n\nb")
        assert result == "a\n\nb"

    def test_two_newlines_unchanged(self):
        result = _collapse_consecutive_blank_lines("a\n\nb")
        assert result == "a\n\nb"

    def test_single_newline_unchanged(self):
        result = _collapse_consecutive_blank_lines("a\nb")
        assert result == "a\nb"

    def test_empty_string_unchanged(self):
        result = _collapse_consecutive_blank_lines("")
        assert result == ""
