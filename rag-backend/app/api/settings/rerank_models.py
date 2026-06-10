from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RerankModel
from app.db.session import get_db
from app.services.settings_service import settings_service
from .helpers import _check_reranker_provider
from .schemas import RerankModelCreateRequest, RerankModelUpdateRequest

router = APIRouter()

SUPPORTED_RERANK_PROVIDERS = ["openai_compatible", "cohere", "jina"]


async def _get_rerank_model_by_model_id(model_id: str, db: AsyncSession) -> RerankModel | None:
    """Lookup RerankModel by model_id (string), not by PK (UUID)."""
    result = await db.execute(select(RerankModel).where(RerankModel.model_id == model_id))
    return result.scalar_one_or_none()


@router.get("/models/rerank")
async def list_rerank_models(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await settings_service.list_rerank_models(db)


@router.post("/models/rerank", status_code=status.HTTP_201_CREATED)
async def create_rerank_model(req: RerankModelCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if req.provider not in SUPPORTED_RERANK_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported reranker provider")
    if await _get_rerank_model_by_model_id(req.model_id, db) is not None:
        raise HTTPException(status_code=409, detail="Rerank model already exists")
    return await settings_service.create_rerank_model(req.model_dump(exclude_none=True), db)


@router.put("/models/rerank/{model_id:path}")
async def update_rerank_model(
    model_id: str, req: RerankModelUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    payload = req.model_dump(exclude_unset=True)
    if payload.get("provider") is not None and payload["provider"] not in SUPPORTED_RERANK_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported reranker provider")
    try:
        return await settings_service.update_rerank_model(model_id, payload, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Rerank model not found") from exc


@router.delete("/models/rerank/{model_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rerank_model(model_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await settings_service.delete_rerank_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Rerank model not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/models/rerank/{model_id:path}/activate")
async def activate_rerank_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await settings_service.activate_rerank_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Rerank model not found") from exc


@router.post("/models/rerank/{model_id:path}/deactivate")
async def deactivate_rerank_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    model = await _get_rerank_model_by_model_id(model_id, db)
    if model is None:
        raise HTTPException(status_code=404, detail="Rerank model not found")
    model.is_active = False
    await db.commit()
    await db.refresh(model)
    return await settings_service.list_rerank_models(db)


@router.post("/models/rerank/{model_id:path}/check")
async def check_rerank_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    model = await _get_rerank_model_by_model_id(model_id, db)
    if model is None:
        raise HTTPException(status_code=404, detail="Rerank model not found")
    started = time.perf_counter()
    try:
        await _check_reranker_provider(model)
        return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000), "error": None}
    except Exception as exc:
        return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "error": str(exc)}
