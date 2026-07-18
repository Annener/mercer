"""Campaign Update Mode — resolver.

Called by POST /internal/update-mode/resolve.

Responsibilities
----------------
1. For each intent, look up the target document (via DB → vault_id + source_path).
2. Read the current file content from disk.
3. Apply the requested operation in-memory to produce proposed_content.
4. Build unified diff + SHA-256 of proposed bytes.
5. Return a list of ResolvedUpdateModeChange objects.

Resolution failures are stored as RESOLUTION_FAILED changes — the endpoint
never raises 500 for per-intent errors.

The LLM is *not* called here: the backend sends note content already embedded
in the stub intent.  rag-indexer's role is purely file-system + diff work.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from app.db_client import IndexerDBClient
from app.update_mode.fs_git import (
    VAULT_ROOT,
    PathValidationError,
    FileReadError,
    build_unified_diff,
    resolve_vault_root,
    resolve_file_path,
    read_original_utf8,
    sha256_bytes,
)
from shared_contracts.models import (
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeChangeStatus,
    UpdateModeIntent,
    UpdateModeOperation,
    UpdateModeResolveRequest,
    UpdateModeResolveResponse,
)

log = logging.getLogger(__name__)

_MAX_CONTENT_BYTES = 10 * 1024 * 1024  # 10 MB guard

# UTF-8 BOM that some editors prepend to files.
_UTF8_BOM = "\ufeff"


# ---------------------------------------------------------------------------
# Helpers: apply operations in-memory
# ---------------------------------------------------------------------------

def _append_to_file(original: str, content: str) -> str:
    """Append content to end of file, ensuring a single blank line separator.

    content is lstrip'd of leading newlines so that a model that returns
    content starting with '\n' does not produce a double blank line between
    the existing text and the new block.
    """
    content = content.lstrip("\n")
    if original and not original.endswith("\n"):
        original += "\n"
    if original:
        original += "\n"
    return original + content


def _normalise_heading_text(raw: str) -> str:
    """Strip leading '#' characters and surrounding whitespace from a heading string.

    Used to normalise both file lines and the incoming anchor.value so that
    comparisons are robust to either format:
      '# Темы на 1:1'  →  'Темы на 1:1'
      'Темы на 1:1'   →  'Темы на 1:1'
    """
    return raw.lstrip("#").strip()


def _append_after_section(original: str, heading: str, content: str) -> str | None:
    """Insert content after the first markdown heading that matches `heading`.

    `heading` may be supplied with or without leading '#' characters
    (both formats are valid per the LLM prompt contract).  The match is
    case-insensitive and whitespace-normalised on both sides.

    content is strip'd of ALL leading and trailing bare newlines before
    wrapping so that a model returning content that starts or ends with '\n'
    does not produce extra blank lines.  The block is wrapped with exactly
    one leading '\n' separator and one trailing '\n'.

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
        # Log repr of all headings found to help diagnose invisible-char mismatches.
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

    # strip("\n") removes both leading and trailing bare newlines from the
    # LLM-supplied content before we add exactly one \n separator on each side.
    block = "\n" + content.strip("\n") + "\n"
    lines.insert(insert_at, block)
    return "".join(lines)


def _build_anchor_pattern(anchor_text: str) -> re.Pattern[str]:
    """Build a regex that matches anchor_text tolerating any whitespace between words.

    The LLM receives indexed (normalised) text where newlines and repeated
    whitespace may have been collapsed.  The real file may contain the same
    words separated by '\\n', '\\r\\n', multiple spaces, etc.

    Strategy: split anchor on whitespace → escape each token → join with \\s+.
    Flags: DOTALL so '.' inside re.escape'd tokens never matters; no IGNORECASE
    because anchor text is expected to be verbatim word content.
    """
    tokens = re.split(r"\s+", anchor_text.strip())
    tokens = [t for t in tokens if t]  # drop empty strings from leading/trailing ws
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    return re.compile(pattern, re.DOTALL)


def _replace_unique_text_exact(original: str, anchor_text: str, content: str) -> str | None:
    """Literal replacement — original behaviour, used as fallback."""
    count = original.count(anchor_text)
    if count != 1:
        return None
    return original.replace(anchor_text, content, 1)


def _replace_unique_text(original: str, anchor_text: str, content: str) -> str | None:
    """Replace the unique occurrence of anchor_text in original with content.

    Matching is whitespace-tolerant: any run of whitespace (spaces, newlines,
    tabs, \\r\\n …) in the file is treated as equivalent to any whitespace in
    the anchor coming from the LLM.  This handles the common case where the
    indexed text sent to the model had newlines collapsed but the real file
    contains line-breaks inside the anchor span.

    Algorithm (variant 2 — word-sequence regex):
      1. Split anchor into word tokens.
      2. Build regex: token1 \\s+ token2 \\s+ … (re.escape on each token).
      3. Find all non-overlapping matches in original.
      4. Require exactly 1 match → replace that span.
      5. Fallback to exact literal match if regex yields 0 or >1 results.

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
        # 0 matches — log useful diagnostic before trying exact fallback
        excerpt = original[:200].replace("\n", "↵")
        log.warning(
            "_replace_unique_text: fuzzy search found 0 matches. "
            "anchor_tokens=%r; original_excerpt=%r",
            re.split(r"\s+", anchor_text.strip())[:10],
            excerpt,
        )

    # Fallback: exact literal match (pre-patch behaviour)
    result = _replace_unique_text_exact(original, anchor_text, content)
    if result is not None:
        log.debug(
            "_replace_unique_text: exact fallback succeeded for anchor %r",
            anchor_text[:80],
        )
    return result


# ---------------------------------------------------------------------------
# Helpers: delete operations
# ---------------------------------------------------------------------------

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
    """Delete the markdown section that starts with `heading`.

    Deletes from the matched heading line up to (but not including) the next
    heading of the same or higher level.  Trailing blank lines before the next
    heading are also removed to avoid leaving double blank lines.

    `heading` may be supplied with or without leading '#' characters — the
    comparison is normalised the same way as _append_after_section.

    Returns None if the heading is not found (anchor_not_found).
    Raises _AnchorAmbiguousError if the heading matches more than once.
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
        raise _AnchorAmbiguousError(heading)

    anchor_idx = matching[0]
    anchor_level = _heading_level(lines[anchor_idx])
    # anchor_level cannot be None here: the loop above guarantees the line
    # starts with '#' and _heading_level only returns None for lines that do
    # not conform to CommonMark ATX syntax.  Guard defensively to avoid
    # AssertionError when Python is run with -O (optimisations strip assert).
    if anchor_level is None:  # pragma: no cover
        log.error(
            "_delete_section: matched line is not a valid ATX heading: %r",
            lines[anchor_idx],
        )
        return None

    # Find end of section: first heading at same or higher level after anchor
    end_idx = len(lines)
    for i in range(anchor_idx + 1, len(lines)):
        lvl = _heading_level(lines[i])
        if lvl is not None and lvl <= anchor_level:
            end_idx = i
            break

    # Trim trailing blank lines before the next heading
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
    """Delete the unique line whose stripped content matches `fragment`.

    The match is performed on stripped line content vs stripped fragment.
    Consecutive blank lines introduced by the removal are collapsed.

    Returns None if no match is found (anchor_not_found).
    Raises _AnchorAmbiguousError if the fragment matches more than once.
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
        raise _AnchorAmbiguousError(fragment)

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


class _AnchorAmbiguousError(Exception):
    """Raised internally when an anchor matches more than once."""
    def __init__(self, anchor_value: str) -> None:
        self.anchor_value = anchor_value
        super().__init__(anchor_value)


def _sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _lookup_document(
    db: IndexerDBClient,
    document_id: str,
) -> dict[str, Any] | None:
    """Fetch document row by id from PostgreSQL.

    asyncpg raw query — db_client has no get_document_by_id, so we use
    the internal _fetchrow helper directly.
    """
    row = await db._fetchrow(
        "SELECT vault_id, source_path FROM documents WHERE id = $1",
        document_id,
    )
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Per-intent resolution
# ---------------------------------------------------------------------------

async def _resolve_one(
    intent: UpdateModeIntent,
    request: UpdateModeResolveRequest,
    db: IndexerDBClient,
) -> ResolvedUpdateModeChange:
    """Resolve a single intent → ResolvedUpdateModeChange.

    Never raises — errors are captured as RESOLUTION_FAILED status.
    """

    def _fail(code: str, msg: str) -> ResolvedUpdateModeChange:
        return ResolvedUpdateModeChange(
            change_id=intent.change_id,
            action=intent.action,
            description=intent.description,
            status=UpdateModeChangeStatus.RESOLUTION_FAILED,
            error_code=code,
            error_message=msg,
        )

    # ── CREATE action ────────────────────────────────────────────────────────────────────
    if intent.action == UpdateModeAction.CREATE:
        vault_id = request.default_vault_id
        filename = intent.suggested_filename or "_note.md"

        try:
            vault_root = resolve_vault_root(vault_id)
        except PathValidationError as exc:
            return _fail(exc.code, str(exc))

        if not filename.startswith("_campaign_notes/"):
            filename = f"_campaign_notes/{filename}"

        try:
            file_path = resolve_file_path(vault_root, filename)
        except PathValidationError as exc:
            return _fail(exc.code, str(exc))

        proposed = intent.content
        proposed_bytes = proposed.encode("utf-8")
        if len(proposed_bytes) > _MAX_CONTENT_BYTES:
            return _fail("content_too_large", "proposed content exceeds 10 MB")

        rel_path = str(file_path.relative_to(vault_root))
        original = ""
        unified_diff = build_unified_diff(original, proposed, rel_path)

        return ResolvedUpdateModeChange(
            change_id=intent.change_id,
            vault_id=vault_id,
            file_path=rel_path,
            action=intent.action,
            description=intent.description,
            original_content=original,
            proposed_content=proposed,
            unified_diff=unified_diff,
            expected_sha256=None,
            status=UpdateModeChangeStatus.PENDING,
        )

    # ── UPDATE action ────────────────────────────────────────────────────────────────────
    assert intent.action == UpdateModeAction.UPDATE
    assert intent.document_id is not None

    doc = await _lookup_document(db, intent.document_id)
    if doc is None:
        return _fail("document_not_found", f"document_id={intent.document_id!r}")

    vault_id: str = doc["vault_id"]
    source_path: str = doc["source_path"]

    if vault_id not in request.vault_ids:
        return _fail(
            "vault_not_in_domain",
            f"document vault_id={vault_id!r} not in request vault_ids",
        )

    try:
        vault_root = resolve_vault_root(vault_id)
    except PathValidationError as exc:
        return _fail(exc.code, str(exc))

    try:
        file_path = resolve_file_path(vault_root, source_path)
    except PathValidationError as exc:
        return _fail(exc.code, str(exc))

    try:
        original = read_original_utf8(file_path)
    except FileReadError as exc:
        return _fail(exc.code, str(exc))

    # Strip UTF-8 BOM if present. Some editors (Obsidian on Windows, Excel
    # exports, etc.) prepend \ufeff. With the BOM the first line starts with
    # '\ufeff#' so startswith('#') is False and the heading is never matched.
    if original.startswith(_UTF8_BOM):
        log.debug("_resolve_one: stripping UTF-8 BOM from %s", source_path)
        original = original[len(_UTF8_BOM):]

    original_sha256 = _sha256_str(original)

    proposed: str | None = None
    op = intent.operation

    if op == UpdateModeOperation.APPEND_TO_FILE:
        proposed = _append_to_file(original, intent.content)

    elif op == UpdateModeOperation.APPEND_AFTER_SECTION:
        assert intent.anchor is not None
        proposed = _append_after_section(original, intent.anchor.value, intent.content)
        if proposed is None:
            return _fail(
                "anchor_not_found",
                f"heading not found: {intent.anchor.value!r}",
            )

    elif op == UpdateModeOperation.REPLACE_UNIQUE_TEXT:
        assert intent.anchor is not None
        proposed = _replace_unique_text(original, intent.anchor.value, intent.content)
        if proposed is None:
            return _fail(
                "anchor_not_unique",
                f"anchor text not found or appears multiple times: {intent.anchor.value!r}",
            )

    elif op == UpdateModeOperation.DELETE_SECTION:
        assert intent.anchor is not None
        try:
            proposed = _delete_section(original, intent.anchor.value)
        except _AnchorAmbiguousError as exc:
            return _fail(
                "anchor_ambiguous",
                f"heading matches more than once: {exc.anchor_value!r}",
            )
        if proposed is None:
            return _fail(
                "anchor_not_found",
                f"heading not found: {intent.anchor.value!r}",
            )

    elif op == UpdateModeOperation.DELETE_UNIQUE_TEXT:
        assert intent.anchor is not None
        try:
            proposed = _delete_unique_text(original, intent.anchor.value)
        except _AnchorAmbiguousError as exc:
            return _fail(
                "anchor_ambiguous",
                f"fragment matches more than once: {exc.anchor_value!r}",
            )
        if proposed is None:
            return _fail(
                "anchor_not_found",
                f"fragment not found: {intent.anchor.value!r}",
            )

    else:
        return _fail("unsupported_operation", f"operation={op!r}")

    proposed_bytes = proposed.encode("utf-8")
    if len(proposed_bytes) > _MAX_CONTENT_BYTES:
        return _fail("content_too_large", "proposed content exceeds 10 MB")

    rel_path = str(file_path.relative_to(vault_root))
    unified_diff = build_unified_diff(original, proposed, rel_path)

    return ResolvedUpdateModeChange(
        change_id=intent.change_id,
        vault_id=vault_id,
        document_id=intent.document_id,
        file_path=rel_path,
        action=intent.action,
        description=intent.description,
        original_content=original,
        proposed_content=proposed,
        unified_diff=unified_diff,
        expected_sha256=original_sha256,
        status=UpdateModeChangeStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def resolve_changes(
    request: UpdateModeResolveRequest,
    db: IndexerDBClient,
) -> UpdateModeResolveResponse:
    """Resolve all intents in `request`, returning one change per intent.

    Individual resolution failures become RESOLUTION_FAILED changes.
    The function never propagates exceptions from individual intents.
    """
    changes: list[ResolvedUpdateModeChange] = []

    for intent in request.intents:
        try:
            change = await _resolve_one(intent, request, db)
        except Exception as exc:
            log.exception(
                "Unexpected error resolving intent change_id=%s",
                intent.change_id,
            )
            change = ResolvedUpdateModeChange(
                change_id=intent.change_id,
                action=intent.action,
                description=intent.description,
                status=UpdateModeChangeStatus.RESOLUTION_FAILED,
                error_code="internal_error",
                error_message=str(exc),
            )
        changes.append(change)
        log.info(
            "resolve change_id=%s status=%s",
            change.change_id,
            change.status.value,
        )

    return UpdateModeResolveResponse(changes=changes)
