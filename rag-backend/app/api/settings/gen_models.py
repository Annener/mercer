from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GenerationModelConfig
from app.db.models import GenerationModel
from app.db.session import get_db
from app.providers.generation.openai_compatible import OpenAICompatibleProvider
from app.services.settings_service import settings_service
from .schemas import GenerationModelCreateRequest, GenerationModelUpdateRequest

router = APIRouter()


@router.get("/models/generation")
async def list_generation_models(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await settings_service.list_generation_models(db)


@router.post("/models/generation", status_code=status.HTTP_201_CREATED)
async def create_generation_model(req: GenerationModelCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if await db.get(GenerationModel, req.model_id) is not None:
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


@router.post("/models/generation/{model_id:path}/check")
async def check_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    model = await db.get(GenerationModel, model_id)
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
        await provider.generate({"role": "user", "content": "ping"})
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