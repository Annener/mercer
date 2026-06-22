"""
pipeline_resume.py — API endpoints для управления жизненным циклом пайплайна.

POST /chat/{chat_id}/pipeline_confirm  — подтверждение/отмена запуска пайплайна
POST /chat/{chat_id}/pipeline_resume   — продолжение/отмена после validation-паузы

Оба endpoint'а возвращают SSE-стрим (text/event-stream).

Структура JSONB-полей в chats:
  pending_pipeline_confirm:
    {pipeline_id, pipeline_name, reasoning, confirm_token, query, context_snapshot, expires_at}
  pipeline_pause_state:
    {pipeline_id, step_id, resume_token, step_results, query, context_snapshot, expires_at}
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat, Message
from app.db.session import get_db
from app.services.pipeline_executor import PipelineExecutor
from app.services.settings_service import settings_service
from shared_contracts.models import (
    ChatMessage,
    PipelineExecutionContext,
    SearchHit,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class PipelineConfirmRequest(BaseModel):
    confirm_token: str
    confirmed: bool


class PipelineResumeRequest(BaseModel):
    resume_token: str
    user_feedback: str | None = None
    cancelled: bool = False


# ---------------------------------------------------------------------------
# POST /chat/{chat_id}/pipeline_confirm
# ---------------------------------------------------------------------------

@router.post("/{chat_id}/pipeline_confirm")
async def pipeline_confirm(
    chat_id: str,
    req: PipelineConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Подтверждение или отмена запуска пайплайна.

    confirmed=true  → проверить токен, запустить executor → SSE-стрим
    confirmed=false → очистить pending_pipeline_confirm → plain RAG SSE-стрим
    Просроченный токен → 410 Gone
    """
    chat = await _get_chat_or_404(chat_id, db)
    pending = chat.pending_pipeline_confirm

    if not pending:
        raise HTTPException(404, "No pending pipeline confirmation for this chat")

    # Проверка токена
    if pending.get("confirm_token") != req.confirm_token:
        raise HTTPException(403, "Invalid confirm_token")

    # Проверка срока действия
    expires_at_raw = pending.get("expires_at")
    if expires_at_raw:
        expires_at = datetime.fromisoformat(expires_at_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires_at:
            # Очищаем протухший pending
            chat.pending_pipeline_confirm = None
            await db.commit()
            raise HTTPException(410, "Confirmation token has expired")

    if not req.confirmed:
        # Пользователь отказался — очищаем pending, отдаём plain RAG fallback
        chat.pending_pipeline_confirm = None
        await db.commit()

        async def cancelled_stream() -> AsyncIterator[str]:
            cancelled_chunk = json.dumps(
                {
                    "type": "pipeline_cancelled",
                    "step_name": pending.get("pipeline_name", ""),
                },
                ensure_ascii=False,
            )
            yield f"data: {cancelled_chunk}\n\n"

            # Plain RAG fallback
            context_snapshot: dict[str, Any] = pending.get("context_snapshot", {})
            ctx = _restore_context(context_snapshot, chat_id)

            async for chunk in _plain_rag_stream(ctx, chat, db):
                yield chunk

            yield "data: [DONE]\n\n"

        return StreamingResponse(cancelled_stream(), media_type="text/event-stream")

    # confirmed=true — восстанавливаем контекст и запускаем executor
    context_snapshot: dict[str, Any] = pending.get("context_snapshot", {})
    chat.pending_pipeline_confirm = None
    await db.commit()

    ctx = _restore_context(context_snapshot, chat_id)

    async def confirmed_stream() -> AsyncIterator[str]:
        from app.api.chat import _maybe_set_title
        executor = PipelineExecutor(db)
        full_answer = ""

        async for chunk in executor.run_stream(ctx):
            if chunk.get("type") == "delta":
                chunk = {**chunk, "type": "token"}
            data = json.dumps(chunk, ensure_ascii=False)
            yield f"data: {data}\n\n"
            if chunk.get("type") == "token":
                full_answer += chunk.get("content", "")

        if full_answer:
            pipeline_id = context_snapshot.get("pipeline_id")
            assistant_msg = Message(
                chat_id=uuid.UUID(chat_id),
                role="assistant",
                content=full_answer,
                pipeline_id=pipeline_id,
            )
            db.add(assistant_msg)
            await db.commit()
            await _maybe_set_title(chat, ctx.original_query or ctx.query, db)
            await db.commit()

        yield "data: [DONE]\n\n"

    return StreamingResponse(confirmed_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# POST /chat/{chat_id}/pipeline_resume
# ---------------------------------------------------------------------------

@router.post("/{chat_id}/pipeline_resume")
async def pipeline_resume(
    chat_id: str,
    req: PipelineResumeRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Продолжение или отмена пайплайна после validation-паузы.

    cancelled=true  → очистить pipeline_pause_state → SSE-чанк pipeline_cancelled
    cancelled=false → восстановить контекст, добавить feedback, продолжить executor → SSE-стрим
    Просроченный токен → 410 Gone
    """
    chat = await _get_chat_or_404(chat_id, db)
    pause_state = chat.pipeline_pause_state

    if not pause_state:
        raise HTTPException(404, "No active pipeline pause state for this chat")

    # Проверка токена
    if pause_state.get("resume_token") != req.resume_token:
        raise HTTPException(403, "Invalid resume_token")

    # Проверка срока действия
    expires_at_raw = pause_state.get("expires_at")
    if expires_at_raw:
        expires_at = datetime.fromisoformat(expires_at_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires_at:
            chat.pipeline_pause_state = None
            await db.commit()
            raise HTTPException(410, "Resume token has expired")

    paused_step_id: str = pause_state.get("step_id", "")
    step_name: str = pause_state.get("step_name", paused_step_id)

    if req.cancelled:
        chat.pipeline_pause_state = None
        await db.commit()

        async def cancel_stream() -> AsyncIterator[str]:
            cancelled_chunk = json.dumps(
                {"type": "pipeline_cancelled", "step_name": step_name},
                ensure_ascii=False,
            )
            yield f"data: {cancelled_chunk}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(cancel_stream(), media_type="text/event-stream")

    # cancelled=false → продолжаем
    context_snapshot: dict[str, Any] = pause_state.get("context_snapshot", {})
    step_results: dict[str, Any] = pause_state.get("step_results", {})

    # Добавляем feedback validation-шага в step_results
    feedback_key = f"_validation_{paused_step_id}"
    step_results[feedback_key] = req.user_feedback or ""

    # Очищаем состояние паузы
    chat.pipeline_pause_state = None
    await db.commit()

    ctx = _restore_context(context_snapshot, chat_id)
    ctx.step_results = step_results

    async def resume_stream() -> AsyncIterator[str]:
        from app.api.chat import _maybe_set_title
        # Уведомляем фронтенд о возобновлении
        resumed_chunk = json.dumps(
            {
                "type": "pipeline_resumed",
                "step_name": step_name,
                "user_feedback_preview": (req.user_feedback or "")[:100],
            },
            ensure_ascii=False,
        )
        yield f"data: {resumed_chunk}\n\n"

        executor = PipelineExecutor(db)
        full_answer = ""

        async for chunk in executor.resume_from_validation(ctx, paused_step_id):
            if chunk.get("type") == "delta":
                chunk = {**chunk, "type": "token"}
            data = json.dumps(chunk, ensure_ascii=False)
            yield f"data: {data}\n\n"
            if chunk.get("type") == "token":
                full_answer += chunk.get("content", "")

        if full_answer:
            pipeline_id = context_snapshot.get("pipeline_id")
            assistant_msg = Message(
                chat_id=uuid.UUID(chat_id),
                role="assistant",
                content=full_answer,
                pipeline_id=pipeline_id,
            )
            db.add(assistant_msg)
            await db.commit()
            await _maybe_set_title(chat, ctx.original_query or ctx.query, db)
            await db.commit()

        yield "data: [DONE]\n\n"

    return StreamingResponse(resume_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_chat_or_404(chat_id: str, db: AsyncSession) -> Chat:
    try:
        chat_uuid = uuid.UUID(chat_id)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid chat_id format: {chat_id}") from exc
    chat = await db.get(Chat, chat_uuid)
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


def _restore_context(snapshot: dict[str, Any], chat_id: str) -> PipelineExecutionContext:
    """Восстанавливает PipelineExecutionContext из JSONB-снапшота.

    Гарантирует chat_id — на случай если снапшот не содержит его.
    Генерирует дефолтный message_id если снапшот не содержит его
    (старые записи до Этапа 1 или неполные снапшоты).
    Генерирует дефолтный query="" если снапшот не содержит его.
    """
    ctx_data = {
        "query": "",  # дефолт, если отсутствует в снапшоте
        "message_id": str(uuid.uuid4()),  # дефолт, если отсутствует в снапшоте
        **snapshot,
        "chat_id": chat_id,  # всегда перезаписываем из chat_id URL-параметра
    }
    return PipelineExecutionContext.model_validate(ctx_data)


async def _plain_rag_stream(
    ctx: PipelineExecutionContext,
    chat: Chat,
    db: AsyncSession,
) -> AsyncIterator[str]:
    """Fallback plain RAG стрим — используется при отмене confirm."""
    from app.api.chat import _fallback_retrieve, _resolve_system_prompt
    from app.services.retrieval import format_context

    provider = settings_service.get_active_provider()
    if provider is None:
        error_data = json.dumps(
            {"type": "error", "message": "No LLM provider configured"},
            ensure_ascii=False,
        )
        yield f"data: {error_data}\n\n"
        return

    system_prompt = await _resolve_system_prompt(ctx.campaign_id, ctx.domain_id, db)
    vault_ids: list[str] = ctx.vault_ids or []

    hits: list[SearchHit] = await _fallback_retrieve(
        query=ctx.query,
        vault_ids=vault_ids,
        domain_id=ctx.domain_id,
        campaign_id=ctx.campaign_id,
        db=db,
    )

    rag_context = format_context(hits)
    full_system = f"{system_prompt}\n\n{rag_context}" if rag_context else system_prompt

    messages: list[dict[str, str]] = []
    if full_system:
        messages.append({"role": "system", "content": full_system})
    for m in (ctx.history or []):
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": ctx.query})

    full_answer = ""
    async for token in provider.generate_stream(messages):
        full_answer += token
        chunk = json.dumps({"type": "token", "content": token}, ensure_ascii=False)
        yield f"data: {chunk}\n\n"

    if full_answer:
        assistant_msg = Message(
            chat_id=chat.id,
            role="assistant",
            content=full_answer,
        )
        db.add(assistant_msg)
        await db.commit()
        if chat.title == "New Chat":
            from app.api.chat import _auto_title
            chat.title = _auto_title(ctx.original_query or ctx.query)
            await db.commit()
