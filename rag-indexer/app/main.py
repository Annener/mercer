from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.db_client import IndexerDBClient
from app.indexer_service import IndexerService
from app.websocket_manager import ConnectionManager
from logging_config import setup_logging
from parser.state.state_manager import load_state
from shared_contracts.models import StartIndexTaskRequest, StartIndexTaskResponse, TaskStateResponse


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging("indexer")
    db_client = IndexerDBClient()
    await db_client.connect(os.getenv("DATABASE_URL", ""), os.getenv("ENCRYPTION_KEY", ""))
    app.state.db_client = db_client
    app.state.ws_manager = ConnectionManager()
    app.state.indexer_service = IndexerService(
        db_client=db_client,
        broadcaster=app.state.ws_manager.broadcast,
    )
    logger.info("Service started. DB client connected.")
    try:
        yield
    finally:
        logger.info("Service shutdown requested. Cancelling active indexer tasks.")
        await app.state.indexer_service.shutdown(timeout_seconds=30)
        await db_client.close()
        logger.info("Service stopped.")


app = FastAPI(title="RAG Indexer", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "rag-indexer"}


@app.post("/api/v1/tasks", response_model=StartIndexTaskResponse)
async def start_index_task(req: StartIndexTaskRequest, request: Request) -> StartIndexTaskResponse:
    try:
        task_id = await _indexer_service(request).start_task(req.vault_id, req.force_reindex)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StartIndexTaskResponse(task_id=task_id, vault_id=req.vault_id, status="queued")


@app.get("/api/v1/tasks")
async def list_index_tasks(request: Request) -> dict[str, list[str]]:
    return {"active_task_ids": await _indexer_service(request).get_active_tasks()}


@app.post("/api/v1/tasks/{task_id}/cancel")
async def cancel_index_task(task_id: str, request: Request) -> dict[str, bool | str]:
    cancelled = await _indexer_service(request).cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Active task not found")
    return {"task_id": task_id, "cancelled": True}


@app.get("/api/v1/tasks/{task_id}/state", response_model=TaskStateResponse)
async def get_task_state(task_id: str) -> TaskStateResponse:
    state = await load_state(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Task state not found")
    return TaskStateResponse(task_id=state.task_id, vault_id=state.vault_id, status=state.status, state=state)


@app.get("/tasks/{task_id}/state", response_model=TaskStateResponse)
async def get_task_state_legacy(task_id: str) -> TaskStateResponse:
    return await get_task_state(task_id)


@app.websocket("/api/v1/tasks/{task_id}/stream")
async def stream_task(task_id: str, websocket: WebSocket) -> None:
    manager = _ws_manager(websocket)
    await manager.connect(task_id, websocket)
    try:
        state = await load_state(task_id)
        if state is not None:
            await websocket.send_json({"type": "snapshot", "state": state.model_dump(mode="json")})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(task_id, websocket)


def _indexer_service(request: Request) -> IndexerService:
    service = getattr(request.app.state, "indexer_service", None)
    if not isinstance(service, IndexerService):
        raise HTTPException(status_code=503, detail="Indexer service is not initialized")
    return service


def _ws_manager(websocket: WebSocket) -> ConnectionManager:
    manager = getattr(websocket.app.state, "ws_manager", None)
    if not isinstance(manager, ConnectionManager):
        raise RuntimeError("WebSocket manager is not initialized")
    return manager


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=9000)
