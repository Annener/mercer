"""campaign_state_value_service.py — Service layer for Campaign State values (Stage 2).

Implements versioned state: read active version, list versions, apply patch
operations with optimistic locking on base_state_version and config_version.

Stage 2 only. Initial State proposal/review and prompt assembly belong to
later stages and are intentionally NOT included here.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Campaign,
    CampaignStateFieldConfig,
    CampaignStateListItem,
    CampaignStateValue,
    CampaignStateVersion,
    Document,
)
from shared_contracts.models import (
    CampaignStateFieldConfigRead,
    CampaignStateFieldValuesRead,
    CampaignStateInitialProposal,
    CampaignStateListItemRead,
    CampaignStatePatchOperation,
    CampaignStatePatchRejection,
    CampaignStatePatchRequest,
    CampaignStatePatchResponse,
    CampaignStateSingleValueRead,
    CampaignStateVersionRead,
    CampaignStateVersionSummary,
    DocumentSnapshot,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed exceptions (mapped to HTTP codes by the router)
# ---------------------------------------------------------------------------


class CampaignStateValueError(Exception):
    """Base for Stage 2 errors mapped to HTTP responses."""

    code: str = "campaign_state_value_error"
    http_status: int = 400

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail)


class CampaignNotFoundError(CampaignStateValueError):
    code = "campaign_not_found"
    http_status = 404


class StateVersionNotFoundError(CampaignStateValueError):
    code = "state_version_not_found"
    http_status = 404


class StateVersionConflictError(CampaignStateValueError):
    """base_state_version не совпадает с активной версией."""

    code = "state_version_conflict"
    http_status = 409


class ConfigVersionConflictError(CampaignStateValueError):
    """config_version в запросе устарел."""

    code = "config_version_conflict"
    http_status = 409


class PatchValidationError(CampaignStateValueError):
    """fail-fast валидация операций."""

    code = "patch_validation_failed"
    http_status = 422

    def __init__(self, rejection: CampaignStatePatchRejection) -> None:
        super().__init__(rejection.code)
        self.rejection = rejection


class InvalidSourceRefError(CampaignStateValueError):
    code = "invalid_source_ref"
    http_status = 422


class InitialAlreadyAppliedError(CampaignStateValueError):
    """Кампания уже имеет хотя бы одну state version — initial применять нельзя."""
    code = "initial_already_applied"
    http_status = 409


class SourceSnapshotStaleError(CampaignStateValueError):
    """Между preview и apply изменился хотя бы один source snapshot (Document.md5)."""

    code = "source_snapshot_stale"
    http_status = 409

    def __init__(self, stale_documents: list[str]) -> None:
        super().__init__("source_snapshot_stale")
        self.stale_documents = stale_documents


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# source_ref formats:
#   file:<uuid>:sha:<hex>
#   chat:<uuid>
#   vault:<slug>
_SOURCE_REF_RE = re.compile(
    r"^(file:[0-9a-fA-F-]{36}:sha:[0-9a-f]{8,64}|chat:[0-9a-fA-F-]{36}|vault:[a-z0-9_-]{1,128})$"
)

_MAX_REASON_LEN = 1024
_MAX_TEXT_LEN = 8192


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_source_refs(refs: list[str]) -> None:
    for ref in refs:
        if not isinstance(ref, str) or not _SOURCE_REF_RE.match(ref):
            raise InvalidSourceRefError(f"invalid source_ref: {ref!r}")


async def _get_campaign_or_404(db: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise CampaignNotFoundError(str(campaign_id))
    return campaign


async def _lock_campaign(db: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    """SELECT … FOR UPDATE для гонки apply_patch ↔ config_version инкремент."""
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


async def _latest_version(
    db: AsyncSession, campaign_id: uuid.UUID
) -> CampaignStateVersion | None:
    stmt = (
        select(CampaignStateVersion)
        .where(CampaignStateVersion.campaign_id == campaign_id)
        .order_by(CampaignStateVersion.state_version.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _get_version(
    db: AsyncSession, campaign_id: uuid.UUID, state_version: int
) -> CampaignStateVersion | None:
    stmt = select(CampaignStateVersion).where(
        CampaignStateVersion.campaign_id == campaign_id,
        CampaignStateVersion.state_version == state_version,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_fields(
    db: AsyncSession, campaign_id: uuid.UUID
) -> list[CampaignStateFieldConfig]:
    stmt = (
        select(CampaignStateFieldConfig)
        .where(CampaignStateFieldConfig.campaign_id == campaign_id)
        .order_by(
            CampaignStateFieldConfig.display_order.asc(),
            CampaignStateFieldConfig.key.asc(),
        )
    )
    return list((await db.execute(stmt)).scalars().all())


def _field_read(f: CampaignStateFieldConfig) -> CampaignStateFieldConfigRead:
    return CampaignStateFieldConfigRead(
        id=str(f.id),
        campaign_id=str(f.campaign_id),
        key=f.key,
        label=f.label,
        description=f.description,
        mode=f.mode,
        enabled=f.enabled,
        display_order=f.display_order,
        created_at=f.created_at,
        updated_at=f.updated_at,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _summary(v: CampaignStateVersion) -> CampaignStateVersionSummary:
    return CampaignStateVersionSummary(
        id=str(v.id),
        campaign_id=str(v.campaign_id),
        state_version=v.state_version,
        config_version=v.config_version,
        source_kind=v.source_kind,  # type: ignore[arg-type]
        base_state_version=v.base_state_version,
        created_at=v.created_at,
        created_by=v.created_by,
    )


async def _serialize_version(
    db: AsyncSession, version: CampaignStateVersion
) -> CampaignStateVersionRead:
    fields = await _load_fields(db, version.campaign_id)

    # values + list-items одной пачкой.
    values_by_field: dict[uuid.UUID, CampaignStateValue] = {}
    items_by_field: dict[uuid.UUID, list[CampaignStateListItem]] = {}

    if fields:
        values_stmt = select(CampaignStateValue).where(
            CampaignStateValue.version_id == version.id,
            CampaignStateValue.field_id.in_([f.id for f in fields]),
        )
        for v in (await db.execute(values_stmt)).scalars().all():
            values_by_field[v.field_id] = v

        items_stmt = (
            select(CampaignStateListItem)
            .where(
                CampaignStateListItem.version_id == version.id,
                CampaignStateListItem.field_id.in_([f.id for f in fields]),
            )
            .order_by(
                CampaignStateListItem.field_id.asc(),
                CampaignStateListItem.created_at.asc(),
                CampaignStateListItem.item_key.asc(),
            )
        )
        for item in (await db.execute(items_stmt)).scalars().all():
            items_by_field.setdefault(item.field_id, []).append(item)

    field_values: list[CampaignStateFieldValuesRead] = []
    for f in fields:
        if f.mode == "single":
            val = values_by_field.get(f.id)
            single: CampaignStateSingleValueRead | None = None
            if val is not None:
                single = CampaignStateSingleValueRead(
                    field_key=f.key,
                    text=val.text,
                    source_refs=list(val.source_refs or []),
                    updated_at=val.updated_at,
                )
            field_values.append(
                CampaignStateFieldValuesRead(
                    field_key=f.key,
                    field_id=str(f.id),
                    mode="single",
                    enabled=f.enabled,
                    display_order=f.display_order,
                    single_value=single,
                    items=[],
                )
            )
        else:
            items = items_by_field.get(f.id, [])
            field_values.append(
                CampaignStateFieldValuesRead(
                    field_key=f.key,
                    field_id=str(f.id),
                    mode="list",
                    enabled=f.enabled,
                    display_order=f.display_order,
                    single_value=None,
                    items=[
                        CampaignStateListItemRead(
                            field_key=f.key,
                            item_key=it.item_key,
                            text=it.text,
                            resolved=it.resolved,
                            source_refs=list(it.source_refs or []),
                            updated_at=it.updated_at,
                        )
                        for it in items
                    ],
                )
            )

    return CampaignStateVersionRead(summary=_summary(version), fields=field_values)


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------


def _check_operation_basic(op: CampaignStatePatchOperation) -> None:
    """Общая валидация payload-а операции до попытки применить."""
    if op.reason is None or not op.reason.strip():
        raise PatchValidationError(
            CampaignStatePatchRejection(
                op_index=-1,
                op_type=op.type,
                code="invalid_payload",
                detail="reason must be non-empty",
            )
        )
    if len(op.reason) > _MAX_REASON_LEN:
        raise PatchValidationError(
            CampaignStatePatchRejection(
                op_index=-1,
                op_type=op.type,
                code="invalid_payload",
                detail="reason exceeds limit",
            )
        )
    _validate_source_refs(op.source_refs)


def _check_text_length(op: CampaignStatePatchOperation) -> None:
    text: str | None = getattr(op, "text", None)
    if text is not None and len(text) > _MAX_TEXT_LEN:
        raise PatchValidationError(
            CampaignStatePatchRejection(
                op_index=-1,
                op_type=op.type,
                code="invalid_payload",
                detail="text exceeds limit",
            )
        )


async def _validate_patch(
    db: AsyncSession,
    fields_by_key: dict[str, CampaignStateFieldConfig],
    base_values_by_field: dict[uuid.UUID, CampaignStateValue],
    base_items_by_field: dict[uuid.UUID, dict[str, CampaignStateListItem]],
    request: CampaignStatePatchRequest,
) -> None:
    """Fail-fast валидация операций. Бросает PatchValidationError при первой ошибке."""
    for index, op in enumerate(request.operations):
        _check_operation_basic(op)
        _check_text_length(op)
        field = fields_by_key.get(op.field_key)
        if field is None:
            raise PatchValidationError(
                CampaignStatePatchRejection(
                    op_index=index,
                    op_type=op.type,
                    code="field_not_found",
                    detail=f"field_key {op.field_key!r} not found",
                )
            )

        if op.type in ("replace_single", "clear_single"):
            if field.mode != "single":
                raise PatchValidationError(
                    CampaignStatePatchRejection(
                        op_index=index,
                        op_type=op.type,
                        code="mode_mismatch",
                        detail=f"field {field.key!r} is mode={field.mode}, expected single",
                    )
                )
        else:
            if field.mode != "list":
                raise PatchValidationError(
                    CampaignStatePatchRejection(
                        op_index=index,
                        op_type=op.type,
                        code="mode_mismatch",
                        detail=f"field {field.key!r} is mode={field.mode}, expected list",
                    )
                )
            if op.type in ("update_list_item", "resolve_list_item", "remove_list_item"):
                items_by_key = base_items_by_field.get(field.id, {})
                if op.item_key not in items_by_key:
                    raise PatchValidationError(
                        CampaignStatePatchRejection(
                            op_index=index,
                            op_type=op.type,
                            code="item_not_found",
                            detail=(
                                f"item_key {op.item_key!r} not found in field "
                                f"{field.key!r} of base state"
                            ),
                        )
                    )


def _next_item_key(
    field_key: str,
    existing_keys: set[str],
    used_prefix_count: int,
) -> str:
    """Генерирует стабильный, человекочитаемый item_key."""
    # Упрощённо: "{field_key}-{NN}", начиная с used_prefix_count+1.
    n = max(used_prefix_count, 0) + 1
    while True:
        candidate = f"{field_key}-{n:02d}"
        if candidate not in existing_keys:
            return candidate
        n += 1


def _build_initial_state_rows(
    proposal: CampaignStateInitialProposal,
    fields_by_key: dict[str, CampaignStateFieldConfig],
    new_version_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Преобразует proposal в строки CampaignStateValue / CampaignStateListItem.

    Правила:
      - поля со status != "proposed" игнорируются;
      - поля, отсутствующие в fields_by_key (кампания) или с enabled=False, игнорируются;
      - для single-полей: ожидается заполненный single_value;
      - для list-полей: ожидается заполненный list_value; item_key генерируется сервером
        через _next_item_key (стабильный, человекочитаемый).
    """
    values_rows: list[dict[str, Any]] = []
    items_rows: list[dict[str, Any]] = []

    for pf in proposal.fields:
        field = fields_by_key.get(pf.field_key)
        if field is None or not field.enabled:
            continue
        if pf.status.status != "proposed":
            continue

        if field.mode == "single":
            if pf.single_value is None:
                continue
            values_rows.append(
                {
                    "version_id": new_version_id,
                    "field_id": field.id,
                    "text": pf.single_value.text,
                    "source_refs": list(pf.single_value.source_refs),
                }
            )
        else:  # list
            if pf.list_value is None:
                continue
            existing_keys: set[str] = set()
            used_prefix = 0
            for item in pf.list_value.items:
                new_key = _next_item_key(field.key, existing_keys, used_prefix)
                existing_keys.add(new_key)
                used_prefix += 1
                items_rows.append(
                    {
                        "version_id": new_version_id,
                        "field_id": field.id,
                        "item_key": new_key,
                        "text": item.text,
                        "resolved": False,
                        "source_refs": list(item.source_refs),
                    }
                )

    return values_rows, items_rows


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


class CampaignStateValueService:
    """Сервис версионированных значений Campaign State."""

    async def get_active_state(
        self, db: AsyncSession, campaign_id: uuid.UUID
    ) -> CampaignStateVersionRead | None:
        await _get_campaign_or_404(db, campaign_id)
        version = await _latest_version(db, campaign_id)
        if version is None:
            return None
        return await _serialize_version(db, version)

    async def get_state_version(
        self, db: AsyncSession, campaign_id: uuid.UUID, state_version: int
    ) -> CampaignStateVersionRead | None:
        await _get_campaign_or_404(db, campaign_id)
        version = await _get_version(db, campaign_id, state_version)
        if version is None:
            return None
        return await _serialize_version(db, version)

    async def list_versions(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CampaignStateVersionSummary]:
        await _get_campaign_or_404(db, campaign_id)
        stmt = (
            select(CampaignStateVersion)
            .where(CampaignStateVersion.campaign_id == campaign_id)
            .order_by(CampaignStateVersion.state_version.desc())
            .limit(limit)
            .offset(offset)
        )
        rows: Sequence[CampaignStateVersion] = (await db.execute(stmt)).scalars().all()
        return [_summary(r) for r in rows]

    async def list_enabled_fields_ordered(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
    ) -> list[CampaignStateFieldConfigRead]:
        """Вернуть enabled-поля кампании в порядке display_order ASC, key ASC.

        Stage 6: Prompt Assembly использует этот порядок для детерминированной
        компиляции state в prompt. Возвращает Pydantic-DTO, а не ORM.
        """
        await _get_campaign_or_404(db, campaign_id)
        stmt = (
            select(CampaignStateFieldConfig)
            .where(
                CampaignStateFieldConfig.campaign_id == campaign_id,
                CampaignStateFieldConfig.enabled == True,  # noqa: E712
            )
            .order_by(
                CampaignStateFieldConfig.display_order.asc(),
                CampaignStateFieldConfig.key.asc(),
            )
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [_field_read(f) for f in rows]

    async def apply_patch(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        request: CampaignStatePatchRequest,
        created_by: str | None = None,
    ) -> CampaignStatePatchResponse:
        # SELECT FOR UPDATE для гонки с инкрементом config_version.
        campaign = await _lock_campaign(db, campaign_id)

        # Config version: должен совпадать с тем, что знает клиент.
        if request.config_version != campaign.config_version:
            raise ConfigVersionConflictError(
                f"config_version mismatch: client={request.config_version}, "
                f"server={campaign.config_version}"
            )

        fields = await _load_fields(db, campaign_id)
        fields_by_key: dict[str, CampaignStateFieldConfig] = {f.key: f for f in fields}

        latest = await _latest_version(db, campaign_id)
        if latest is None:
            # Базы ещё нет — первый state создаётся с base_state_version = None
            # и state_version = 1. Базовых значений и list-items нет.
            if request.base_state_version is not None:
                raise StateVersionConflictError(
                    "base_state_version provided but no state versions exist; pass null"
                )
            base_values_by_field: dict[uuid.UUID, CampaignStateValue] = {}
            base_items_by_field: dict[uuid.UUID, dict[str, CampaignStateListItem]] = {}
            new_state_version = 1
        else:
            if request.base_state_version != latest.state_version:
                raise StateVersionConflictError(
                    f"base_state_version mismatch: client={request.base_state_version}, "
                    f"server={latest.state_version}"
                )
            # Загружаем базовые single-значения и list-items текущей активной версии.
            base_values_by_field = {
                v.field_id: v
                for v in (
                    await db.execute(
                        select(CampaignStateValue).where(
                            CampaignStateValue.version_id == latest.id
                        )
                    )
                ).scalars().all()
            }
            base_items_rows = (
                await db.execute(
                    select(CampaignStateListItem).where(
                        CampaignStateListItem.version_id == latest.id
                    )
                )
            ).scalars().all()
            base_items_by_field: dict[uuid.UUID, dict[str, CampaignStateListItem]] = {}
            for it in base_items_rows:
                base_items_by_field.setdefault(it.field_id, {})[it.item_key] = it
            new_state_version = latest.state_version + 1

        # Fail-fast валидация операций.
        await _validate_patch(
            db,
            fields_by_key,
            base_values_by_field,
            base_items_by_field,
            request,
        )

        # Создаём новую версию-снимок.
        new_version = CampaignStateVersion(
            campaign_id=campaign_id,
            state_version=new_state_version,
            config_version=campaign.config_version,
            source_kind="patch",
            base_state_version=(
                None if latest is None else latest.state_version
            ),
            created_by=created_by,
        )
        db.add(new_version)
        try:
            await db.flush()
        except Exception:
            await db.rollback()
            raise

        new_version_id = new_version.id

        # Подготовка значений и list-items новой версии.
        # Берём за основу base-данные, потом применяем операции.
        new_values_text: dict[uuid.UUID, tuple[str, list[str]]] = {}
        for field_id, val in base_values_by_field.items():
            new_values_text[field_id] = (val.text, list(val.source_refs or []))

        # Для list-items храним упорядоченный список [(item_key, text, resolved, refs)].
        new_items: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for field_id, items_by_key in base_items_by_field.items():
            new_items[field_id] = [
                {
                    "item_key": it.item_key,
                    "text": it.text,
                    "resolved": it.resolved,
                    "source_refs": list(it.source_refs or []),
                }
                for it in items_by_key.values()
            ]
        # Для полей, которые есть в конфигурации, но не имели list-items в базе.
        for f in fields:
            if f.mode == "list" and f.id not in new_items:
                new_items[f.id] = []

        applied_types: list[str] = []

        for op in request.operations:
            field = fields_by_key[op.field_key]
            refs = list(op.source_refs)
            if op.type == "replace_single":
                new_values_text[field.id] = (op.text, refs)  # type: ignore[assignment]
            elif op.type == "clear_single":
                new_values_text.pop(field.id, None)
            elif op.type == "add_list_item":
                existing = new_items[field.id]
                existing_keys = {x["item_key"] for x in existing}
                used_prefix = sum(
                    1 for k in existing_keys if k.startswith(f"{field.key}-")
                )
                new_key = _next_item_key(field.key, existing_keys, used_prefix)
                existing.append(
                    {
                        "item_key": new_key,
                        "text": op.text,
                        "resolved": False,
                        "source_refs": refs,
                    }
                )
            elif op.type == "update_list_item":
                for x in new_items[field.id]:
                    if x["item_key"] == op.item_key:
                        x["text"] = op.text
                        x["source_refs"] = refs
                        break
            elif op.type == "resolve_list_item":
                for x in new_items[field.id]:
                    if x["item_key"] == op.item_key:
                        x["resolved"] = True
                        x["source_refs"] = refs
                        break
            elif op.type == "remove_list_item":
                new_items[field.id] = [
                    x for x in new_items[field.id] if x["item_key"] != op.item_key
                ]
            applied_types.append(op.type)

        # Удаляем старые строки новой версии (их быть не должно, но безопасности ради).
        await db.execute(
            delete(CampaignStateValue).where(
                CampaignStateValue.version_id == new_version_id
            )
        )
        await db.execute(
            delete(CampaignStateListItem).where(
                CampaignStateListItem.version_id == new_version_id
            )
        )

        # Вставляем новые значения.
        if new_values_text:
            await db.execute(
                insert(CampaignStateValue).values(
                    [
                        {
                            "version_id": new_version_id,
                            "field_id": fid,
                            "text": text,
                            "source_refs": refs,
                        }
                        for fid, (text, refs) in new_values_text.items()
                    ]
                )
            )

        # Вставляем новые list-items.
        item_rows: list[dict[str, Any]] = []
        for fid, items in new_items.items():
            for x in items:
                item_rows.append(
                    {
                        "version_id": new_version_id,
                        "field_id": fid,
                        "item_key": x["item_key"],
                        "text": x["text"],
                        "resolved": x["resolved"],
                        "source_refs": x["source_refs"],
                    }
                )
        if item_rows:
            await db.execute(
                insert(CampaignStateListItem).values(item_rows)
            )

        # Audit log.
        from app.db.models import AuditLog  # local import to avoid circular

        await db.execute(
            insert(AuditLog).values(
                id=str(uuid.uuid4()),
                action="campaign_state_patch_applied",
                entity_type="campaign",
                entity_id=str(campaign_id),
                actor=created_by,
                payload={
                    "from_state_version": (
                        None if latest is None else latest.state_version
                    ),
                    "to_state_version": new_state_version,
                    "config_version": campaign.config_version,
                    "operations": [
                        {"type": op.type, "field_key": op.field_key}
                        for op in request.operations
                    ],
                },
                created_at=func.now(),
            )
        )

        await db.commit()
        await db.refresh(new_version)

        logger.info(
            "campaign_state_value.patch: campaign=%s from=%s to=%s ops=%d",
            campaign_id,
            None if latest is None else latest.state_version,
            new_state_version,
            len(request.operations),
        )

        return CampaignStatePatchResponse(
            applied_state_version=new_state_version,
            config_version=campaign.config_version,
            applied_operations=applied_types,
            failed_operations=[],
        )

    # -- initial state -----------------------------------------------------

    async def apply_initial(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        proposal: CampaignStateInitialProposal,
        source_snapshot: list[DocumentSnapshot],
        config_version: int,
        created_by: str | None = None,
    ) -> CampaignStateVersionRead:
        """Применить LLM-proposal как первую active state version кампании.

        Контракт:
          - кампания должна существовать и не иметь ни одной state version;
          - config_version в запросе должен совпадать с Campaign.config_version;
          - для каждого doc_id из source_snapshot текущий Document.md5 должен
            совпадать с snapshot.content_sha, иначе 409 source_snapshot_stale
            со списком устаревших doc_id;
          - enabled-поля кампании, отсутствующие в proposal, трактуются как
            "empty" (значения не вставляются);
          - при status='proposed' вставляются CampaignStateValue / CampaignStateListItem;
          - при status='empty' / 'needs_clarification' значения не вставляются;
          - config_version НЕ инкрементируется (initial не меняет конфигурацию полей);
          - пишется audit log action="campaign_state_initial_applied".
        """
        campaign = await _lock_campaign(db, campaign_id)

        if config_version != campaign.config_version:
            raise ConfigVersionConflictError(
                f"config_version mismatch: client={config_version}, "
                f"server={campaign.config_version}"
            )

        latest = await _latest_version(db, campaign_id)
        if latest is not None:
            raise InitialAlreadyAppliedError(
                f"campaign {campaign_id} already has state_version={latest.state_version}"
            )

        # Snapshot freshness check.
        if source_snapshot:
            snapshot_sha: dict[str, str] = {
                s.document_id: s.content_sha for s in source_snapshot
            }
            try:
                doc_uuids = [uuid.UUID(d) for d in snapshot_sha.keys()]
            except ValueError as exc:
                raise SourceSnapshotStaleError(
                    stale_documents=list(snapshot_sha.keys())
                ) from exc

            docs_rows = await db.execute(
                select(Document.id, Document.md5).where(Document.id.in_(doc_uuids))
            )
            stale: list[str] = []
            for did, current_md5 in docs_rows.all():
                expected = snapshot_sha.get(str(did))
                if expected is None or current_md5 != expected:
                    stale.append(str(did))
            if stale:
                raise SourceSnapshotStaleError(stale_documents=sorted(stale))

        fields = await _load_fields(db, campaign_id)
        fields_by_key: dict[str, CampaignStateFieldConfig] = {f.key: f for f in fields}

        # Создаём новую версию-снимок.
        new_version = CampaignStateVersion(
            campaign_id=campaign_id,
            state_version=1,
            config_version=campaign.config_version,
            source_kind="initial",
            base_state_version=None,
            created_by=created_by,
        )
        db.add(new_version)
        try:
            await db.flush()
        except Exception:
            await db.rollback()
            raise

        new_version_id = new_version.id

        # Подготовка значений и list-items новой версии из proposal.
        values_rows, items_rows = _build_initial_state_rows(
            proposal,
            fields_by_key,
            new_version_id,
        )

        if values_rows:
            await db.execute(insert(CampaignStateValue).values(values_rows))
        if items_rows:
            await db.execute(insert(CampaignStateListItem).values(items_rows))

        # Audit log.
        from app.db.models import AuditLog  # local import to avoid circular

        await db.execute(
            insert(AuditLog).values(
                id=str(uuid.uuid4()),
                action="campaign_state_initial_applied",
                entity_type="campaign",
                entity_id=str(campaign_id),
                actor=created_by,
                payload={
                    "from_state_version": None,
                    "to_state_version": 1,
                    "config_version": campaign.config_version,
                    "source_documents": [s.document_id for s in source_snapshot],
                    "fields_count": len(proposal.fields),
                },
                created_at=func.now(),
            )
        )

        await db.commit()
        await db.refresh(new_version)

        logger.info(
            "campaign_state_initial.apply: campaign=%s sources=%d values=%d items=%d",
            campaign_id,
            len(source_snapshot),
            len(values_rows),
            len(items_rows),
        )

        return await _serialize_version(db, new_version)


campaign_state_value_service = CampaignStateValueService()


# ---------------------------------------------------------------------------
# Router helper
# ---------------------------------------------------------------------------


def http_from_error(exc: CampaignStateValueError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.code)