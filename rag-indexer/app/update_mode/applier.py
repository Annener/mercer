"""Campaign Update Mode — applier.

Called by POST /internal/update-mode/apply.

Responsibilities
----------------
1. Group accepted changes by vault_id.
2. For each vault:
   a. git_init_if_needed.
   b. git_snapshot (pre-apply safety commit, --allow-empty).
   c. For each change: CAS-check expected_sha256, then atomic_write.
   d. git_apply_commit with list of written paths.
   e. Trigger re-index via IndexerService.start_task.
3. Return UpdateModeApplyResponse with per-vault results.

CAS failures and write errors produce CONFLICT / FAILED vault results,
not HTTP 500.  Partial success is possible across vaults.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

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
    UpdateModeAction,
    UpdateModeApplyChange,
    UpdateModeApplyRequest,
    UpdateModeApplyResponse,
    UpdateModeVaultApplyResult,
    UpdateModeVaultApplyStatus,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    ) -> UpdateModeVaultApplyResult:
        return UpdateModeVaultApplyResult(
            vault_id=vault_id,
            status=status,
            applied_count=0,
            error_code=code,
            error_message=msg,
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

    # 4. Snapshot commit (pre-apply)
    # Collect only the paths that will be touched (must exist for UPDATE actions).
    snapshot_paths: list[Path] = []
    for change in changes:
        if change.action == UpdateModeAction.UPDATE:
            try:
                abs_path = resolve_file_path(vault_root, change.file_path)
                if abs_path.exists():
                    snapshot_paths.append(abs_path)
            except PathValidationError:
                pass  # will fail properly in the write loop below

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

    # 5. Apply each change
    written_paths: list[Path] = []
    conflict_changes: list[str] = []

    for change in changes:
        try:
            abs_path = resolve_file_path(vault_root, change.file_path)
        except PathValidationError as exc:
            log.error(
                "update-mode path validation failed vault=%s path=%s: %s",
                vault_id,
                change.file_path,
                exc,
            )
            return _fail(exc.code, f"path={change.file_path!r}: {exc}")

        # CAS guard for UPDATE
        if change.action == UpdateModeAction.UPDATE:
            assert change.expected_sha256 is not None  # validated by Pydantic
            if abs_path.exists():
                current_sha = _sha256_str(abs_path.read_text(encoding="utf-8"))
                if current_sha != change.expected_sha256:
                    log.warning(
                        "update-mode CAS conflict vault=%s path=%s",
                        vault_id,
                        change.file_path,
                    )
                    conflict_changes.append(change.change_id)
                    continue  # skip this change; report conflict at vault level
            else:
                # File was deleted between resolve and apply — treat as conflict
                conflict_changes.append(change.change_id)
                continue

        # CREATE: ensure parent directory exists
        if change.action == UpdateModeAction.CREATE:
            abs_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            atomic_write(abs_path, change.proposed_content)
        except AtomicWriteError as exc:
            return _fail(exc.code, f"write failed for {change.file_path!r}: {exc}")

        written_paths.append(abs_path)
        log.info(
            "update-mode wrote vault=%s path=%s action=%s",
            vault_id,
            change.file_path,
            change.action.value,
        )

    if conflict_changes:
        return UpdateModeVaultApplyResult(
            vault_id=vault_id,
            status=UpdateModeVaultApplyStatus.CONFLICT,
            applied_count=len(written_paths),
            snapshot_commit_sha=snapshot_sha,
            error_code="cas_conflict",
            error_message=f"conflict on change_ids: {conflict_changes}",
        )

    if not written_paths:
        return UpdateModeVaultApplyResult(
            vault_id=vault_id,
            status=UpdateModeVaultApplyStatus.NO_CHANGES,
            applied_count=0,
            snapshot_commit_sha=snapshot_sha,
        )

    # 6. git apply commit
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
            vault_id,
            commit_sha,
            len(written_paths),
        )
    except GitError as exc:
        log.error(
            "update-mode git commit failed vault=%s: %s",
            vault_id,
            exc,
        )
        return _fail(exc.code, str(exc))

    # 7. Trigger re-index
    reindex_task_id: str | None = None
    reindex_error: str | None = None
    try:
        reindex_task_id = await indexer_service.start_task(
            vault_id=vault_id,
            force_reindex=False,
        )
        log.info(
            "update-mode re-index triggered vault=%s task_id=%s",
            vault_id,
            reindex_task_id,
        )
    except (KeyError, ValueError) as exc:
        log.warning(
            "update-mode re-index not started vault=%s: %s",
            vault_id,
            exc,
        )
        reindex_error = str(exc)
    except Exception as exc:
        log.error(
            "update-mode re-index unexpected error vault=%s: %s",
            vault_id,
            exc,
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
# Public entry-point
# ---------------------------------------------------------------------------

async def apply_changes(
    request: UpdateModeApplyRequest,
    db: IndexerDBClient,
    indexer_service: IndexerService,
) -> UpdateModeApplyResponse:
    """Apply all accepted changes grouped by vault_id.

    Returns per-vault results.  Never raises — vault-level errors are
    captured in UpdateModeVaultApplyResult.
    """
    # Group changes by vault_id
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
            vault_id,
            result.status.value,
            result.applied_count,
        )

    return UpdateModeApplyResponse(
        apply_id=request.apply_id,
        results=results,
    )
