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

    Оба поля опциональны и обновляются независимо друг от друга:
    - campaign_id: передать строку UUID для установки кампании, null — для сброса.
      Поле обновляется ТОЛЬКО если явно присутствует в теле запроса (model_fields_set).
      Если поле не передано — campaign_id чата не изменяется.
    - full_document_mode_enabled: true/false для управления Full Document Mode.
      Если поле не передано — флаг чата не изменяется.

    Примеры:
      { "full_document_mode_enabled": true }              — только тоглер, campaign_id не трогается
      { "campaign_id": "<uuid>" }                          — только кампания, флаг не трогается
      { "campaign_id": null }                              — сброс кампании, флаг не трогается
      { "campaign_id": "<uuid>", "full_document_mode_enabled": false } — оба поля
    """
    campaign_id: str | None = None
    full_document_mode_enabled: bool | None = None


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
            title = re.sub(r'^["\u00ab\u00bb\'\s]+|["\u00ab\u00bb\'\s.]+$', "", raw.strip())
            if title:
                chat.title = title[:255]
                logger.debug("auto_title LLM: '%s' \u2192 '%s'", query[:60], chat.title)
                return
        except Exception:
            logger.warning("auto_title LLM generation failed, falling back to word-cut", exc_info=True)

    chat.title = _auto_title_fallback(query)
    logger.debug("auto_title fallback: '%s' \u2192 '%s'", query[:60], chat.title)


async def _save_partial_answer(
    db: AsyncSession,
    chat: Chat,
    full_answer: str,
    title_query: str,
) -> None:
    """Сохраняем частичный ответ модели в БД, защищая commit от CancelledError."""
    if not full_answer:
        return
    try:
        assistant_msg = Message(chat_id=chat.id, role="assistant", content=full_answer)
        db.add(assistant_msg)
        await asyncio.shield(db.commit())
        await _maybe_set_title(chat, title_query, db)
        await asyncio.shield(db.commit())
    except Exception:
        logger.exception("Failed to persist partial assistant answer chat_id=%s", chat.id)


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
            raise HTTPException(422, f"Invalid campaign_id format: {req.campaign_id}") from exc

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
        db, "chat.create", "chat", str(chat.id),
        {"vault_id": req.vault_id, "domain_id": req.domain_id, "campaign_id": req.campaign_id},
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
                raise HTTPException(422, f"Invalid campaign_id: {req.campaign_id}") from exc
        else:
            chat.campaign_id = None

    if req.full_document_mode_enabled is not None:
        chat.full_document_mode_enabled = req.full_document_mode_enabled
        logger.info(
            "full_document_mode_enabled=%s for chat_id=%s",
            req.full_document_mode_enabled, chat_id,
        )

    await db.commit()
    await db.refresh(chat)
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
    """Non-streaming endpoint. Accumulates all tokens from run_stream and returns final answer."""
    chat = await _get_chat_or_404(chat_id, db)

    user_msg = Message(chat_id=chat.id, role="user", content=req.content)
    db.add(user_msg)
    await db.flush()

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
        vault_id=chat.vault_id,
        vault_ids=vault_ids,
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
        logger.info("Pipeline disabled (__none__ sentinel) — skipping router, plain RAG; chat_id=%s", chat.id)
    else:
        pipeline_router = PipelineRouter(db)
        pipeline = await pipeline_router.select(context, locked_pipeline_id=chat.locked_pipeline_id)

    if pipeline is None:
        logger.info("No pipeline found for domain_id=%s — falling back to plain LLM chat", domain_id)
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
        chat_id=chat.id, role="assistant", content=full_answer,
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
        max_turns: int = int(await settings_service.get("chat.max_clarification_turns", db))
        prompt_pack = PromptPack(await domain_service.get_prompts(chat.domain_id or "default", db))
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
            history=[{"role": m.role, "content": m.content} for m in (context.history or [])],
        )
        if decision.clarification_needed and missing_fields:
            max_turns: int = int(await settings_service.get("chat.max_clarification_turns", db))
            prompt_pack = PromptPack(await domain_service.get_prompts(domain_id or "default", db))
            new_state = await clarification_fsm.start_collecting(db, chat.id, missing_fields, prompt_pack)
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
                chunk = json.dumps({"type": "clarification", "content": question}, ensure_ascii=False)
                yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(clarif_start_stream(), media_type="text/event-stream")

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
            domain_obj = await db.get(DomainModel, context.domain_id) if context.domain_id else None
            context.query = await query_rewriter.rewrite(
                original_query=context.query,
                history=context.history,
                provider=_provider,
                domain_description=(
                    domain_obj.description if domain_obj and domain_obj.description else None
                ),
            )

        # ── 2. Pipeline routing ───────────────────────────────────────────────
        if _locked_pipeline_id == PIPELINE_NONE_ID:
            pipeline = None
            logger.info("Pipeline disabled (__none__ sentinel) — skipping router; chat_id=%s", _chat.id)
        else:
            yield _step("Анализирую контекст запроса...")
            _pipeline_router = PipelineRouter(db)
            pipeline = await _pipeline_router.select(context, locked_pipeline_id=_locked_pipeline_id)

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
                _chat.id, pipeline.pipeline_id, confirm_token[:8],
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
        logger.info("No pipeline found for domain_id=%s — falling back to plain LLM stream", domain_id)

        system_prompt = await _resolve_system_prompt(context.campaign_id, domain_id, db)

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
                    _chat.id, len(candidates),
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
        full_system = f"{system_prompt}\n\n{rag_context}" if system_prompt else rag_context

        messages: list[dict[str, str]] = []
        if full_system:
            messages.append({"role": "system", "content": full_system})
        for m in (context.history or []):
            messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": req.content})

        yield _step("Отправка контекста в генеративную модель для ответа...")

        full_answer = ""
        cancelled = False
        try:
            async for token in _provider.generate_stream(messages):
                full_answer += token
                chunk = json.dumps({"type": "token", "content": token}, ensure_ascii=False)
                yield f"data: {chunk}\n\n"
        except asyncio.CancelledError:
            cancelled = True
        finally:
            await _reset_clarif_fsm()
            await _save_partial_answer(
                db, _chat, full_answer,
                title_query=context.original_query or req.content,
            )
            if cancelled:
                return

        if hits:
            sources_chunk = json.dumps(
                {
                    "type": "sources",
                    "grouped_by_step": False,
                    "sources": _hits_to_sources(hits),
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
    chat = await db.get(Chat, uuid.UUID(chat_id))
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
    if campaign_id:
        campaign = await db.get(Campaign, uuid.UUID(campaign_id))
        if campaign is not None and campaign.system_prompt:
            return campaign.system_prompt
    return await domain_service.get_prompt(domain_id or "default", "system", db)


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
        logger.info("Fallback RAG skipped: vault_ids=%s domain_id=%s", vault_ids, domain_id)
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
            document_ids = await get_document_ids_by_tags(list(allowed_tag_ids), domain_id, db)
            logger.info(
                "Fallback RAG campaign scope: campaign_id=%s allowed_tags=%d document_ids=%d",
                campaign_id, len(allowed_tag_ids), len(document_ids),
            )
            if document_ids == []:
                logger.info("Fallback RAG: no indexed documents for campaign tags, returning empty")
                return []
        else:
            logger.info("Fallback RAG: campaign has no tags, searching full domain domain_id=%s", domain_id)

    return await retrieve_multi_vault(
        query, vault_ids,
        document_ids=document_ids,
        top_k=top_k,
        strategy="hybrid",
        config=None,
        db=db,
        skip_rerank=skip_rerank,
    )


def _hits_to_sources(hits: list[SearchHit]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for hit in hits:
        metadata = hit.metadata or {}
        path = metadata.get("source_path") or hit.document_id
        page = metadata.get("page_number")
        vault_id = metadata.get("vault_id") or ""
        key = (path, page, vault_id)
        if key in seen:
            continue
        seen.add(key)
        sources.append({"path": path, "page": page, "vault_id": vault_id})
    return sources


async def _plain_llm_reply(
    query: str,
    context: PipelineExecutionContext,
    domain_id: str | None,
    db: AsyncSession,
) -> str:
    provider = settings_service.get_active_provider()
    if provider is None:
        raise HTTPException(503, "No LLM provider configured")

    system_prompt = await _resolve_system_prompt(context.campaign_id, domain_id, db)
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
    for m in (context.history or []):
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
    from app.db.models import AuditLog
    db.add(AuditLog(action=action, entity_type=entity_type, entity_id=entity_id, details=payload))


async def _pipeline_versions(request: Request) -> dict[str, str]:
    return {
        k.removeprefix("x-pipeline-"): v
        for k, v in request.headers.items()
        if k.lower().startswith("x-pipeline-")
    }
