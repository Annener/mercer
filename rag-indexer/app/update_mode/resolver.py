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
from app.update_mode.text_ops import (
    AnchorAmbiguousError,
    AnchorNotFoundError,
    _append_to_file,
    _append_after_section,
    _replace_unique_text,
    _delete_section,
    _delete_unique_text,
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

# Internal alias kept for backward compat with any code that catches _AnchorAmbiguousError.
_AnchorAmbiguousError = AnchorAmbiguousError


def _sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _lookup_document(
    db: IndexerDBClient,
    document_id: str,
) -> dict[str, Any] | None:
    """Fetch document row by id from PostgreSQL."""
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

    # ── CREATE action ────────────────────────────────────────────────────────────────────────────────────
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

    # ── UPDATE action ────────────────────────────────────────────────────────────────────────────────────
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

    # Strip UTF-8 BOM if present.
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
        except AnchorAmbiguousError as exc:
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
        except AnchorAmbiguousError as exc:
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
