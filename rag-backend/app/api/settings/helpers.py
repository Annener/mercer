from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, EmbeddingModel, Pipeline, Vault, World
from app.services.settings_service import settings_service

STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")


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