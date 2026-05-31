from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, EmbeddingModel, Pipeline, Vault
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


def campaign_dict(campaign: Campaign) -> dict[str, Any]:
    return {
        "id": str(campaign.id),
        "vault_id": campaign.vault_id,
        "name": campaign.name,
        "description": campaign.description,
        "system_prompt": campaign.system_prompt,
        "last_session_at": campaign.last_session_at,
        "created_at": campaign.created_at,
    }


def pipeline_dict(pipeline: Pipeline) -> dict[str, Any]:
    return {
        "id": str(pipeline.id), "pipeline_id": pipeline.pipeline_id,
        "domain_id": pipeline.domain_id, "version": pipeline.version,
        "name": pipeline.name, "description": pipeline.description,
        "steps": pipeline.steps, "final_composition": pipeline.final_composition,
        "is_active": pipeline.is_active, "created_at": pipeline.created_at,
    }


async def _get_campaign(campaign_id: str, db: AsyncSession) -> Campaign:
    result = await db.get(Campaign, uuid.UUID(campaign_id))
    if result is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return result


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
    final_count = 0

    for step in steps:
        for key in ["order", "type", "name", "system_prompt"]:
            if key not in step:
                raise HTTPException(status_code=422, detail=f"Pipeline step missing key: {key}")
        if not isinstance(step["order"], int) or step["order"] in orders:
            raise HTTPException(status_code=422, detail="Pipeline step order must be unique int")
        orders.add(step["order"])

        step_type = step.get("type")
        if step_type not in ("retrieval", "final"):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid step type: {step_type!r}. Must be 'retrieval' or 'final'",
            )

        if step.get("is_final"):
            final_count += 1
            if step.get("tag_ids"):
                raise HTTPException(status_code=422, detail="Final step must not have tag_ids")

    if final_count != 1:
        raise HTTPException(
            status_code=422,
            detail=f"Pipeline must have exactly one final step (is_final=True), got {final_count}",
        )

    if not isinstance(final_composition, dict) or not isinstance(final_composition.get("system_prompt"), str):
        raise HTTPException(status_code=422, detail="final_composition.system_prompt is required")


def _increment_patch(version: str) -> str:
    try:
        major, minor, patch = (int(part) for part in version.split("."))
    except ValueError:
        return "1.0.1"
    return f"{major}.{minor}.{patch + 1}"
