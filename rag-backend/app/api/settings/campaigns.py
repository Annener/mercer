from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.settings.schemas import CampaignTagCreateRequest
from app.db.models import Campaign, Tag, campaign_tags
from app.db.session import get_db
from shared_contracts.models import CampaignCreate, CampaignRead, CampaignUpdate, TagRead

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=list[CampaignRead])
async def list_campaigns(
    domain_id: str | None = None,
    vault_id: str | None = None,  # deprecated, ignored — campaigns bind to domain, not vault
    db: AsyncSession = Depends(get_db),
) -> list[CampaignRead]:
    # S45-1 fix: vault_id backward-compat branch removed — Campaign.vault_id deleted by 0009
    stmt = select(Campaign).order_by(Campaign.created_at.desc())
    if domain_id:
        stmt = stmt.where(Campaign.domain_id == domain_id)
    result = await db.execute(stmt)
    campaigns = result.scalars().all()
    if not campaigns:
        return []

    # D03 fix: single batch query instead of N+1 _campaign_with_tags calls
    ids = [c.id for c in campaigns]
    tags_result = await db.execute(select(Tag).where(Tag.campaign_id.in_(ids)))
    tags_by_campaign: dict[uuid.UUID, list[TagRead]] = {}
    for t in tags_result.scalars().all():
        tags_by_campaign.setdefault(t.campaign_id, []).append(
            TagRead.model_validate(t, from_attributes=True)
        )
    return [
        _campaign_read(c, tags_by_campaign.get(c.id, []))
        for c in campaigns
    ]


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
    # S46-1 fix: removed vault_id=req.vault_id (field deleted by 0009; CampaignCreate has no vault_id)
    # S46-2 fix: removed hasattr guard — domain_id is required in CampaignCreate
    campaign = Campaign(
        domain_id=req.domain_id,
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
    # S48-1 fix: use exclude_unset so client can explicitly null out nullable fields
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(campaign, field, value)
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


# --- Теги кампании (собственные) ---

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
    payload: CampaignTagCreateRequest,  # D04 fix: was payload: dict — KeyError → 500
    db: AsyncSession = Depends(get_db),
) -> TagRead:
    """\u0428\u043e\u0440\u0442\u043a\u0430\u0442: \u0441\u043e\u0437\u0434\u0430\u0442\u044c \u0442\u0435\u0433 \u043a\u0430\u043c\u043f\u0430\u043d\u0438\u0438. domain_id \u0431\u0435\u0440\u0451\u0442\u0441\u044f \u0438\u0437 \u043a\u0430\u043c\u043f\u0430\u043d\u0438\u0438."""
    campaign = await db.get(Campaign, uuid.UUID(campaign_id))
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    # S51-1 fix: removed vault_id=campaign.vault_id — Campaign and Tag have no vault_id after 0009
    tag = Tag(
        name=payload.name,
        domain_id=campaign.domain_id,
        campaign_id=campaign.id,
        color=payload.color,
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return TagRead.model_validate(tag, from_attributes=True)


# --- Глобальные теги домена, подключённые к кампании ---

@router.get("/{campaign_id}/global-tags", response_model=list[TagRead])
async def get_campaign_global_tags(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[TagRead]:
    """\u0412\u0435\u0440\u043d\u0443\u0442\u044c \u0433\u043b\u043e\u0431\u0430\u043b\u044c\u043d\u044b\u0435 \u0442\u0435\u0433\u0438 \u0434\u043e\u043c\u0435\u043d\u0430, \u044f\u0432\u043d\u043e \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0451\u043d\u043d\u044b\u0435 \u043a \u044d\u0442\u043e\u0439 \u043a\u0430\u043c\u043f\u0430\u043d\u0438\u0438."""
    camp_uuid = uuid.UUID(campaign_id)
    stmt = (
        select(Tag)
        .join(campaign_tags, campaign_tags.c.tag_id == Tag.id)
        .where(
            campaign_tags.c.campaign_id == camp_uuid,
            Tag.campaign_id.is_(None),
        )
    )
    result = await db.execute(stmt)
    return [TagRead.model_validate(t, from_attributes=True) for t in result.scalars().all()]


@router.post("/{campaign_id}/global-tags/{tag_id}", response_model=TagRead, status_code=201)
async def link_global_tag(
    campaign_id: str,
    tag_id: str,
    db: AsyncSession = Depends(get_db),
) -> TagRead:
    """\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0433\u043b\u043e\u0431\u0430\u043b\u044c\u043d\u044b\u0439 \u0442\u0435\u0433 \u0434\u043e\u043c\u0435\u043d\u0430 \u043a \u043a\u0430\u043c\u043f\u0430\u043d\u0438\u0438."""
    camp_uuid = uuid.UUID(campaign_id)
    tag_uuid = uuid.UUID(tag_id)

    campaign = await db.get(Campaign, camp_uuid)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    tag = await db.get(Tag, tag_uuid)
    if not tag:
        raise HTTPException(404, "Tag not found")
    if tag.campaign_id is not None:
        raise HTTPException(400, "Tag is not a global domain tag (has campaign_id set)")
    if tag.domain_id != campaign.domain_id:
        raise HTTPException(400, "Tag does not belong to the same domain as campaign")

    existing = await db.execute(
        select(campaign_tags).where(
            campaign_tags.c.campaign_id == camp_uuid,
            campaign_tags.c.tag_id == tag_uuid,
        )
    )
    if existing.first() is not None:
        return TagRead.model_validate(tag, from_attributes=True)

    await db.execute(
        insert(campaign_tags).values(campaign_id=camp_uuid, tag_id=tag_uuid)
    )
    await db.commit()
    return TagRead.model_validate(tag, from_attributes=True)


@router.delete("/{campaign_id}/global-tags/{tag_id}", status_code=204)
async def unlink_global_tag(
    campaign_id: str,
    tag_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """\u041e\u0442\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0433\u043b\u043e\u0431\u0430\u043b\u044c\u043d\u044b\u0439 \u0442\u0435\u0433 \u043e\u0442 \u043a\u0430\u043c\u043f\u0430\u043d\u0438\u0438 (\u0442\u0435\u0433 \u043d\u0435 \u0443\u0434\u0430\u043b\u044f\u0435\u0442\u0441\u044f, \u0442\u043e\u043b\u044c\u043a\u043e \u0441\u0432\u044f\u0437\u044c)."""
    camp_uuid = uuid.UUID(campaign_id)
    tag_uuid = uuid.UUID(tag_id)
    await db.execute(
        delete(campaign_tags).where(
            campaign_tags.c.campaign_id == camp_uuid,
            campaign_tags.c.tag_id == tag_uuid,
        )
    )
    await db.commit()


# --- Вспомогательные ---

async def _campaign_with_tags(campaign: Campaign, db: AsyncSession) -> CampaignRead:
    """\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442\u0441\u044f \u0434\u043b\u044f \u043e\u0434\u0438\u043d\u043e\u0447\u043d\u044b\u0445 \u043e\u0431\u044a\u0435\u043a\u0442\u043e\u0432 (get/create/update). \u0414\u043b\u044f \u0441\u043f\u0438\u0441\u043a\u0430 — batch \u0432 list_campaigns."""
    stmt = select(Tag).where(Tag.campaign_id == campaign.id)
    result = await db.execute(stmt)
    tags = [TagRead.model_validate(t, from_attributes=True) for t in result.scalars().all()]
    return _campaign_read(campaign, tags)


def _campaign_read(campaign: Campaign, tags: list[TagRead]) -> CampaignRead:
    data = CampaignRead.model_validate(campaign, from_attributes=True)
    data.tags = tags
    return data
