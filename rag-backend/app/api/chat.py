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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import StreamingResponse

from app.config import AppConfig, EmbeddingModelConfig, VaultConfig
from app.db.models import (
    AuditLog,
    Chat,
    ClarificationState as ClarificationStateRow,
    EmbeddingModel,
    Message,
    Vault,
)
from app.db.session import SessionLocal, get_db
from app.providers.generation import GenerationProviderUnavailableError, get_generation_provider
from app.services import clarification_fsm
from app.services.planner import LLMRAGPlanner, Planner
from app.services.pipeline_executor import pipeline_executor
from app.services.pipeline_router import pipeline_router
from app.services.prompt_pack import PromptPack, format_prompt
from app.services.retrieval import format_context, retrieve, retrieve_multi_vault
from app.services.domain_service import domain_service
from app.services.settings_service import settings_service
from shared_contracts.models import (
    ChatMessage,
    ChatRecord,
    ChunkRecord,
    ClarificationResponse,
    CreateChatRequest,
    CreateChatResponse,
    PipelineContext,
    PipelineResult,
    PlannerDecision,
    SearchHit,
    SendMessageRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


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
    chat = Chat(
        title="New Chat",
        vault_id=req.vault_id,
        domain_id=req.domain_id,
        world_id=req.world_id,
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
        {"vault_id": req.vault_id, "domain_id": req.domain_id},
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
    return ChatListResponse(chats=[_chat_list_item(chat) for chat in result.scalars().all()])


@router.get("/{chat_id}", response_model=ChatHistoryResponse)
async def get_chat(chat_id: str, db: AsyncSession = Depends(get_db)) -> ChatHistoryResponse:
    chat = await _get_chat_with_messages(db, chat_id)
    return ChatHistoryResponse(
        chat=_chat_record(chat),
        messages=[_chat_message(message) for message in chat.messages],
        vault_enabled=await _vault_enabled(db, chat.vault_id),
    )


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    chat_uuid = _parse_uuid(chat_id)
    result = await db.execute(delete(Chat).where(Chat.id == chat_uuid))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    await _audit(db, "chat.delete", "chat", chat_id)
    await db.commit()
    logger.info("Deleted chat: chat_id=%s", chat_id)
    return {"status": "ok"}


@router.post("/{chat_id}/rename", response_model=CreateChatResponse)
async def rename_chat(
    chat_id: str,
    req: RenameChatRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateChatResponse:
    chat = await _get_chat(db, chat_id)
    chat.title = req.title.strip()
    await _audit(db, "chat.rename", "chat", chat_id, {"title": chat.title})
    await db.commit()
    await db.refresh(chat)
    logger.info("Renamed chat: chat_id=%s", chat_id)
    return CreateChatResponse(chat_id=str(chat.id), title=chat.title)


@router.put("/{chat_id}/pipeline")
async def lock_pipeline(
    chat_id: str,
    req: PipelineLockRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | None]:
    chat = await _get_chat(db, chat_id)
    chat.locked_pipeline_id = req.pipeline_id
    await _audit(db, "chat.pipeline.lock", "chat", chat_id, {"pipeline_id": req.pipeline_id})
    await db.commit()
    return {"chat_id": chat_id, "locked_pipeline_id": chat.locked_pipeline_id}


@router.post("/{chat_id}/message", response_model=None)
async def send_message(
    chat_id: str,
    req: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse | MessageResponse | ClarificationResponse:
    chat = await _get_chat(db, chat_id)
    existing_messages = await _get_messages(db, chat.id)
    is_first_user_message = not any(message.role == "user" for message in existing_messages)
    user_message = Message(chat_id=chat.id, role="user", content=req.content)
    db.add(user_message)
    await db.flush()
    await _audit(
        db,
        "message.create",
        "message",
        str(user_message.id),
        {"chat_id": chat_id, "role": "user"},
    )
    await db.commit()
    await db.refresh(user_message)

    if is_first_user_message and await settings_service.get("chat.auto_title", db):
        asyncio.create_task(_generate_title(chat_id, req.content))

    prompt_pack = await _prompt_pack_for_chat(chat, db)
    state = await clarification_fsm.get_state(db, chat.id)

    if state.stage == "idle":
        domain_id = await _domain_id_for_chat(chat, db)
        runtime_config = await _runtime_config_from_db(db)
        decision, missing_fields = await Planner(runtime_config, None).decide(
            db=db,
            query=req.content,
            vault_id=chat.vault_id,
            domain_id=domain_id,
            history=[_llm_message(message) for message in existing_messages[-8:]],
        )
        if decision.clarification_needed and missing_fields:
            next_state = await clarification_fsm.start_collecting(db, chat.id, missing_fields, prompt_pack)
            assistant_message = await _add_assistant_message(
                db,
                chat.id,
                next_state.next_question or "Уточните, пожалуйста.",
                chat_id,
            )
            await db.commit()
            return ClarificationResponse(
                message_id=str(assistant_message.id),
                content=assistant_message.content,
                state=next_state,
            )
    elif state.stage == "collecting":
        next_state = clarification_fsm.process_clarification_answer(
            state=state,
            user_message=req.content,
            max_turns=int(await settings_service.get("chat.max_clarification_turns", db)),
            prompt_pack=prompt_pack,
        )
        await clarification_fsm.save_state(db, chat.id, next_state)
        if next_state.stage == "collecting":
            assistant_message = await _add_assistant_message(
                db,
                chat.id,
                next_state.next_question or "Уточните, пожалуйста.",
                chat_id,
            )
            await db.commit()
            return ClarificationResponse(
                message_id=str(assistant_message.id),
                content=assistant_message.content,
                state=next_state,
            )
        await db.commit()
        decision = PlannerDecision(
            retrieval_strategy="semantic" if chat.vault_id and await settings_service.get("retrieval.enabled", db) else "none",
            clarification_needed=False,
            reasoning=f"clarification_state={next_state.stage}",
        )
        state = next_state
    else:
        decision = PlannerDecision(
            retrieval_strategy="semantic" if chat.vault_id and await settings_service.get("retrieval.enabled", db) else "none",
            clarification_needed=False,
            reasoning=f"clarification_state={state.stage}",
        )

    collected = state.collected if state.stage in {"complete", "fallback"} else {}
    selected_pipeline, mode, confidence, reasoning = await pipeline_router.decide(req.content, chat, db)
    if selected_pipeline is not None:
        # Резолвим vault_id: если чат привязан к vault — берём его,
        # иначе берём все vault'ы домена (для pipeline executor достаточно первого bound)
        pipeline_vault_id = chat.vault_id
        if pipeline_vault_id is None and chat.domain_id:
            config_for_vault = await _runtime_config_from_db(db)
            domain_vaults = [
                v.vault_id for v in config_for_vault.vaults.values()
                if v.domain_id == chat.domain_id and v.enabled
            ]
            pipeline_vault_id = domain_vaults[0] if domain_vaults else None
    
        chat_context = {
            "chat_id": chat.id,
            "vault_id": pipeline_vault_id,   # ← было chat.vault_id
            "domain_id": chat.domain_id,
            "collected_fields": collected,
            "history": [_llm_message(message) for message in existing_messages[-8:]],
            "mode": mode,
            "confidence": confidence,
            "reasoning": reasoning,
            "config": await _runtime_config_from_db(db),
        }
        return StreamingResponse(
            _pipeline_sse_response(
                chat_id=str(chat.id),
                user_message_id=str(user_message.id),
                pipeline=selected_pipeline,
                query=req.content,
                chat_context=chat_context,
                db=db,
                request=request,
            ),
            media_type="text/event-stream",
        )
    return await _generate_answer(
        chat=chat,
        req=req,
        request=request,
        existing_messages=existing_messages,
        user_message=user_message,
        db=db,
        prompt_pack=prompt_pack,
        decision=decision,
        collected=collected,
    )


async def _generate_answer(
    chat: Chat,
    req: SendMessageRequest,
    request: Request,
    existing_messages: list[Message],
    user_message: Message,
    db: AsyncSession,
    prompt_pack: PromptPack,
    decision: PlannerDecision,
    collected: dict[str, Any],
) -> StreamingResponse | MessageResponse:
    config = await _runtime_config_from_db(db)
    queries = [req.content]
    if decision.retrieval_strategy == "semantic" and await settings_service.get("retrieval.enabled", db):
        try:
            planner = LLMRAGPlanner(config)
            history_texts = [m.content for m in existing_messages[-4:]]
            queries = await planner.decompose(req.content, await _domain_id_for_chat(chat, db) or "default", history_texts)
        except Exception as e:
            logger.warning("LLM decomposition failed, using raw query: %s", e)
            queries = [req.content]

    all_hits: list[SearchHit] = []
    top_k = int(await settings_service.get("retrieval.top_k", db))

    if chat.vault_id:
        for q in queries:
            hits = await retrieve(query=q, vault_id=chat.vault_id, top_k=top_k, strategy=decision.retrieval_strategy, config=config)
            all_hits.extend(hits)
    elif chat.domain_id and decision.retrieval_strategy == "semantic":
        vault_ids = [v.vault_id for v in config.vaults.values() if v.domain_id == chat.domain_id and v.enabled]
        for q in queries:
            hits = await retrieve_multi_vault(query=q, vault_ids=vault_ids, top_k=top_k, strategy=decision.retrieval_strategy, config=config)
            all_hits.extend(hits)
    else:
        all_hits = []

    seen = set()
    unique_hits: list[SearchHit] = []
    for h in all_hits:
        if h.chunk_id not in seen:
            seen.add(h.chunk_id)
            unique_hits.append(h)
    unique_hits.sort(key=lambda h: h.score, reverse=True)
    hits = unique_hits[: top_k * 2]

    pipeline_results = await _run_pipelines(
        request=request,
        chat=chat,
        query=req.content,
        hits=hits,
        existing_messages=existing_messages,
        collected=collected,
        decision=decision,
    )
    context_text = _combined_context(hits, pipeline_results)
    system_prompt = _system_prompt(prompt_pack, query=req.content, hits_context=context_text, collected=collected)
    messages_for_llm = [{"role": "system", "content": system_prompt}]
    messages_for_llm.extend(_llm_message(message) for message in existing_messages[-16:])
    messages_for_llm.append({"role": "user", "content": req.content})

    try:
        provider = get_generation_provider()
    except Exception:
        logger.warning("Generation provider configuration failed.", exc_info=True)
        provider = None

    if req.stream:
        stream_iterator = provider.generate_stream(messages_for_llm) if provider is not None else _fallback_stream()
        return StreamingResponse(
            _sse_response(str(chat.id), str(user_message.id), stream_iterator, request, hits),
            media_type="text/event-stream",
        )

    try:
        content = await provider.generate(messages_for_llm) if provider is not None else _fallback_answer()
    except GenerationProviderUnavailableError:
        logger.warning("Generation provider unavailable; returning fallback answer.", exc_info=True)
        content = _fallback_answer()

    assistant_message = await _save_assistant_message(str(chat.id), content, reset_clarification=True)
    logger.info("Completed non-stream chat response: chat_id=%s message_id=%s", chat.id, assistant_message.id)
    return MessageResponse(content=content, message_id=str(assistant_message.id))


def _hits_to_sources(hits: list[SearchHit]) -> list[dict]:
    seen: set[tuple[str, int | None]] = set()
    sources = []
    for hit in hits:
        path = hit.metadata.get("source_path") or hit.document_id or "unknown"
        page = hit.metadata.get("page_number")
        key = (path, page)
        if key not in seen:
            seen.add(key)
            sources.append({
                "path": path,
                "page": page,
                "vault_id": hit.metadata.get("vault_id") or "",
            })
    return sources


async def _sse_response(
    chat_id: str,
    user_message_id: str,
    stream_iterator: AsyncIterator[str],
    request: Request,
    hits: list[SearchHit] | None = None,
) -> AsyncIterator[str]:
    tokens: list[str] = []
    try:
        async for token in stream_iterator:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: chat_id=%s", chat_id)
                return
            tokens.append(token)
            yield _sse_data({"token": token})
        # ИСПРАВЛЕНО: склеиваем токены БЕЗ разделителя — провайдеры
        # (OpenAI/Ollama) возвращают токены уже с пробелами в нужных местах.
        # Было: " ".join(tokens) → давало "П р о в е р к а"
        # Стало: "".join(tokens)  → даёт "Проверка"
        assistant_message = await _save_assistant_message(chat_id, "".join(tokens), reset_clarification=True)
        logger.info(
            "Completed streaming chat response: chat_id=%s user_message_id=%s assistant_message_id=%s",
            chat_id,
            user_message_id,
            assistant_message.id,
        )
        if hits:
            sources = _hits_to_sources(hits)
            yield _sse_data({"sources": sources})
        yield "data: [DONE]\n\n"
    except GenerationProviderUnavailableError as exc:
        logger.warning("Streaming generation failed: chat_id=%s", chat_id, exc_info=True)
        fallback = _fallback_answer()
        tokens.append(fallback)
        yield _sse_data({"token": fallback, "warning": str(exc)})
        await _save_assistant_message(chat_id, fallback, reset_clarification=True)
        yield "data: [DONE]\n\n"


async def _pipeline_sse_response(
    chat_id: str,
    user_message_id: str,
    pipeline: Any,
    query: str,
    chat_context: dict[str, Any],
    db: AsyncSession,
    request: Request,
) -> AsyncIterator[str]:
    tokens: list[str] = []
    async for event in pipeline_executor.run(pipeline, query, chat_context, db, request=request):
        if event.get("type") == "token":
            tokens.append(str(event.get("content", "")))
        yield _sse_data(event)
    if tokens:
        # ИСПРАВЛЕНО: склеиваем токены БЕЗ разделителя
        assistant_message = await _save_assistant_message(chat_id, "".join(tokens), reset_clarification=True)
        logger.info(
            "Completed pipeline chat response: chat_id=%s user_message_id=%s assistant_message_id=%s",
            chat_id,
            user_message_id,
            assistant_message.id,
        )
    yield "data: [DONE]\n\n"


async def _save_assistant_message(chat_id: str, content: str, reset_clarification: bool = False) -> Message:
    async with SessionLocal() as db:
        chat = await _get_chat(db, chat_id)
        assistant_message = await _add_assistant_message(db, chat.id, content, chat_id)
        if reset_clarification:
            await clarification_fsm.save_state(db, chat.id, clarification_fsm.idle_state())
        await db.commit()
        await db.refresh(assistant_message)
        return assistant_message


async def _add_assistant_message(db: AsyncSession, chat_uuid: uuid.UUID, content: str, chat_id: str) -> Message:
    assistant_message = Message(chat_id=chat_uuid, role="assistant", content=content)
    db.add(assistant_message)
    await db.flush()
    await _audit(
        db,
        "message.create",
        "message",
        str(assistant_message.id),
        {"chat_id": chat_id, "role": "assistant"},
    )
    return assistant_message


async def _generate_title(chat_id: str, first_message: str) -> None:
    try:
        provider = get_generation_provider()
    except Exception:
        logger.warning("Auto-title generation provider is not configured: chat_id=%s", chat_id, exc_info=True)
        return
    prompt = (
        "Сгенерируй краткое название для чата на основе сообщения. "
        "Максимум 5 слов. Верни только название без кавычек.\n\n"
        f"Сообщение: {first_message}"
    )
    try:
        title = await provider.generate(
            [
                {"role": "system", "content": "Ты создаешь короткие названия чатов."},
                {"role": "user", "content": prompt},
            ]
        )
    except GenerationProviderUnavailableError:
        logger.warning("Auto-title generation failed: chat_id=%s", chat_id, exc_info=True)
        return
    normalized_title = _normalize_title(title)
    if not normalized_title:
        return
    async with SessionLocal() as db:
        chat = await _get_chat(db, chat_id)
        if chat.title != "New Chat":
            return
        chat.title = normalized_title
        await _audit(db, "chat.auto_title", "chat", chat_id, {"title": normalized_title})
        await db.commit()
        logger.info("Generated chat title: chat_id=%s title=%s", chat_id, normalized_title)


async def _get_chat(db: AsyncSession, chat_id: str) -> Chat:
    chat_uuid = _parse_uuid(chat_id)
    chat = await db.get(Chat, chat_uuid)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


async def _get_chat_with_messages(db: AsyncSession, chat_id: str) -> Chat:
    chat_uuid = _parse_uuid(chat_id)
    result = await db.execute(
        select(Chat).options(selectinload(Chat.messages)).where(Chat.id == chat_uuid)
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


async def _get_messages(db: AsyncSession, chat_id: uuid.UUID) -> list[Message]:
    result = await db.execute(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at, Message.id))
    return list(result.scalars().all())


async def _audit(
    db: AsyncSession,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(AuditLog(action=action, entity_type=entity_type, entity_id=entity_id, details=details or {}))


def _chat_record(chat: Chat) -> ChatRecord:
    return ChatRecord(
        chat_id=str(chat.id),
        title=chat.title or "New Chat",
        vault_id=chat.vault_id,
        domain_id=chat.domain_id,
        world_id=chat.world_id,
        locked_pipeline_id=chat.locked_pipeline_id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        pipeline_versions=chat.pipeline_versions or {},
    )


def _chat_message(message: Message) -> ChatMessage:
    return ChatMessage(
        message_id=str(message.id),
        chat_id=str(message.chat_id),
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        metadata={},
    )


def _chat_list_item(chat: Chat) -> ChatListItem:
    return ChatListItem(
        chat_id=str(chat.id),
        title=chat.title or "New Chat",
        vault_id=chat.vault_id,
        domain_id=chat.domain_id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


async def _vault_enabled(db: AsyncSession, vault_id: str | None) -> bool:
    if not vault_id:
        return False
    vault = await db.get(Vault, vault_id)
    return bool(vault and vault.enabled)


async def _runtime_config_from_db(db: AsyncSession) -> AppConfig:
    vaults_result = await db.execute(select(Vault))
    vaults = {
        vault.vault_id: VaultConfig(
            vault_id=vault.vault_id,
            domain_id=vault.domain_id,
            path=f"/data/vaults/{vault.vault_id}",
            enabled=vault.enabled,
        )
        for vault in vaults_result.scalars().all()
    }
    models_result = await db.execute(select(EmbeddingModel).where(EmbeddingModel.enabled == True))
    embedding_models = {
        model.model_id: EmbeddingModelConfig(
            model_id=model.model_id,
            provider=model.provider,
            model_name=model.model_name,
            base_url=model.base_url,
            dimensions=model.dimensions,
            enabled=model.enabled,
            timeout_seconds=model.timeout_seconds,
            max_retries=model.max_retries,
        )
        for model in models_result.scalars().all()
    }
    return AppConfig(vaults=vaults, embedding_models=embedding_models, generation_models={})


def _llm_message(message: Message) -> dict[str, str]:
    return {"role": message.role, "content": message.content}


async def _prompt_pack_for_chat(chat: Chat, db: AsyncSession) -> PromptPack:
    domain_id = await _domain_id_for_chat(chat, db) or "default"
    domain = await domain_service.get_domain(domain_id, db)
    return PromptPack(
        domain_id=domain.domain_id,
        description="",
        prompts=domain.prompts,
    )


async def _domain_id_for_chat(chat: Chat, db: AsyncSession) -> str | None:
    if chat.domain_id is not None:
        return chat.domain_id
    if chat.vault_id:
        vault = await db.get(Vault, chat.vault_id)
        if vault is not None:
            return vault.domain_id
    return None


async def _pipeline_versions(request: Request) -> dict[str, str]:
    _ = request
    return {}


async def _run_pipelines(
    request: Request,
    chat: Chat,
    query: str,
    hits: list[SearchHit],
    existing_messages: list[Message],
    collected: dict[str, Any],
    decision: PlannerDecision,
) -> list[PipelineResult]:
    _ = request, chat, query, hits, existing_messages, collected, decision
    return []


def _hit_to_chunk(hit: SearchHit, vault_id: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        vault_id=vault_id,
        text=hit.text,
        vector=None,
        metadata=hit.metadata,
        summary=None,
    )


def _combined_context(hits: list[SearchHit], pipeline_results: list[PipelineResult]) -> str:
    parts = []
    search_context = format_context(hits)
    if search_context:
        parts.append(search_context)
    for result in pipeline_results:
        parts.append(f"Pipeline result confidence={result.confidence}: {result.content}\nmetadata={result.metadata}")
    return "\n\n".join(parts)


def _system_prompt(prompt_pack: PromptPack, query: str, hits_context: str, collected: dict[str, Any]) -> str:
    template = prompt_pack.get(
        "system",
        "You are a helpful assistant. Use retrieved context when relevant.\n\nContext:\n{context}",
    )
    return format_prompt(
        template,
        {
            "query": query,
            "context": hits_context,
            "collected_fields": collected,
        },
    )


async def _fallback_stream() -> AsyncIterator[str]:
    yield _fallback_answer()


def _fallback_answer() -> str:
    return "LLM service unavailable. Попробуйте повторить запрос позже."


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid UUID") from exc


def _sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _normalize_title(title: str) -> str:
    cleaned = title.strip().strip('"').strip("'")
    words = cleaned.split()
    if len(words) > 7:
        cleaned = " ".join(words[:7])
    return cleaned[:255]