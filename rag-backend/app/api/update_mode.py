"""update_mode.py — Campaign Update Mode API router.

Endpoints (all under /api/chats/{chat_id}/update-mode):

  POST   /start    — kick-off: parse note → resolve via indexer → store session
  GET    /session  — get current session status + changes list
  PATCH  /review   — accept / reject individual changes
  POST   /apply    — write accepted changes to vault filesystem + re-index
  DELETE /session  — cancel session

chat_id is the primary key for all operations.
campaign_id is a query param in this skeleton; Phase 3 will resolve it
from chat.campaign_id via DB (UpdateModeExecutor).

Error mapping:
  UpdateModeError subclasses → HTTP 409 / 404 / 422 where appropriate
  IndexerUnavailableError    → HTTP 502
  IndexerConflictError       → HTTP 409
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, Document, Vault
from app.db.session import get_db
from app.services.indexer_client import (
    IndexerConflictError,
    IndexerUnavailableError,
    indexer_client,
)
from app.services.update_mode_store import (
    ApplyConflictError,
    CannotAcceptFailedChangeError,
    ReviewConflictError,
    SessionAlreadyActiveError,
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
    UpdateModeIntent,
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

_SESSION_HOURS = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_campaign_context(
    db: AsyncSession,
    campaign_id: str,
) -> tuple[str, list[str], str, list[str]]:
    """Return (domain_id, vault_ids, default_vault_id, candidate_doc_ids).

    candidate_doc_ids: up to 15 recently indexed document ids from all vaults
    belonging to the campaign domain — sent to indexer for resolve lookup.

    Raises 404 if campaign not found.
    Raises 422 if domain has no enabled vaults.
    """
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id)
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    domain_id: str = campaign.domain_id

    vault_result = await db.execute(
        select(Vault)
        .where(Vault.domain_id == domain_id, Vault.enabled.is_(True))
        .order_by(Vault.vault_id)
    )
    vaults = vault_result.scalars().all()
    if not vaults:
        raise HTTPException(status_code=422, detail="Domain has no enabled vaults")

    vault_ids = [v.vault_id for v in vaults]
    default_vault_id = vault_ids[0]

    doc_result = await db.execute(
        select(Document.id)
        .where(
            Document.vault_id.in_(vault_ids),
            Document.status == "indexed",
        )
        .order_by(Document.indexed_at.desc())
        .limit(15)
    )
    candidate_doc_ids = [str(row) for row in doc_result.scalars().all()]

    return domain_id, vault_ids, default_vault_id, candidate_doc_ids


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


# ---------------------------------------------------------------------------
# POST /start
# ---------------------------------------------------------------------------


@router.post("/start", response_model=StartUpdateModeResponse, status_code=200)
async def start_update_mode(
    chat_id: str,
    body: StartUpdateModeRequest,
    request: Request,
    campaign_id: str = Query(..., description="Campaign ID (Phase 3: resolved from chat.campaign_id)"),
    db: AsyncSession = Depends(get_db),
) -> StartUpdateModeResponse:
    """Parse note, resolve changes via rag-indexer, store session in Redis.

    campaign_id is a temporary query param for the Phase 2 skeleton.
    Phase 3 (UpdateModeExecutor) will resolve it from chat.campaign_id via DB
    and remove this query param.

    Calling /start while a session already exists for this chat_id returns 409.
    """
    redis = request.app.state.redis

    domain_id, vault_ids, default_vault_id, candidate_doc_ids = (
        await _get_campaign_context(db, campaign_id)
    )

    stub_intent = UpdateModeIntent(
        change_id="stub-0",
        action=UpdateModeAction.CREATE,
        description=body.note[:2000],
        operation=UpdateModeOperation.CREATE_FILE,
        suggested_filename="_note.md",
        content=body.note,
    )
    resolve_req = UpdateModeResolveRequest(
        chat_id=chat_id,
        campaign_id=campaign_id,
        domain_id=domain_id,
        vault_ids=vault_ids,
        intents=[stub_intent],
        default_vault_id=default_vault_id,
        candidate_document_ids=candidate_doc_ids,
    )

    try:
        resolve_resp = await indexer_client.resolve(resolve_req)
    except IndexerUnavailableError as exc:
        logger.error("indexer resolve failed: %s", exc.detail)
        raise HTTPException(status_code=502, detail=f"Indexer unavailable: {exc.detail}")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=_SESSION_HOURS)
    session = UpdateModeSession(
        session_id=str(uuid.uuid4()),
        chat_id=chat_id,
        campaign_id=campaign_id,
        domain_id=domain_id,
        vault_ids=vault_ids,
        default_vault_id=default_vault_id,
        candidate_document_ids=candidate_doc_ids,
        note=body.note,
        warnings=[],
        changes=resolve_resp.changes,
        created_at=now,
        expires_at=expires_at,
    )

    try:
        await update_mode_store.create(redis, session)
    except SessionAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return StartUpdateModeResponse(
        chat_id=chat_id,
        expires_at=expires_at,
        changes=resolve_resp.changes,
        warnings=[],
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
        # Distinguish expired (key existed, TTL elapsed) from never-created.
        # Redis DEL on TTL expiry is indistinguishable from never-set at this
        # level, so we return 410 Gone for any missing key on GET /session —
        # the client must call POST /start to create a new session.
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
) -> ApplyUpdateModeResponse:
    """Delegate writing + reindex to rag-indexer. Idempotent for same apply_id."""
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

    apply_changes_list = []
    for ch in accepted:
        if ch.vault_id is None or ch.file_path is None:
            logger.warning("Skipping change %s: missing vault_id or file_path", ch.change_id)
            continue
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
