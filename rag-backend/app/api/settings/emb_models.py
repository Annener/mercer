from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmbeddingModel, Vault
from app.db.session import get_db
from app.services.settings_service import settings_service
from .helpers import _check_embedding_provider
from .schemas import EmbeddingModelCreateRequest, EmbeddingModelUpdateRequest

router = APIRouter()

SUPPORTED_PROVIDERS = ["ollama", "openai_compatible", "sidecar"]


async def _get_embedding_model_by_model_id(model_id: str, db: AsyncSession) -> EmbeddingModel | None:
    """Lookup EmbeddingModel by model_id (string), not by PK (UUID)."""
    result = await db.execute(select(EmbeddingModel).where(EmbeddingModel.model_id == model_id))
    return result.scalar_one_or_none()


@router.get("/models/embedding")
async def list_embedding_models(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await settings_service.list_embedding_models(db)


@router.post("/models/embedding", status_code=status.HTTP_201_CREATED)
async def create_embedding_model(req: EmbeddingModelCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if req.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported embedding provider")
    if await _get_embedding_model_by_model_id(req.model_id, db) is not None:
        raise HTTPException(status_code=409, detail="Embedding model already exists")
    return await settings_service.create_embedding_model(req.model_dump(exclude_none=True), db)


@router.post("/models/embedding/{model_id:path}/check")
async def check_embedding_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    # E-CHK01 fix: был db.get(EmbeddingModel, model_id) — ищет по PK (UUID), падает
    # с asyncpg.DataError когда model_id — строка вида "vendor/model:tag".
    # Правильный lookup — по полю model_id (String), не по id (UUID).
    model = await _get_embedding_model_by_model_id(model_id, db)
    if model is None:
        raise HTTPException(status_code=404, detail="Embedding model not found")
    started = time.perf_counter()
    try:
        vector = await _check_embedding_provider(model)
        return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000), "dimensions": len(vector), "error": None}
    except Exception as exc:
        return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "dimensions": None, "error": str(exc)}


@router.put("/models/embedding/{model_id:path}")
async def update_embedding_model(
    model_id: str, req: EmbeddingModelUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    payload = req.model_dump(exclude_unset=True)
    if payload.get("provider") is not None and payload["provider"] not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported embedding provider")
    try:
        return await settings_service.update_embedding_model(model_id, payload, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Embedding model not found") from exc


@router.delete("/models/embedding/{model_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_embedding_model(model_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    result = await db.execute(select(func.count()).select_from(Vault).where(Vault.embedding_model_id == model_id))
    if result.scalar_one() > 0:
        raise HTTPException(status_code=409, detail="Model is used by existing vaults")
    try:
        await settings_service.delete_embedding_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Embedding model not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
