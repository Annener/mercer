"""API-прокси к host-agent для управления pdf-sidecar.

Все запросы передаются на host-agent, запущенный на хосте.

Маршруты:
  GET  /api/settings/sidecar/status
  POST /api/settings/sidecar/start
  POST /api/settings/sidecar/stop
  POST /api/settings/sidecar/restart
  GET  /api/settings/sidecar/install/stream   (Проксируем SSE-поток)
"""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sidecar", tags=["sidecar"])

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

# Адрес host-agent. На macOS/Windows Docker Desktop host.docker.internal резолвится автоматически.
# На Linux нужно добавить extra_hosts: host.docker.internal=host-gateway в docker-compose.yml.
HOST_AGENT_URL: str = os.getenv("HOST_AGENT_URL", "http://host.docker.internal:9090")
HOST_AGENT_TOKEN: str | None = os.getenv("HOST_AGENT_TOKEN")

_AGENT_UNAVAILABLE = "host-agent недоступен. Убедитесь, что host-agent запущен на хосте."


def _agent_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if HOST_AGENT_TOKEN:
        headers["X-Agent-Token"] = HOST_AGENT_TOKEN
    return headers


def _safe_json(resp: httpx.Response) -> dict:
    """Парсит JSON из ответа; при ошибке возвращает dict с raw-текстом."""
    try:
        return resp.json()
    except Exception:
        return {"error": resp.text}


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------

@router.get("/status")
async def sidecar_status() -> JSONResponse:
    """Status sidecar-процесса и факт установки."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{HOST_AGENT_URL}/sidecar/status",
                headers=_agent_headers(),
            )
        return JSONResponse(content=_safe_json(resp), status_code=resp.status_code)
    except httpx.ConnectError:
        # Агент не запущен — возвращаем 503 с признаком agent_unavailable
        return JSONResponse(
            content={"running": False, "installed": False, "agent_unavailable": True},
            status_code=200,  # 200 чтобы frontend не считал это ошибкой
        )
    except httpx.HTTPError as exc:
        logger.warning("host-agent error: %s", exc)
        raise HTTPException(status_code=502, detail=_AGENT_UNAVAILABLE) from exc


@router.post("/start")
async def sidecar_start() -> JSONResponse:
    """Start sidecar."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{HOST_AGENT_URL}/sidecar/start",
                headers=_agent_headers(),
            )
        if resp.status_code >= 500:
            raise HTTPException(status_code=502, detail=resp.text)
        return JSONResponse(content=_safe_json(resp), status_code=resp.status_code)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail=_AGENT_UNAVAILABLE) from exc


@router.post("/stop")
async def sidecar_stop() -> JSONResponse:
    """Stop sidecar."""
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{HOST_AGENT_URL}/sidecar/stop",
                headers=_agent_headers(),
            )
        if resp.status_code >= 500:
            raise HTTPException(status_code=502, detail=resp.text)
        return JSONResponse(content=_safe_json(resp), status_code=resp.status_code)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail=_AGENT_UNAVAILABLE) from exc


@router.post("/restart")
async def sidecar_restart() -> JSONResponse:
    """Restart sidecar."""
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(
                f"{HOST_AGENT_URL}/sidecar/restart",
                headers=_agent_headers(),
            )
        if resp.status_code >= 500:
            raise HTTPException(status_code=502, detail=resp.text)
        return JSONResponse(content=_safe_json(resp), status_code=resp.status_code)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail=_AGENT_UNAVAILABLE) from exc


@router.get("/install/stream")
async def sidecar_install_stream() -> StreamingResponse:
    """SSE-прокси вывода install.sh из host-agent."""

    async def _proxy_stream() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET",
                    f"{HOST_AGENT_URL}/sidecar/install/stream",
                    headers=_agent_headers(),
                ) as response:
                    async for chunk in response.aiter_bytes(1024):
                        yield chunk
        except httpx.ConnectError:
            yield "data: ERROR: host-agent недоступен\n\n".encode("utf-8")
        except Exception as exc:
            logger.exception("install stream error")
            yield f"data: ERROR: {exc}\n\n".encode("utf-8")

    return StreamingResponse(
        _proxy_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
