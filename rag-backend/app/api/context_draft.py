"""context_draft.py — API для работы с auto-draft campaign state.

Предоставляет endpoints для просмотра, принятия и отклонения draft-а,
который фоновый loop (Phases 2b + 3) создаёт на основе drift hints.

Endpoints (prefix=/api/chats/{chat_id}/context-draft):
- GET ""                   → {"draft": dict | None}
- POST "/accept"           → применить state_patch + очистить drift
- POST "/reject"           → удалить draft + очистить drift
- POST "/check-files"      → Phase 5 (не реализовано) → 501

Draft хранится в Redis: draft:campaign:{campaign_id}:chat:{chat_id}.
TTL задаётся Phase 3 (3 часа).
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Campaign, Chat
from app.db.session import get_db
from app.services.campaign_state_value_service import campaign_state_value_service
from shared_contracts.models import (
    CampaignStatePatchOperation,
    CampaignStatePatchRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chats/{chat_id}/context-draft",
    tags=["context-draft"],
)

_DRAFT_REDIS_KEY_TEMPLATE = "draft:campaign:{campaign_id}:chat:{chat_id}"

_PATCH_LIST_ADAPTER = TypeAdapter(list[CampaignStatePatchOperation])


def _draft_key(campaign_id: str, chat_id: str) -> str:
    return _DRAFT_REDIS_KEY_TEMPLATE.format(campaign_id=campaign_id, chat_id=chat_id)


async def _load_chat_or_404(chat_id: str, db: AsyncSession) -> Chat:
    try:
        chat_uuid = _uuid.UUID(chat_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="chat_not_found")
    chat = await db.get(Chat, chat_uuid)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat_not_found")
    return chat


def _parse_draft_raw(raw: str | bytes) -> dict:
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("context_draft: failed to parse draft JSON: %s", exc)
        raise HTTPException(status_code=500, detail="draft_corrupted") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="draft_corrupted")
    return payload


def _parse_state_patch(raw_operations: list[dict]) -> list[CampaignStatePatchOperation]:
    try:
        return list(_PATCH_LIST_ADAPTER.validate_python(raw_operations))
    except ValidationError as exc:
        logger.warning("context_draft: invalid state_patch payload: %s", exc)
        raise HTTPException(status_code=400, detail="invalid_patch") from exc


@router.get("")
async def get_context_draft(
    chat_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Получить текущий draft для чата. Возвращает null если draft не существует."""
    chat = await _load_chat_or_404(chat_id, db)
    if chat.campaign_id is None:
        return {"draft": None}

    redis = request.app.state.redis
    if redis is None:
        return {"draft": None}

    raw = await redis.get(_draft_key(str(chat.campaign_id), chat_id))
    if raw is None:
        return {"draft": None}
    return {"draft": _parse_draft_raw(raw)}


@router.post("/accept")
async def accept_context_draft(
    chat_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Применить state_patch из draft-а, очистить drift и draft."""
    chat = await _load_chat_or_404(chat_id, db)
    if chat.campaign_id is None:
        raise HTTPException(status_code=422, detail="campaign_required")

    redis = request.app.state.redis
    raw = await redis.get(_draft_key(str(chat.campaign_id), chat_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="draft_not_found")

    draft = _parse_draft_raw(raw)
    raw_patch = draft.get("state_patch") or []
    if not isinstance(raw_patch, list):
        raise HTTPException(status_code=400, detail="invalid_patch")

    operations = _parse_state_patch(raw_patch)

    # Получаем активную версию для base_state_version + config_version
    active = await campaign_state_value_service.get_active_state(
        db, chat.campaign_id
    )
    base_state_version = active.summary.state_version if active is not None else None

    campaign = await db.get(Campaign, chat.campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="campaign_not_found")
    config_version = campaign.config_version

    patch_request = CampaignStatePatchRequest(
        base_state_version=base_state_version,
        config_version=config_version,
        operations=operations,
    )

    try:
        result = await campaign_state_value_service.apply_patch(
            db, chat.campaign_id, patch_request
        )
    except Exception as exc:
        logger.warning("context_draft: apply_patch failed: %s", exc)
        raise HTTPException(
            status_code=409, detail=f"apply_failed: {exc}"
        ) from exc

    # Удаляем draft из Redis + очищаем drift под-пространство
    await redis.delete(_draft_key(str(chat.campaign_id), chat_id))

    from app.services.context_engine.scene_memory import clear_drift

    await clear_drift(chat_id, db)

    audit = AuditLog(
        action="context_draft_accepted",
        entity_type="chat",
        entity_id=chat_id,
        payload={
            "campaign_id": str(chat.campaign_id),
            "applied_state_version": result.applied_state_version,
            "operations_count": len(operations),
        },
    )
    db.add(audit)
    await db.commit()

    return {
        "applied_state_version": result.applied_state_version,
        "operations_count": len(operations),
    }


@router.post("/reject")
async def reject_context_draft(
    chat_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Отклонить draft: удалить из Redis + очистить drift."""
    chat = await _load_chat_or_404(chat_id, db)
    if chat.campaign_id is None:
        raise HTTPException(status_code=422, detail="campaign_required")

    redis = request.app.state.redis

    await redis.delete(_draft_key(str(chat.campaign_id), chat_id))

    from app.services.context_engine.scene_memory import clear_drift

    await clear_drift(chat_id, db)

    audit = AuditLog(
        action="context_draft_rejected",
        entity_type="chat",
        entity_id=chat_id,
        payload={"campaign_id": str(chat.campaign_id)},
    )
    db.add(audit)
    await db.commit()

    return {"status": "rejected"}


@router.post("/check-files")
async def check_files_after_draft(
    chat_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Phase 5: запустить Update Mode с уже применённым state_patch как
    обязательным контекстом. LLM генерирует ТОЛЬКО file_changes, отражающие
    принятые изменения в .md документах кампании.

    Используется потоком:
    1. Фоновый drift-loop создаёт auto-draft (Phase 3).
    2. Пользователь делает Accept — state_patch применяется.
    3. Пользователь нажимает «Применить и проверить файлы» — этот endpoint.
    4. Открывается UpdateModePanel с уже сгенерированными file_changes.

    После успеха draft и drift очищаются (пользователь уже принял решения).
    """
    chat = await _load_chat_or_404(chat_id, db)
    if chat.campaign_id is None:
        raise HTTPException(status_code=422, detail="campaign_required")

    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(status_code=503, detail="redis_unavailable")

    draft_key = _draft_key(str(chat.campaign_id), chat_id)
    raw = await redis.get(draft_key)
    if raw is None:
        raise HTTPException(status_code=404, detail="draft_not_found")

    draft = _parse_draft_raw(raw)
    raw_patch = draft.get("state_patch") or []
    if not isinstance(raw_patch, list):
        raise HTTPException(status_code=400, detail="invalid_patch")
    if not raw_patch:
        raise HTTPException(status_code=422, detail="empty_state_patch")

    # Validate the stored state_patch payload early — better to fail here
    # than inside the executor (where errors are less obvious).
    operations = _parse_state_patch(raw_patch)

    # Build proposal: empty state_patch/field_changes — patch comes via context.
    summary = str(draft.get("summary") or "")
    note = f"Примени уже подтверждённые изменения контекста в файлы .md: {summary}".strip()
    from shared_contracts.models import ContextUpdateProposal

    proposal = ContextUpdateProposal(
        state_patch=[],
        field_changes=[],
        file_changes=[],
        confidence=1.0,
        reason=note,
        review_summary="from auto-draft",
    )

    # Lazy import: executor pulls in heavy deps (pydantic, settings, etc.)
    from app.services.indexer_client import indexer_client
    from app.services.update_mode_executor import (
        UpdateModeExecutor,
        UpdateModeGenerationProviderUnavailableError,
        UpdateModeIndexerInvalidResponseError,
        UpdateModeIndexerUnavailableError,
        UpdateModeInvalidGenerationOutputError,
        UpdateModeNoIndexedMarkdownError,
        UpdateModeNoRelevantContextError,
        UpdateModeNoUsableContextError,
    )
    from app.services.update_mode_store import update_mode_store

    executor = UpdateModeExecutor(
        db=db,
        store=update_mode_store,
        indexer_client=indexer_client,
    )

    state_patch_context = [op.model_dump() for op in operations]

    try:
        session = await executor.start_from_proposal(
            chat_id=chat_id,
            redis=redis,
            proposal=proposal,
            state_patch_context=state_patch_context,
        )
    except UpdateModeNoIndexedMarkdownError:
        raise HTTPException(status_code=422, detail="no_indexed_markdown")
    except UpdateModeNoRelevantContextError:
        raise HTTPException(status_code=422, detail="no_relevant_context")
    except UpdateModeNoUsableContextError:
        raise HTTPException(status_code=422, detail="no_usable_context")
    except UpdateModeInvalidGenerationOutputError:
        raise HTTPException(status_code=422, detail="invalid_generation_output")
    except UpdateModeGenerationProviderUnavailableError:
        raise HTTPException(status_code=503, detail="generation_provider_unavailable")
    except UpdateModeIndexerUnavailableError:
        raise HTTPException(status_code=503, detail="indexer_unavailable")
    except UpdateModeIndexerInvalidResponseError:
        raise HTTPException(status_code=502, detail="indexer_invalid_response")

    # Очищаем draft и drift после успешного создания session.
    await redis.delete(draft_key)

    from app.services.context_engine.scene_memory import clear_drift

    await clear_drift(chat_id, db)

    audit = AuditLog(
        action="context_draft_check_files",
        entity_type="chat",
        entity_id=chat_id,
        payload={
            "campaign_id": str(chat.campaign_id),
            "session_id": session.session_id,
            "applied_state_patch_count": len(operations),
        },
    )
    db.add(audit)
    await db.commit()

    return {
        "session_id": session.session_id,
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
        "applied_state_patch_count": len(operations),
    }
