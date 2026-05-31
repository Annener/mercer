from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tag
from app.db.session import get_db
from shared_contracts.models import TagCreate, TagRead, TagUpdate, TagsGrouped

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=TagsGrouped)
async def list_tags(
    domain_id: str | None = None,
    vault_id: str | None = None,  # deprecated — kept for backward compat URL params only
    campaign_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> TagsGrouped:
    """
    Возвращает теги домена, сгруппированные для UI.
    Приоритет: domain_id > vault_id (устаревший, всегда возвращает пустой результат — Tag.vault_id удалён).
    Если campaign_id задан — возвращает только глобальные + теги этой кампании.
    """
    if domain_id:
        base_filter = Tag.domain_id == domain_id
    elif vault_id:
        # vault_id больше не поддерживается на уровне ORM (поле удалено из Tag).
        # Возвращаем пустой результат, чтобы не падать с AttributeError.
        logger.warning(
            "list_tags called with vault_id=%s — vault_id is deprecated and ignored. "
            "Pass domain_id instead.",
            vault_id,
        )
        return TagsGrouped(global_tags=[], by_campaign={})
    else:
        return TagsGrouped(global_tags=[], by_campaign={})

    if campaign_id:
        stmt = select(Tag).where(
            base_filter,
            or_(Tag.campaign_id.is_(None), Tag.campaign_id == uuid.UUID(campaign_id)),
        )
    else:
        stmt = select(Tag).where(base_filter)

    result = await db.execute(stmt)
    tags = result.scalars().all()

    global_tags = [TagRead.model_validate(t, from_attributes=True) for t in tags if t.campaign_id is None]
    by_campaign: dict[str, list[TagRead]] = {}
    for t in tags:
        if t.campaign_id is not None:
            key = str(t.campaign_id)
            by_campaign.setdefault(key, []).append(TagRead.model_validate(t, from_attributes=True))

    return TagsGrouped(global_tags=global_tags, by_campaign=by_campaign)


@router.post("", response_model=TagRead, status_code=201)
async def create_tag(req: TagCreate, db: AsyncSession = Depends(get_db)) -> TagRead:
    """
    Создаёт тег, привязанный к домену.
    TagCreate требует domain_id (обязательное поле).
    Tag ORM не имеет поля vault_id — оно было удалено в процессе рефакторинга.
    """
    if not req.domain_id:
        raise HTTPException(400, "domain_id is required to create a tag")

    tag = Tag(
        name=req.name,
        domain_id=req.domain_id,
        campaign_id=uuid.UUID(req.campaign_id) if req.campaign_id else None,
        color=req.color,
    )
    db.add(tag)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, f"Tag with name '{req.name}' already exists in this domain")
    await db.refresh(tag)
    return TagRead.model_validate(tag, from_attributes=True)


@router.put("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: str,
    req: TagUpdate,
    db: AsyncSession = Depends(get_db),
) -> TagRead:
    tag = await db.get(Tag, uuid.UUID(tag_id))
    if not tag:
        raise HTTPException(404, "Tag not found")
    if req.name is not None:
        tag.name = req.name
    if req.color is not None:
        tag.color = req.color
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, f"Tag with name '{req.name}' already exists in this domain")
    await db.refresh(tag)
    return TagRead.model_validate(tag, from_attributes=True)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: str, db: AsyncSession = Depends(get_db)) -> None:
    tag = await db.get(Tag, uuid.UUID(tag_id))
    if not tag:
        raise HTTPException(404, "Tag not found")
    await db.delete(tag)
    await db.commit()
