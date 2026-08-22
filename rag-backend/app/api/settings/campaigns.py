from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.settings.schemas import CampaignTagCreateRequest
from app.db.models import Campaign, Tag, campaign_tags
from app.db.session import get_db
from app.services.campaign_state_service import (
    CampaignStateFieldError,
    campaign_state_field_service,
)
from app.services.campaign_state_value_service import (
    CampaignStateValueError,
    campaign_state_value_service,
)
from shared_contracts.models import (
    CampaignCreate,
    CampaignRead,
    CampaignStateFieldConfigCreate,
    CampaignStateFieldConfigRead,
    CampaignStateFieldConfigReorderRequest,
    CampaignStateFieldConfigUpdate,
    CampaignStatePatchRequest,
    CampaignStatePatchResponse,
    CampaignStateVersionRead,
    CampaignStateVersionSummary,
    CampaignUpdate,
    TagRead,
)

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
    """Шорткат: создать тег кампании. domain_id берётся из кампании."""
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
    """Вернуть глобальные теги домена, явно подключённые к этой кампании."""
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
    """Подключить глобальный тег домена к кампании."""
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
    """Отключить глобальный тег от кампании (тег не удаляется, только связь)."""
    camp_uuid = uuid.UUID(campaign_id)
    tag_uuid = uuid.UUID(tag_id)
    await db.execute(
        delete(campaign_tags).where(
            campaign_tags.c.campaign_id == camp_uuid,
            campaign_tags.c.tag_id == tag_uuid,
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Campaign State field configuration (Stage 1)
# ---------------------------------------------------------------------------

@router.get(
    "/{campaign_id}/state-fields",
    response_model=list[CampaignStateFieldConfigRead],
)
async def list_campaign_state_fields(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[CampaignStateFieldConfigRead]:
    try:
        return await campaign_state_field_service.list_fields(
            db, uuid.UUID(campaign_id)
        )
    except CampaignStateFieldError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


@router.post(
    "/{campaign_id}/state-fields",
    response_model=CampaignStateFieldConfigRead,
    status_code=201,
)
async def create_campaign_state_field(
    campaign_id: str,
    payload: CampaignStateFieldConfigCreate,
    db: AsyncSession = Depends(get_db),
) -> CampaignStateFieldConfigRead:
    try:
        return await campaign_state_field_service.create_field(
            db, uuid.UUID(campaign_id), payload
        )
    except CampaignStateFieldError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


@router.put(
    "/{campaign_id}/state-fields/{field_id}",
    response_model=CampaignStateFieldConfigRead,
)
async def update_campaign_state_field(
    campaign_id: str,
    field_id: str,
    payload: CampaignStateFieldConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> CampaignStateFieldConfigRead:
    """Partial update — поля, отсутствующие в теле, не изменяются.

    Семантика `exclude_unset` согласуется с `PUT /campaigns/{id}`.
    Попытка передать `key` или `mode` в теле → 409 (immutable).
    """
    try:
        return await campaign_state_field_service.update_field(
            db, uuid.UUID(campaign_id), uuid.UUID(field_id), payload
        )
    except CampaignStateFieldError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


@router.delete(
    "/{campaign_id}/state-fields/{field_id}",
    status_code=204,
)
async def delete_campaign_state_field(
    campaign_id: str,
    field_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Удалить поле Campaign State. История state не сохраняется (Stage 2 не существует)."""
    try:
        await campaign_state_field_service.delete_field(
            db, uuid.UUID(campaign_id), uuid.UUID(field_id)
        )
    except CampaignStateFieldError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


@router.post(
    "/{campaign_id}/state-fields/reorder",
    response_model=list[CampaignStateFieldConfigRead],
)
async def reorder_campaign_state_fields(
    campaign_id: str,
    payload: CampaignStateFieldConfigReorderRequest,
    db: AsyncSession = Depends(get_db),
) -> list[CampaignStateFieldConfigRead]:
    """Полная перестановка порядка полей. Все ID должны быть UUID-строками и
    принадлежать кампании; длина списка должна равняться числу полей.
    """
    try:
        return await campaign_state_field_service.reorder_fields(
            db, uuid.UUID(campaign_id), payload.field_ids
        )
    except CampaignStateFieldError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


# ---------------------------------------------------------------------------
# Campaign State — Stage 2: Versioned State endpoints
# ---------------------------------------------------------------------------

from typing import Any


@router.get(
    "/{campaign_id}/state",
    response_model=CampaignStateVersionRead | None,
)
async def get_active_campaign_state(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
) -> CampaignStateVersionRead | None:
    """Возвращает активную (последнюю) версию state кампании или null, если версий ещё нет."""
    try:
        return await campaign_state_value_service.get_active_state(
            db, uuid.UUID(campaign_id)
        )
    except CampaignStateValueError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


@router.get(
    "/{campaign_id}/state/versions",
    response_model=list[CampaignStateVersionSummary],
)
async def list_campaign_state_versions(
    campaign_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[CampaignStateVersionSummary]:
    """Краткий список версий state (DESC по state_version)."""
    try:
        return await campaign_state_value_service.list_versions(
            db, uuid.UUID(campaign_id), limit=limit, offset=offset
        )
    except CampaignStateValueError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


@router.get(
    "/{campaign_id}/state/versions/{state_version}",
    response_model=CampaignStateVersionRead | None,
)
async def get_campaign_state_version(
    campaign_id: str,
    state_version: int,
    db: AsyncSession = Depends(get_db),
) -> CampaignStateVersionRead | None:
    """Полный снимок конкретной версии state. 404, если версия не найдена."""
    try:
        return await campaign_state_value_service.get_state_version(
            db, uuid.UUID(campaign_id), state_version
        )
    except CampaignStateValueError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


@router.post(
    "/{campaign_id}/state/patch",
    response_model=CampaignStatePatchResponse,
)
async def apply_campaign_state_patch(
    campaign_id: str,
    payload: CampaignStatePatchRequest,
    db: AsyncSession = Depends(get_db),
) -> CampaignStatePatchResponse:
    """Применить patch к Campaign State.

    Контракт:
      - base_state_version должен совпадать с активной версией кампании (или null,
        если активной версии ещё нет).
      - config_version должен совпадать с текущим Campaign.config_version.
      - При несовпадении любой версии — 409, без частичного применения.
      - При валидационной ошибке любой операции — 422, без частичного применения.
    """
    try:
        return await campaign_state_value_service.apply_patch(
            db, uuid.UUID(campaign_id), payload
        )
    except CampaignStateValueError as exc:
        # PatchValidationError несёт rejection; пробрасываем как 422 с деталями.
        rejection: Any = getattr(exc, "rejection", None)
        if rejection is not None:
            raise HTTPException(
                status_code=exc.http_status,
                detail={
                    "code": exc.code,
                    "rejection": rejection.model_dump(),
                },
            ) from exc
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc


# --- Вспомогательные ---

async def _campaign_with_tags(campaign: Campaign, db: AsyncSession) -> CampaignRead:
    """Используется для одиночных объектов (get/create/update). Для списка — batch в list_campaigns."""
    stmt = select(Tag).where(Tag.campaign_id == campaign.id)
    result = await db.execute(stmt)
    tags = [TagRead.model_validate(t, from_attributes=True) for t in result.scalars().all()]
    return _campaign_read(campaign, tags)


def _campaign_read(campaign: Campaign, tags: list[TagRead]) -> CampaignRead:
    data = CampaignRead.model_validate(campaign, from_attributes=True)
    data.tags = tags
    return data
