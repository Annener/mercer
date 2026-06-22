from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Chat, Message
from app.services.pipeline_executor import PipelineExecutor
from app.services.settings_service import settings_service
from app.services.vault_config import config_for_vault
from shared_contracts.models import (
    ChatMessage,
    PipelineExecutionContext,
    PipelineStep,
    SearchHit,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class PipelineResumeRequest(BaseModel):
    resume_token: str
    answer: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_chat_or_404(chat_id: str, db: AsyncSession) -> Chat:
    try:
        uid = uuid.UUID(chat_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid chat_id format")
    chat = await db.get(Chat, uid)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


def _restore_context(snapshot: dict) -> PipelineExecutionContext:
    history_raw = snapshot.pop("history", None) or []
    history: list[ChatMessage] = []
    for item in history_raw:
        if isinstance(item, dict):
            try:
                history.append(ChatMessage(**item))
            except Exception:
                pass
        elif isinstance(item, ChatMessage):
            history.append(item)

    steps_raw = snapshot.pop("steps", None) or []
    steps: list[PipelineStep] = []
    for item in steps_raw:
        if isinstance(item, dict):
            try:
                steps.append(PipelineStep(**item))
            except Exception:
                pass
        elif isinstance(item, PipelineStep):
            steps.append(item)

    ctx = PipelineExecutionContext(**snapshot)
    ctx.history = history
    ctx.steps = steps
    return ctx


async def _fallback_retrieve(
    query: str,
    vault_id: str | None,
    vault_ids: list[str],
    db: AsyncSession,
) -> list[SearchHit]:
    from app.services.retrieval import retrieve, retrieve_multi_vault

    effective = vault_ids or ([vault_id] if vault_id else [])
    if not effective:
        return []

    top_k = int(await settings_service.get("retrieval.top_k"))
    if len(effective) == 1:
        return await retrieve(query, effective[0], top_k=top_k, db=db)
    return await retrieve_multi_vault(query, effective, top_k=top_k, db=db)


async def _plain_rag_stream(
    context: PipelineExecutionContext,
    request: Request,
    db: AsyncSession,
) -> AsyncIterator[str]:
    """Fallback: plain RAG stream without pipeline (used after validation complete)."""
    provider = settings_service.get_active_provider()
    if provider is None:
        yield f"data: {json.dumps({'type': 'error', 'message': 'No active model configured'}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    messages: list[dict] = []

    retrieval_enabled = await settings_service.get("retrieval.enabled", db)
    if retrieval_enabled and (context.vault_id or context.vault_ids):
        yield f"data: {json.dumps({'type': 'step_status', 'text': 'Searching knowledge base...'}, ensure_ascii=False)}\n\n"
        hits: list[SearchHit] = await _fallback_retrieve(
            context.query,
            context.vault_id,
            context.vault_ids or [],
            db,
        )
        if hits:
            from app.services.retrieval import format_context_with_role
            ctx_text = format_context_with_role(hits, None)
            messages.append({"role": "system", "content": f"Context:\n{ctx_text}"})

    messages.append({"role": "user", "content": context.query})

    yield f"data: {json.dumps({'type': 'step_status', 'text': 'Generating response...'}, ensure_ascii=False)}\n\n"
    full_answer = ""
    async for token in provider.generate_stream(messages):
        full_answer += token
        chunk = json.dumps({"type": "token", "content": token}, ensure_ascii=False)
        yield f"data: {chunk}\n\n"
        if await request.is_disconnected():
            break

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Resume endpoint
# ---------------------------------------------------------------------------

@router.post("/{chat_id}/resume")
async def resume_pipeline(
    chat_id: str,
    req: PipelineResumeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    chat = await _get_chat_or_404(chat_id, db)

    pause_state = chat.pipeline_pause_state
    if not pause_state:
        raise HTTPException(status_code=400, detail="No pending pipeline validation")

    if pause_state.get("resume_token") != req.resume_token:
        raise HTTPException(status_code=403, detail="Invalid resume token")

    from datetime import UTC, datetime
    expires_at_raw = pause_state.get("expires_at")
    if expires_at_raw:
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
            if datetime.now(UTC) > expires_at:
                raise HTTPException(status_code=410, detail="Resume token expired")
        except ValueError:
            pass

    snapshot = pause_state.get("context_snapshot", {})
    if snapshot:
        context = _restore_context(dict(snapshot))
    else:
        raise HTTPException(status_code=500, detail="Missing context snapshot")

    if req.answer is not None:
        context.step_results[pause_state["step_id"]] = req.answer

    validated_step_id = pause_state["step_id"]

    chat.pipeline_pause_state = None
    await db.commit()

    history_stmt = (
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.created_at)
        .limit(20)
    )
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

    await config_for_vault.ensure_loaded(db)

    async def resume_stream() -> AsyncIterator[str]:
        executor = PipelineExecutor(db)
        full_answer = ""
        cancelled = False
        has_pipeline_steps = bool(context.steps)

        if has_pipeline_steps:
            try:
                async for chunk in executor.resume_from_validation(context, validated_step_id):
                    chunk_type = chunk.get("type", "")

                    if chunk_type == "step_status":
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                        continue

                    if chunk_type == "validation_required":
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    if chunk_type == "token":
                        full_answer += chunk.get("content", "")
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                        if await request.is_disconnected():
                            cancelled = True
                            break
                        continue

                    if chunk_type == "pipeline_complete":
                        break

                    if chunk_type in ("step_complete", "step_skipped_no_docs", "step_error", "pipeline_selected"):
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                        continue

                    if chunk_type == "error":
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

            except Exception as exc:
                logger.error("resume_stream pipeline error: %s", exc, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
        else:
            async for sse_chunk in _plain_rag_stream(context, request, db):
                if sse_chunk.strip() == "data: [DONE]":
                    cancelled = False
                    break
                yield sse_chunk
                if await request.is_disconnected():
                    cancelled = True
                    break

        if not cancelled and full_answer:
            assistant_msg = Message(
                chat_id=chat.id,
                role="assistant",
                content=full_answer,
                pipeline_id=context.pipeline_id,
            )
            db.add(assistant_msg)
            await db.commit()

        yield "data: [DONE]\n\n"

    return StreamingResponse(resume_stream(), media_type="text/event-stream")
