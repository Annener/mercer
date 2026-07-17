"""Campaign Update Mode — internal FastAPI router for rag-indexer.

Endpoints
---------
  POST /internal/update-mode/resolve
      Body: UpdateModeResolveRequest
      Response: UpdateModeResolveResponse

  POST /internal/update-mode/apply
      Body: UpdateModeApplyRequest
      Response: UpdateModeApplyResponse

Both endpoints read db_client and indexer_service from app.state.
They are internal-only (no auth) — must not be exposed to the public network.

Error mapping
-------------
  Per-intent / per-vault failures → 200 with RESOLUTION_FAILED / FAILED status
  Invalid request body            → 422 (FastAPI default)
  app.state missing               → 503
  apply_id in-progress on another worker → 409
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.db_client import IndexerDBClient
from app.indexer_service import IndexerService
from app.update_mode.applier import ApplyInProgressError, apply_changes
from app.update_mode.resolver import resolve_changes
from shared_contracts.models import (
    UpdateModeApplyRequest,
    UpdateModeApplyResponse,
    UpdateModeResolveRequest,
    UpdateModeResolveResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/update-mode",
    tags=["update-mode-internal"],
)


def _db_client(request: Request) -> IndexerDBClient:
    client = getattr(request.app.state, "db_client", None)
    if not isinstance(client, IndexerDBClient):
        raise HTTPException(status_code=503, detail="DB client not initialised")
    return client


def _indexer_service(request: Request) -> IndexerService:
    service = getattr(request.app.state, "indexer_service", None)
    if not isinstance(service, IndexerService):
        raise HTTPException(status_code=503, detail="Indexer service not initialised")
    return service


def _redis(request: Request):
    redis = getattr(request.app.state, "redis_client", None)
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis not initialised")
    return redis


@router.post("/resolve", response_model=UpdateModeResolveResponse)
async def resolve(
    body: UpdateModeResolveRequest,
    request: Request,
) -> UpdateModeResolveResponse:
    """Parse intents and resolve each against vault filesystem.

    Per-intent resolution failures are returned as RESOLUTION_FAILED
    changes inside the 200 response body — they never cause 500.
    """
    db = _db_client(request)
    log.info(
        "update-mode resolve chat_id=%s campaign_id=%s intents=%d",
        body.chat_id,
        body.campaign_id,
        len(body.intents),
    )
    return await resolve_changes(request=body, db=db)


@router.post("/apply", response_model=UpdateModeApplyResponse)
async def apply(
    body: UpdateModeApplyRequest,
    request: Request,
) -> UpdateModeApplyResponse:
    """Write accepted changes to vault filesystem, commit, and re-index.

    Per-vault failures are captured in UpdateModeVaultApplyResult —
    they never cause 500.

    Returns 409 if the same apply_id is currently being processed by another
    worker instance (distributed lock contention).
    """
    db = _db_client(request)
    indexer_service = _indexer_service(request)
    redis = _redis(request)
    log.info(
        "update-mode apply chat_id=%s apply_id=%s changes=%d",
        body.chat_id,
        body.apply_id,
        len(body.accepted_changes),
    )
    try:
        return await apply_changes(
            request=body,
            db=db,
            indexer_service=indexer_service,
            redis=redis,
        )
    except ApplyInProgressError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"apply_in_progress: {exc}",
        ) from exc
