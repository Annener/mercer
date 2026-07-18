"""Tests for delete operations in rag-indexer/app/update_mode/resolver.py

All tests are pure unit tests on the in-memory helpers:
  _delete_section, _delete_unique_text, _heading_level,
  _collapse_consecutive_blank_lines, _AnchorAmbiguousError.

Also covers _resolve_one dispatcher integration (mocked DB + filesystem)
to verify that anchor_ambiguous and anchor_not_found are correctly
translated into RESOLUTION_FAILED changes with the right error_code.

No real DB, no real filesystem, no Docker required.

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
  _resolve_one (integration, mocked)
    ✓ DELETE_SECTION anchor_ambiguous → RESOLUTION_FAILED error_code=anchor_ambiguous
    ✓ DELETE_SECTION anchor_not_found → RESOLUTION_FAILED error_code=anchor_not_found
    ✓ DELETE_UNIQUE_TEXT anchor_ambiguous → RESOLUTION_FAILED error_code=anchor_ambiguous
    ✓ DELETE_UNIQUE_TEXT anchor_not_found → RESOLUTION_FAILED error_code=anchor_not_found
    ✓ DELETE_SECTION success → PENDING, proposed_content retains remaining file content
    ✓ DELETE_UNIQUE_TEXT success → PENDING, deleted line absent from proposed_content
    ✓ DELETE_SECTION only section → PENDING, proposed_content is empty string (empty file, not error)
    ✓ DELETE_UNIQUE_TEXT only line → PENDING, proposed_content is empty string (empty file, not error)
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.update_mode.resolver import (
    _AnchorAmbiguousError,
    _collapse_consecutive_blank_lines,
    _delete_section,
    _delete_unique_text,
    _heading_level,
    _resolve_one,
)
from shared_contracts.models import (
    UpdateModeAction,
    UpdateModeAnchor,
    UpdateModeChangeStatus,
    UpdateModeIntent,
    UpdateModeOperation,
    UpdateModeResolveRequest,
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


# ---------------------------------------------------------------------------
# _resolve_one — integration tests (mocked DB + filesystem)
#
# These tests verify that the dispatcher correctly translates
# _AnchorAmbiguousError → error_code="anchor_ambiguous" and
# None return → error_code="anchor_not_found" for both delete operations,
# and that successful deletes yield PENDING status with correct proposed_content.
#
# proposed_content semantics for delete operations:
#   - On partial delete (other content remains): proposed_content contains the
#     remaining file content (not empty string).
#   - On total delete (only section/line in file): proposed_content == "" and
#     status is still PENDING — empty file is a warning, not an error.
# ---------------------------------------------------------------------------

_VAULT_ID = "vault-test-001"
_DOC_ID = str(uuid.uuid4())
_CHANGE_ID = "chg-001"

# Document content used in integration tests
_FILE_WITH_SECTION = "## Удалить меня\n\nТекст раздела.\n\n## Оставить\n\nДругой текст.\n"
_FILE_DUPLICATE_SECTION = "## Дубль\nТекст.\n\n## Дубль\nЕщё текст.\n"
_FILE_WITH_LINE = "# Задачи\n\n- [ ] Удалить эту строку\n- [ ] Оставить эту\n"
_FILE_DUPLICATE_LINE = "- [ ] Дубль\n- [ ] Дубль\n"
# Files where the deleted element is the only content → empty file after delete
_FILE_ONLY_SECTION = "## Единственный раздел\n\nТекст раздела.\n"
_FILE_ONLY_LINE = "- [ ] Единственная строка\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_intent(
    operation: UpdateModeOperation,
    anchor_value: str,
    anchor_kind: str = "markdown_heading",
) -> UpdateModeIntent:
    return UpdateModeIntent(
        change_id=_CHANGE_ID,
        action=UpdateModeAction.UPDATE,
        description="test delete",
        document_id=_DOC_ID,
        operation=operation,
        anchor=UpdateModeAnchor(kind=anchor_kind, value=anchor_value),
        content="",
    )


def _make_request() -> UpdateModeResolveRequest:
    return UpdateModeResolveRequest(
        chat_id="chat-001",
        campaign_id="camp-001",
        domain_id="dom-001",
        vault_ids=[_VAULT_ID],
        intents=[],
        default_vault_id=_VAULT_ID,
        candidate_document_ids=[_DOC_ID],
    )


def _mock_db(vault_id: str = _VAULT_ID, source_path: str = "notes/test.md") -> AsyncMock:
    db = AsyncMock()
    db._fetchrow = AsyncMock(return_value={"vault_id": vault_id, "source_path": source_path})
    return db


def _patch_fs(file_content: str, vault_id: str = _VAULT_ID, source_path: str = "notes/test.md"):
    """Context manager that patches fs_git helpers to use in-memory content."""
    import contextlib

    vault_root = Path(f"/vaults/{vault_id}")
    file_path = vault_root / source_path

    @contextlib.contextmanager
    def _ctx():
        with (
            patch("app.update_mode.resolver.resolve_vault_root", return_value=vault_root),
            patch("app.update_mode.resolver.resolve_file_path", return_value=file_path),
            patch("app.update_mode.resolver.read_original_utf8", return_value=file_content),
            patch("app.update_mode.resolver.build_unified_diff", return_value="--- diff ---"),
        ):
            yield

    return _ctx()


class TestResolveOneDeleteSection:
    @pytest.mark.asyncio
    async def test_anchor_ambiguous_returns_failed(self):
        intent = _make_intent(UpdateModeOperation.DELETE_SECTION, "Дубль")
        request = _make_request()
        db = _mock_db()

        with _patch_fs(_FILE_DUPLICATE_SECTION):
            result = await _resolve_one(intent, request, db)

        assert result.status == UpdateModeChangeStatus.RESOLUTION_FAILED
        assert result.error_code == "anchor_ambiguous"

    @pytest.mark.asyncio
    async def test_anchor_not_found_returns_failed(self):
        intent = _make_intent(UpdateModeOperation.DELETE_SECTION, "## Несуществующий")
        request = _make_request()
        db = _mock_db()

        with _patch_fs(_FILE_WITH_SECTION):
            result = await _resolve_one(intent, request, db)

        assert result.status == UpdateModeChangeStatus.RESOLUTION_FAILED
        assert result.error_code == "anchor_not_found"

    @pytest.mark.asyncio
    async def test_success_returns_pending_with_remaining_content(self):
        """Partial delete: sibling section survives in proposed_content."""
        intent = _make_intent(UpdateModeOperation.DELETE_SECTION, "## Удалить меня")
        request = _make_request()
        db = _mock_db()

        with _patch_fs(_FILE_WITH_SECTION):
            result = await _resolve_one(intent, request, db)

        assert result.status == UpdateModeChangeStatus.PENDING
        assert result.proposed_content is not None
        assert "Удалить меня" not in (result.proposed_content or "")
        assert "Оставить" in (result.proposed_content or "")
        assert result.expected_sha256 == _sha256(_FILE_WITH_SECTION)

    @pytest.mark.asyncio
    async def test_only_section_returns_pending_with_empty_proposed(self):
        """Total delete: file becomes empty → proposed_content == "", status PENDING (not error).

        The empty-file warning is logged by _delete_section but must NOT cause
        RESOLUTION_FAILED.  The change is applied as-is; the user explicitly accepted it.
        """
        intent = _make_intent(UpdateModeOperation.DELETE_SECTION, "Единственный раздел")
        request = _make_request()
        db = _mock_db()

        with _patch_fs(_FILE_ONLY_SECTION):
            result = await _resolve_one(intent, request, db)

        assert result.status == UpdateModeChangeStatus.PENDING
        assert result.proposed_content is not None
        assert result.proposed_content.strip() == ""
        assert result.expected_sha256 == _sha256(_FILE_ONLY_SECTION)


class TestResolveOneDeleteUniqueText:
    @pytest.mark.asyncio
    async def test_anchor_ambiguous_returns_failed(self):
        intent = _make_intent(
            UpdateModeOperation.DELETE_UNIQUE_TEXT,
            "- [ ] Дубль",
            anchor_kind="exact_text",
        )
        request = _make_request()
        db = _mock_db()

        with _patch_fs(_FILE_DUPLICATE_LINE):
            result = await _resolve_one(intent, request, db)

        assert result.status == UpdateModeChangeStatus.RESOLUTION_FAILED
        assert result.error_code == "anchor_ambiguous"

    @pytest.mark.asyncio
    async def test_anchor_not_found_returns_failed(self):
        intent = _make_intent(
            UpdateModeOperation.DELETE_UNIQUE_TEXT,
            "- [ ] Не существует",
            anchor_kind="exact_text",
        )
        request = _make_request()
        db = _mock_db()

        with _patch_fs(_FILE_WITH_LINE):
            result = await _resolve_one(intent, request, db)

        assert result.status == UpdateModeChangeStatus.RESOLUTION_FAILED
        assert result.error_code == "anchor_not_found"

    @pytest.mark.asyncio
    async def test_success_returns_pending_with_deleted_line(self):
        """Partial delete: sibling line survives in proposed_content."""
        intent = _make_intent(
            UpdateModeOperation.DELETE_UNIQUE_TEXT,
            "- [ ] Удалить эту строку",
            anchor_kind="exact_text",
        )
        request = _make_request()
        db = _mock_db()

        with _patch_fs(_FILE_WITH_LINE):
            result = await _resolve_one(intent, request, db)

        assert result.status == UpdateModeChangeStatus.PENDING
        assert result.proposed_content is not None
        assert "Удалить эту строку" not in (result.proposed_content or "")
        assert "Оставить эту" in (result.proposed_content or "")
        assert result.expected_sha256 == _sha256(_FILE_WITH_LINE)

    @pytest.mark.asyncio
    async def test_only_line_returns_pending_with_empty_proposed(self):
        """Total delete: file becomes empty → proposed_content == "", status PENDING (not error).

        The empty-file warning is logged by _delete_unique_text but must NOT cause
        RESOLUTION_FAILED.  The change is applied as-is; the user explicitly accepted it.
        """
        intent = _make_intent(
            UpdateModeOperation.DELETE_UNIQUE_TEXT,
            "- [ ] Единственная строка",
            anchor_kind="exact_text",
        )
        request = _make_request()
        db = _mock_db()

        with _patch_fs(_FILE_ONLY_LINE):
            result = await _resolve_one(intent, request, db)

        assert result.status == UpdateModeChangeStatus.PENDING
        assert result.proposed_content is not None
        assert result.proposed_content.strip() == ""
        assert result.expected_sha256 == _sha256(_FILE_ONLY_LINE)
