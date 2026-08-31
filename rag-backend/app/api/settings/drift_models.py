"""Settings API for drift models — Phase 2a of context-engine refactor.

Mirrors ``rerank_models.py``: full CRUD plus ``activate`` / ``deactivate``
/ ``check`` health probe. The active model is enforced server-side via
a partial unique index on ``drift_models(is_active) WHERE is_active``.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DriftModel
from app.db.session import get_db
from app.services.settings_service import settings_service

from .helpers import _check_drift_provider
from .schemas import DriftModelCreateRequest, DriftModelUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter()

SUPPORTED_DRIFT_PROVIDERS = ["host_sidecar", "openai_compatible"]


async def _get_drift_model_by_model_id(
    model_id: str, db: AsyncSession
) -> DriftModel | None:
    result = await db.execute(select(DriftModel).where(DriftModel.model_id == model_id))
    return result.scalar_one_or_none()


@router.get("/models/drift")
async def list_drift_models(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await settings_service.list_drift_models(db)


@router.post("/models/drift", status_code=status.HTTP_201_CREATED)
async def create_drift_model(
    req: DriftModelCreateRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if req.provider not in SUPPORTED_DRIFT_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported drift provider")
    if await _get_drift_model_by_model_id(req.model_id, db) is not None:
        raise HTTPException(status_code=409, detail="Drift model already exists")
    return await settings_service.create_drift_model(
        req.model_dump(exclude_none=True), db
    )


@router.put("/models/drift/{model_id:path}")
async def update_drift_model(
    model_id: str,
    req: DriftModelUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    payload = req.model_dump(exclude_unset=True)
    if payload.get("provider") is not None and payload["provider"] not in SUPPORTED_DRIFT_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported drift provider")
    try:
        return await settings_service.update_drift_model(model_id, payload, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Drift model not found") from exc


@router.delete("/models/drift/{model_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_drift_model(
    model_id: str, db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        await settings_service.delete_drift_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Drift model not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/models/drift/{model_id:path}/activate")
async def activate_drift_model(
    model_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        return await settings_service.activate_drift_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Drift model not found") from exc


@router.post("/models/drift/{model_id:path}/deactivate")
async def deactivate_drift_model(
    model_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    model = await _get_drift_model_by_model_id(model_id, db)
    if model is None:
        raise HTTPException(status_code=404, detail="Drift model not found")
    return await settings_service.deactivate_drift_model(model_id, db)


@router.post("/models/drift/{model_id:path}/check")
async def check_drift_model(
    model_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    model = await _get_drift_model_by_model_id(model_id, db)
    if model is None:
        raise HTTPException(status_code=404, detail="Drift model not found")
    started = time.perf_counter()
    try:
        await _check_drift_provider(model)
        return {
            "ok": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001  # health check must catch all errors
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": str(exc),
        }
