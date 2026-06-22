from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Campaign, Chat, Domain, Message
from app.schemas.chat import (
    ChatCreate,
    ChatListResponse,
    ChatResponse,
    MessageResponse,
    SendMessageRequest,
)
from app.services.clarification_fsm import clarification_fsm
from app.services.domain_service import domain_service
from app.services.pipeline_executor import PipelineExecutor
from app.services.pipeline_router import PipelineRouter
from app.services.planner import Planner
from app.services.prompt_pack import PromptPack
from app.services.query_rewriter import query_rewriter
from app.services.settings_service import settings_service
from app.services.vault_config import config_for_vault
from shared_contracts.models import ChatMessage, PipelineExecutionContext, SearchHit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chats", tags=["chats"])


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


async def _domain_id_for_chat(chat: Chat, db: AsyncSession) -> str | None:
    if chat.domain_id:
        return str(chat.domain_id)
    if chat.campaign_id:
        campaign = await db.get(Campaign, chat.campaign_id)
        if campaign and campaign.domain_id:
            return str(campaign.domain_id)
    return None


async def _maybe_set_title(chat: Chat, query: str, db: AsyncSession) -> None:
    if not chat.title or chat.title == "New chat":
        chat.title = query[:60]
        await db.commit()


async def _plain_llm_reply(
    content: str,
    context: PipelineExecutionContext,
    domain_id: str | None,
    db: AsyncSession,
) -> str:
    provider = settings_service.get_active_provider()
    if provider is None:
        return "No active model configured."

    system_prompt = await _resolve_system_prompt(context.campaign_id, domain_id, db)
    messages = [
        {"role": "system", "content": system_prompt},
        *[
            {"role": m.role, "content": m.content}
            for m in (context.history or [])
        ],
        {"role": "user", "content": content},
    ]
    return await provider.generate(messages)


async def _resolve_system_prompt(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
) -> str:
    if campaign_id:
        try:
            cid = uuid.UUID(campaign_id)
        except ValueError:
            pass
        else:
            campaign = await db.get(Campaign, cid)
            if campaign and campaign.system_prompt:
                return campaign.system_prompt

    if domain_id:
        prompts = await domain_service.get_prompts(domain_id, db)
        if prompts and prompts.get("system_prompt"):
            return prompts["system_prompt"]

    return "You are a helpful assistant."


async def _fallback_retrieve(
    query: str,
    vault_id: str | None,
    vault_ids: list[str],
    db: AsyncSession,
) -> list[SearchHit]:
    from app.services.retrieval import retrieve, retrieve_multi_vault

    if not vault_ids and not vault_id:
        return []

    effective_vault_ids = vault_ids or ([vault_id] if vault_id else [])
    if not effective_vault_ids:
        return []

    top_k = int(await settings_service.get("retrieval.top_k"))
    if len(effective_vault_ids) == 1:
        return await retrieve(query, effective_vault_ids[0], top_k=top_k, db=db)
    return await retrieve_multi_vault(query, effective_vault_ids, top_k=top_k, db=db)


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    payload: ChatCreate,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    domain_id: uuid.UUID | None = None
    if payload.domain_id:
        try:
            domain_id = uuid.UUID(payload.domain_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid domain_id")

    vault_id: uuid.UUID | None = None
    if payload.vault_id:
        try:
            vault_id = uuid.UUID(payload.vault_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid vault_id")

    campaign_id: uuid.UUID | None = None
    if payload.campaign_id:
        try:
            campaign_id = uuid.UUID(payload.campaign_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid campaign_id")

    chat = Chat(
        title=payload.title or "New chat",
        domain_id=domain_id,
        vault_id=vault_id,
        campaign_id=campaign_id,
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return ChatResponse(
        chat_id=str(chat.id),
        title=chat.title,
        domain_id=str(chat.domain_id) if chat.domain_id else None,
        vault_id=str(chat.vault_id) if chat.vault_id else None,
        campaign_id=str(chat.campaign_id) if chat.campaign_id else None,
    )


@router.get("", response_model=ChatListResponse)
async def list_chats(
    db: AsyncSession = Depends(get_db),
) -> ChatListResponse:
    result = await db.execute(select(Chat).order_by(Chat.created_at.desc()))
    chats = result.scalars().all()
    return ChatListResponse(
        chats=[
            ChatResponse(
                chat_id=str(c.id),
                title=c.title,
                domain_id=str(c.domain_id) if c.domain_id else None,
                vault_id=str(c.vault_id) if c.vault_id else None,
                campaign_id=str(c.campaign_id) if c.campaign_id else None,
            )
            for c in chats
        ]
    )


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    chat = await _get_chat_or_404(chat_id, db)
    return ChatResponse(
        chat_id=str(chat.id),
        title=chat.title,
        domain_id=str(chat.domain_id) if chat.domain_id else None,
        vault_id=str(chat.vault_id) if chat.vault_id else None,
        campaign_id=str(chat.campaign_id) if chat.campaign_id else None,
    )


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    chat = await _get_chat_or_404(chat_id, db)
    await db.delete(chat)
    await db.commit()


@router.get("/{chat_id}/messages")
async def get_messages(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    chat = await _get_chat_or_404(chat_id, db)
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return [
        {
            "message_id": str(m.id),
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
            "pipeline_id": m.pipeline_id,
        }
        for m in messages
    ]


@router.patch("/{chat_id}")
async def update_chat(
    chat_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    chat = await _get_chat_or_404(chat_id, db)
    if "title" in payload:
        chat.title = payload["title"]
    if "locked_pipeline_id" in payload:
        chat.locked_pipeline_id = payload["locked_pipeline_id"]
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Send message (non-streaming)
# ---------------------------------------------------------------------------

@router.post("/{chat_id}/send", response_model=MessageResponse)
async def send_message(
    chat_id: str,
    req: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    chat = await _get_chat_or_404(chat_id, db)

    clarif_state = await clarification_fsm.get_state(db, chat.id)
    if clarif_state.stage == "collecting":
        max_turns: int = int(await settings_service.get("chat.max_clarification_turns", db))
        prompt_pack = PromptPack(await domain_service.get_prompts(
            chat.domain_id or "default", db
        ))
        new_state = clarification_fsm.process_clarification_answer(
            clarif_state, req.content, max_turns, prompt_pack
        )
        await clarification_fsm.save_state(db, chat.id, new_state)

        if new_state.stage == "collecting":
            user_msg = Message(chat_id=chat.id, role="user", content=req.content)
            db.add(user_msg)
            question = new_state.next_question or ""
            assistant_msg = Message(chat_id=chat.id, role="assistant", content=question)
            db.add(assistant_msg)
            await db.commit()
            return MessageResponse(content=question, message_id=str(assistant_msg.id))

    user_msg = Message(chat_id=chat.id, role="user", content=req.content)
    db.add(user_msg)
    await db.commit()

    domain_id = await _domain_id_for_chat(chat, db) or chat.domain_id

    await config_for_vault.ensure_loaded(db)
    vault_ids: list[str] = [
        v.vault_id for v in config_for_vault.vaults.values()
        if v.domain_id == domain_id and v.enabled
    ] if domain_id else []

    retrieval_strategy = (
        "hybrid" if chat.vault_id and await settings_service.get("retrieval.enabled", db)
        else "none"
    )

    context = PipelineExecutionContext(
        chat_id=str(chat.id),
        message_id=str(user_msg.id),
        query=req.content,
        original_query=req.content,
        domain_id=domain_id,
        campaign_id=str(chat.campaign_id) if chat.campaign_id else None,
        vault_ids=vault_ids,
        vault_id=chat.vault_id,
        retrieval_strategy=retrieval_strategy,
    )

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

    provider = settings_service.get_active_provider()
    if provider:
        from app.db.models import Domain as DomainModel
        domain_obj = await db.get(DomainModel, context.domain_id) if context.domain_id else None
        domain_description = (
            domain_obj.description
            if domain_obj and domain_obj.description
            else None
        )
        context.query = await query_rewriter.rewrite(
            original_query=context.query,
            history=context.history,
            provider=provider,
            domain_description=domain_description,
        )

    if clarif_state.stage == "idle":
        planner = Planner()
        decision, missing_fields = await planner.decide(
            db=db,
            query=context.query,
            vault_id=chat.vault_id,
            domain_id=domain_id,
            history=[
                {"role": m.role, "content": m.content}
                for m in (context.history or [])
            ],
        )
        if decision.clarification_needed and missing_fields:
            max_turns: int = int(await settings_service.get("chat.max_clarification_turns", db))
            prompt_pack = PromptPack(await domain_service.get_prompts(
                domain_id or "default", db
            ))
            new_state = await clarification_fsm.start_collecting(
                db, chat.id, missing_fields, prompt_pack
            )
            await db.commit()
            question = new_state.next_question or ""
            assistant_msg = Message(chat_id=chat.id, role="assistant", content=question)
            db.add(assistant_msg)
            await db.commit()
            return MessageResponse(content=question, message_id=str(assistant_msg.id))

    pipeline_router = PipelineRouter(db)
    pipeline = await pipeline_router.select(
        context,
        locked_pipeline_id=chat.locked_pipeline_id,
    )

    if pipeline is None:
        logger.info(
            "No pipeline found for domain_id=%s — falling back to plain LLM chat", domain_id
        )
        answer = await _plain_llm_reply(req.content, context, domain_id, db)
        assistant_msg = Message(chat_id=chat.id, role="assistant", content=answer)
        db.add(assistant_msg)
        await db.commit()
        await _maybe_set_title(chat, context.original_query or req.content, db)
        await db.commit()
        return MessageResponse(content=answer, message_id=str(assistant_msg.id))

    context.pipeline_id = pipeline.pipeline_id
    context.pipeline_version = pipeline.version
    context.steps = pipeline.steps
    context.final_composition = pipeline.final_composition

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

    await _maybe_set_title(chat, context.original_query or req.content, db)
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

    # ---------------------------------------------------------------------------
    # Clarification: if active collection session — continue it
    # ---------------------------------------------------------------------------
    clarif_state = await clarification_fsm.get_state(db, chat.id)
    if clarif_state.stage == "collecting":
        max_turns: int = int(await settings_service.get("chat.max_clarification_turns", db))
        prompt_pack = PromptPack(await domain_service.get_prompts(
            chat.domain_id or "default", db
        ))
        new_state = clarification_fsm.process_clarification_answer(
            clarif_state, req.content, max_turns, prompt_pack
        )
        await clarification_fsm.save_state(db, chat.id, new_state)

        if new_state.stage == "collecting":
            user_msg = Message(chat_id=chat.id, role="user", content=req.content)
            db.add(user_msg)
            question = new_state.next_question or ""
            assistant_msg = Message(chat_id=chat.id, role="assistant", content=question)
            db.add(assistant_msg)
            await db.commit()

            async def clarif_stream() -> AsyncIterator[str]:
                chunk = json.dumps({"type": "token", "content": question}, ensure_ascii=False)
                yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(clarif_stream(), media_type="text/event-stream")

    user_msg = Message(chat_id=chat.id, role="user", content=req.content)
    db.add(user_msg)
    await db.commit()

    domain_id = await _domain_id_for_chat(chat, db) or chat.domain_id

    await config_for_vault.ensure_loaded(db)
    vault_ids: list[str] = [
        v.vault_id for v in config_for_vault.vaults.values()
        if v.domain_id == domain_id and v.enabled
    ] if domain_id else []

    retrieval_strategy = (
        "hybrid" if chat.vault_id and await settings_service.get("retrieval.enabled", db)
        else "none"
    )

    context = PipelineExecutionContext(
        chat_id=str(chat.id),
        message_id=str(user_msg.id),
        query=req.content,
        original_query=req.content,
        domain_id=domain_id,
        campaign_id=str(chat.campaign_id) if chat.campaign_id else None,
        vault_ids=vault_ids,
        vault_id=chat.vault_id,
        retrieval_strategy=retrieval_strategy,
    )

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

    provider = settings_service.get_active_provider()
    if provider:
        from app.db.models import Domain as DomainModel
        domain_obj = await db.get(DomainModel, context.domain_id) if context.domain_id else None
        domain_description = (
            domain_obj.description
            if domain_obj and domain_obj.description
            else None
        )
        context.query = await query_rewriter.rewrite(
            original_query=context.query,
            history=context.history,
            provider=provider,
            domain_description=domain_description,
        )

    # ---------------------------------------------------------------------------
    # Planner: decide if clarification needed (only when FSM was idle)
    # ---------------------------------------------------------------------------
    if clarif_state.stage == "idle":
        planner = Planner()
        decision, missing_fields = await planner.decide(
            db=db,
            query=context.query,
            vault_id=chat.vault_id,
            domain_id=domain_id,
            history=[
                {"role": m.role, "content": m.content}
                for m in (context.history or [])
            ],
        )
        if decision.clarification_needed and missing_fields:
            max_turns: int = int(await settings_service.get("chat.max_clarification_turns", db))
            prompt_pack = PromptPack(await domain_service.get_prompts(
                domain_id or "default", db
            ))
            new_state = await clarification_fsm.start_collecting(
                db, chat.id, missing_fields, prompt_pack
            )
            await db.commit()
            question = new_state.next_question or ""
            assistant_msg = Message(chat_id=chat.id, role="assistant", content=question)
            db.add(assistant_msg)
            await db.commit()
            logger.info(
                "Clarification started: chat_id=%s missing=%s max_turns=%s",
                chat.id, missing_fields, max_turns,
            )

            async def clarif_start_stream() -> AsyncIterator[str]:
                chunk = json.dumps(
                    {"type": "clarification", "content": question},
                    ensure_ascii=False,
                )
                yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(clarif_start_stream(), media_type="text/event-stream")

    pipeline_router = PipelineRouter(db)
    pipeline = await pipeline_router.select(
        context,
        locked_pipeline_id=chat.locked_pipeline_id,
    )

    async def _reset_clarif_fsm() -> None:
        await clarification_fsm.save_state(
            db, chat.id, clarification_fsm.idle_state()
        )

    # ---------------------------------------------------------------------------
    # FALLBACK: no pipeline found -> plain RAG stream
    # ---------------------------------------------------------------------------
    if pipeline is None:
        logger.info(
            "No pipeline found for domain_id=%s — falling back to plain LLM stream", domain_id
        )

        async def plain_stream() -> AsyncIterator[str]:
            _provider = settings_service.get_active_provider()
            if _provider is None:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No active model configured'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            yield f"data: {json.dumps({'type': 'step_status', 'text': 'Preparing context...'}, ensure_ascii=False)}\n\n"
            system_prompt = await _resolve_system_prompt(context.campaign_id, domain_id, db)
            messages: list[dict] = [{"role": "system", "content": system_prompt}]
            for m in (context.history or []):
                messages.append({"role": m.role, "content": m.content})

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
            cancelled = False
            try:
                async for token in _provider.generate_stream(messages):
                    full_answer += token
                    chunk = json.dumps({"type": "token", "content": token}, ensure_ascii=False)
                    yield f"data: {chunk}\n\n"
                    if await request.is_disconnected():
                        cancelled = True
                        break
            except Exception as exc:
                logger.error("plain_stream LLM error: %s", exc, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            if not cancelled:
                assistant_msg = Message(
                    chat_id=chat.id,
                    role="assistant",
                    content=full_answer,
                )
                db.add(assistant_msg)
                await db.commit()
                await _maybe_set_title(chat, context.original_query or req.content, db)
                await db.commit()
                await _reset_clarif_fsm()

            yield "data: [DONE]\n\n"

        return StreamingResponse(plain_stream(), media_type="text/event-stream")

    # ---------------------------------------------------------------------------
    # Pipeline found: show confirm card first
    # ---------------------------------------------------------------------------
    context.pipeline_id = pipeline.pipeline_id
    context.pipeline_version = pipeline.version
    context.steps = pipeline.steps
    context.final_composition = pipeline.final_composition

    async def pipeline_stream() -> AsyncIterator[str]:
        executor = PipelineExecutor(db)
        full_answer = ""
        cancelled = False

        try:
            async for chunk in executor.run_stream(context):
                chunk_type = chunk.get("type", "")

                if chunk_type == "step_status":
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    continue

                if chunk_type == "pipeline_selected":
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

                if chunk_type in ("step_complete", "step_skipped_no_docs", "step_error"):
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    continue

                if chunk_type == "error":
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

        except Exception as exc:
            logger.error("pipeline_stream error: %s", exc, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        if not cancelled:
            assistant_msg = Message(
                chat_id=chat.id,
                role="assistant",
                content=full_answer,
                pipeline_id=pipeline.pipeline_id,
            )
            db.add(assistant_msg)
            await db.commit()
            await _maybe_set_title(chat, context.original_query or req.content, db)
            await db.commit()
            await _reset_clarif_fsm()

        yield "data: [DONE]\n\n"

    return StreamingResponse(pipeline_stream(), media_type="text/event-stream")
