"""Campaign Update Mode — pure text transformation helpers.

All functions operate on in-memory strings only — no I/O, no DB access.

Public API
----------
apply_op(text, op, anchor_value, content) -> str
    Apply a single UpdateModeOperation to *text*, return the result.

Exceptions
----------
AnchorNotFoundError     — the requested anchor was not found in *text*.
AnchorAmbiguousError    — the anchor matches more than once.
UnsupportedOperationError — *op* is not handled (should never happen in
                            practice; means a new operation enum was added
                            without updating this module).

All private helpers (prefixed with ``_``) preserve the original behaviour
from resolver.py verbatim so that resolver.py can import them directly and
applier.py can sequence them without duplicating logic.
"""
from __future__ import annotations

import logging
import re

from shared_contracts.models import UpdateModeOperation

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class AnchorNotFoundError(Exception):
    """Raised when an anchor lookup returns None (heading / text not in file)."""

    def __init__(self, anchor_value: str) -> None:
        self.anchor_value = anchor_value
        super().__init__(anchor_value)


class AnchorAmbiguousError(Exception):
    """Raised when an anchor matches more than once."""

    def __init__(self, anchor_value: str) -> None:
        self.anchor_value = anchor_value
        super().__init__(anchor_value)


class UnsupportedOperationError(Exception):
    """Raised when *op* has no handler in apply_op()."""


# Internal alias kept for import compatibility with resolver.py:
# resolver.py uses ``_AnchorAmbiguousError`` internally.
_AnchorAmbiguousError = AnchorAmbiguousError


# ---------------------------------------------------------------------------
# Private helpers (moved verbatim from resolver.py)
# ---------------------------------------------------------------------------

def _append_to_file(original: str, content: str) -> str:
    """Append *content* to end of *original*, ensuring a single blank line separator."""
    content = content.lstrip("\n")
    if original and not original.endswith("\n"):
        original += "\n"
    if original:
        original += "\n"
    return original + content


def _normalise_heading_text(raw: str) -> str:
    """Strip leading '#' characters and surrounding whitespace from a heading string."""
    return raw.lstrip("#").strip()


def _append_after_section(original: str, heading: str, content: str) -> str | None:
    """Insert *content* after the first markdown heading that matches *heading*.

    Returns None if the heading is not found.
    """
    heading_text = _normalise_heading_text(heading)
    log.debug(
        "_append_after_section: searching for heading %r (normalised: %r)",
        heading,
        heading_text,
    )

    lines = original.splitlines(keepends=True)
    insert_at: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            text = _normalise_heading_text(stripped)
            log.debug(
                "_append_after_section: line %d heading %r (normalised: %r) match=%s",
                i,
                stripped,
                text,
                text.lower() == heading_text.lower(),
            )
            if text.lower() == heading_text.lower():
                level = len(stripped) - len(stripped.lstrip("#"))
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if next_line.startswith("#"):
                        next_level = len(next_line) - len(next_line.lstrip("#"))
                        if next_level <= level:
                            break
                    j += 1
                insert_at = j
                break

    if insert_at is None:
        found_headings = [
            _normalise_heading_text(line.strip())
            for line in lines
            if line.strip().startswith("#")
        ]
        log.warning(
            "_append_after_section: heading not found. searched=%r; "
            "headings in file (normalised): %r",
            heading_text,
            found_headings,
        )
        return None

    block = "\n" + content.strip("\n") + "\n"
    lines.insert(insert_at, block)
    return "".join(lines)


def _build_anchor_pattern(anchor_text: str) -> re.Pattern[str]:
    """Build a regex that matches *anchor_text* tolerating any whitespace between words."""
    tokens = re.split(r"\s+", anchor_text.strip())
    tokens = [t for t in tokens if t]
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    return re.compile(pattern, re.DOTALL)


def _replace_unique_text_exact(original: str, anchor_text: str, content: str) -> str | None:
    """Literal replacement — used as fallback in _replace_unique_text."""
    count = original.count(anchor_text)
    if count != 1:
        return None
    return original.replace(anchor_text, content, 1)


def _replace_unique_text(original: str, anchor_text: str, content: str) -> str | None:
    """Replace the unique occurrence of *anchor_text* in *original* with *content*.

    Whitespace-tolerant matching first; exact literal match as fallback.
    Returns None if anchor is not found uniquely (both strategies exhausted).
    """
    pattern = _build_anchor_pattern(anchor_text)
    matches = list(pattern.finditer(original))

    if len(matches) == 1:
        m = matches[0]
        log.debug(
            "_replace_unique_text: fuzzy match at [%d:%d] for anchor %r",
            m.start(),
            m.end(),
            anchor_text[:80],
        )
        return original[: m.start()] + content + original[m.end() :]

    if len(matches) > 1:
        log.warning(
            "_replace_unique_text: anchor matches %d times (fuzzy); "
            "falling back to exact search. anchor=%r",
            len(matches),
            anchor_text[:120],
        )
    else:
        excerpt = original[:200].replace("\n", "↵")
        log.warning(
            "_replace_unique_text: fuzzy search found 0 matches. "
            "anchor_tokens=%r; original_excerpt=%r",
            re.split(r"\s+", anchor_text.strip())[:10],
            excerpt,
        )

    result = _replace_unique_text_exact(original, anchor_text, content)
    if result is not None:
        log.debug(
            "_replace_unique_text: exact fallback succeeded for anchor %r",
            anchor_text[:80],
        )
    return result


def _heading_level(line: str) -> int | None:
    """Return heading level (1-6) or None if the line is not a heading."""
    stripped = line.lstrip()
    if stripped.startswith("#"):
        count = len(stripped) - len(stripped.lstrip("#"))
        if 1 <= count <= 6 and (len(stripped) <= count or stripped[count] == " "):
            return count
    return None


def _collapse_consecutive_blank_lines(lines: list[str]) -> list[str]:
    """Collapse 3+ consecutive blank lines down to 2."""
    result: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)
    return result


def _delete_section(original: str, heading: str) -> str | None:
    """Delete the markdown section that starts with *heading*.

    Returns None if the heading is not found.
    Raises AnchorAmbiguousError if the heading matches more than once.
    """
    heading_text = _normalise_heading_text(heading)
    lines = original.splitlines(keepends=True)

    matching: list[int] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            if _normalise_heading_text(stripped).lower() == heading_text.lower():
                matching.append(i)

    if len(matching) == 0:
        found_headings = [
            _normalise_heading_text(line.strip())
            for line in lines
            if line.strip().startswith("#")
        ]
        log.warning(
            "_delete_section: heading not found. searched=%r; "
            "headings in file (normalised): %r",
            heading_text,
            found_headings,
        )
        return None

    if len(matching) > 1:
        log.warning(
            "_delete_section: heading matches %d times — anchor is ambiguous: %r",
            len(matching),
            heading_text,
        )
        raise AnchorAmbiguousError(heading)

    anchor_idx = matching[0]
    anchor_level = _heading_level(lines[anchor_idx])
    if anchor_level is None:  # pragma: no cover
        log.error(
            "_delete_section: matched line is not a valid ATX heading: %r",
            lines[anchor_idx],
        )
        return None

    end_idx = len(lines)
    for i in range(anchor_idx + 1, len(lines)):
        lvl = _heading_level(lines[i])
        if lvl is not None and lvl <= anchor_level:
            end_idx = i
            break

    while end_idx > anchor_idx and lines[end_idx - 1].strip() == "":
        end_idx -= 1

    new_lines = lines[:anchor_idx] + lines[end_idx:]
    new_lines = _collapse_consecutive_blank_lines(new_lines)
    result = "".join(new_lines)

    if result.strip() == "":
        log.warning(
            "_delete_section: deleting heading=%r will result in an empty file",
            heading_text,
        )

    return result


def _delete_unique_text(original: str, fragment: str) -> str | None:
    """Delete the unique line whose stripped content matches *fragment*.

    Returns None if no match is found.
    Raises AnchorAmbiguousError if the fragment matches more than once.
    """
    fragment_stripped = fragment.strip()
    lines = original.splitlines(keepends=True)

    matching_indices = [
        i for i, line in enumerate(lines)
        if line.strip() == fragment_stripped
    ]

    if len(matching_indices) == 0:
        excerpt = original[:200].replace("\n", "↵")
        log.warning(
            "_delete_unique_text: fragment not found. fragment=%r; "
            "original_excerpt=%r",
            fragment_stripped,
            excerpt,
        )
        return None

    if len(matching_indices) > 1:
        log.warning(
            "_delete_unique_text: fragment matches %d times — anchor is ambiguous: %r",
            len(matching_indices),
            fragment_stripped,
        )
        raise AnchorAmbiguousError(fragment)

    target_idx = matching_indices[0]
    new_lines = lines[:target_idx] + lines[target_idx + 1:]
    new_lines = _collapse_consecutive_blank_lines(new_lines)
    result = "".join(new_lines)

    if result.strip() == "":
        log.warning(
            "_delete_unique_text: deleting fragment=%r will result in an empty file",
            fragment_stripped,
        )

    return result


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def apply_op(
    text: str,
    op: UpdateModeOperation,
    anchor_value: str | None,
    content: str,
) -> str:
    """Apply a single *op* to *text* and return the transformed string.

    Parameters
    ----------
    text:
        Current file content (in-memory, may have been already modified by a
        previous operation in the same batch).
    op:
        The operation to perform.
    anchor_value:
        The anchor string — required for section/text operations, None for
        APPEND_TO_FILE and CREATE_FILE.
    content:
        The new content to insert/replace.  Must be ``""`` for delete operations.

    Raises
    ------
    AnchorNotFoundError
        The requested anchor was not present in *text*.
    AnchorAmbiguousError
        The anchor matched more than one location.
    UnsupportedOperationError
        *op* has no handler (programming error — update this function when
        adding new enum values).
    """
    if op == UpdateModeOperation.APPEND_TO_FILE:
        return _append_to_file(text, content)

    if op == UpdateModeOperation.APPEND_AFTER_SECTION:
        assert anchor_value is not None, "anchor_value required for append_after_section"
        result = _append_after_section(text, anchor_value, content)
        if result is None:
            raise AnchorNotFoundError(anchor_value)
        return result

    if op == UpdateModeOperation.REPLACE_UNIQUE_TEXT:
        assert anchor_value is not None, "anchor_value required for replace_unique_text"
        result = _replace_unique_text(text, anchor_value, content)
        if result is None:
            raise AnchorNotFoundError(anchor_value)
        return result

    if op == UpdateModeOperation.DELETE_SECTION:
        assert anchor_value is not None, "anchor_value required for delete_section"
        # _delete_section raises AnchorAmbiguousError internally
        result = _delete_section(text, anchor_value)
        if result is None:
            raise AnchorNotFoundError(anchor_value)
        return result

    if op == UpdateModeOperation.DELETE_UNIQUE_TEXT:
        assert anchor_value is not None, "anchor_value required for delete_unique_text"
        result = _delete_unique_text(text, anchor_value)
        if result is None:
            raise AnchorNotFoundError(anchor_value)
        return result

    if op == UpdateModeOperation.CREATE_FILE:
        # CREATE_FILE is handled at the batch level (action=CREATE, full content).
        # If it arrives here the caller made a mistake — treat as append.
        log.warning("apply_op: CREATE_FILE op routed to append_to_file fallback")
        return _append_to_file(text, content)

    raise UnsupportedOperationError(f"No handler for operation={op!r}")
