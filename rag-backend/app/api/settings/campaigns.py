from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, Tag
from app.db.session import get_db
from shared_contracts.models import CampaignCreate, CampaignRead, CampaignUpdate, TagRead

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=list[CampaignRead])
async def list_campaigns(
    vault_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[CampaignRead]:
    stmt = select(Campaign).order_by(Campaign.created_at.desc())
    if vault_id:
        stmt = stmt.where(Campaign.vault_id == vault_id)
    result = await db.execute(stmt)
    campaigns = result.scalars().all()
    return [await _campaign_with_tags(c, db) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignRead)
async def get_campaign(campaign_id: str, db: AsyncSession = Depends(get_db)) -> CampaignRead:
    campaign = await db.get(Campaign, uuid.UUID(campaign_id))
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return await _campaign_with_tags(campaign, db)


@router.post("", response_model=CampaignRead, status_code=201)
async def create_campaign(
    req: CampaignCreate,
    db: AsyncSession = Depends(get_db),
) -> CampaignRead:
    campaign = Campaign(
        vault_id=req.vault_id,
        name=req.name,
        description=req.description,
        system_prompt=req.system_prompt,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return await _campaign_with_tags(campaign, db)


@router.put("/{campaign_id}", response_model=CampaignRead)
async def update_campaign(
    campaign_id: str,
    req: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
) -> CampaignRead:
    campaign = await db.get(Campaign, uuid.UUID(campaign_id))
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    if req.name is not None:
        campaign.name = req.name
    if req.description is not None:
        campaign.description = req.description
    if req.system_prompt is not None:
        campaign.system_prompt = req.system_prompt
    await db.commit()
    await db.refresh(campaign)
    return await _campaign_with_tags(campaign, db)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, db: AsyncSession = Depends(get_db)) -> None:
    campaign = await db.get(Campaign, uuid.UUID(campaign_id))
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    await db.delete(campaign)
    await db.commit()


# --- Теги кампании ---

@router.get("/{campaign_id}/tags", response_model=list[TagRead])
async def get_campaign_tags(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[TagRead]:
    stmt = select(Tag).where(Tag.campaign_id == uuid.UUID(campaign_id))
    result = await db.execute(stmt)
    return [TagRead.model_validate(t, from_attributes=True) for t in result.scalars().all()]


@router.post("/{campaign_id}/tags", response_model=TagRead, status_code=201)
async def create_campaign_tag(
    campaign_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> TagRead:
    """Шорткат: создать тег кампании. vault_id берётся из кампании."""
    campaign = await db.get(Campaign, uuid.UUID(campaign_id))
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    tag = Tag(
        name=payload["name"],
        vault_id=campaign.vault_id,
        campaign_id=campaign.id,
        color=payload.get("color"),
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return TagRead.model_validate(tag, from_attributes=True)


# --- Вспомогательные ---

async def _campaign_with_tags(campaign: Campaign, db: AsyncSession) -> CampaignRead:
    stmt = select(Tag).where(Tag.campaign_id == campaign.id)
    result = await db.execute(stmt)
    tags = [TagRead.model_validate(t, from_attributes=True) for t in result.scalars().all()]
    data = CampaignRead.model_validate(campaign, from_attributes=True)
    data.tags = tags
    return data
