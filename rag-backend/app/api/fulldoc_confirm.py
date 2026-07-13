"""fulldoc_confirm.py

Endpoint: POST /chat/{chat_id}/full_document_confirm

SSE-поток. Принимает список document_ids, выбранных пользователем в full_document_selection_required,
и возобновляет пайплайн через PipelineExecutor.resume_from_full_doc_selection().

Архитектурные соглашения см. context.md §«SSE conventions»:
  - media_type="text/event-stream"
  - каждый чанк: data: <json>\n\n
  - финальный чанк: data: [DONE]\n\n

SSE chunk types (повторяют типы pipeline_resume.py):
  {"type": "step_status", "text": str}
  {"type": "token", "content": str}
  {"type": "pipeline_complete"}
  {"type": "error", "message": str}
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message
from app.db.session import SessionLocal, get_db
from app.services.pipeline_executor import PipelineExecutor
from app.services.settings_service import settings_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


class FullDocConfirmRequest(BaseModel):
    """Тело запроса POST /chat/{chat_id}/full_document_confirm.

    selected_document_ids: список document_id документов, выбранных пользователем.
    Пустой список ("пропустить") допустим: пайплайн запустится с одними чанками.
    """
    selected_document_ids: list[str] = []


@router.post("/{chat_id}/full_document_confirm")
async def full_document_confirm(
    chat_id: str,
    req: FullDocConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """SSE-эндпоинт: возобновляет пайплайн после выбора полных документов.

    1. Валидируем chat_id.
    2. Запускаем PipelineExecutor.resume_from_full_doc_selection() — SSE-поток.
    3. Токены передаём клиенту, по завершению сохраняем сообщение в БД.
    """
    # Быстрая валидация chat_id до старта стрима — чтобы вернуть 422 сразу, а не в SSE.
    try:
        uuid.UUID(chat_id)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid chat_id: {chat_id}") from exc

    async def _stream() -> AsyncIterator[str]:
        full_answer = ""
        message_saved = False

        # Используем отдельную сессию для исполнения (SessionLocal),
        # т.к. db из Depends(get_db) может закрыться до окончания генератора.
        # Точно так же сделано в pipeline_resume.py::pipeline_resume.
        async with SessionLocal() as exec_db:
            executor = PipelineExecutor(exec_db)
            async for chunk in executor.resume_from_full_doc_selection(
                chat_id=chat_id,
                selected_document_ids=req.selected_document_ids,
                db=exec_db,
            ):
                chunk_type = chunk.get("type")

                if chunk_type == "token":
                    token_content = chunk.get("content", "")
                    full_answer += token_content

                if chunk_type == "pipeline_complete":
                    # Сохраняем ответ ассистента в БД перед отправкой pipeline_complete
                    if full_answer and not message_saved:
                        try:
                            chat_uuid = uuid.UUID(chat_id)
                            from app.db.models import Chat as ChatModel
                            chat = await exec_db.get(ChatModel, chat_uuid)
                            if chat is not None:
                                assistant_msg = Message(
                                    chat_id=chat.id,
                                    role="assistant",
                                    content=full_answer,
                                )
                                exec_db.add(assistant_msg)
                                await exec_db.commit()
                                message_saved = True
                                logger.info(
                                    "full_document_confirm: saved assistant message "
                                    "chat_id=%s len=%d",
                                    chat_id, len(full_answer),
                                )
                        except Exception as save_exc:
                            logger.warning(
                                "full_document_confirm: failed to save message: %s", save_exc
                            )

                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
