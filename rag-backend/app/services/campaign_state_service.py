"""campaign_state_service.py — Service layer for Campaign State field configuration.

Stage 1 (Field Configuration) only.
Implements CRUD + reorder + immutability rules for CampaignStateFieldConfig.
Persists state VALUES (versions, list items, source refs) belongs to Stage 2
and is intentionally NOT included here.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Campaign,
    CampaignStateFieldConfig,
    CampaignStateListItem,
    CampaignStateValue,
    CampaignStateVersion,
)
from shared_contracts.models import (
    CampaignStateFieldConfigCreate,
    CampaignStateFieldConfigRead,
    CampaignStateFieldConfigUpdate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed exceptions (mapped to HTTP codes by the router)
# ---------------------------------------------------------------------------

class CampaignStateFieldError(Exception):
    """Base for all field-config errors mapped to HTTP responses."""
    code: str = "campaign_state_field_error"
    http_status: int = 400

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail)


class CampaignNotFoundError(CampaignStateFieldError):
    code = "campaign_not_found"
    http_status = 404


class FieldNotFoundError(CampaignStateFieldError):
    code = "field_not_found"
    http_status = 404


class InvalidFieldKeyError(CampaignStateFieldError):
    code = "invalid_field_key"
    http_status = 422


class FieldKeyImmutableError(CampaignStateFieldError):
    code = "field_key_immutable"
    http_status = 409


class FieldModeImmutableError(CampaignStateFieldError):
    code = "field_mode_immutable"
    http_status = 409


class FieldKeyDuplicateError(CampaignStateFieldError):
    code = "field_key_duplicate"
    http_status = 409


class InvalidReorderPayloadError(CampaignStateFieldError):
    code = "invalid_reorder_payload"
    http_status = 422


class FieldInUseError(CampaignStateFieldError):
    """Удаление/переименование запрещено: на поле ссылаются значения/элементы state."""

    code = "field_in_use"
    http_status = 409


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# key: lowercase letter + alnum/underscore, 1..64 chars.
_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_ALLOWED_MODES: frozenset[str] = frozenset({"single", "list"})

_DESCRIPTION_MAX_BYTES = 8 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_field_key(key: str) -> None:
    """Raises InvalidFieldKeyError if key doesn't match the canonical pattern."""
    if not isinstance(key, str) or not _FIELD_KEY_RE.match(key):
        raise InvalidFieldKeyError(
            "field key must match ^[a-z][a-z0-9_]{0,63}$ and be 1..64 chars"
        )


def _validate_description(description: str | None) -> None:
    if description is None:
        return
    if len(description.encode("utf-8")) > _DESCRIPTION_MAX_BYTES:
        raise CampaignStateFieldError("description exceeds 8 KiB limit")


def _validate_mode(mode: str) -> None:
    if mode not in _ALLOWED_MODES:
        # Pydantic Literal already filters these, but defence-in-depth.
        raise CampaignStateFieldError(
            f"mode must be one of {sorted(_ALLOWED_MODES)}, got {mode!r}"
        )


async def _get_campaign_or_404(db: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(str(campaign_id))
    return campaign


async def _lock_campaign_for_config_change(
    db: AsyncSession, campaign_id: uuid.UUID
) -> Campaign:
    """SELECT … FOR UPDATE строки Campaign для безопасного инкремента config_version.

    Используется во всех мутирующих операциях (create/update/delete/reorder),
    чтобы гонка с apply_patch не привела к потере инкремента.
    """
    stmt = (
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise CampaignNotFoundError(str(campaign_id))
    return campaign


async def _bump_config_version(db: AsyncSession, campaign: Campaign) -> None:
    """Атомарный инкремент Campaign.config_version.

    Campaign уже залочен через SELECT … FOR UPDATE в вызывающем коде.
    """
    campaign.config_version = campaign.config_version + 1


def _to_read_dto(row: CampaignStateFieldConfig) -> CampaignStateFieldConfigRead:
    return CampaignStateFieldConfigRead(
        id=str(row.id),
        field_id=str(row.id),  # алиас для совместимости со старыми клиентами
        campaign_id=str(row.campaign_id),
        key=row.key,
        label=row.label,
        description=row.description,
        mode=row.mode,
        enabled=row.enabled,
        display_order=row.display_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------

class CampaignStateFieldService:
    """CRUD/reorder сервис для конфигурации полей Campaign State.

    Все методы работают в рамках переданной AsyncSession.
    При ошибке коммита откатывают транзакцию и поднимают типизированное
    исключение, которое роутер превращает в HTTPException.
    """

    # -- list --------------------------------------------------------------

    async def list_fields(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
    ) -> list[CampaignStateFieldConfigRead]:
        """Возвращает все поля кампании в порядке display_order ASC, key ASC."""
        await _get_campaign_or_404(db, campaign_id)

        stmt = (
            select(CampaignStateFieldConfig)
            .where(CampaignStateFieldConfig.campaign_id == campaign_id)
            .order_by(
                CampaignStateFieldConfig.display_order.asc(),
                CampaignStateFieldConfig.key.asc(),
            )
        )
        result = await db.execute(stmt)
        rows: Sequence[CampaignStateFieldConfig] = result.scalars().all()
        return [_to_read_dto(r) for r in rows]

    # -- create ------------------------------------------------------------

    async def create_field(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        payload: CampaignStateFieldConfigCreate,
        *,
        commit: bool = True,
    ) -> CampaignStateFieldConfigRead:
        """Создать поле Campaign State.

        Параметр commit:
          - commit=True (по умолчанию) — сразу коммитит изменения (для standalone
            CRUD-эндпоинта).
          - commit=False — только добавляет в db.session и бампит config_version,
            НЕ делает commit. Это нужно для batch-операций (например, apply
            Initial State с suggested_fields), где все изменения должны
            зафиксироваться одной транзакцией — иначе при ошибке на
            последующих шагах поля останутся «осиротевшими» в БД.
        """
        campaign = await _lock_campaign_for_config_change(db, campaign_id)
        _validate_field_key(payload.key)
        _validate_mode(payload.mode)
        _validate_description(payload.description)

        row = CampaignStateFieldConfig(
            campaign_id=campaign_id,
            key=payload.key,
            label=payload.label,
            description=payload.description,
            mode=payload.mode,
            enabled=payload.enabled,
            display_order=payload.display_order,
        )
        db.add(row)
        await _bump_config_version(db, campaign)
        if not commit:
            # Flush, чтобы row.id заполнился (нужен для downstream-логики),
            # но commit остаётся на ответственности вызывающего.
            try:
                await db.flush()
            except IntegrityError as exc:
                await db.rollback()
                raise FieldKeyDuplicateError(
                    f"field with key {payload.key!r} already exists for this campaign"
                ) from exc
            logger.info(
                "campaign_state_field.create (no-commit): campaign=%s key=%s "
                "id=%s config_version=%d",
                campaign_id, payload.key, row.id, campaign.config_version,
            )
            return _to_read_dto(row)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise FieldKeyDuplicateError(
                f"field with key {payload.key!r} already exists for this campaign"
            ) from exc
        await db.refresh(row)
        logger.info(
            "campaign_state_field.create: campaign=%s key=%s id=%s config_version=%d",
            campaign_id, payload.key, row.id, campaign.config_version,
        )
        return _to_read_dto(row)

    # -- update ------------------------------------------------------------

    async def update_field(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        field_id: uuid.UUID,
        payload: CampaignStateFieldConfigUpdate,
    ) -> CampaignStateFieldConfigRead:
        """Partial update (exclude_unset semantics — set fields only).

        Запреты:
          - payload.key is not None  → 409 (key immutable).
          - payload.mode is not None → 409 (mode immutable).
        """
        row = await self._get_field_or_404(db, campaign_id, field_id)
        campaign = await _lock_campaign_for_config_change(db, campaign_id)

        if "key" in payload.model_fields_set and payload.key is not None:
            raise FieldKeyImmutableError(
                "field key is immutable after creation"
            )
        if "mode" in payload.model_fields_set and payload.mode is not None:
            raise FieldModeImmutableError(
                "field mode is immutable after creation"
            )

        data = payload.model_dump(exclude_unset=True)
        if not data:
            return _to_read_dto(row)

        if "description" in data:
            _validate_description(data["description"])
        if "display_order" in data and data["display_order"] < 0:
            raise CampaignStateFieldError("display_order must be >= 0")
        if "label" in data and (not data["label"] or len(data["label"]) > 256):
            raise CampaignStateFieldError("label must be 1..256 chars")

        for field_name, value in data.items():
            setattr(row, field_name, value)
        await _bump_config_version(db, campaign)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise FieldKeyDuplicateError(
                f"field with key {row.key!r} already exists for this campaign"
            ) from exc
        await db.refresh(row)
        logger.info(
            "campaign_state_field.update: campaign=%s field=%s fields=%s config_version=%d",
            campaign_id, field_id, sorted(data.keys()), campaign.config_version,
        )
        return _to_read_dto(row)

    # -- delete ------------------------------------------------------------

    async def delete_field(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        field_id: uuid.UUID,
        created_by: str | None = None,
    ) -> None:
        """Удаление поля с каскадной очисткой значения в активной версии state.

        Транзакция:
          1. SELECT … FOR UPDATE на Campaign (config-уровневая синхронизация).
          2. Найти latest state_version (если есть).
          3. Если latest есть — посчитать и удалить CampaignStateValue /
             CampaignStateListItem для (latest.id, field_id).
          4. Создать новую CampaignStateVersion:
               state_version = latest.state_version + 1,
               config_version = campaign.config_version (снимок ДО bump),
               base_state_version = latest.state_version,
               source_kind = 'patch'.
          5. Записать AuditLog action='campaign_state_field_cascade_purged'
             (если latest был).
          6. Удалить CampaignStateFieldConfig.
          7. _bump_config_version.
          8. commit.

        Прошлые state_versions и их значения НЕ трогаются — аудит-трейл
        диффов остаётся фактически неизменным.
        """
        row = await self._get_field_or_404(db, campaign_id, field_id)
        campaign = await _lock_campaign_for_config_change(db, campaign_id)

        # latest active state version, если есть.
        latest = (
            await db.execute(
                select(CampaignStateVersion)
                .where(CampaignStateVersion.campaign_id == campaign_id)
                .order_by(CampaignStateVersion.state_version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if latest is None:
            # Активного state ещё нет — просто удаляем поле и бампим config_version.
            await db.delete(row)
            await _bump_config_version(db, campaign)
            await db.commit()
            logger.info(
                "campaign_state_field.delete: campaign=%s field=%s key=%s "
                "config_version=%d (no active state)",
                campaign_id, field_id, row.key, campaign.config_version,
            )
            return

        # Считаем и удаляем значения/элементы активной версии по этому полю.
        purged_values = int(
            (
                await db.execute(
                    select(func.count()).select_from(CampaignStateValue).where(
                        CampaignStateValue.version_id == latest.id,
                        CampaignStateValue.field_id == field_id,
                    )
                )
            ).scalar_one()
            or 0
        )
        purged_list_items = int(
            (
                await db.execute(
                    select(func.count()).select_from(CampaignStateListItem).where(
                        CampaignStateListItem.version_id == latest.id,
                        CampaignStateListItem.field_id == field_id,
                    )
                )
            ).scalar_one()
            or 0
        )

        await db.execute(
            sa_delete(CampaignStateValue).where(
                CampaignStateValue.version_id == latest.id,
                CampaignStateValue.field_id == field_id,
            )
        )
        await db.execute(
            sa_delete(CampaignStateListItem).where(
                CampaignStateListItem.version_id == latest.id,
                CampaignStateListItem.field_id == field_id,
            )
        )

        # Снимок config_version — ДО bump, чтобы state_version фиксировала
        # «состояние до удаления поля», а компилятор брал снимок конфига,
        # привязанный к версии (как и у apply_patch).
        new_state_version = latest.state_version + 1
        new_version = CampaignStateVersion(
            campaign_id=campaign_id,
            state_version=new_state_version,
            config_version=campaign.config_version,
            source_kind="patch",
            base_state_version=latest.state_version,
            created_by=created_by,
        )
        db.add(new_version)
        await db.flush()
        new_version_id = new_version.id

        # Audit-trail: фиксируем каскадную очистку.
        await db.execute(
            insert(AuditLog).values(
                id=uuid.uuid4(),
                action="campaign_state_field_cascade_purged",
                entity_type="campaign",
                entity_id=str(campaign_id),
                actor=created_by,
                payload={
                    "from_state_version": latest.state_version,
                    "to_state_version": new_state_version,
                    "config_version": campaign.config_version,
                    "field_id": str(field_id),
                    "field_key": row.key,
                    "purged_values": purged_values,
                    "purged_list_items": purged_list_items,
                },
                created_at=func.now(),
            )
        )

        await db.delete(row)
        await _bump_config_version(db, campaign)
        await db.commit()

        logger.info(
            "campaign_state_field.delete: campaign=%s field=%s key=%s "
            "config_version=%d cascade=v%d purged_values=%d purged_list_items=%d",
            campaign_id, field_id, row.key, campaign.config_version,
            new_state_version, purged_values, purged_list_items,
        )
        _ = new_version_id  # currently unused; kept for symmetry with apply_patch

    # -- reorder -----------------------------------------------------------

    async def reorder_fields(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        ordered_field_ids: list[str],
    ) -> list[CampaignStateFieldConfigRead]:
        """Переупорядочивает поля кампании.

        Правила:
          - все ID должны быть UUID-строками и принадлежать кампании;
          - len(ordered_field_ids) == текущему числу полей в кампании;
          - ID должны быть уникальны.
        display_order = позиция в списке (0-based).

        Также инкрементирует Campaign.config_version, потому что изменение
        порядка меняет контракт компиляции state.
        """
        campaign = await _lock_campaign_for_config_change(db, campaign_id)

        if not ordered_field_ids:
            raise InvalidReorderPayloadError("field_ids must not be empty")

        # Validate uniqueness and parse UUIDs.
        try:
            parsed_ids = [uuid.UUID(fid) for fid in ordered_field_ids]
        except ValueError as exc:
            raise InvalidReorderPayloadError(
                f"field_ids contains non-UUID value: {exc}"
            ) from exc
        if len(parsed_ids) != len(set(parsed_ids)):
            raise InvalidReorderPayloadError("field_ids must be unique")

        # Load current rows and verify coverage + ownership.
        stmt = select(CampaignStateFieldConfig).where(
            CampaignStateFieldConfig.campaign_id == campaign_id
        )
        rows: Sequence[CampaignStateFieldConfig] = (await db.execute(stmt)).scalars().all()
        existing_ids: set[uuid.UUID] = {r.id for r in rows}

        requested_set = set(parsed_ids)
        if requested_set != existing_ids:
            missing = existing_ids - requested_set
            unknown = requested_set - existing_ids
            details: list[str] = []
            if missing:
                details.append(f"missing={sorted(str(m) for m in missing)}")
            if unknown:
                details.append(f"unknown={sorted(str(u) for u in unknown)}")
            raise InvalidReorderPayloadError(
                "field_ids must cover exactly all fields of this campaign. " + "; ".join(details)
            )

        # Apply display_order = position, in a single UPDATE per id (postgresql UPDATE
        # within one transaction is atomic; ordering matters only via the index).
        for index, fid in enumerate(parsed_ids):
            await db.execute(
                update(CampaignStateFieldConfig)
                .where(
                    CampaignStateFieldConfig.id == fid,
                    CampaignStateFieldConfig.campaign_id == campaign_id,
                )
                .values(display_order=index)
            )
        await _bump_config_version(db, campaign)
        await db.commit()

        logger.info(
            "campaign_state_field.reorder: campaign=%s ordered=%d config_version=%d",
            campaign_id, len(parsed_ids), campaign.config_version,
        )
        return await self.list_fields(db, campaign_id)

    # -- internals ---------------------------------------------------------

    async def _get_field_or_404(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        field_id: uuid.UUID,
    ) -> CampaignStateFieldConfig:
        row = await db.get(CampaignStateFieldConfig, field_id)
        if row is None or row.campaign_id != campaign_id:
            raise FieldNotFoundError(str(field_id))
        return row


# Module-level singleton — same pattern as domain_service / settings_service
campaign_state_field_service = CampaignStateFieldService()


# ---------------------------------------------------------------------------
# Router helper: map service errors to HTTPException
# ---------------------------------------------------------------------------

def _http_from_error(exc: CampaignStateFieldError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.code)
