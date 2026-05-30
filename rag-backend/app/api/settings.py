from __future__ import annotations

import logging
import re
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GenerationModelConfig
from app.db.models import Campaign, Domain, EmbeddingModel, GenerationModel, Pipeline, Vault, World
from app.db.session import get_db
from app.providers.generation.openai_compatible import OpenAICompatibleProvider
from app.services.domain_service import domain_service
from app.services.settings_service import settings_service

logger = logging.getLogger(__name__)
router = APIRouter()

DOMAIN_ID_RE = re.compile(r"^[a-z0-9_]{3,32}$")
SLUG_RE = re.compile(r"^[a-z0-9\-]{3,64}$")
STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")


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
    base_url: str = ""
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

class EmbeddingModelCreateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    provider: str
    display_name: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    dimensions: int = Field(gt=0)
    timeout_seconds: int = 30
    max_retries: int = 3
    enabled: bool = True

class EmbeddingModelUpdateRequest(BaseModel):
    provider: str | None = None
    display_name: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    timeout_seconds: int | None = None
    max_retries: int | None = None
    enabled: bool | None = None

class VaultCreateRequest(BaseModel):
    vault_id: str
    domain_id: str
    display_name: str | None = None
    embedding_model_id: str | None = None
    create_folder: bool = False

class VaultUpdateRequest(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    embedding_model_id: str | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None

class WorldCreateRequest(BaseModel):
    world_id: str
    vault_id: str
    name: str
    description: str | None = None
    path_prefix: str
    is_active: bool = True

class WorldUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    path_prefix: str | None = None
    is_active: bool | None = None

class CampaignCreateRequest(BaseModel):
    campaign_id: str
    name: str
    description: str | None = None
    path_prefix: str
    is_active: bool = True

class CampaignUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    path_prefix: str | None = None
    is_active: bool | None = None

class PipelineCreateRequest(BaseModel):
    pipeline_id: str
    domain_id: str
    name: str
    description: str | None = None
    steps: list[dict[str, Any]]
    final_composition: dict[str, Any]
    is_active: bool = True

class PipelineUpdateRequest(BaseModel):
    domain_id: str | None = None
    name: str | None = None
    description: str | None = None
    steps: list[dict[str, Any]] | None = None
    final_composition: dict[str, Any] | None = None
    is_active: bool | None = None


# --- Status ---

@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    has_active_generation_model = settings_service.get_active_provider() is not None
    embedding_count = await db.execute(
        select(func.count()).select_from(Vault)
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


# --- Params ---

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

@router.post("/reset")
async def reset_params(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await settings_service.reset_all(db)
    return {"status": "ok"}


# --- Domains ---

@router.get("/domains")
async def list_domains(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    domains = await domain_service.list_domains(db)
    for d in domains:
        if not d.get("enabled"):
            stmt = (
                select(func.count()).select_from(Vault)
                .where(Vault.domain_id == d["domain_id"], Vault.enabled == True)
            )
            result = await db.execute(stmt)
            if result.scalar_one() > 0:
                d["enabled"] = True
                try:
                    await domain_service.update_domain(d["domain_id"], {"enabled": True}, db)
                except Exception:
                    pass
    return domains

@router.post("/domains", status_code=status.HTTP_201_CREATED)
async def create_domain(req: DomainCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if DOMAIN_ID_RE.fullmatch(req.domain_id) is None:
        raise HTTPException(status_code=422, detail="domain_id must match [a-z0-9_]{3,32}")
    try:
        return await domain_service.create_domain(req.model_dump(), db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

# !! ИСПРАВЛЕНИЕ: убран :path — он захватывал /prompts и /fields как часть domain_id
@router.get("/domains/{domain_id}")
async def get_domain(domain_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    domain = await db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return {
        "domain_id": domain.domain_id,
        "display_name": domain.display_name,
        "description": domain.description,
        "enabled": domain.enabled,
        "is_system": domain.is_system,
    }

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

# !! ИСПРАВЛЕНИЕ: было /domains/{domain_id:path}/prompts → domain_id="dnd/prompts" → 404
@router.get("/domains/{domain_id}/prompts")
async def get_domain_prompts(domain_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    if await db.get(Domain, domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return {
        prompt_type: await domain_service.get_prompt(domain_id, prompt_type, db)
        for prompt_type in ["system", "clarification", "planner", "pipeline_router"]
    }

@router.put("/domains/{domain_id}/prompts/{prompt_type}")
async def update_domain_prompt(
    domain_id: str, prompt_type: str, req: PromptUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if prompt_type not in ["system", "clarification", "planner", "pipeline_router"]:
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
    domain_id: str, fields: list[ClarificationFieldRequest], db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        await domain_service.update_clarification_fields(
            domain_id, [field.model_dump() for field in fields], db
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok"}


# --- Generation Models ---

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

@router.put("/models/generation/{model_id}")
async def update_generation_model(
    model_id: str, req: GenerationModelUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await settings_service.update_generation_model(model_id, req.model_dump(exclude_unset=True), db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.delete("/models/generation/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await settings_service.delete_generation_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/models/generation/{model_id}/activate")
async def activate_generation_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await settings_service.activate_generation_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Generation model not found") from exc
    return {"status": "ok"}

@router.post("/models/generation/{model_id}/check")
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


# --- Embedding Models ---

@router.get("/models/embedding")
async def list_embedding_models(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await settings_service.list_embedding_models(db)

@router.post("/models/embedding", status_code=status.HTTP_201_CREATED)
async def create_embedding_model(req: EmbeddingModelCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if req.provider not in ["ollama", "openai_compatible"]:
        raise HTTPException(status_code=422, detail="Unsupported embedding provider")
    if await db.get(EmbeddingModel, req.model_id) is not None:
        raise HTTPException(status_code=409, detail="Embedding model already exists")
    return await settings_service.create_embedding_model(req.model_dump(exclude_none=True), db)

@router.put("/models/embedding/{model_id}")
async def update_embedding_model(
    model_id: str, req: EmbeddingModelUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    payload = req.model_dump(exclude_unset=True)
    if payload.get("provider") is not None and payload["provider"] not in ["ollama", "openai_compatible"]:
        raise HTTPException(status_code=422, detail="Unsupported embedding provider")
    try:
        return await settings_service.update_embedding_model(model_id, payload, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Embedding model not found") from exc

@router.delete("/models/embedding/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_embedding_model(model_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    result = await db.execute(select(func.count()).select_from(Vault).where(Vault.embedding_model_id == model_id))
    if result.scalar_one() > 0:
        raise HTTPException(status_code=409, detail="Model is used by existing vaults")
    try:
        await settings_service.delete_embedding_model(model_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Embedding model not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/models/embedding/{model_id}/check")
async def check_embedding_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    model = await db.get(EmbeddingModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Embedding model not found")
    started = time.perf_counter()
    try:
        vector = await _check_embedding_provider(model)
        return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000), "dimensions": len(vector), "error": None}
    except Exception as exc:
        return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "dimensions": None, "error": str(exc)}


# --- Vaults ---

@router.get("/vaults")
async def list_vaults(
    domain_id: str | None = Query(default=None, description="Фильтр по домену"),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(Vault).order_by(Vault.vault_id)
    if domain_id:
        stmt = stmt.where(Vault.domain_id == domain_id)
    result = await db.execute(stmt)
    return [vault_dict(vault) for vault in result.scalars().all()]

@router.post("/vaults", status_code=status.HTTP_201_CREATED)
async def create_vault(req: VaultCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if SLUG_RE.fullmatch(req.vault_id) is None:
        raise HTTPException(status_code=422, detail="vault_id must be a slug with 3-64 characters")
    if await db.get(Domain, req.domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    if req.embedding_model_id and await db.get(EmbeddingModel, req.embedding_model_id) is None:
        raise HTTPException(status_code=404, detail="Embedding model not found")
    if await db.get(Vault, req.vault_id) is not None:
        raise HTTPException(status_code=409, detail="Vault already exists")
    vault_path = f"/data/vaults/{req.vault_id}"
    try:
        os.makedirs(vault_path, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create vault directory: {exc}") from exc
    vault = Vault(
        vault_id=req.vault_id, domain_id=req.domain_id, display_name=req.display_name,
        embedding_model_id=req.embedding_model_id, binding_status="unbound", chunk_count=0,
    )
    db.add(vault)
    await db.commit()
    await db.refresh(vault)
    return vault_dict(vault)

@router.put("/vaults/{vault_id}")
async def update_vault(vault_id: str, req: VaultUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    vault = await db.get(Vault, vault_id)
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    payload = req.model_dump(exclude_unset=True)
    new_embedding_model_id = payload.get("embedding_model_id")
    if new_embedding_model_id and await db.get(EmbeddingModel, new_embedding_model_id) is None:
        raise HTTPException(status_code=404, detail="Embedding model not found")
    embedding_changed = "embedding_model_id" in payload and payload["embedding_model_id"] != vault.embedding_model_id
    chunking_changed = any(key in payload and payload[key] != getattr(vault, key) for key in ["chunk_size", "overlap", "entity_aware_mode"])
    try:
        async with db.begin_nested():
            if embedding_changed:
                await _delete_vault_vectors(vault_id, strict=True)
                vault.binding_status = "unbound"
                vault.chunk_count = 0
            elif chunking_changed:
                vault.binding_status = "unbound"
            for key, value in payload.items():
                setattr(vault, key, value)
        await db.commit()
    except httpx.HTTPError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Failed to clear vault vectors: {exc}") from exc
    await db.refresh(vault)
    return vault_dict(vault)

@router.delete("/vaults/{vault_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vault(vault_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    vault = await db.get(Vault, vault_id)
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    try:
        await _delete_vault_vectors(vault_id, strict=False)
    finally:
        await db.execute(delete(Campaign).where(Campaign.vault_id == vault_id))
        await db.execute(delete(World).where(World.vault_id == vault_id))
        await db.delete(vault)
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/vaults/{vault_id}/toggle")
async def toggle_vault(vault_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    vault = await db.get(Vault, vault_id)
    if vault is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    vault.enabled = not vault.enabled
    await db.commit()
    await db.refresh(vault)
    return vault_dict(vault)


# --- Worlds ---

@router.get("/worlds")
async def list_worlds(vault_id: str | None = None, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    stmt = select(World).order_by(World.name)
    if vault_id:
        stmt = stmt.where(World.vault_id == vault_id)
    result = await db.execute(stmt)
    return [world_dict(world) for world in result.scalars().all()]

@router.post("/worlds", status_code=status.HTTP_201_CREATED)
async def create_world(req: WorldCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if SLUG_RE.fullmatch(req.world_id) is None:
        raise HTTPException(status_code=422, detail="world_id must be a slug with 3-64 characters")
    if not req.path_prefix.endswith("/"):
        raise HTTPException(status_code=422, detail="path_prefix must end with /")
    if await db.get(Vault, req.vault_id) is None:
        raise HTTPException(status_code=404, detail="Vault not found")
    duplicate = await db.execute(select(World).where(World.world_id == req.world_id, World.vault_id == req.vault_id))
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="World already exists for vault")
    world = World(**req.model_dump())
    db.add(world)
    await db.commit()
    await db.refresh(world)
    return world_dict(world)

@router.put("/worlds/{world_id}")
async def update_world(world_id: str, req: WorldUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    world = await _get_world_by_slug(world_id, db)
    payload = req.model_dump(exclude_unset=True)
    if "path_prefix" in payload and not payload["path_prefix"].endswith("/"):
        raise HTTPException(status_code=422, detail="path_prefix must end with /")
    for key, value in payload.items():
        setattr(world, key, value)
    await db.commit()
    await db.refresh(world)
    return world_dict(world)

@router.get("/worlds/{world_id}/campaigns")
async def list_campaigns(world_id: str, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    result = await db.execute(select(Campaign).where(Campaign.world_id == world_id).order_by(Campaign.name))
    return [campaign_dict(campaign) for campaign in result.scalars().all()]

@router.post("/worlds/{world_id}/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(world_id: str, req: CampaignCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    world = await _get_world_by_slug(world_id, db)
    if SLUG_RE.fullmatch(req.campaign_id) is None:
        raise HTTPException(status_code=422, detail="campaign_id must be a slug with 3-64 characters")
    if not req.path_prefix.startswith(world.path_prefix) or not req.path_prefix.endswith("/"):
        raise HTTPException(status_code=422, detail="campaign pathprefix must be inside world pathprefix and end with /")
    duplicate = await db.execute(select(Campaign).where(Campaign.campaign_id == req.campaign_id, Campaign.world_id == world_id))
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Campaign already exists for world")
    campaign = Campaign(world_id=world_id, vault_id=world.vault_id, **req.model_dump())
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign_dict(campaign)

@router.put("/worlds/{world_id}/campaigns/{campaign_id}")
async def update_campaign(
    world_id: str, campaign_id: str, req: CampaignUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    world = await _get_world_by_slug(world_id, db)
    campaign = await _get_campaign(world_id, campaign_id, db)
    payload = req.model_dump(exclude_unset=True)
    if "path_prefix" in payload and (not payload["path_prefix"].startswith(world.path_prefix) or not payload["path_prefix"].endswith("/")):
        raise HTTPException(status_code=422, detail="campaign pathprefix must be inside world pathprefix and end with /")
    for key, value in payload.items():
        setattr(campaign, key, value)
    await db.commit()
    await db.refresh(campaign)
    return campaign_dict(campaign)

@router.post("/worlds/{world_id}/campaigns/{campaign_id}/toggle")
async def toggle_campaign(world_id: str, campaign_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    campaign = await _get_campaign(world_id, campaign_id, db)
    campaign.is_active = not campaign.is_active
    await db.commit()
    await db.refresh(campaign)
    return campaign_dict(campaign)


# --- Pipelines ---

@router.get("/pipelines")
async def list_pipelines(domain_id: str | None = None, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    stmt = select(Pipeline).order_by(Pipeline.pipeline_id, Pipeline.version)
    if domain_id:
        stmt = stmt.where(Pipeline.domain_id == domain_id)
    result = await db.execute(stmt)
    return [pipeline_dict(pipeline) for pipeline in result.scalars().all()]

@router.post("/pipelines", status_code=status.HTTP_201_CREATED)
async def create_pipeline(req: PipelineCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if SLUG_RE.fullmatch(req.pipeline_id) is None:
        raise HTTPException(status_code=422, detail="pipeline_id must be a slug with 3-64 characters")
    if await db.get(Domain, req.domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    _validate_pipeline_json(req.steps, req.final_composition)
    duplicate = await db.execute(select(Pipeline).where(Pipeline.pipeline_id == req.pipeline_id, Pipeline.version == "1.0.0"))
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Pipeline version already exists")
    pipeline = Pipeline(**req.model_dump(), version="1.0.0")
    db.add(pipeline)
    await db.commit()
    await db.refresh(pipeline)
    return pipeline_dict(pipeline)

@router.put("/pipelines/{pipeline_uuid}")
async def update_pipeline(
    pipeline_uuid: str, req: PipelineUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    pipeline = await _get_pipeline_by_uuid(pipeline_uuid, db)
    payload = req.model_dump(exclude_unset=True)
    steps = payload.get("steps", pipeline.steps)
    final_composition = payload.get("final_composition", pipeline.final_composition)
    _validate_pipeline_json(steps, final_composition)
    new_version = _increment_patch(pipeline.version)
    await db.execute(update(Pipeline).where(Pipeline.pipeline_id == pipeline.pipeline_id).values(is_active=False))
    new_pipeline = Pipeline(
        pipeline_id=pipeline.pipeline_id,
        domain_id=payload.get("domain_id", pipeline.domain_id),
        version=new_version,
        name=payload.get("name", pipeline.name),
        description=payload.get("description", pipeline.description),
        steps=steps,
        final_composition=final_composition,
        is_active=payload.get("is_active", True),
    )
    db.add(new_pipeline)
    await db.commit()
    await db.refresh(new_pipeline)
    return pipeline_dict(new_pipeline)

@router.delete("/pipelines/{pipeline_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(pipeline_uuid: str, db: AsyncSession = Depends(get_db)) -> Response:
    pipeline = await _get_pipeline_by_uuid(pipeline_uuid, db)
    pipeline.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/pipelines/{pipeline_uuid}/activate")
async def activate_pipeline(pipeline_uuid: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    pipeline = await _get_pipeline_by_uuid(pipeline_uuid, db)
    await db.execute(update(Pipeline).where(Pipeline.pipeline_id == pipeline.pipeline_id).values(is_active=False))
    pipeline.is_active = True
    await db.commit()
    return {"status": "ok"}


# --- Helpers ---

async def _check_pdf_sidecar(base_url: str) -> bool:
    if not base_url:
        return False
    async with httpx.AsyncClient(timeout=2.0) as client:
        for path in ["/health", "/"]:
            try:
                response = await client.get(f"{base_url.rstrip('/')}{path}")
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                continue
    return False

async def _check_embedding_provider(model: EmbeddingModel) -> list[float]:
    if model.provider == "ollama":
        async with httpx.AsyncClient(timeout=model.timeout_seconds) as client:
            response = await client.post(
                f"{model.base_url.rstrip('/')}/api/embeddings",
                json={"model": model.model_name, "prompt": "test"},
            )
    elif model.provider == "openai_compatible":
        api_key = settings_service.decrypt_api_key(model.encrypted_api_key) if model.encrypted_api_key else ""
        async with httpx.AsyncClient(timeout=model.timeout_seconds, headers={"Authorization": f"Bearer {api_key}"}) as client:
            response = await client.post(
                f"{model.base_url.rstrip('/')}/embeddings",
                json={"model": model.model_name, "input": "test"},
            )
    else:
        raise ValueError(f"Unsupported embedding provider: {model.provider}")
    response.raise_for_status()
    payload = response.json()
    vector = payload.get("embedding")
    if vector is None:
        data = payload.get("data")
        vector = data[0].get("embedding") if isinstance(data, list) and data else None
    if not isinstance(vector, list):
        raise ValueError("Provider returned no embedding vector")
    return [float(value) for value in vector]

async def _delete_vault_vectors(vault_id: str, *, strict: bool) -> None:
    try:
        async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=30) as client:
            response = await client.delete(f"/index/vault/{vault_id}")
            response.raise_for_status()
    except httpx.HTTPError:
        if strict:
            raise

def vault_dict(vault: Vault) -> dict[str, Any]:
    return {
        "vault_id": vault.vault_id, "domain_id": vault.domain_id,
        "display_name": vault.display_name, "enabled": vault.enabled,
        "embedding_model_id": vault.embedding_model_id,
        "expected_dimensions": vault.expected_dimensions,
        "chunk_size": vault.chunk_size, "overlap": vault.overlap,
        "entity_aware_mode": vault.entity_aware_mode,
        "binding_status": vault.binding_status, "chunk_count": vault.chunk_count,
        "created_at": vault.created_at, "updated_at": vault.updated_at,
    }

def world_dict(world: World) -> dict[str, Any]:
    return {
        "id": str(world.id), "world_id": world.world_id, "vault_id": world.vault_id,
        "name": world.name, "description": world.description, "path_prefix": world.path_prefix,
        "is_active": world.is_active, "created_at": world.created_at, "updated_at": world.updated_at,
    }

def campaign_dict(campaign: Campaign) -> dict[str, Any]:
    return {
        "id": str(campaign.id), "campaign_id": campaign.campaign_id,
        "world_id": campaign.world_id, "vault_id": campaign.vault_id,
        "name": campaign.name, "description": campaign.description,
        "path_prefix": campaign.path_prefix, "is_active": campaign.is_active,
        "created_at": campaign.created_at, "updated_at": campaign.updated_at,
    }

def pipeline_dict(pipeline: Pipeline) -> dict[str, Any]:
    return {
        "id": str(pipeline.id), "pipeline_id": pipeline.pipeline_id,
        "domain_id": pipeline.domain_id, "version": pipeline.version,
        "name": pipeline.name, "description": pipeline.description,
        "steps": pipeline.steps, "final_composition": pipeline.final_composition,
        "is_active": pipeline.is_active, "created_at": pipeline.created_at,
    }

async def _get_world_by_slug(world_id: str, db: AsyncSession) -> World:
    result = await db.execute(select(World).where(World.world_id == world_id))
    world = result.scalar_one_or_none()
    if world is None:
        raise HTTPException(status_code=404, detail="World not found")
    return world

async def _get_campaign(world_id: str, campaign_id: str, db: AsyncSession) -> Campaign:
    result = await db.execute(select(Campaign).where(Campaign.world_id == world_id, Campaign.campaign_id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign

async def _get_pipeline_by_uuid(pipeline_uuid: str, db: AsyncSession) -> Pipeline:
    try:
        parsed = uuid.UUID(pipeline_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid pipeline UUID") from exc
    pipeline = await db.get(Pipeline, parsed)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline

def _validate_pipeline_json(steps: list[dict[str, Any]], final_composition: dict[str, Any]) -> None:
    if not isinstance(steps, list) or not steps:
        raise HTTPException(status_code=422, detail="steps must be a non-empty list")
    orders: set[int] = set()
    for step in steps:
        for key in ["order", "type", "name", "role", "system_prompt"]:
            if key not in step:
                raise HTTPException(status_code=422, detail=f"Pipeline step missing key: {key}")
        if not isinstance(step["order"], int) or step["order"] in orders:
            raise HTTPException(status_code=422, detail="Pipeline step order must be unique int")
        orders.add(step["order"])
        if step["type"] == "book" and not step.get("document_ids"):
            raise HTTPException(status_code=422, detail="book step requires document_ids")
        if step["type"] == "world" and not step.get("world_id"):
            raise HTTPException(status_code=422, detail="world step requires world_id")
        if step["type"] == "campaign" and not step.get("campaign_id"):
            raise HTTPException(status_code=422, detail="campaign step requires campaign_id")
        if step["type"] not in ["book", "world", "campaign"]:
            raise HTTPException(status_code=422, detail="Invalid pipeline step type")
    if not isinstance(final_composition, dict) or not isinstance(final_composition.get("system_prompt"), str):
        raise HTTPException(status_code=422, detail="final_composition.system_prompt is required")

def _increment_patch(version: str) -> str:
    try:
        major, minor, patch = (int(part) for part in version.split("."))
    except ValueError:
        return "1.0.1"
    return f"{major}.{minor}.{patch + 1}"