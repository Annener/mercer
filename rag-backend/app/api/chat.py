from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, Chat, ClarificationStateRow, Message
from app.db.session import get_db
from app.services import settings_service
from app.services.pipeline_executor import PipelineExecutor
from app.services.pipeline_router import PipelineRouter
from app.services.vault_config_service import VaultConfigService
from shared_contracts.models import (
    ChatMessage,
    ChatRecord,
    ClarificationAnswer,
    ClarificationResponse,
    CreateChatRequest,
    CreateChatResponse,
    PipelineExecutionContext,
    SendMessageRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

config_for_vault = VaultConfigService()


class CreateChatRequest(BaseModel):
    """
    domain_id — основной идентификатор контекста чата.
    vault_id оставлен nullable для back-compat (старые клиенты).
    campaign_id — опциональная привязка к кампании (iter2).
    TODO(iter4-cleanup): сделать domain_id обязательным, убрать vault_id.
    """
    domain_id: str | None = None
    vault_id: str | None = None  # deprecated back-compat
    campaign_id: str | None = None


class RenameChatRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChatHistoryResponse(BaseModel):
    chat: ChatRecord
    messages: list[ChatMessage]
    vault_enabled: bool = False


# BUG FIX #5: добавлено поле vault_enabled, которое ранее вычислялось
# в list_chats но отсутствовало в модели → Pydantic молча его отбрасывал.
class ChatListItem(BaseModel):
    chat_id: str
    title: str
    vault_id: str | None = None
    domain_id: str | None = None
    vault_enabled: bool = False
    created_at: datetime
    updated_at: datetime


class ChatListResponse(BaseModel):
    chats: list[ChatListItem]


class MessageResponse(BaseModel):
    content: str
    message_id: str


class PipelineLockRequest(BaseModel):
    pipeline_id: str | None = None


@router.post("/create", response_model=CreateChatResponse)
async def create_chat(
    req: CreateChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CreateChatResponse:
    # BUG FIX #1: явная валидация формата campaign_id перед вызовом uuid.UUID,
    # чтобы получить 422 вместо 500 при невалидном значении.
    campaign_uuid: uuid.UUID | None = None
    if req.campaign_id:
        try:
            campaign_uuid = uuid.UUID(req.campaign_id)
        except ValueError as exc:
            raise HTTPException(422, f"Invalid campaign_id format: {req.campaign_id}") from exc

    chat = Chat(
        title="New Chat",
        vault_id=req.vault_id,
        domain_id=req.domain_id,
        campaign_id=campaign_uuid,
        pipeline_versions=await _pipeline_versions(request),
    )
    db.add(chat)
    await db.flush()
    db.add(ClarificationStateRow(chat_id=chat.id, stage="idle"))
    await _audit(
        db,
        "chat.create",
        "chat",
        str(chat.id),
        {"vault_id": req.vault_id, "domain_id": req.domain_id, "campaign_id": req.campaign_id},
    )
    await db.commit()
    logger.info("Created chat: chat_id=%s", chat.id)
    return CreateChatResponse(chat_id=str(chat.id), title=chat.title)


@router.get("/list", response_model=ChatListResponse)
async def list_chats(
    domain_id: str | None = Query(default=None, description="Фильтр по домену"),
    db: AsyncSession = Depends(get_db),
) -> ChatListResponse:
    stmt = select(Chat).order_by(Chat.updated_at.desc())
    if domain_id is not None:
        stmt = stmt.where(Chat.domain_id == domain_id)
    result = await db.execute(stmt)
    chats = result.scalars().all()
    return ChatListResponse(
        chats=[
            ChatListItem(
                chat_id=str(c.id),
                title=c.title,
                vault_id=c.vault_id,
                domain_id=c.domain_id,
                vault_enabled=await _vault_enabled(db, c.vault_id),
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in chats
        ]
    )


@router.get("/{chat_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
) -> ChatHistoryResponse:
    chat = await _get_chat_or_404(chat_id, db)
    stmt = select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return ChatHistoryResponse(
        chat=ChatRecord.model_validate(chat, from_attributes=True),
        messages=[
            ChatMessage(
                message_id=str(m.id),
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                pipeline_id=m.pipeline_id,
            )
            for m in messages
        ],
        vault_enabled=await _vault_enabled(db, chat.vault_id),
    )


@router.post("/{chat_id}/rename", response_model=CreateChatResponse)
async def rename_chat(
    chat_id: str,
    req: RenameChatRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateChatResponse:
    chat = await _get_chat_or_404(chat_id, db)
    chat.title = req.title
    await db.commit()
    return CreateChatResponse(chat_id=str(chat.id), title=chat.title)


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: str, db: AsyncSession = Depends(get_db)) -> None:
    chat = await _get_chat_or_404(chat_id, db)
    await db.delete(chat)
    await db.commit()


@router.post("/{chat_id}/lock_pipeline", response_model=dict)
async def lock_pipeline(
    chat_id: str,
    req: PipelineLockRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    chat = await _get_chat_or_404(chat_id, db)
    chat.locked_pipeline_id = req.pipeline_id
    await db.commit()
    return {"status": "ok", "locked_pipeline_id": req.pipeline_id}


@router.post("/{chat_id}/send", response_model=MessageResponse)
async def send_message(
    chat_id: str,
    req: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    chat = await _get_chat_or_404(chat_id, db)

    user_msg = Message(chat_id=chat.id, role="user", content=req.content)
    db.add(user_msg)
    await db.flush()

    # BUG FIX #8: domain_id и retrieval_strategy вычисляются один раз,
    # ранее domain_id вызывался дважды (_domain_id_for_chat), а retrieval_strategy
    # дублировался — одно присвоение при создании context и ещё одно после pipeline.
    domain_id = await _domain_id_for_chat(chat, db) or chat.domain_id
    vault_ids: list[str] = [
        v.vault_id for v in config_for_vault.vaults.values()
        if v.domain_id == domain_id and v.enabled
    ] if domain_id else []

    retrieval_strategy = (
        "semantic" if chat.vault_id and await settings_service.get("retrieval.enabled", db)
        else "none"
    )

    context = PipelineExecutionContext(
        chat_id=str(chat.id),
        message_id=str(user_msg.id),
        query=req.content,
        domain_id=domain_id,
        campaign_id=str(chat.campaign_id) if chat.campaign_id else None,
        vault_id=chat.vault_id,
        vault_ids=vault_ids,
        retrieval_strategy=retrieval_strategy,
    )

    pipeline_router = PipelineRouter(db)
    pipeline = await pipeline_router.select(
        context,
        locked_pipeline_id=chat.locked_pipeline_id,
    )
    if pipeline is None:
        raise HTTPException(503, "No active pipeline found for this domain")

    context.pipeline_id = pipeline.pipeline_id
    context.pipeline_version = pipeline.version
    context.steps = pipeline.steps
    context.final_composition = pipeline.final_composition
    # retrieval_strategy больше не переприсваивается здесь повторно

    history_stmt = select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at).limit(20)
    history_result = await db.execute(history_stmt)
    context.history = [
        ChatMessage(
            message_id=str(m.id),
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            pipeline_id=m.pipeline_id,
        )
        for m in history_result.scalars().all()
    ]

    executor = PipelineExecutor(db)
    result = await executor.run(context)

    assistant_msg = Message(
        chat_id=chat.id,
        role="assistant",
        content=result.final_answer,
        pipeline_id=pipeline.pipeline_id,
    )
    db.add(assistant_msg)
    await db.commit()

    # Auto-rename chat on first exchange
    if chat.title == "New Chat":
        chat.title = _auto_title(req.content)
        await db.commit()

    return MessageResponse(content=result.final_answer, message_id=str(assistant_msg.id))


@router.post("/{chat_id}/send_stream")
async def send_message_stream(
    chat_id: str,
    req: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    from fastapi.responses import StreamingResponse

    chat = await _get_chat_or_404(chat_id, db)

    user_msg = Message(chat_id=chat.id, role="user", content=req.content)
    db.add(user_msg)
    await db.flush()

    # BUG FIX #8 (stream): приведено в соответствие с send_message —
    # retrieval_strategy вычисляется один раз и явно передаётся в context.
    domain_id = await _domain_id_for_chat(chat, db) or chat.domain_id
    vault_ids: list[str] = [
        v.vault_id for v in config_for_vault.vaults.values()
        if v.domain_id == domain_id and v.enabled
    ] if domain_id else []

    retrieval_strategy = (
        "semantic" if chat.vault_id and await settings_service.get("retrieval.enabled", db)
        else "none"
    )

    context = PipelineExecutionContext(
        chat_id=str(chat.id),
        message_id=str(user_msg.id),
        query=req.content,
        domain_id=domain_id,
        campaign_id=str(chat.campaign_id) if chat.campaign_id else None,
        vault_ids=vault_ids,
        vault_id=chat.vault_id,
        pipeline_id="",
        pipeline_version="",
        steps=[],
        final_composition=None,  # type: ignore[arg-type]
        history=[],
        retrieval_strategy=retrieval_strategy,
    )

    pipeline_router = PipelineRouter(db)
    pipeline = await pipeline_router.select(
        context,
        locked_pipeline_id=chat.locked_pipeline_id,
    )
    if pipeline is None:
        raise HTTPException(503, "No active pipeline found for this domain")

    context.pipeline_id = pipeline.pipeline_id
    context.pipeline_version = pipeline.version
        context.steps = pipeline.steps
    context.final_composition = pipeline.final_composition

    history_stmt = select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at).limit(20)
    history_result = await db.execute(history_stmt)
    context.history = [
        ChatMessage(
            message_id=str(m.id),
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            pipeline_id=m.pipeline_id,
        )
        for m in history_result.scalars().all()
    ]

    async def event_stream() -> AsyncIterator[str]:
        executor = PipelineExecutor(db)
        full_answer = ""
        assistant_msg_id: str | None = None

        async for chunk in executor.run_stream(context):
            # BUG FIX C: переименован тип чанка delta→token.
            # chat.js обрабатывает только type==="token" для рендера текста во время стриминга.
            # С type==="delta" текст накапливался внутри but not рендерился до конца стрима.
            if chunk.get("type") == "delta":
                chunk = {**chunk, "type": "token"}
            data = json.dumps(chunk, ensure_ascii=False)
            yield f"data: {data}\n\n"
            if chunk.get("type") == "token":
                full_answer += chunk.get("content", "")
            elif chunk.get("type") == "done":
                assistant_msg_id = chunk.get("message_id")

        if full_answer:
            assistant_msg = Message(
                chat_id=chat.id,
                role="assistant",
                content=full_answer,
                pipeline_id=pipeline.pipeline_id,
            )
            db.add(assistant_msg)
            await db.commit()
            if chat.title == "New Chat":
                chat.title = _auto_title(req.content)
                await db.commit()

        # BUG FIX B: эмитим [DONE] в конце стрима.
        # chat.js ждёт 'data: [DONE]' чтобы выставить флаг streamDone.
        # Без этого флаг не выставлялся, хотя цикл всё равно завершался через reader.read() done.
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{chat_id}/clarify", response_model=ClarificationResponse)
async def submit_clarification(
    chat_id: str,
    req: ClarificationAnswer,
    db: AsyncSession = Depends(get_db),
) -> ClarificationResponse:
    """Accept clarification answers and trigger pipeline execution."""
    from app.services.clarification_service import ClarificationService
    svc = ClarificationService(db)
    return await svc.handle_answer(chat_id, req)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_chat_or_404(chat_id: str, db: AsyncSession) -> Chat:
    chat = await db.get(Chat, uuid.UUID(chat_id))
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


async def _vault_enabled(db: AsyncSession, vault_id: str | None) -> bool:
    if not vault_id:
        return False
    return await settings_service.get("retrieval.enabled", db)


async def _domain_id_for_chat(chat: Chat, db: AsyncSession) -> str | None:
    """Resolve domain_id: prefer chat.domain_id, fall back to campaign.domain_id."""
    if chat.domain_id:
        return chat.domain_id
    if chat.campaign_id:
        campaign = await db.get(Campaign, chat.campaign_id)
        if campaign is not None and campaign.domain_id:
            return campaign.domain_id
    return None


async def _audit(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    from app.db.models import AuditLog
    db.add(AuditLog(action=action, entity_type=entity_type, entity_id=entity_id, payload=payload))


async def _pipeline_versions(request: Request) -> dict[str, str]:
    """Extract X-Pipeline-Version headers for reproducibility tracking."""
    return {
        k.removeprefix("x-pipeline-"): v
        for k, v in request.headers.items()
        if k.lower().startswith("x-pipeline-")
    }


def _auto_title(query: str) -> str:
    """Generate a short chat title from the first user message."""
    import re
    cleaned = re.sub(r"[^\w\s\u0400-\u04ff]", " ", query).strip()
    words = cleaned.split()
    if len(words) > 7:
        cleaned = " ".join(words[:7])
    return cleaned[:255]
