from __future__ import annotations

import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GenerationModelConfig
from app.db.models import Domain, EmbeddingModel, GenerationModel, Vault
from app.db.session import get_db
from app.providers.generation.openai_compatible import OpenAICompatibleProvider
from app.services.domain_service import domain_service
from app.services.settings_service import settings_service


router = APIRouter()
DOMAIN_ID_RE = re.compile(r"^[a-z0-9_]{3,32}$")


class ParamUpdateRequest(BaseModel):
    value: Any = None


class DomainCreateRequest(BaseModel):
    domain_id: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    enabled: bool = True


class DomainUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    enabled: bool | None = None


class PromptUpdateRequest(BaseModel):
    content: str


class ClarificationFieldRequest(BaseModel):
    field_name: str
    label: str
    hint: str | None = None
    required: bool = True
    display_order: int = 0


class GenerationModelCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    provider: str = "openai_compatible"
    display_name: str | None = None
    base_url: str
    api_key: str | None = None
    timeout_seconds: int = 60
    enabled: bool = True


class GenerationModelUpdateRequest(BaseModel):
    provider: str | None = None
    display_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None


@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    try:
        settings_service.get_active_provider()
        has_active_generation_model = True
    except RuntimeError:
        has_active_generation_model = False

    embedding_count = await db.execute(
        select(func.count())
        .select_from(Vault)
        .join(EmbeddingModel, Vault.embedding_model_id == EmbeddingModel.model_id)
        .where(Vault.embedding_model_id.is_not(None), EmbeddingModel.enabled == True)
    )
    vault_count = await db.execute(select(func.count()).select_from(Vault).where(Vault.enabled == True))

    try:
        sidecar_url = await settings_service.get("pdf_sidecar.url", db)
    except KeyError as exc:
        raise HTTPException(status_code=500, detail="pdf_sidecar.url not configured") from exc

    return {
        "has_active_generation_model": has_active_generation_model,
        "has_active_embedding_model": embedding_count.scalar_one() > 0,
        "pdf_sidecar_available": await _check_pdf_sidecar(str(sidecar_url)),
        "has_vaults": vault_count.scalar_one() > 0,
    }


@router.get("/params")
async def get_params(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await settings_service.get_all(db)


@router.put("/params/{key:path}")
async def update_param(key: str, req: ParamUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await settings_service.set(key, req.value, db)
        settings_service.invalidate(key)
        value = await settings_service.get(key, db)
        return {"key": key, "value": value}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Parameter not found") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/params/reset")
async def reset_params(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await settings_service.reset_all(db)
    return {"status": "ok"}


@router.get("/domains")
async def list_domains(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await domain_service.list_domains(db)


@router.post("/domains", status_code=status.HTTP_201_CREATED)
async def create_domain(req: DomainCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if DOMAIN_ID_RE.fullmatch(req.domain_id) is None:
        raise HTTPException(status_code=422, detail="domain_id must match [a-z0-9_]{3,32}")
    try:
        return await domain_service.create_domain(req.model_dump(), db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/domains/{domain_id}")
async def update_domain(domain_id: str, req: DomainUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await domain_service.update_domain(domain_id, req.model_dump(exclude_unset=True), db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(domain_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await domain_service.delete_domain(domain_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/domains/{domain_id}/prompts")
async def get_domain_prompts(domain_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    if await db.get(Domain, domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return {
        prompt_type: await domain_service.get_prompt(domain_id, prompt_type, db)
        for prompt_type in ("system", "clarification", "planner", "pipeline_router")
    }


@router.put("/domains/{domain_id}/prompts/{prompt_type}")
async def update_domain_prompt(
    domain_id: str,
    prompt_type: str,
    req: PromptUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if prompt_type not in {"system", "clarification", "planner", "pipeline_router"}:
        raise HTTPException(status_code=422, detail="Invalid prompt type")
    try:
        await domain_service.update_prompts(domain_id, {prompt_type: req.content}, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc
    return {"status": "ok"}


@router.get("/domains/{domain_id}/fields")
async def get_domain_fields(domain_id: str, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    if await db.get(Domain, domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return await domain_service.get_clarification_fields(domain_id, db)


@router.put("/domains/{domain_id}/fields")
async def update_domain_fields(
    domain_id: str,
    fields: list[ClarificationFieldRequest],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        await domain_service.update_clarification_fields(domain_id, [field.model_dump() for field in fields], db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok"}


@router.get("/generation-models")
async def list_generation_models(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await settings_service.list_generation_models(db)


@router.post("/generation-models", status_code=status.HTTP_201_CREATED)
async def create_generation_model(req: GenerationModelCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if await db.get(GenerationModel, req.model_id) is not None:
        raise HTTPException(status_code=409, detail="Generation model already exists")
    try:
        return await settings_service.create_generation_model(req.model_dump(exclude_none=True), db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/generation-models/{model_id}")
async def update_generation_model(
    model_id: str,
    req: GenerationModelUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await settings_service.update_generation_model(model_id, req.model_dump(exclude_unset=True), db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/generation-models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await settings_service.delete_generation_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/generation-models/{model_id}/activate")
async def activate_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await settings_service.activate_generation_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    return {"status": "ok"}


@router.post("/generation-models/{model_id}/check")
async def check_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    model = await db.get(GenerationModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Generation model not found")
    started = time.perf_counter()
    try:
        api_key = settings_service.decrypt_api_key(model.encrypted_api_key) if model.encrypted_api_key else ""
        if model.provider != "openai_compatible":
            raise ValueError(f"Unsupported provider: {model.provider}")
        provider = OpenAICompatibleProvider(
            config=GenerationModelConfig(
                model_id=model.model_id,
                provider="openai_compatible",
                base_url=model.base_url,
                api_key_env="",
                enabled=model.enabled,
                timeout_seconds=model.timeout_seconds,
            ),
            api_key=api_key,
            max_retries=1,
        )
        await provider.generate([{"role": "user", "content": "ping"}])
        return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000), "error": None}
    except Exception as exc:
        return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "error": str(exc)}


async def _check_pdf_sidecar(base_url: str) -> bool:
    if not base_url:
        return False
    async with httpx.AsyncClient(timeout=2.0) as client:
        for path in ("/health", "/"):
            try:
                response = await client.get(f"{base_url.rstrip('/')}{path}")
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                continue
    return False
