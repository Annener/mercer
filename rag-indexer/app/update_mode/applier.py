"""Campaign Update Mode — applier.

Called by POST /internal/update-mode/apply.

Responsibilities
----------------
1. Idempotency: if apply_id already completed, return cached response from Redis.
2. Distributed lock: SET NX / PX lock key for duration of apply to prevent
   concurrent duplicate in-flight requests for the same apply_id.
3. Iterate request.file_batches (grouped by vault_id + file_path).
4. For each vault:
   a. git_init_if_needed.
   b. git_snapshot (pre-apply safety commit, --allow-empty).
   c. Preflight CAS check: verify expected_sha256 from ops[0] of each
      UPDATE batch against on-disk content.
   d. For each file batch: read once, apply all ops in-memory via
      text_ops.apply_op() in deterministic order
      (delete → replace → append/create), write once.
   e. git_apply_commit with list of written paths.
   f. Trigger TARGETED re-index via IndexerService.start_task(source_paths=...).
5. Persist completed response in Redis (idempotency record, TTL=3h).
6. Return UpdateModeApplyResponse with per-vault results.

Multiple ops on the same file
------------------------------
file_batches already contains pre-grouped ops per (vault_id, file_path).
Within a batch ops are sorted by _OPERATION_ORDER[op.operation]:

  0 — delete operations  (DELETE_SECTION, DELETE_UNIQUE_TEXT)
  1 — replace operations (REPLACE_UNIQUE_TEXT)
  2 — append operations  (APPEND_AFTER_SECTION, APPEND_TO_FILE)
  3 — create operations  (CREATE_FILE)

This ordering ensures anchors resolve before content is appended around them.
The result is written atomically as a single file write and committed in a
single git commit per vault.

CAS failures and write errors produce CONFLICT / FAILED vault results,
not HTTP 500.  Partial success is possible across vaults.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import redis.asyncio as aioredis

from app.db_client import IndexerDBClient
from app.indexer_service import IndexerService
from app.update_mode.fs_git import (
    AtomicWriteError,
    GitError,
    GitIdentity,
    PathValidationError,
    atomic_write,
    git_apply_commit,
    git_init_if_needed,
    git_snapshot,
    resolve_file_path,
    resolve_vault_root,
)
from app.update_mode.text_ops import (
    AnchorAmbiguousError,
    AnchorNotFoundError,
    apply_op,
)
from shared_contracts.models import (
    IndexerApplyState,
    UpdateModeAction,
    UpdateModeApplyRequest,
    UpdateModeApplyResponse,
    UpdateModeFileChangeBatch,
    UpdateModeFileOp,
    UpdateModeOperation,
    UpdateModeVaultApplyResult,
    UpdateModeVaultApplyStatus,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

_APPLY_STATE_TTL = 3 * 60 * 60  # 3 hours — matches session TTL
_LOCK_TTL_MS = 30_000  # 30 s lock TTL (auto-expire on crash)

# Deterministic application order for multiple ops on the same file.
# Lower rank = applied first.
_OPERATION_ORDER: dict[UpdateModeOperation, int] = {
    UpdateModeOperation.DELETE_SECTION: 0,
    UpdateModeOperation.DELETE_UNIQUE_TEXT: 0,
    UpdateModeOperation.REPLACE_UNIQUE_TEXT: 1,
    UpdateModeOperation.APPEND_AFTER_SECTION: 2,
    UpdateModeOperation.APPEND_TO_FILE: 2,
    UpdateModeOperation.CREATE_FILE: 3,
}


def _apply_state_key(apply_id: str) -> str:
    return f"update_mode:apply:{apply_id}"


def _apply_lock_key(apply_id: str) -> str:
    return f"update_mode:apply:lock:{apply_id}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _request_fingerprint(request: UpdateModeApplyRequest) -> str:
    """Stable canonical fingerprint for the apply payload."""
    payload = request.model_dump(mode="json", exclude_none=False)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _get_vault_identity(db: IndexerDBClient, vault_id: str) -> GitIdentity | None:
    """Return GitIdentity from vault DB record, or None to fall back to env."""
    row = await db._fetchrow(
        "SELECT git_author_name, git_author_email FROM vaults WHERE vault_id = $1",
        vault_id,
    )
    if row is None:
        return None
    name = (row["git_author_name"] or "").strip()
    email = (row["git_author_email"] or "").strip()
    if name and email:
        return GitIdentity(name=name, email=email)
    return None


def _sort_op(op: UpdateModeFileOp) -> int:
    """Return deterministic application-order rank for an op."""
    return _OPERATION_ORDER.get(op.operation, 2)


# ---------------------------------------------------------------------------
# Apply a single op to the in-memory buffer
# ---------------------------------------------------------------------------

def _apply_op_to_buffer(
    buffer: str,
    op: UpdateModeFileOp,
    vault_id: str,
    file_path: str,
) -> str:
    """Call text_ops.apply_op() and return the updated buffer.

    Raises AnchorNotFoundError or AnchorAmbiguousError on failure so the
    caller can produce a FAILED vault result without crashing.
    """
    return apply_op(
        text=buffer,
        op=op.operation,
        anchor_value=op.anchor_value,
        content=op.content or "",
    )


# ---------------------------------------------------------------------------
# Per-vault apply
# ---------------------------------------------------------------------------

async def _apply_vault(
    vault_id: str,
    batches: list[UpdateModeFileChangeBatch],
    request: UpdateModeApplyRequest,
    db: IndexerDBClient,
    indexer_service: IndexerService,
) -> UpdateModeVaultApplyResult:
    """Apply all file batches for a single vault.

    Each batch targets one file; ops within it are sorted by _OPERATION_ORDER
    and applied sequentially to an in-memory buffer, producing a single
    atomic write per file and a single git commit for all files.

    Returns a result object — never raises.
    """
    def _fail(
        code: str,
        msg: str,
        status: UpdateModeVaultApplyStatus = UpdateModeVaultApplyStatus.FAILED,
        manual_recovery_required: bool = False,
    ) -> UpdateModeVaultApplyResult:
        return UpdateModeVaultApplyResult(
            vault_id=vault_id,
            status=status,
            applied_count=0,
            error_code=code,
            error_message=msg,
            manual_recovery_required=manual_recovery_required,
        )

    # 1. Resolve vault root
    try:
        vault_root = resolve_vault_root(vault_id)
    except PathValidationError as exc:
        return _fail(exc.code, str(exc))

    # 2. git init if needed
    try:
        git_init_if_needed(vault_root)
    except GitError as exc:
        return _fail(exc.code, str(exc))

    # 3. Resolve vault identity
    try:
        vault_identity = await _get_vault_identity(db, vault_id)
    except Exception as exc:
        log.warning("Could not fetch vault git identity vault_id=%s: %s", vault_id, exc)
        vault_identity = None

    # 4. Sort ops within each batch by deterministic operation order.
    #    Use sorted() to avoid mutating the incoming Pydantic model in-place.
    sorted_batches = [
        UpdateModeFileChangeBatch(
            vault_id=batch.vault_id,
            file_path=batch.file_path,
            action=batch.action,
            ops=sorted(batch.ops, key=_sort_op),
        )
        for batch in batches
    ]

    # 5. Preflight CAS check (read-only, before any writes).
    #    For UPDATE batches: ops[0].expected_sha256 must match on-disk sha256.
    preflight_conflicts: list[str] = []
    for batch in sorted_batches:
        if batch.action != UpdateModeAction.UPDATE:
            continue
        first_op = batch.ops[0]
        if first_op.expected_sha256 is None:
            continue
        try:
            abs_path = resolve_file_path(vault_root, batch.file_path)
        except PathValidationError:
            preflight_conflicts.append(first_op.change_id)
            continue
        if not abs_path.exists():
            preflight_conflicts.append(first_op.change_id)
            continue
        current_sha = _sha256_str(abs_path.read_text(encoding="utf-8"))
        if current_sha != first_op.expected_sha256:
            preflight_conflicts.append(first_op.change_id)

    if preflight_conflicts:
        log.warning(
            "update-mode preflight CAS conflict vault=%s change_ids=%s",
            vault_id, preflight_conflicts,
        )
        return UpdateModeVaultApplyResult(
            vault_id=vault_id,
            status=UpdateModeVaultApplyStatus.CONFLICT,
            applied_count=0,
            error_code="cas_conflict",
            error_message=f"preflight conflict on change_ids: {preflight_conflicts}",
        )

    # 6. Snapshot commit (pre-apply) for UPDATE files.
    snapshot_paths: list[Path] = []
    for batch in sorted_batches:
        if batch.action == UpdateModeAction.UPDATE:
            try:
                abs_path = resolve_file_path(vault_root, batch.file_path)
                if abs_path.exists():
                    snapshot_paths.append(abs_path)
            except PathValidationError:
                pass

    snapshot_sha: str | None = None
    try:
        if snapshot_paths:
            snapshot_sha = git_snapshot(
                vault_root,
                snapshot_paths,
                vault_identity,
                message=f"update-mode: pre-apply snapshot chat_id={request.chat_id}",
            )
            log.info("update-mode snapshot vault=%s commit=%s", vault_id, snapshot_sha)
    except GitError as exc:
        log.warning(
            "update-mode snapshot failed vault=%s — continuing without snapshot: %s",
            vault_id, exc,
        )

    # 7. Apply ops per file: read once → apply all ops in-memory → write once.
    written_paths: list[Path] = []
    written_rel_paths: list[str] = []
    total_ops_applied: int = 0

    for batch in sorted_batches:
        file_path = batch.file_path
        try:
            abs_path = resolve_file_path(vault_root, file_path)
        except PathValidationError as exc:
            log.error(
                "update-mode path validation failed vault=%s path=%s: %s",
                vault_id, file_path, exc,
            )
            return _fail(
                exc.code,
                f"path={file_path!r}: {exc}",
                manual_recovery_required=bool(written_paths),
            )

        # Read current on-disk content (empty string for new files).
        if abs_path.exists():
            current_content = abs_path.read_text(encoding="utf-8")
        else:
            current_content = ""

        # CREATE: ensure parent directory exists before writing.
        if batch.action == UpdateModeAction.CREATE:
            abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Apply all ops sequentially to the in-memory buffer.
        buffer = current_content
        for op in batch.ops:
            try:
                buffer = _apply_op_to_buffer(buffer, op, vault_id, file_path)
                total_ops_applied += 1
                log.debug(
                    "update-mode op vault=%s path=%s change_id=%s op=%s",
                    vault_id, file_path, op.change_id, op.operation.value,
                )
            except AnchorNotFoundError as exc:
                log.error(
                    "update-mode anchor not found vault=%s path=%s change_id=%s anchor=%r written_paths=%s",
                    vault_id, file_path, op.change_id, exc.anchor_value, written_paths,
                )
                return _fail(
                    "anchor_not_found",
                    f"path={file_path!r} change_id={op.change_id} anchor={exc.anchor_value!r}",
                    manual_recovery_required=bool(written_paths),
                )
            except AnchorAmbiguousError as exc:
                log.error(
                    "update-mode anchor ambiguous vault=%s path=%s change_id=%s anchor=%r written_paths=%s",
                    vault_id, file_path, op.change_id, exc.anchor_value, written_paths,
                )
                return _fail(
                    "anchor_ambiguous",
                    f"path={file_path!r} change_id={op.change_id} anchor={exc.anchor_value!r}",
                    manual_recovery_required=bool(written_paths),
                )

        # Warn if the result is an empty file.
        if buffer == "" and abs_path.exists():
            log.warning(
                "update-mode file_would_become_empty: vault=%s path=%s — applying as accepted",
                vault_id, file_path,
            )

        # Write once.
        try:
            atomic_write(abs_path, buffer)
        except AtomicWriteError as exc:
            return _fail(
                exc.code,
                f"write failed for {file_path!r}: {exc}",
                manual_recovery_required=bool(written_paths),
            )

        written_paths.append(abs_path)
        written_rel_paths.append(file_path)
        log.info(
            "update-mode wrote vault=%s path=%s ops=%d",
            vault_id, file_path, len(batch.ops),
        )

    if not written_paths:
        return UpdateModeVaultApplyResult(
            vault_id=vault_id,
            status=UpdateModeVaultApplyStatus.NO_CHANGES,
            applied_count=0,
            snapshot_commit_sha=snapshot_sha,
        )

    # 8. git apply commit.
    commit_msg = (
        f"update-mode: apply chat_id={request.chat_id} "
        f"campaign_id={request.campaign_id} "
        f"apply_id={request.apply_id}"
    )
    commit_sha: str | None = None
    try:
        commit_sha = git_apply_commit(
            vault_root,
            written_paths,
            vault_identity,
            message=commit_msg,
        )
        log.info(
            "update-mode apply commit vault=%s commit=%s files=%d ops=%d",
            vault_id, commit_sha, len(written_paths), total_ops_applied,
        )
    except GitError as exc:
        log.error("update-mode git commit failed vault=%s: %s", vault_id, exc)
        return _fail(exc.code, str(exc), manual_recovery_required=True)

    # 9. Trigger TARGETED re-index.
    reindex_task_id: str | None = None
    reindex_error: str | None = None
    try:
        reindex_task_id = await indexer_service.start_task(
            vault_id=vault_id,
            force_reindex=False,
            source_paths=written_rel_paths,
        )
        log.info(
            "update-mode targeted re-index triggered vault=%s task_id=%s paths=%s",
            vault_id, reindex_task_id, written_rel_paths,
        )
    except (KeyError, ValueError) as exc:
        log.warning("update-mode re-index not started vault=%s: %s", vault_id, exc)
        reindex_error = str(exc)
    except Exception as exc:
        log.error(
            "update-mode re-index unexpected error vault=%s: %s", vault_id, exc,
            exc_info=True,
        )
        reindex_error = str(exc)

    return UpdateModeVaultApplyResult(
        vault_id=vault_id,
        status=UpdateModeVaultApplyStatus.APPLIED,
        # applied_count reflects total ops applied across all files in this
        # vault, not just the number of files written.
        applied_count=total_ops_applied,
        snapshot_commit_sha=snapshot_sha,
        commit_sha=commit_sha,
        commit_message=commit_msg,
        reindex_task_id=reindex_task_id,
        reindex_error=reindex_error,
    )


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------

async def _get_apply_state(
    redis: aioredis.Redis,
    apply_id: str,
) -> IndexerApplyState | None:
    raw = await redis.get(_apply_state_key(apply_id))
    if raw is None:
        return None
    return IndexerApplyState.model_validate(json.loads(raw))


async def _save_apply_state(
    redis: aioredis.Redis,
    state: IndexerApplyState,
) -> None:
    await redis.set(
        _apply_state_key(state.apply_id),
        json.dumps(state.model_dump(mode="json"), ensure_ascii=False),
        ex=_APPLY_STATE_TTL,
    )


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def apply_changes(
    request: UpdateModeApplyRequest,
    db: IndexerDBClient,
    indexer_service: IndexerService,
    redis: aioredis.Redis,
) -> UpdateModeApplyResponse:
    """Apply all file_batches grouped by vault_id.

    Idempotent: re-sending the same apply_id returns cached response.
    Concurrent duplicates for the same apply_id are blocked by a Redis NX lock.

    Returns per-vault results.  Never raises — vault-level errors are
    captured in UpdateModeVaultApplyResult.
    """
    apply_id = request.apply_id
    fingerprint = _request_fingerprint(request)

    # --- 1. Check completed idempotency record ---
    existing_state = await _get_apply_state(redis, apply_id)
    if existing_state is not None and existing_state.status == "completed":
        assert existing_state.response is not None
        log.info("update-mode apply idempotent hit apply_id=%s", apply_id)
        return existing_state.response

    # --- 2. Acquire distributed lock (NX, auto-expires) ---
    lock_key = _apply_lock_key(apply_id)
    acquired = await redis.set(lock_key, "1", nx=True, px=_LOCK_TTL_MS)
    if not acquired:
        raise _ApplyInProgressError(
            f"apply_id={apply_id} is already in progress on another instance"
        )

    try:
        # --- 3. Persist in_progress record ---
        in_progress_state = IndexerApplyState(
            apply_id=apply_id,
            request_fingerprint=fingerprint,
            status="in_progress",
            response=None,
            created_at=datetime.now(timezone.utc),
        )
        await _save_apply_state(redis, in_progress_state)

        # --- 4. Group file_batches by vault_id ---
        by_vault: dict[str, list[UpdateModeFileChangeBatch]] = defaultdict(list)
        for batch in request.file_batches:
            by_vault[batch.vault_id].append(batch)

        results: list[UpdateModeVaultApplyResult] = []
        for vault_id, vault_batches in by_vault.items():
            result = await _apply_vault(
                vault_id=vault_id,
                batches=vault_batches,
                request=request,
                db=db,
                indexer_service=indexer_service,
            )
            results.append(result)
            log.info(
                "apply vault=%s status=%s applied=%d",
                vault_id, result.status.value, result.applied_count,
            )

        response = UpdateModeApplyResponse(
            apply_id=apply_id,
            results=results,
        )

        # --- 5. Persist completed state ---
        completed_state = IndexerApplyState(
            apply_id=apply_id,
            request_fingerprint=fingerprint,
            status="completed",
            response=response,
            created_at=in_progress_state.created_at,
        )
        await _save_apply_state(redis, completed_state)
        return response

    finally:
        await redis.delete(lock_key)


class _ApplyInProgressError(Exception):
    """Raised when a distributed lock prevents duplicate concurrent apply."""
    pass


# Expose for import in router
ApplyInProgressError = _ApplyInProgressError
