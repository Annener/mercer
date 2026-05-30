from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, Vault, World
from app.db.session import get_db
from .helpers import _get_world_by_slug, _get_campaign, world_dict, campaign_dict
from .schemas import (
    CampaignCreateRequest, CampaignUpdateRequest,
    WorldCreateRequest, WorldUpdateRequest,
)

router = APIRouter()
SLUG_RE = re.compile(r"^[a-z0-9-]{3,64}$")


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


@router.delete("/worlds/{world_id}", status_code=204)
async def delete_world(world_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    world = await _get_world_by_slug(world_id, db)
    await db.execute(delete(Campaign).where(Campaign.world_id == world_id))
    await db.delete(world)
    await db.commit()
    return Response(status_code=204)


@router.post("/worlds/{world_id}/toggle")
async def toggle_world(world_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    world = await _get_world_by_slug(world_id, db)
    world.is_active = not world.is_active
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
    if "path_prefix" in payload and (
        not payload["path_prefix"].startswith(world.path_prefix) or not payload["path_prefix"].endswith("/")
    ):
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