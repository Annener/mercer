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
from datetime import datetime, timedelta, timezone

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
    StartUpdateModeRequest,
    StartUpdateModeResponse,
    UpdateModeAction,
    UpdateModeApplyChange,
    UpdateModeApplyRequest,
    UpdateModeChangeStatus,
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

    After receiving the indexer response:
    - persists apply_result in the Redis session via complete_apply()
    - writes an AuditLog row

    Notes on deduplication:
    - UpdateModeApplyRequest enforces unique (vault_id, file_path) pairs.
    - A session may legitimately contain several accepted changes for the same
      file (e.g. DELETE_SECTION + APPEND_AFTER_SECTION).  The indexer currently
      supports only one write operation per file per request, so we keep only the
      first accepted change per (vault_id, file_path) pair and warn about skipped
      duplicates.
    - TODO: once the indexer supports ordered multi-op batches per file, remove
      the dedup logic below and pass all accepted changes through unchanged.
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

    # Build apply list, deduplicating by (vault_id, file_path).
    # The indexer accepts only one operation per file per request.
    # When the same file appears in multiple accepted changes we keep the first
    # and emit a warning for every skipped duplicate.
    seen_file_keys: set[tuple[str, str]] = set()
    apply_changes_list: list[UpdateModeApplyChange] = []

    for ch in accepted:
        if ch.vault_id is None or ch.file_path is None:
            logger.warning(
                "apply_changes: skipping change %s — missing vault_id or file_path",
                ch.change_id,
            )
            continue

        file_key = (ch.vault_id, ch.file_path)
        if file_key in seen_file_keys:
            logger.warning(
                "apply_changes: skipping duplicate (vault_id=%s, file_path=%s) "
                "for change_id=%s — only the first accepted change per file is sent "
                "to the indexer in this request",
                ch.vault_id,
                ch.file_path,
                ch.change_id,
            )
            continue

        seen_file_keys.add(file_key)
        apply_changes_list.append(
            UpdateModeApplyChange(
                change_id=ch.change_id,
                vault_id=ch.vault_id,
                file_path=ch.file_path,
                action=ch.action,
                proposed_content=ch.proposed_content,
                expected_sha256=ch.expected_sha256,
            )
        )

    if not apply_changes_list:
        raise HTTPException(
            status_code=422,
            detail="No complete changes to apply (missing vault_id or file_path).",
        )

    apply_req = UpdateModeApplyRequest(
        apply_id=session.apply_id or str(uuid.uuid4()),
        chat_id=chat_id,
        campaign_id=session.campaign_id,
        accepted_changes=apply_changes_list,
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
