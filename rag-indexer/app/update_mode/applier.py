"""Campaign Update Mode — applier.

Called by POST /internal/update-mode/apply.

Responsibilities
----------------
1. Idempotency: if apply_id already completed, return cached response from Redis.
2. Distributed lock: SET NX / PX lock key for duration of apply to prevent
   concurrent duplicate in-flight requests for the same apply_id.
3. Group accepted changes by vault_id.
4. For each vault:
   a. git_init_if_needed.
   b. git_snapshot (pre-apply safety commit, --allow-empty).
   c. For each change: CAS-check expected_sha256, then atomic_write.
   d. git_apply_commit with list of written paths.
   e. Trigger TARGETED re-index via IndexerService.start_task(source_paths=...).
5. Persist completed response in Redis (idempotency record, TTL=3h).
6. Return UpdateModeApplyResponse with per-vault results.

CAS failures and write errors produce CONFLICT / FAILED vault results,
not HTTP 500.  Partial success is possible across vaults.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

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
from shared_contracts.models import (
    IndexerApplyState,
    UpdateModeAction,
    UpdateModeApplyChange,
    UpdateModeApplyRequest,
    UpdateModeApplyResponse,
    UpdateModeVaultApplyResult,
    UpdateModeVaultApplyStatus,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

_APPLY_STATE_TTL = 3 * 60 * 60  # 3 hours — matches session TTL
_LOCK_TTL_MS = 30_000  # 30 s lock TTL (auto-expire on crash)


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


# ---------------------------------------------------------------------------
# Per-vault apply
# ---------------------------------------------------------------------------

async def _apply_vault(
    vault_id: str,
    changes: list[UpdateModeApplyChange],
    request: UpdateModeApplyRequest,
    db: IndexerDBClient,
    indexer_service: IndexerService,
) -> UpdateModeVaultApplyResult:
    """Apply all accepted changes for a single vault.

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

    # 3. Resolve vault identity (DB override → env fallback handled inside fs_git)
    try:
        vault_identity = await _get_vault_identity(db, vault_id)
    except Exception as exc:
        log.warning("Could not fetch vault git identity vault_id=%s: %s", vault_id, exc)
        vault_identity = None

    # 4. Preflight CAS check (read-only, before any writes)
    #    Fail fast if any UPDATE change would CAS-conflict.
    preflight_conflicts: list[str] = []
    for change in changes:
        if change.action == UpdateModeAction.UPDATE:
            assert change.expected_sha256 is not None  # validated by Pydantic
            try:
                abs_path = resolve_file_path(vault_root, change.file_path)
            except PathValidationError:
                preflight_conflicts.append(change.change_id)
                continue
            if not abs_path.exists():
                preflight_conflicts.append(change.change_id)
                continue
            current_sha = _sha256_str(abs_path.read_text(encoding="utf-8"))
            if current_sha != change.expected_sha256:
                preflight_conflicts.append(change.change_id)

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

    # 5. Snapshot commit (pre-apply)
    # Collect only the paths that will be touched (must exist for UPDATE actions).
    snapshot_paths: list[Path] = []
    for change in changes:
        if change.action == UpdateModeAction.UPDATE:
            try:
                abs_path = resolve_file_path(vault_root, change.file_path)
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
            log.info(
                "update-mode snapshot vault=%s commit=%s",
                vault_id,
                snapshot_sha,
            )
    except GitError as exc:
        log.warning(
            "update-mode snapshot failed vault=%s — continuing without snapshot: %s",
            vault_id,
            exc,
        )
        # Non-fatal: proceed without snapshot

    # 6. Apply each change
    written_paths: list[Path] = []
    written_rel_paths: list[str] = []  # relative source paths for targeted reindex

    for change in changes:
        try:
            abs_path = resolve_file_path(vault_root, change.file_path)
        except PathValidationError as exc:
            log.error(
                "update-mode path validation failed vault=%s path=%s: %s",
                vault_id, change.file_path, exc,
            )
            # Any write-time path error after preflight passed — flag manual recovery
            return _fail(
                exc.code,
                f"path={change.file_path!r}: {exc}",
                manual_recovery_required=bool(written_paths),
            )

        # CREATE: ensure parent directory exists
        if change.action == UpdateModeAction.CREATE:
            abs_path.parent.mkdir(parents=True, exist_ok=True)

        # DELETE operations: proposed_content is "" (empty string).
        # Warn if the file will become empty after apply.
        # This is NOT a blocking error — the user explicitly accepted the change.
        if (
            change.action == UpdateModeAction.UPDATE
            and change.proposed_content == ""
            and abs_path.exists()
        ):
            log.warning(
                "update-mode file_would_become_empty: vault=%s path=%s change_id=%s — "
                "delete operation will result in an empty file; applying as accepted",
                vault_id,
                change.file_path,
                change.change_id,
            )

        try:
            atomic_write(abs_path, change.proposed_content)
        except AtomicWriteError as exc:
            return _fail(
                exc.code,
                f"write failed for {change.file_path!r}: {exc}",
                manual_recovery_required=bool(written_paths),
            )

        written_paths.append(abs_path)
        written_rel_paths.append(change.file_path)
        log.info(
            "update-mode wrote vault=%s path=%s action=%s",
            vault_id, change.file_path, change.action.value,
        )

    if not written_paths:
        return UpdateModeVaultApplyResult(
            vault_id=vault_id,
            status=UpdateModeVaultApplyStatus.NO_CHANGES,
            applied_count=0,
            snapshot_commit_sha=snapshot_sha,
        )

    # 7. git apply commit
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
            "update-mode apply commit vault=%s commit=%s files=%d",
            vault_id, commit_sha, len(written_paths),
        )
    except GitError as exc:
        log.error(
            "update-mode git commit failed vault=%s: %s",
            vault_id, exc,
        )
        return _fail(exc.code, str(exc), manual_recovery_required=True)

    # 8. Trigger TARGETED re-index (only written files — avoids full vault rescan)
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
        log.warning(
            "update-mode re-index not started vault=%s: %s",
            vault_id, exc,
        )
        reindex_error = str(exc)
    except Exception as exc:
        log.error(
            "update-mode re-index unexpected error vault=%s: %s",
            vault_id, exc,
            exc_info=True,
        )
        reindex_error = str(exc)

    return UpdateModeVaultApplyResult(
        vault_id=vault_id,
        status=UpdateModeVaultApplyStatus.APPLIED,
        applied_count=len(written_paths),
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
    """Apply all accepted changes grouped by vault_id.

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
        log.info(
            "update-mode apply idempotent hit apply_id=%s",
            apply_id,
        )
        return existing_state.response

    # --- 2. Acquire distributed lock (NX, auto-expires) ---
    lock_key = _apply_lock_key(apply_id)
    acquired = await redis.set(lock_key, "1", nx=True, px=_LOCK_TTL_MS)
    if not acquired:
        # Another instance is processing the same apply_id.
        # Return 409-equivalent by raising — router will translate.
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

        # --- 4. Group changes by vault_id ---
        by_vault: dict[str, list[UpdateModeApplyChange]] = {}
        for change in request.accepted_changes:
            by_vault.setdefault(change.vault_id, []).append(change)

        results: list[UpdateModeVaultApplyResult] = []
        for vault_id, vault_changes in by_vault.items():
            result = await _apply_vault(
                vault_id=vault_id,
                changes=vault_changes,
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
        # Always release the lock, even on unexpected exception
        await redis.delete(lock_key)


class _ApplyInProgressError(Exception):
    """Raised when a distributed lock prevents duplicate concurrent apply."""
    pass


# Expose for import in router
ApplyInProgressError = _ApplyInProgressError
