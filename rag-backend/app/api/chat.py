from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, Chat, ClarificationStateRow, Message, Vault
from app.db.session import get_db
from app.services import clarification_fsm
from app.services.context_engine.assembly import (
    build_chat_context as compose_full_system_prompt,
)
from app.services.domain_service import domain_service
from app.services.pipeline_executor import PipelineExecutor
from app.services.pipeline_router import PipelineRouter
from app.services.planner import Planner
from app.services.prompt_pack import PromptPack
from app.services.query_rewriter import query_rewriter
from app.services.retrieval import (
    format_context,
    get_allowed_tag_ids,
    get_document_ids_by_tags,
    rerank_hits,
    retrieve_multi_vault,
)
from app.services.settings_service import settings_service
from app.services.source_utils import (
    dedup_sources,
    hits_to_sources,
    sources_to_message_sources,
)
from app.services.vault_config_service import VaultConfigService
from shared_contracts.models import (
    ChatMessage,
    ChatRecord,
    ClarificationAnswer,
    ClarificationResponse,
    CreateChatResponse,
    PipelineExecutionContext,
    SearchHit,
    SendMessageRequest,
    Source,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

config_for_vault = VaultConfigService()

# Срок действия confirm-токена (концепт: 1 час)
_CONFIRM_TTL = timedelta(hours=1)

# Специальное значение-сентинел: пайплайны отключены, чат работает только через plain RAG
PIPELINE_NONE_ID = "__none__"

# TTL для full_document_selection pause (те же 1 час)
_FULLDOC_TTL = timedelta(hours=1)

_AUTO_TITLE_PROMPT = """\
Придумай короткое название (3–7 слов) для чата по первому вопросу пользователя.
Название должно отражать суть вопроса, быть на том же языке что и вопрос.
Верни ТОЛЬКО название, без кавычек, точек и пояснений.

Вопрос: {query}"""


class CreateChatRequest(BaseModel):
    """
    domain_id — обязательный идентификатор контекста чата (инвариант arch.md §2.6, §8).
    vault_id оставлен nullable для back-compat (старые клиенты).
    campaign_id — опциональная привязка к кампании.
    """

    domain_id: str
    vault_id: str | None = None  # deprecated back-compat
    campaign_id: str | None = None


class UpdateChatRequest(BaseModel):
    """
    Частичное обновление метаданных существующего чата (partial PATCH semantics).

    Все поля опциональны и обновляются независимо друг от друга:
    - campaign_id: передать строку UUID для установки кампании, null — для сброса.
      Поле обновляется ТОЛЬКО если явно присутствует в теле запроса (model_fields_set).
      Если поле не передано — campaign_id чата не изменяется.
    - full_document_mode_enabled: true/false для управления Full Document Mode.
      Если поле не передано — флаг чата не изменяется. Нельзя включить, если
      rag_prefill_enabled == false (422 full_document_requires_prefill).
    - context_update_mode: true/false для управления model-proposed context
      updates (Sprint 1 agent-assistant). Если поле не передано — флаг
      не изменяется.
    - rag_prefill_enabled: true/false для управления per-turn RAG prefetch.
      True — prefill evidence инжектируется в system_prompt и round 0
      заставляет модель вызвать tool (режим grounded). False (default) —
      модель сама решает, нужен ли search_knowledge.

    Примеры:
      { "full_document_mode_enabled": true }              — только тоглер, campaign_id не трогается
      { "campaign_id": "<uuid>" }                          — только кампания, флаг не трогается
      { "campaign_id": null }                              — сброс кампании, флаг не трогается
      { "campaign_id": "<uuid>", "full_document_mode_enabled": false } — оба поля
      { "rag_prefill_enabled": true }                      — включить prefill для этого чата
    """

    campaign_id: str | None = None
    full_document_mode_enabled: bool | None = None
    context_update_mode: bool | None = None
    rag_prefill_enabled: bool | None = None


class RenameChatRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChatHistoryResponse(BaseModel):
    chat: ChatRecord
    messages: list[ChatMessage]
    vault_enabled: bool = False


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


def _auto_title_fallback(query: str) -> str:
    """Fallback: берём первые 7 слов запроса как заголовок."""
    cleaned = re.sub(r"[^\w\s\u0400-\u04ff]", " ", query).strip()
    words = cleaned.split()
    if len(words) > 7:
        cleaned = " ".join(words[:7])
    return cleaned[:255]


async def _maybe_set_title(chat: Chat, query: str, db: AsyncSession) -> None:
    """Устанавливает заголовок чата если chat.auto_title=true.

    Логика:
    - Если настройка выключена — ничего не делаем (заголовок остаётся 'New Chat').
    - Если включена и есть активный LLM-провайдер — генерируем заголовок через LLM.
    - Если LLM недоступен или вернул пустой ответ — fallback на срез первых 7 слов.
    """
    if chat.title != "New Chat":
        return

    auto_title_enabled: bool = await settings_service.get("chat.auto_title", db)
    if not auto_title_enabled:
        return

    provider = settings_service.get_active_provider()
    if provider is not None:
        try:
            prompt = _AUTO_TITLE_PROMPT.format(query=query[:500])
            raw = await provider.generate([{"role": "user", "content": prompt}])
            title = re.sub(
                r'^["\u00ab\u00bb\'\s]+|["\u00ab\u00bb\'\s.]+$', "", raw.strip()
            )
            if title:
                chat.title = title[:255]
                logger.debug("auto_title LLM: '%s' \u2192 '%s'", query[:60], chat.title)
                return
        except Exception:
            logger.warning(
                "auto_title LLM generation failed, falling back to word-cut",
                exc_info=True,
            )

    chat.title = _auto_title_fallback(query)
    logger.debug("auto_title fallback: '%s' \u2192 '%s'", query[:60], chat.title)


async def _save_partial_answer(
    db: AsyncSession,
    chat: Chat,
    full_answer: str,
    title_query: str,
    sources: list[dict[str, Any]] | None = None,
) -> None:
    """Сохраняем частичный ответ модели в БД, защищая commit от CancelledError.

    `sources` — JSON-serialisable список MessageSource (dict-формат), который будет
    записан в `messages.sources`. Используется для восстановления блока источников
    при reload чата.
    """
    if not full_answer:
        return
    try:
        assistant_msg = Message(
            chat_id=chat.id,
            role="assistant",
            content=full_answer,
            sources=sources if sources else None,
        )
        db.add(assistant_msg)
        await asyncio.shield(db.commit())
        await _maybe_set_title(chat, title_query, db)
        await asyncio.shield(db.commit())
    except BaseException:
        # ВАЖНО: ловим BaseException (включая CancelledError, KeyboardInterrupt),
        # потому что при disconnect клиента во время стрима текущий task отменён,
        # и `await db.commit()` бросает CancelledError. Если пробрасывать дальше —
        # SQLAlchemy pool cleanup получает необработанное исключение в do_terminate.
        logger.exception(
            "Failed to persist partial assistant answer chat_id=%s", chat.id
        )


async def _check_vault_domain(
    vault_id: str | None,
    expected_domain_id: str,
    db: AsyncSession,
) -> None:
    if vault_id is None:
        return

    result = await db.execute(select(Vault).where(Vault.vault_id == vault_id))
    vault = result.scalars().first()

    if vault is None:
        raise HTTPException(status_code=404, detail=f"Vault '{vault_id}' not found")

    if vault.domain_id != expected_domain_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Vault '{vault_id}' belongs to domain '{vault.domain_id}', "
                f"but chat domain is '{expected_domain_id}'"
            ),
        )


@router.post("/create", response_model=CreateChatResponse)
async def create_chat(
    req: CreateChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CreateChatResponse:
    campaign_uuid: uuid.UUID | None = None
    if req.campaign_id:
        try:
            campaign_uuid = uuid.UUID(req.campaign_id)
        except ValueError as exc:
            raise HTTPException(
                422, f"Invalid campaign_id format: {req.campaign_id}"
            ) from exc

    await _check_vault_domain(req.vault_id, req.domain_id, db)

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
        {
            "vault_id": req.vault_id,
            "domain_id": req.domain_id,
            "campaign_id": req.campaign_id,
        },
    )
    await db.commit()
    logger.info("Created chat: chat_id=%s", chat.id)
    return CreateChatResponse(chat_id=str(chat.id), title=chat.title)


@router.patch("/{chat_id}", response_model=CreateChatResponse)
async def update_chat(
    chat_id: str,
    req: UpdateChatRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateChatResponse:
    chat = await _get_chat_or_404(chat_id, db)

    if "campaign_id" in req.model_fields_set:
        if req.campaign_id:
            try:
                chat.campaign_id = uuid.UUID(req.campaign_id)
            except ValueError as exc:
                raise HTTPException(
                    422, f"Invalid campaign_id: {req.campaign_id}"
                ) from exc
        else:
            chat.campaign_id = None

    if req.full_document_mode_enabled is not None:
        chat.full_document_mode_enabled = req.full_document_mode_enabled
        logger.info(
            "full_document_mode_enabled=%s for chat_id=%s",
            req.full_document_mode_enabled,
            chat_id,
        )

    if req.context_update_mode is not None:
        chat.context_update_mode = req.context_update_mode
        logger.info(
            "context_update_mode=%s for chat_id=%s",
            req.context_update_mode,
            chat_id,
        )

    if req.rag_prefill_enabled is not None:
        chat.rag_prefill_enabled = req.rag_prefill_enabled
        logger.info(
            "rag_prefill_enabled=%s for chat_id=%s",
            req.rag_prefill_enabled,
            chat_id,
        )

    # Guard: Full Document Mode требует активного prefill, т.к. пауза для выбора
    # документов работает только после retrieval-шага. Если пользователь пытается
    # оставить full_document_mode_enabled=True при отключённом prefill — отказ.
    if chat.full_document_mode_enabled and not chat.rag_prefill_enabled:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "full_document_requires_prefill",
                "message": (
                    "Full Document Mode requires RAG prefill (rag_prefill_enabled) "
                    "to be enabled for the same chat. Enable rag_prefill_enabled first."
                ),
            },
        )

    await db.commit()
    await db.refresh(chat)
    return CreateChatResponse(chat_id=str(chat.id), title=chat.title)


@router.get("/list", response_model=ChatListResponse)
async def list_chats(
    domain_id: str | None = Query(default=None, description="Фильтр по домену"),
    campaign_id: str | None = Query(
        default=None,
        description=(
            "Фильтр по кампании. "
            "Специальное значение '__none__' — только чаты без campaign_id (общий режим). "
            "UUID — только чаты в указанной кампании."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> ChatListResponse:
    stmt = select(Chat).order_by(Chat.updated_at.desc())
    if domain_id is not None:
        stmt = stmt.where(Chat.domain_id == domain_id)
    if campaign_id is not None:
        if campaign_id == "__none__":
            stmt = stmt.where(Chat.campaign_id.is_(None))
        else:
            try:
                stmt = stmt.where(Chat.campaign_id == uuid.UUID(campaign_id))
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid campaign_id: {campaign_id}",
                ) from exc
    result = await db.execute(stmt)
    chats = result.scalars().all()

    unique_vault_ids: set[str] = {c.vault_id for c in chats if c.vault_id}
    vault_enabled_cache: dict[str | None, bool] = {None: False}
    if unique_vault_ids:
        retrieval_enabled: bool = await settings_service.get("retrieval.enabled", db)
        for vid in unique_vault_ids:
            vault_enabled_cache[vid] = retrieval_enabled

    return ChatListResponse(
        chats=[
            ChatListItem(
                chat_id=str(c.id),
                title=c.title,
                vault_id=c.vault_id,
                domain_id=c.domain_id,
                vault_enabled=vault_enabled_cache.get(c.vault_id, False),
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
    stmt = (
        select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
    )
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
async def delete_chat(
    chat_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    chat = await _get_chat_or_404(chat_id, db)
    await db.delete(chat)
    await db.commit()

    # Best-effort cleanup of chat-scoped Redis state. A stale
    # `update_mode:{chat_id}` would block new proposals for up to its
    # 3-hour TTL and confuse the next chat created with the same id.
    redis = request.app.state.redis
    if redis is not None:
        try:
            deleted = await redis.delete(f"update_mode:{chat_id}")
            logger.info(
                "delete_chat: cleared %d update_mode Redis key(s) for chat_id=%s",
                deleted,
                chat_id,
            )
        except Exception as exc:
            logger.warning(
                "delete_chat: failed to clear update_mode Redis key for chat_id=%s: %s",
                chat_id,
                exc,
            )


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
    """Non-streaming endpoint. Accumulates all tokens from run_stream and returns final answer."""
    chat = await _get_chat_or_404(chat_id, db)

    user_msg = Message(chat_id=chat.id, role="user", content=req.content)
    db.add(user_msg)
    await db.flush()

    domain_id = await _domain_id_for_chat(chat, db) or chat.domain_id

    await config_for_vault.ensure_loaded(db)
    vault_ids: list[str] = (
        [
            v.vault_id
            for v in config_for_vault.vaults.values()
            if v.domain_id == domain_id and v.enabled
        ]
        if domain_id
        else []
    )

    retrieval_strategy = (
        "hybrid"
        if chat.vault_id and await settings_service.get("retrieval.enabled", db)
        else "none"
    )

    context = PipelineExecutionContext(
        chat_id=str(chat.id),
        message_id=str(user_msg.id),
        query=req.content,
        original_query=req.content,
        domain_id=domain_id,
        campaign_id=str(chat.campaign_id) if chat.campaign_id else None,
        vault_id=chat.vault_id,
        vault_ids=vault_ids,
        retrieval_strategy=retrieval_strategy,
    )

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

    provider = settings_service.get_active_provider()
    if provider:
        from app.db.models import Domain as DomainModel

        domain_obj = (
            await db.get(DomainModel, context.domain_id) if context.domain_id else None
        )
        domain_description = (
            domain_obj.description if domain_obj and domain_obj.description else None
        )
        context.query = await query_rewriter.rewrite(
            original_query=context.query,
            history=context.history,
            provider=provider,
            domain_description=domain_description,
        )

    if chat.locked_pipeline_id == PIPELINE_NONE_ID:
        pipeline = None
        logger.info(
            "Pipeline disabled (__none__ sentinel) — skipping router, plain RAG; chat_id=%s",
            chat.id,
        )
    else:
        pipeline_router = PipelineRouter(db)
        pipeline = await pipeline_router.select(
            context, locked_pipeline_id=chat.locked_pipeline_id
        )

    if pipeline is None:
        logger.info(
            "No pipeline found for domain_id=%s — falling back to plain LLM chat",
            domain_id,
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
    full_answer = ""
    async for chunk in executor.run_stream(context):
        if chunk.get("type") == "token":
            full_answer += chunk.get("content", "")

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
    return MessageResponse(content=full_answer, message_id=str(assistant_msg.id))


@router.post("/{chat_id}/send_stream")
async def send_message_stream(
    chat_id: str,
    req: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    from fastapi.responses import StreamingResponse

    chat = await _get_chat_or_404(chat_id, db)

    # ───────────────────────────────────────────────────────────────────────────────
    # Кларификация: если есть активная сессия сбора — продолжаем её, не идём дальше
    # ───────────────────────────────────────────────────────────────────────────────
    clarif_state = await clarification_fsm.get_state(db, chat.id)
    if clarif_state.stage == "collecting":
        max_turns: int = int(
            await settings_service.get("chat.max_clarification_turns", db)
        )
        prompt_pack = PromptPack(
            await domain_service.get_prompts(chat.domain_id or "default", db)
        )
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
                chunk = json.dumps(
                    {"type": "token", "content": question}, ensure_ascii=False
                )
                yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(clarif_stream(), media_type="text/event-stream")

    user_msg = Message(chat_id=chat.id, role="user", content=req.content)
    db.add(user_msg)
    await db.commit()

    domain_id = await _domain_id_for_chat(chat, db) or chat.domain_id

    await config_for_vault.ensure_loaded(db)
    vault_ids: list[str] = (
        [
            v.vault_id
            for v in config_for_vault.vaults.values()
            if v.domain_id == domain_id and v.enabled
        ]
        if domain_id
        else []
    )

    retrieval_strategy = (
        "hybrid"
        if chat.vault_id and await settings_service.get("retrieval.enabled", db)
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

    # ───────────────────────────────────────────────────────────────────────────────
    # Planner: решаем нужна ли кларификация (только если FSM был idle)
    # ───────────────────────────────────────────────────────────────────────────────
    if clarif_state.stage == "idle":
        planner = Planner()
        decision, missing_fields = await planner.decide(
            db=db,
            query=context.query,
            vault_id=chat.vault_id,
            domain_id=domain_id,
            history=[
                {"role": m.role, "content": m.content} for m in (context.history or [])
            ],
        )
        if decision.clarification_needed and missing_fields:
            max_turns: int = int(
                await settings_service.get("chat.max_clarification_turns", db)
            )
            prompt_pack = PromptPack(
                await domain_service.get_prompts(domain_id or "default", db)
            )
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
                chat.id,
                missing_fields,
                max_turns,
            )

            async def clarif_start_stream() -> AsyncIterator[str]:
                chunk = json.dumps(
                    {"type": "clarification", "content": question}, ensure_ascii=False
                )
                yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                clarif_start_stream(), media_type="text/event-stream"
            )

    _locked_pipeline_id = chat.locked_pipeline_id
    _chat = chat

    async def _reset_clarif_fsm() -> None:
        await clarification_fsm.save_state(db, _chat.id, clarification_fsm.idle_state())

    def _step(text: str) -> str:
        return f"data: {json.dumps({'type': 'step_status', 'text': text}, ensure_ascii=False)}\n\n"

    async def plain_stream() -> AsyncIterator[str]:
        _provider = settings_service.get_active_provider()
        if _provider is None:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No LLM provider configured'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        # ── 1. Query rewriting ─────────────────────────────────────────────────
        if bool(context.history):
            yield _step("Переформулирую вопрос для поиска в базе знаний...")
            from app.db.models import Domain as DomainModel

            domain_obj = (
                await db.get(DomainModel, context.domain_id)
                if context.domain_id
                else None
            )
            context.query = await query_rewriter.rewrite(
                original_query=context.query,
                history=context.history,
                provider=_provider,
                domain_description=(
                    domain_obj.description
                    if domain_obj and domain_obj.description
                    else None
                ),
            )

        # ── 2. Pipeline routing ───────────────────────────────────────────────
        if _locked_pipeline_id == PIPELINE_NONE_ID:
            pipeline = None
            logger.info(
                "Pipeline disabled (__none__ sentinel) — skipping router; chat_id=%s",
                _chat.id,
            )
        else:
            yield _step("Анализирую контекст запроса...")
            _pipeline_router = PipelineRouter(db)
            pipeline = await _pipeline_router.select(
                context, locked_pipeline_id=_locked_pipeline_id
            )

        # ── 2a. Pipeline found ────────────────────────────────────────────────
        if pipeline is not None:
            context.pipeline_id = pipeline.pipeline_id
            context.pipeline_version = pipeline.version
            context.steps = pipeline.steps
            context.final_composition = pipeline.final_composition

            confirm_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(UTC) + _CONFIRM_TTL
            pipeline_name: str = getattr(pipeline, "name", None) or pipeline.pipeline_id

            _chat.pending_pipeline_confirm = _build_confirm_payload(
                confirm_token=confirm_token,
                pipeline_id=pipeline.pipeline_id,
                pipeline_name=pipeline_name,
                context=context,
                expires_at=expires_at,
            )
            await asyncio.shield(db.commit())

            logger.info(
                "Pipeline confirm required: chat_id=%s pipeline_id=%s token=%s…",
                _chat.id,
                pipeline.pipeline_id,
                confirm_token[:8],
            )
            chunk = json.dumps(
                {
                    "type": "pipeline_confirm_required",
                    "pipeline_name": pipeline_name,
                    "reasoning": f"Выбран пайплайн «{pipeline_name}». Запустить?",
                    "confirm_token": confirm_token,
                },
                ensure_ascii=False,
            )
            yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
            return

        # ── 3. Plain RAG fallback ─────────────────────────────────────────────
        logger.info(
            "No pipeline found for domain_id=%s — falling back to plain LLM stream",
            domain_id,
        )

        system_prompt = await _compose_full_system_prompt(
            context.campaign_id, domain_id, db,
            scene_state=_chat.metadata_json.get("scene_state"),
        )

        # Per-chat: если per-chat rag_prefill_enabled=False — модель получит
        # вопрос без префилл-выборки. Добавляем специальный hint-блок, чтобы
        # модель знала что search_knowledge доступен и сама решает, когда звать.
        if not _chat.rag_prefill_enabled:
            from app.services.effective_context import _RAG_DECIDES_HINT
            system_prompt = (
                f"{system_prompt}{_RAG_DECIDES_HINT}"
                if system_prompt
                else _RAG_DECIDES_HINT.lstrip()
            )

        # Stage 8.5: load retrieval tool settings and decide whether the
        # model gets the `search_knowledge` tool (conditional RAG) or
        # falls back to the unconditional single-shot retrieval path.
        from app.services.retrieval_tool_settings import load_retrieval_tool_settings

        tool_settings = await load_retrieval_tool_settings(db)
        use_tool = tool_settings.tool_enabled and bool(_provider)

        # ── 2b. Prefill RAG (Sprint 2) ──────────────────────────────────────────
        # Per-chat gated: only when rag_prefill_enabled is set on the chat itself.
        # When a retrieval is performed up-front and its evidence is injected
        # into system_prompt. The model therefore starts the turn with concrete
        # campaign context already visible, instead of having to call
        # search_knowledge manually.
        if (
            bool(_chat.rag_prefill_enabled)
            and context.campaign_id
            and vault_ids
        ):
            yield _step("Загружаю базу знаний для контекста…")
            prefill_queries, rag_block = await _prefill_rag(
                original_query=context.original_query or req.content,
                vault_ids=vault_ids,
                domain_id=domain_id,
                campaign_id=context.campaign_id,
                db=db,
                provider=_provider,
            )
            if rag_block:
                system_prompt = (
                    f"{system_prompt}\n\n{rag_block}"
                    if system_prompt
                    else rag_block
                )
                hits_count = rag_block.count("\n\n[") + (1 if rag_block.strip() else 0)
                yield _step(
                    f"Найдено фрагментов в базе знаний: {hits_count}"
                )
            else:
                yield _step("В базе знаний по запросу ничего не найдено")
            yield f"data: {json.dumps({'type': 'prefill_rag', 'queries_used': prefill_queries, 'has_evidence': bool(rag_block)}, ensure_ascii=False)}\n\n"

        if use_tool:
            # ── 3-tool. Conditional/cyclic RAG via AgentLoop ────────────────
            from app.services.agent_loop import AgentLoop
            from app.services.effective_context import append_tool_use_rules

            loop = AgentLoop()
            history_payload = [
                {"role": m.role, "content": m.content} for m in (context.history or [])
            ]
            # Накопитель источников для финального SSE `sources` event и
            # для персистенции в Message.sources.
            all_sources: list[Source] = []
            full_answer = ""
            cancelled = False
            # Stage 8.6: append the tool-use rules (§12.1) to the system
            # prompt. The legacy path keeps the bare system_prompt.
            tool_system_prompt = append_tool_use_rules(system_prompt)
            # Redis is needed if model-proposed context updates are enabled
            # (so we can persist the proposal as an Update Mode session).
            _redis = request.app.state.redis if _chat.context_update_mode else None
            try:
                async for event in loop.run_stream(
                    provider=_provider,
                    system_prompt=tool_system_prompt,
                    history=history_payload,
                    user_message=context.original_query or req.content,
                    domain_id=domain_id,
                    campaign_id=context.campaign_id,
                    chat_id=_chat.id and str(_chat.id),
                    vault_ids=vault_ids,
                    max_rounds=tool_settings.max_rounds,
                    evidence_token_budget=tool_settings.evidence_token_budget,
                    policy=tool_settings.policy,
                    effective_grounded=bool(_chat.rag_prefill_enabled),
                    db=db,
                    context_update_mode_enabled=bool(_chat.context_update_mode),
                    redis=_redis,
                ):
                    if event.type == "round_start":
                        yield _step(
                            f"Раунд {event.round + 1}/{event.payload.get('max_rounds', '?')} "
                            f"({event.payload.get('policy', 'assistive')})"
                        )
                    elif event.type == "tool_call":
                        tool_name = event.payload.get("tool")
                        queries = event.payload.get("queries") or []
                        patch = event.payload.get("patch") or {}
                        reason = event.payload.get("reason") or ""
                        if tool_name == "update_scene_state":
                            applied_summary = ", ".join(
                                f"{k}={v!r}" for k, v in list(patch.items())[:3]
                            )
                            yield _step(
                                "Обновляю контекст сцены: "
                                + (applied_summary or "(пусто)")
                            )
                            yield f"data: {json.dumps({'type': 'tool_call', 'round': event.round, 'tool': tool_name, 'patch': patch, 'reason': reason}, ensure_ascii=False)}\n\n"
                        elif tool_name == "propose_context_update":
                            field_changes_count = event.payload.get("field_changes_count", 0)
                            state_patch_count = event.payload.get("state_patch_count", 0)
                            file_changes_count = event.payload.get("file_changes_count", 0)
                            confidence = event.payload.get("confidence", 0.0)
                            yield _step(
                                f"Предлагаю обновление контекста: "
                                f"поля={field_changes_count} значения={state_patch_count} "
                                f"файлы={file_changes_count} (conf={confidence:.0%})"
                            )
                            yield f"data: {json.dumps({'type': 'tool_call', 'round': event.round, 'tool': tool_name, 'field_changes_count': field_changes_count, 'state_patch_count': state_patch_count, 'file_changes_count': file_changes_count, 'confidence': confidence, 'reason': reason}, ensure_ascii=False)}\n\n"
                        else:
                            yield _step(
                                "Ищу в базе знаний: "
                                + ", ".join(queries[:3])
                                + ("…" if len(queries) > 3 else "")
                            )
                            yield f"data: {json.dumps({'type': 'tool_call', 'round': event.round, 'tool': tool_name, 'queries': queries, 'reason': reason}, ensure_ascii=False)}\n\n"
                    elif event.type == "tool_result":
                        tool_name = event.payload.get("tool")
                        if tool_name == "update_scene_state":
                            status = event.payload.get("status", "ok")
                            applied = event.payload.get("applied_keys") or []
                            removed = event.payload.get("removed_keys") or []
                            note = event.payload.get("note")
                            yield _step(
                                f"Контекст сцены: {status}; "
                                f"применено={len(applied)} удалено={len(removed)}"
                            )
                            yield f"data: {json.dumps({'type': 'tool_result', 'round': event.round, 'tool': tool_name, 'status': status, 'applied_keys': applied, 'removed_keys': removed, 'note': note}, ensure_ascii=False)}\n\n"
                            continue
                        if tool_name == "propose_context_update":
                            status = event.payload.get("status", "ok")
                            session_id = event.payload.get("session_id")
                            field_changes_count = event.payload.get("field_changes_count", 0)
                            state_patch_count = event.payload.get("state_patch_count", 0)
                            file_changes_count = event.payload.get("file_changes_count", 0)
                            note = event.payload.get("note")
                            yield _step(
                                f"Предложение: {status} — "
                                f"поля={field_changes_count} значения={state_patch_count} "
                                f"файлы={file_changes_count}"
                            )
                            yield f"data: {json.dumps({'type': 'tool_result', 'round': event.round, 'tool': tool_name, 'status': status, 'session_id': session_id, 'field_changes_count': field_changes_count, 'state_patch_count': state_patch_count, 'file_changes_count': file_changes_count, 'note': note}, ensure_ascii=False)}\n\n"
                            # Sprint 3: dedicated event so the UI can pop a
                            # review card when the proposal is created.
                            if status == "ok" and session_id:
                                yield f"data: {json.dumps({'type': 'context_update_proposal', 'session_id': session_id, 'field_changes_count': field_changes_count, 'state_patch_count': state_patch_count, 'file_changes_count': file_changes_count, 'note': note}, ensure_ascii=False)}\n\n"
                            continue
                        hits_count = event.payload.get("hits_count", 0)
                        scope = event.payload.get("scope", "domain")
                        note = event.payload.get("note")
                        # Аккумулируем источники из каждого tool_result —
                        # multi-round agent loop аггрегирует все запросы.
                        round_sources_raw = event.payload.get("sources") or []
                        for src in round_sources_raw:
                            try:
                                all_sources.append(Source.model_validate(src))
                            except Exception:  # skip malformed sources
                                logger.warning(
                                    "agent_loop: invalid source payload, skipping: %r",
                                    src,
                                )
                        if hits_count > 0:
                            yield _step(f"Найдено фрагментов: {hits_count} ({scope})")
                        else:
                            yield _step("В базе знаний ничего не найдено")
                        yield f"data: {json.dumps({'type': 'tool_result', 'round': event.round, 'queries_used': event.payload.get('queries_used', []), 'hits_count': hits_count, 'evidence_tokens': event.payload.get('evidence_tokens', 0), 'scope': scope, 'note': note}, ensure_ascii=False)}\n\n"
                    elif event.type == "token":
                        full_answer += event.payload.get("content", "")
                        yield f"data: {json.dumps({'type': 'token', 'content': event.payload.get('content', '')}, ensure_ascii=False)}\n\n"
                    elif event.type == "error":
                        yield f"data: {json.dumps({'type': 'error', 'message': event.payload.get('message', 'agent loop error')}, ensure_ascii=False)}\n\n"
                    elif event.type == "final":
                        logger.info(
                            "agent_loop final: chat_id=%s rounds=%d tool_calls=%d content_chars=%d",
                            _chat.id,
                            len(event.payload.get("rounds", [])),
                            event.payload.get("tool_calls_made", 0),
                            event.payload.get("content_chars", 0),
                        )
                        # Stage 8.7: audit trail for retrieval tool calls.
                        # Persist a single row summarising the whole turn
                        # so admins can inspect "did the model actually
                        # use search_knowledge and with what scope".
                        try:
                            await _audit(
                                db,
                                "chat.agent_loop",
                                "chat",
                                str(_chat.id),
                                {
                                    "campaign_id": context.campaign_id,
                                    "domain_id": domain_id,
                                    "policy": tool_settings.policy.value,
                                    "rounds": event.payload.get("rounds", []),
                                    "tool_calls_made": event.payload.get(
                                        "tool_calls_made", 0
                                    ),
                                },
                            )
                        except Exception:
                            logger.exception(
                                "audit chat.agent_loop failed for chat_id=%s",
                                _chat.id,
                            )
            except asyncio.CancelledError:
                cancelled = True
            finally:
                # При отмене (клиент нажал «Стоп» / disconnect) cleanup БД
                # выполняется в отменённом task scope — wrap в shield+except,
                # чтобы исключения не пробивались до SQLAlchemy pool cleanup.
                try:
                    await asyncio.shield(_reset_clarif_fsm())
                except (asyncio.CancelledError, Exception):
                    pass
                if not cancelled and full_answer:
                    # Сохраняем partial answer только если НЕ было отмены.
                    # При cancel клиент сам решит, отправлять ли заново.
                    deduped = dedup_sources(all_sources)
                    persisted_sources: list[dict[str, Any]] = [
                        s.model_dump(mode="json", exclude_none=True)
                        for s in sources_to_message_sources(deduped)
                    ]
                    try:
                        await asyncio.shield(
                            _save_partial_answer(
                                db,
                                _chat,
                                full_answer,
                                title_query=context.original_query or req.content,
                                sources=persisted_sources,
                            )
                        )
                    except (asyncio.CancelledError, Exception):
                        logger.exception(
                            "Failed to persist partial answer after stream (use_tool)"
                        )
                was_cancelled = cancelled

            if was_cancelled:
                return

            # Эмитим финальный `sources` event для UI — даже если LLM не
            # сгенерировал токенов, источники должны быть видны.
            deduped_sources = dedup_sources(all_sources)
            if deduped_sources:
                sources_chunk = json.dumps(
                    {
                        "type": "sources",
                        "grouped_by_step": False,
                        "sources": [
                            s.model_dump(mode="json", exclude_none=True)
                            for s in deduped_sources
                        ],
                    },
                    ensure_ascii=False,
                )
                yield f"data: {sources_chunk}\n\n"

            yield "data: [DONE]\n\n"
            return

        # ── 3-legacy. Unconditional single-shot retrieval (no tool) ──────────
        hits: list[SearchHit] = []
        if vault_ids:
            yield _step("Ищу в базе знаний...")
            hits = await _fallback_retrieve(
                query=context.query,
                vault_ids=vault_ids,
                domain_id=domain_id,
                campaign_id=context.campaign_id,
                db=db,
                skip_rerank=True,
            )
            if hits:
                yield _step("Выбираю лучшие результаты поиска...")
                hits = await rerank_hits(context.query, hits, db)

        # Предвычисляем sources event payload заранее — понадобится и для
        # SSE-чанка, и для персистенции в Message.sources.
        legacy_sources: list[dict[str, Any]] = _hits_to_sources(hits)
        legacy_message_sources: list[dict[str, Any]] = [
            s.model_dump(mode="json", exclude_none=True)
            for s in sources_to_message_sources(hits_to_sources(hits))
        ]

        # ── 3a. Full Document Mode: если флаг включён — паузим и предлагаем документы
        # ───────────────────────────────────────────────────────────────────────────────
        if hits and _chat.full_document_mode_enabled:
            from app.services.full_document_service import collect_document_candidates

            sent_ids: list[str] = list(_chat.sent_full_document_ids or [])
            candidates = await collect_document_candidates(hits, sent_ids, db)
            if candidates:
                # Сохраняем пауза-стейт в том же формате что и PipelineExecutor
                _chat.pipeline_pause_state = {
                    "step": "full_document_selection",
                    "candidates": [c.model_dump() for c in candidates],
                    "saved_hits": [h.model_dump() for h in hits],
                    "context_snapshot": context.model_dump(mode="json"),
                    "expires_at": (datetime.now(UTC) + _FULLDOC_TTL).isoformat(),
                }
                await asyncio.shield(db.commit())
                logger.info(
                    "plain_stream full_document_mode: pausing for selection. "
                    "chat_id=%s candidates=%d",
                    _chat.id,
                    len(candidates),
                )
                chunk = json.dumps(
                    {
                        "type": "full_document_selection_required",
                        "candidates": [c.model_dump() for c in candidates],
                    },
                    ensure_ascii=False,
                )
                yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"
                return

        # ── 3b. Generation ──────────────────────────────────────────────────────
        rag_context = format_context(hits)
        full_system = (
            f"{system_prompt}\n\n{rag_context}" if system_prompt else rag_context
        )

        messages: list[dict[str, str]] = []
        if full_system:
            messages.append({"role": "system", "content": full_system})
        for m in context.history or []:
            messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": req.content})

        yield _step("Отправка контекста в генеративную модель для ответа...")

        full_answer = ""
        cancelled = False
        try:
            async for token in _provider.generate_stream(messages):
                full_answer += token
                chunk = json.dumps(
                    {"type": "token", "content": token}, ensure_ascii=False
                )
                yield f"data: {chunk}\n\n"
        except asyncio.CancelledError:
            cancelled = True
        finally:
            # При отмене (клиент нажал «Стоп» / disconnect) cleanup БД
            # выполняется в отменённом task scope — wrap в shield+except,
            # чтобы исключения не пробивались до SQLAlchemy pool cleanup.
            try:
                await asyncio.shield(_reset_clarif_fsm())
            except (asyncio.CancelledError, Exception):
                pass
            if not cancelled and full_answer:
                try:
                    await asyncio.shield(
                        _save_partial_answer(
                            db,
                            _chat,
                            full_answer,
                            title_query=context.original_query or req.content,
                            sources=legacy_message_sources,
                        )
                    )
                except (asyncio.CancelledError, Exception):
                    logger.exception(
                        "Failed to persist partial answer after stream (legacy)"
                    )
            was_cancelled = cancelled

        if was_cancelled:
            return

        if hits:
            sources_chunk = json.dumps(
                {
                    "type": "sources",
                    "grouped_by_step": False,
                    "sources": legacy_sources,
                },
                ensure_ascii=False,
            )
            yield f"data: {sources_chunk}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(plain_stream(), media_type="text/event-stream")


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


def _build_confirm_payload(
    confirm_token: str,
    pipeline_id: str,
    pipeline_name: str,
    context: PipelineExecutionContext,
    expires_at: datetime,
) -> dict[str, Any]:
    return {
        "confirm_token": confirm_token,
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "expires_at": expires_at.isoformat(),
        "context_snapshot": context.model_dump(mode="json"),
    }


async def _get_chat_or_404(chat_id: str, db: AsyncSession) -> Chat:
    try:
        uuid_obj = uuid.UUID(chat_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(404, f"Invalid chat_id format: {chat_id}")
    chat = await db.get(Chat, uuid_obj)
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


async def _vault_enabled(db: AsyncSession, vault_id: str | None) -> bool:
    if not vault_id:
        return False
    return await settings_service.get("retrieval.enabled", db)


async def _domain_id_for_chat(chat: Chat, db: AsyncSession) -> str | None:
    if chat.domain_id:
        return chat.domain_id
    if chat.campaign_id:
        campaign = await db.get(Campaign, chat.campaign_id)
        if campaign is not None and campaign.domain_id:
            return campaign.domain_id
    return None


async def _resolve_system_prompt(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
) -> str:
    """Совместимость со старым контрактом: вернуть только system_prompt.

    Stage 6: для runtime чата используйте `compose_full_system_prompt` из
    `app.services.effective_context` (включает Campaign State block).
    """
    from app.services.context_engine.assembly import _resolve_system_prompt_text as _impl

    return await _impl(campaign_id, domain_id, db)


async def _compose_full_system_prompt(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    scene_state: dict[str, Any] | None = None,
) -> str:
    return await compose_full_system_prompt(
        campaign_id, domain_id, db, scene_state=scene_state
    )


async def _prefill_rag(
    *,
    original_query: str,
    vault_ids: list[str],
    domain_id: str | None,
    campaign_id: str | None,
    db: AsyncSession,
    provider: Any | None = None,
) -> tuple[list[str], str]:
    """Sprint 2: prefill retrieval for grounded mode.

    Returns `(queries_used, rag_block_or_empty)`. When the campaign has tags
    we scope the search to the campaign's allowed documents; otherwise we
    search the full domain. We dedupe hits by `chunk_id` and clip to the
    `retrieval.evidence_token_budget` budget.

    Never raises — if anything goes wrong, we return ([], "") so the
    chat turn can continue with a bare system_prompt.
    """
    if not vault_ids or not domain_id or not original_query.strip():
        return [], ""

    # Build queries (original + RU translation if needed).
    from app.services.query_rewriter import query_rewriter as _qr
    prefill_queries = await _qr.build_search_queries(
        original_query, provider=provider
    )
    if not prefill_queries:
        return [], ""

    # Read knobs with safe defaults (6000/20) if platform_settings missing.
    try:
        prefill_top_k = int(
            await settings_service.get("retrieval.top_k", db)
        )
    except Exception:  # use safe default if settings unavailable
        prefill_top_k = 20
    try:
        prefill_budget = int(
            await settings_service.get("retrieval.evidence_token_budget", db)
        )
    except Exception:  # use safe default if settings unavailable
        prefill_budget = 6000

    # Scope to campaign tags.
    doc_ids: list[str] | None = None
    if campaign_id:
        try:
            allowed = await get_allowed_tag_ids(domain_id, campaign_id, db)
            if allowed:
                doc_ids = await get_document_ids_by_tags(
                    list(allowed), domain_id, db
                )
                if not doc_ids:
                    doc_ids = None  # fallback: full domain
        except Exception:
            logger.exception("prefill_rag: failed to resolve campaign tag scope")
            doc_ids = None

    # Per-query retrieval + dedup.
    try:
        per_query_hits: list[SearchHit] = []
        for q in prefill_queries:
            hits = await retrieve_multi_vault(
                q,
                vault_ids,
                document_ids=doc_ids,
                top_k=prefill_top_k,
                strategy="hybrid",
                config=None,
                db=db,
                skip_rerank=True,
            )
            per_query_hits.extend(hits)
        dedup: dict[str, SearchHit] = {}
        for h in per_query_hits:
            if h.chunk_id not in dedup or h.score > dedup[h.chunk_id].score:
                dedup[h.chunk_id] = h
        merged = sorted(
            dedup.values(), key=lambda x: x.score, reverse=True
        )[:prefill_top_k]
    except Exception:
        logger.exception("prefill_rag: retrieval failed, continuing without prefill")
        return prefill_queries, ""

    if not merged:
        return prefill_queries, ""

    # Truncate to evidence_token_budget.
    from app.services.campaign_state_compiler import default_token_counter
    kept: list[SearchHit] = []
    running = 0
    for h in merged:
        cost = default_token_counter(h.text)
        if running + cost > prefill_budget and kept:
            break
        kept.append(h)
        running += cost

    if not kept:
        return prefill_queries, ""

    return prefill_queries, format_context(kept)


async def _fallback_retrieve(
    query: str,
    vault_ids: list[str],
    domain_id: str | None,
    campaign_id: str | None,
    db: AsyncSession,
    *,
    skip_rerank: bool = False,
) -> list[SearchHit]:
    """RAG retrieval для no-pipeline fallback пути."""
    if not vault_ids or not domain_id:
        logger.info(
            "Fallback RAG skipped: vault_ids=%s domain_id=%s", vault_ids, domain_id
        )
        return []

    retrieval_enabled: bool = await settings_service.get("retrieval.enabled", db)
    if not retrieval_enabled:
        logger.info("Fallback RAG skipped: retrieval.enabled=False")
        return []

    top_k: int = int(await settings_service.get("retrieval.top_k", db))
    document_ids: list[str] | None = None

    if campaign_id:
        allowed_tag_ids = await get_allowed_tag_ids(domain_id, campaign_id, db)
        if allowed_tag_ids:
            document_ids = await get_document_ids_by_tags(
                list(allowed_tag_ids), domain_id, db
            )
            logger.info(
                "Fallback RAG campaign scope: campaign_id=%s allowed_tags=%d document_ids=%d",
                campaign_id,
                len(allowed_tag_ids),
                len(document_ids),
            )
            if document_ids == []:
                logger.info(
                    "Fallback RAG: no indexed documents for campaign tags, returning empty"
                )
                return []
        else:
            logger.info(
                "Fallback RAG: campaign has no tags, searching full domain domain_id=%s",
                domain_id,
            )

    return await retrieve_multi_vault(
        query,
        vault_ids,
        document_ids=document_ids,
        top_k=top_k,
        strategy="hybrid",
        config=None,
        db=db,
        skip_rerank=skip_rerank,
    )


def _hits_to_sources(hits: list[SearchHit]) -> list[dict[str, Any]]:
    """Legacy-формат sources event для SSE: list[{path, page, vault_id, ...}].

    Обратносовместима со старым фронтом: ключи path/page/vault_id сохранены.
    Дополнительно пробрасывает document_id, chunk_id, score, source_kind — фронт
    может их игнорировать, если они не нужны.
    """
    return [s.model_dump(mode="json", exclude_none=True) for s in hits_to_sources(hits)]


async def _plain_llm_reply(
    query: str,
    context: PipelineExecutionContext,
    domain_id: str | None,
    db: AsyncSession,
) -> str:
    provider = settings_service.get_active_provider()
    if provider is None:
        raise HTTPException(503, "No LLM provider configured")

    system_prompt = await _compose_full_system_prompt(
        context.campaign_id, domain_id, db
    )
    vault_ids: list[str] = getattr(context, "vault_ids", []) or []
    hits: list[SearchHit] = await _fallback_retrieve(
        query=context.query,
        vault_ids=vault_ids,
        domain_id=domain_id,
        campaign_id=context.campaign_id,
        db=db,
    )

    rag_context = format_context(hits)
    full_system = f"{system_prompt}\n\n{rag_context}" if system_prompt else rag_context

    messages: list[dict[str, str]] = []
    if full_system:
        messages.append({"role": "system", "content": full_system})
    for m in context.history or []:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": query})

    return await provider.generate(messages)


async def _audit(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    # NOTE: AuditLog column was renamed details -> payload in migration 0010_audit_log_actor_payload
    from app.db.models import AuditLog

    db.add(
        AuditLog(
            action=action, entity_type=entity_type, entity_id=entity_id, payload=payload
        )
    )


async def _pipeline_versions(request: Request) -> dict[str, str]:
    return {
        k.removeprefix("x-pipeline-"): v
        for k, v in request.headers.items()
        if k.lower().startswith("x-pipeline-")
    }
