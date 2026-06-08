from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GenerationModelConfig
from app.db.models import GenerationModel
from app.db.session import get_db
from app.providers.generation.openai_compatible import OpenAICompatibleProvider
from app.services.settings_service import settings_service
from .schemas import GenerationModelCreateRequest, GenerationModelUpdateRequest

router = APIRouter()


async def _get_generation_model_by_model_id(model_id: str, db: AsyncSession) -> GenerationModel | None:
    """Lookup GenerationModel by model_id (string), not by PK (UUID)."""
    result = await db.execute(select(GenerationModel).where(GenerationModel.model_id == model_id))
    return result.scalar_one_or_none()


@router.get("/models/generation")
async def list_generation_models(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await settings_service.list_generation_models(db)


@router.post("/models/generation", status_code=status.HTTP_201_CREATED)
async def create_generation_model(req: GenerationModelCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    # E-CHK02 fix: db.get() искал по PK (UUID), падал с asyncpg.DataError на строковом model_id
    if await _get_generation_model_by_model_id(req.model_id, db) is not None:
        raise HTTPException(status_code=409, detail="Generation model already exists")
    try:
        return await settings_service.create_generation_model(req.model_dump(exclude_none=True), db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/models/generation/{model_id:path}/activate")
async def activate_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await settings_service.activate_generation_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    return {"status": "ok"}


@router.post("/models/generation/{model_id:path}/toggle")
async def toggle_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    # E-CHK02 fix: db.get() искал по PK (UUID), падал с asyncpg.DataError
    model = await _get_generation_model_by_model_id(model_id, db)
    if model is None:
        raise HTTPException(status_code=404, detail="Generation model not found")
    if model.is_active and model.enabled:
        raise HTTPException(status_code=409, detail="Cannot disable the active generation model")
    try:
        updated = await settings_service.update_generation_model(
            model_id, {"enabled": not model.enabled}, db
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    return updated


@router.post("/models/generation/{model_id:path}/check")
async def check_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    # E-CHK02 fix: db.get() искал по PK (UUID), падал с asyncpg.DataError
    model = await _get_generation_model_by_model_id(model_id, db)
    if model is None:
        raise HTTPException(status_code=404, detail="Generation model not found")
    started = time.perf_counter()
    try:
        api_key = settings_service.decrypt_api_key(model.encrypted_api_key) if model.encrypted_api_key else ""
        if model.provider != "openai_compatible":
            raise ValueError(f"Unsupported provider {model.provider}")
        provider = OpenAICompatibleProvider(
            config=GenerationModelConfig(
                model_id=model.model_id, provider="openai_compatible",
                base_url=model.base_url, api_key_env="",
                enabled=model.enabled, timeout_seconds=model.timeout_seconds,
            ),
            api_key=api_key, max_retries=1,
        )
        # FIX: generate() expects list[dict], not a bare dict.
        # Passing a plain dict caused "messages" to be serialized as a JSON
        # object instead of an array → OpenRouter: 'str' object has no attribute 'get'.
        await provider.generate([{"role": "user", "content": "ping"}])
        return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000), "error": None}
    except Exception as exc:
        return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "error": str(exc)}


@router.put("/models/generation/{model_id:path}")
async def update_generation_model(
    model_id: str, req: GenerationModelUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await settings_service.update_generation_model(model_id, req.model_dump(exclude_unset=True), db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/models/generation/{model_id:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await settings_service.delete_generation_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
