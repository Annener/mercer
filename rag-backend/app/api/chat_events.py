"""chat_events.py

SSE + poll endpoints, через которые фронт узнаёт о фазах drift loop.

Архитектурные соглашения (см. context.md §«SSE conventions»):
- media_type="text/event-stream"
- каждый чанк: ``data: <json>\n\n``
- heartbeat: ``: heartbeat\n\n`` каждые 15 секунд без активности
- финальный чанк не отправляется — клиент сам разрывает по unmount/endpoints.

Один SSE-эндпоинт покрывает все drift-фазы (``detecting`` → ``drafting``
→ ``draft_ready`` → ``idle`` или ``error``). Подписки на чат
per-connection — asyncio.Queue из ``DriftStatusBus.subscribe``.

Poll-fallback (``GET /api/chats/{chat_id}/drift-status``) — возвращает
последний зафиксированный статус из Redis (TTL 60 сек). Полезен если
EventSource блокируется прокси/файрволом.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid as _uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat
from app.db.session import get_db
from app.services.context_engine.status_bus import DriftStatusBus
from shared_contracts.models import DriftStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat-events"])


_HEARTBEAT_INTERVAL_SECONDS = 15.0
_QUEUE_GET_TIMEOUT_SECONDS = 15.0


async def _load_chat_or_404(chat_id: str, db: AsyncSession) -> Chat:
    try:
        chat_uuid = _uuid.UUID(chat_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="chat_not_found") from None
    chat = await db.get(Chat, chat_uuid)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat_not_found")
    return chat


def _resolve_bus(request: Request) -> DriftStatusBus:
    bus = getattr(request.app.state, "drift_status_bus", None)
    if bus is None:
        raise HTTPException(status_code=503, detail="status_bus_unavailable")
    return bus


@router.get("/api/chats/{chat_id}/events")
async def stream_chat_events(
    chat_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE-поток drift-статусов.

    Сначала отдаёт текущий последний статус из Redis (catch-up), затем
    подписывается на шину и транслирует события в реальном времени.
    Пустой поток не закрывается — клиент получит heartbeat, пока
    что-то не произойдёт.
    """
    await _load_chat_or_404(chat_id, db)
    bus = _resolve_bus(request)

    async def _stream() -> AsyncIterator[str]:
        try:
            async with bus.subscribe(chat_id) as queue:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        status = await asyncio.wait_for(
                            queue.get(),
                            timeout=_QUEUE_GET_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        # Heartbeat — держит SSE-соединение живым и
                        # помогает прокси отличать активный стрим от зависшего.
                        yield ": heartbeat\n\n"
                        continue
                    yield f"data: {status.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            logger.debug("chat_events: client disconnected chat_id=%s", chat_id)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chat_events: stream failed chat_id=%s: %s", chat_id, exc
            )
            # yield error envelope чтобы клиент увидел причину
            try:
                err = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
                yield f"data: {err}\n\n"
            except Exception:  # noqa: BLE001
                pass

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/api/chats/{chat_id}/drift-status")
async def get_drift_status(
    chat_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poll-fallback: последний известный drift-статус из Redis (TTL 60 сек)."""
    await _load_chat_or_404(chat_id, db)
    bus = _resolve_bus(request)
    status: DriftStatus | None = await bus.get(chat_id)
    if status is None:
        # Возвращаем явный idle, чтобы клиент не показывал "неизвестно".
        from datetime import datetime, timezone

        status = DriftStatus(
            chat_id=chat_id,
            published_at=datetime.now(timezone.utc),
        )
    return status.model_dump(mode="json")
