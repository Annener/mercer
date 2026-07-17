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


# ---------------------------------------------------------------------------
# Helpers: apply operations in-memory
# ---------------------------------------------------------------------------

def _append_to_file(original: str, content: str) -> str:
    """Append content to end of file, ensuring a blank line separator."""
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

    Returns None if the heading is not found.
    """
    # Normalise the anchor so '# Foo' and 'Foo' both match a '# Foo' line.
    heading_text = _normalise_heading_text(heading)

    lines = original.splitlines(keepends=True)
    insert_at: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match heading prefix: # Heading or ## Heading etc.
        if stripped.startswith("#"):
            text = _normalise_heading_text(stripped)
            if text.lower() == heading_text.lower():
                # Find the end of this section (next heading at same or higher level)
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
        return None

    # Ensure blank line before and after inserted block
    block = "\n" + content.rstrip("\n") + "\n"
    lines.insert(insert_at, block)
    return "".join(lines)


def _replace_unique_text(original: str, anchor_text: str, content: str) -> str | None:
    """Replace the first (and must-be-unique) occurrence of anchor_text with content.

    Returns None if not found or if the anchor_text appears more than once.
    """
    count = original.count(anchor_text)
    if count == 0:
        return None
    if count > 1:
        return None
    return original.replace(anchor_text, content, 1)


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

        # Normalise: ensure _campaign_notes/ prefix for new files
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
            expected_sha256=None,  # CREATE: no CAS guard needed
            status=UpdateModeChangeStatus.PENDING,
        )

    # ── UPDATE action ────────────────────────────────────────────────────────────────────
    assert intent.action == UpdateModeAction.UPDATE  # validated by Pydantic
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

    original_sha256 = _sha256_str(original)

    # Apply operation
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
