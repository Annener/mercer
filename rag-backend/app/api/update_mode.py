"""update_mode.py — Campaign Update Mode API router.

Endpoints (all under /api/chats/{chat_id}/update-mode):

  POST   /start    — kick-off: parse note → resolve via indexer → store session
  GET    /session  — get current session status + changes list
  PATCH  /review   — accept / reject individual changes
  POST   /apply    — write accepted changes to vault filesystem + re-index
  DELETE /session  — cancel session

chat_id is the primary key for all operations.

Error mapping (POST /start):
  UpdateModeSessionAlreadyActiveError     → 409
  UpdateModeChatNotFoundError             → 404
  UpdateModeCampaignRequiredError         → 422
  UpdateModeCampaignNotFoundError         → 404
  UpdateModeCampaignDomainMismatchError   → 409
  UpdateModeCampaignTagsRequiredError     → 422
  UpdateModeNoEnabledVaultsError          → 422
  UpdateModeNoIndexedMarkdownError        → 422
  UpdateModeNoRelevantContextError        → 422
  UpdateModeNoUsableContextError          → 422
  UpdateModeGenerationProviderUnavailableError → 503
  UpdateModeInvalidGenerationOutputError  → 422
  UpdateModeIndexerUnavailableError       → 503
  UpdateModeIndexerInvalidResponseError   → 502
  UpdateModeReviewStoreUnavailableError   → 503
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.indexer_client import (
    IndexerConflictError,
    IndexerUnavailableError,
    indexer_client,
)
from app.services.update_mode_executor import (
    UpdateModeExecutor,
    UpdateModeCampaignDomainMismatchError,
    UpdateModeCampaignNotFoundError,
    UpdateModeCampaignRequiredError,
    UpdateModeCampaignTagsRequiredError,
    UpdateModeChatNotFoundError,
    UpdateModeGenerationProviderUnavailableError,
    UpdateModeIndexerInvalidResponseError,
    UpdateModeIndexerUnavailableError,
    UpdateModeInvalidGenerationOutputError,
    UpdateModeNoEnabledVaultsError,
    UpdateModeNoIndexedMarkdownError,
    UpdateModeNoRelevantContextError,
    UpdateModeNoUsableContextError,
    UpdateModeReviewStoreUnavailableError,
    UpdateModeSessionAlreadyActiveError,
)
from app.services.update_mode_store import (
    ApplyConflictError,
    CannotAcceptFailedChangeError,
    ReviewConflictError,
    SessionExpiredError,
    UnknownChangeIdError,
    update_mode_store,
)
from shared_contracts.models import (
    ApplyUpdateModeRequest,
    ApplyUpdateModeResponse,
    CancelUpdateModeResponse,
    ResolvedUpdateModeChange,
    StartUpdateModeRequest,
    StartUpdateModeResponse,
    UpdateModeAction,
    UpdateModeApplyRequest,
    UpdateModeChangeStatus,
    UpdateModeFileChangeBatch,
    UpdateModeFileOp,
    UpdateModeOperation,
    UpdateModeResolveRequest,
    UpdateModeReviewRequest,
    UpdateModeSession,
    UpdateModeSessionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chats/{chat_id}/update-mode",
    tags=["update-mode"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_to_response(session: UpdateModeSession) -> UpdateModeSessionResponse:
    return UpdateModeSessionResponse(
        chat_id=session.chat_id,
        campaign_id=session.campaign_id,
        domain_id=session.domain_id,
        vault_ids=session.vault_ids,
        expires_at=session.expires_at,
        changes=session.changes,
        warnings=session.warnings,
    )


async def _write_audit_log(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: str,
    actor: str,
    payload: dict,
) -> None:
    """Fire-and-forget audit log write. Errors are logged but never re-raised."""
    try:
        from app.db.models import AuditLog  # local import to avoid circular
        from sqlalchemy import insert

        await db.execute(
            insert(AuditLog).values(
                id=str(uuid.uuid4()),
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor=actor,
                payload=payload,
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    except Exception:
        logger.warning("audit log write failed action=%s entity_id=%s", action, entity_id, exc_info=True)


def _build_file_batches(
    accepted: list[ResolvedUpdateModeChange],
) -> list[UpdateModeFileChangeBatch]:
    """Group accepted changes by (vault_id, file_path) and build file_batches.

    Sorting by resolve_order guarantees that multiple ops on the same file are
    applied in the order they were originally resolved (which matches the order
    LLM produced them and the order patch hunks were computed).

    Backward-compat: if a change has no operation field (session was written
    before this PR), fall back to a single overwrite op:
    - For a single legacy change: use proposed_content as a REPLACE via
      CREATE_FILE-style overwrite (the applier receives the full desired state).
    - For multiple legacy changes on the same file: last-write-wins — only
      the last change's proposed_content is used. A warning is logged.

    NOTE: proposed_content is the FULL file content after the op, not a delta.
    It must NOT be passed as content for incremental ops like APPEND_TO_FILE.
    Legacy path uses a dedicated overwrite operation (APPEND_TO_FILE with the
    full proposed_content only makes sense when the file is empty/new, which
    is not guaranteed here). For truly safe legacy overwrite semantics, the
    applier receives proposed_content as the complete desired file state via a
    synthetic single-op batch where the op replaces the entire file contents.
    """
    # Group by (vault_id, file_path), preserving vault/file_path from change
    groups: dict[tuple[str, str], list[ResolvedUpdateModeChange]] = defaultdict(list)
    skipped = 0
    for ch in accepted:
        if ch.vault_id is None or ch.file_path is None:
            logger.warning(
                "Skipping change %s: missing vault_id or file_path", ch.change_id
            )
            skipped += 1
            continue
        groups[(ch.vault_id, ch.file_path)].append(ch)

    if skipped:
        logger.info("_build_file_batches: skipped %d incomplete changes", skipped)

    batches: list[UpdateModeFileChangeBatch] = []
    for (vault_id, file_path), changes in groups.items():
        # Sort by resolve_order so multi-op patches are applied in correct sequence.
        # resolve_order=-1 is the legacy sentinel; treat as 0 for sorting purposes.
        changes.sort(key=lambda c: c.resolve_order if c.resolve_order >= 0 else 0)

        # Detect whether any change in this group carries operation metadata.
        has_operation = any(ch.operation is not None for ch in changes)

        ops: list[UpdateModeFileOp] = []
        if has_operation:
            # New-style changes: build one op per change.
            for i, ch in enumerate(changes):
                if ch.operation is not None:
                    ops.append(
                        UpdateModeFileOp(
                            change_id=ch.change_id,
                            operation=ch.operation,
                            anchor_value=ch.anchor.value if ch.anchor else None,
                            content=ch.op_content,
                            # CAS check only on first op of UPDATE batches
                            expected_sha256=(
                                ch.expected_sha256
                                if i == 0 and ch.action == UpdateModeAction.UPDATE
                                else None
                            ),
                        )
                    )
                else:
                    # Mixed group: some changes have operation, some don't.
                    # This shouldn't happen in practice but handle it gracefully:
                    # skip the legacy change and log a warning.
                    logger.warning(
                        "Change %s in mixed group has no operation field — skipping",
                        ch.change_id,
                    )
        else:
            # Pure legacy group: no change has operation field.
            # proposed_content is the FULL desired file state, not a delta.
            # We cannot compose multiple legacy full-file states, so last-write-wins.
            if len(changes) > 1:
                logger.warning(
                    "update-mode legacy backward-compat: %d changes share "
                    "file_path=%r but none has operation field — "
                    "using only the last change (%s). "
                    "Other changes are dropped (last-write-wins fallback).",
                    len(changes), file_path, changes[-1].change_id,
                )
            last = changes[-1]
            # Use REPLACE_UNIQUE_TEXT is not suitable here because we don't have
            # an anchor. Instead, use a single CREATE_FILE-style op: the applier
            # will receive the full desired content and write it atomically.
            # For UPDATE batches we reuse the same action but pass proposed_content
            # as the full file — the applier's text_ops will write it via
            # APPEND_TO_FILE on an empty buffer after current content is cleared.
            # The safest legacy overwrite is: deliver proposed_content as the
            # sole op content for a CREATE_FILE operation regardless of action,
            # since proposed_content == full intended state of the file.
            # We set action=CREATE to bypass the CAS check that would otherwise
            # fire on ops[0].expected_sha256=None for an UPDATE batch.
            # This is safe because proposed_content was computed at resolve time
            # from the original and already encodes the full desired state.
            if last.action == UpdateModeAction.UPDATE:
                ops = [
                    UpdateModeFileOp(
                        change_id=last.change_id,
                        operation=UpdateModeOperation.CREATE_FILE,
                        anchor_value=None,
                        content=last.proposed_content,
                        expected_sha256=None,
                    )
                ]
                # Override action to CREATE so the validator and applier skip
                # the CAS check (proposed_content is already the full state).
                batches.append(
                    UpdateModeFileChangeBatch(
                        vault_id=vault_id,
                        file_path=file_path,
                        action=UpdateModeAction.CREATE,
                        ops=ops,
                    )
                )
                continue
            else:
                # action=CREATE already: write proposed_content as-is.
                ops = [
                    UpdateModeFileOp(
                        change_id=last.change_id,
                        operation=UpdateModeOperation.CREATE_FILE,
                        anchor_value=None,
                        content=last.proposed_content,
                        expected_sha256=None,
                    )
                ]

        if ops:
            batches.append(
                UpdateModeFileChangeBatch(
                    vault_id=vault_id,
                    file_path=file_path,
                    action=changes[0].action,
                    ops=ops,
                )
            )

    return batches


# ---------------------------------------------------------------------------
# POST /start
# ---------------------------------------------------------------------------


@router.post("/start", response_model=StartUpdateModeResponse, status_code=200)
async def start_update_mode(
    chat_id: str,
    body: StartUpdateModeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StartUpdateModeResponse:
    """Validate campaign context, retrieve docs, generate intents, resolve via indexer,
    store Redis review session.

    campaign_id is resolved from chat.campaign_id via DB — no query param needed.
    """
    redis = request.app.state.redis

    executor = UpdateModeExecutor(
        db=db,
        store=update_mode_store,
        indexer_client=indexer_client,
    )

    try:
        session = await executor.start(chat_id=chat_id, redis=redis, note=body.note)
    except UpdateModeSessionAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=exc.code)
    except UpdateModeChatNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.code)
    except UpdateModeCampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.code)
    except UpdateModeCampaignRequiredError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeCampaignDomainMismatchError as exc:
        raise HTTPException(status_code=409, detail=exc.code)
    except UpdateModeCampaignTagsRequiredError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeNoEnabledVaultsError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeNoIndexedMarkdownError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeNoRelevantContextError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeNoUsableContextError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeInvalidGenerationOutputError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeGenerationProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.code)
    except UpdateModeIndexerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.code)
    except UpdateModeIndexerInvalidResponseError as exc:
        raise HTTPException(status_code=502, detail=exc.code)
    except UpdateModeReviewStoreUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.code)

    return StartUpdateModeResponse(
        chat_id=session.chat_id,
        expires_at=session.expires_at,
        changes=session.changes,
        warnings=session.warnings,
    )


# ---------------------------------------------------------------------------
# GET /session
# ---------------------------------------------------------------------------


@router.get("/session", response_model=UpdateModeSessionResponse)
async def get_update_mode_session(
    chat_id: str,
    request: Request,
    response: Response,
) -> UpdateModeSessionResponse:
    redis = request.app.state.redis

    session = await update_mode_store.get(redis, chat_id)
    if session is None:
        response.headers["Cache-Control"] = "no-store"
        raise HTTPException(status_code=410, detail="session_expired")

    return _session_to_response(session)


# ---------------------------------------------------------------------------
# PATCH /review
# ---------------------------------------------------------------------------


@router.patch("/review", response_model=UpdateModeSessionResponse)
async def review_changes(
    chat_id: str,
    body: UpdateModeReviewRequest,
    request: Request,
) -> UpdateModeSessionResponse:
    redis = request.app.state.redis

    try:
        session = await update_mode_store.update_review(
            redis,
            chat_id,
            accepted_change_ids=set(body.accepted_change_ids),
            rejected_change_ids=set(body.rejected_change_ids),
        )
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    except UnknownChangeIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CannotAcceptFailedChangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return _session_to_response(session)


# ---------------------------------------------------------------------------
# POST /apply
# ---------------------------------------------------------------------------


@router.post("/apply", response_model=ApplyUpdateModeResponse)
async def apply_changes(
    chat_id: str,
    body: ApplyUpdateModeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApplyUpdateModeResponse:
    """Delegate writing + reindex to rag-indexer. Idempotent for same apply_id.

    Builds file_batches from accepted session changes so the indexer can apply
    multiple ops to the same file in a single atomic read-modify-write cycle.

    After receiving the indexer response:
    - persists apply_result in the Redis session via complete_apply()
    - writes an AuditLog row
    """
    redis = request.app.state.redis

    try:
        session = await update_mode_store.begin_apply(redis, chat_id, body.apply_id)
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    except ApplyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    accepted = [
        ch for ch in session.changes
        if ch.status == UpdateModeChangeStatus.ACCEPTED
    ]
    if not accepted:
        raise HTTPException(
            status_code=422,
            detail="No accepted changes to apply. Use PATCH /review to accept changes first.",
        )

    file_batches = _build_file_batches(accepted)

    if not file_batches:
        raise HTTPException(
            status_code=422,
            detail="No complete changes to apply (missing vault_id or file_path).",
        )

    apply_req = UpdateModeApplyRequest(
        apply_id=session.apply_id or str(uuid.uuid4()),
        chat_id=chat_id,
        campaign_id=session.campaign_id,
        file_batches=file_batches,
    )

    try:
        apply_resp = await indexer_client.apply(apply_req)
    except IndexerConflictError as exc:
        raise HTTPException(status_code=409, detail=f"Apply conflict: {exc.detail}")
    except IndexerUnavailableError as exc:
        raise HTTPException(status_code=502, detail=f"Indexer unavailable: {exc.detail}")

    # Persist completed result into Redis session (non-fatal if session already expired)
    await update_mode_store.complete_apply(redis, chat_id, apply_resp)

    # Audit log — non-fatal
    await _write_audit_log(
        db=db,
        action="update_mode.apply",
        entity_type="campaign",
        entity_id=session.campaign_id,
        actor=f"chat:{chat_id}",
        payload={
            "apply_id": apply_resp.apply_id,
            "chat_id": chat_id,
            "campaign_id": session.campaign_id,
            "vault_results": [
                {
                    "vault_id": r.vault_id,
                    "status": r.status.value,
                    "applied_count": r.applied_count,
                    "commit_sha": r.commit_sha,
                    "reindex_task_id": r.reindex_task_id,
                }
                for r in apply_resp.results
            ],
        },
    )

    return ApplyUpdateModeResponse(
        apply_id=apply_resp.apply_id,
        results=apply_resp.results,
    )


# ---------------------------------------------------------------------------
# DELETE /session
# ---------------------------------------------------------------------------


@router.delete("/session", response_model=CancelUpdateModeResponse)
async def cancel_update_mode(
    chat_id: str,
    request: Request,
) -> CancelUpdateModeResponse:
    redis = request.app.state.redis
    await update_mode_store.delete(redis, chat_id)
    return CancelUpdateModeResponse(status="cancelled")
