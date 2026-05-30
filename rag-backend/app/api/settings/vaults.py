from __future__ import annotations

import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, Domain, EmbeddingModel, Vault, World
from app.db.session import get_db
from .helpers import _delete_vault_vectors, vault_dict
from .schemas import VaultCreateRequest, VaultUpdateRequest

router = APIRouter()
SLUG_RE = re.compile(r"^[a-z0-9-]{3,64}$")


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
    chunking_changed = any(
        key in payload and payload[key] != getattr(vault, key)
        for key in ["chunk_size", "overlap", "entity_aware_mode"]
    )

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