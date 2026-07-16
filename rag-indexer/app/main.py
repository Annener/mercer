from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException, Request

from app.db_client import IndexerDBClient
from app.indexer_service import IndexerService
from app.update_mode.router import router as update_mode_router
from logging_config import setup_logging
from parser.scanning.vault_scanner import scan_vault
from parser.state.redis_state_manager import RedisStateManager
from parser.watchdog.vault_watchdog import watchdog_loop
from shared_contracts.models import StartIndexTaskRequest, StartIndexTaskResponse, TaskStateResponse
from storage.storage_client import StorageClient


logger = logging.getLogger(__name__)

VAULT_DATA_ROOT = os.getenv("VAULT_DATA_ROOT", "/data/vaults")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging("indexer")

    # Redis
    redis_client = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379"),
        decode_responses=True,
    )
    state_manager = RedisStateManager(redis_client)

    # DB
    db_client = IndexerDBClient()
    await db_client.connect(os.getenv("DATABASE_URL", ""), os.getenv("ENCRYPTION_KEY", ""))

    # Rebuild vault cache из PostgreSQL + disk scan
    try:
        vaults = await db_client.get_all_vaults()
        rebuild_tasks = [
            _rebuild_one_vault(
                state_manager,
                db_client,
                vault["vault_id"],
                f"{VAULT_DATA_ROOT}/{vault['vault_id']}",
            )
            for vault in vaults
        ]
        results = await asyncio.gather(*rebuild_tasks, return_exceptions=True)
        for vault, result in zip(vaults, results):
            if isinstance(result, Exception):
                logger.error(
                    "Vault cache rebuild failed: vault_id=%s error=%s",
                    vault["vault_id"], result,
                )
    except Exception:
        logger.exception("Failed to rebuild vault cache on startup — continuing")

    app.state.db_client = db_client
    app.state.redis_client = redis_client
    app.state.state_manager = state_manager
    app.state.indexer_service = IndexerService(
        db_client=db_client,
        state_manager=state_manager,
    )

    # Watchdog — interval_sec читается из platform_settings на каждой итерации
    storage_client = StorageClient(
        os.getenv("STORAGE_API_URL", "http://db-api-server:8080")
    )
    watchdog_task: asyncio.Task[None] | None = None
    watchdog_task = asyncio.create_task(
        watchdog_loop(
            db_client=db_client,
            state_manager=state_manager,
            indexer_service=app.state.indexer_service,
            storage_client=storage_client,
        ),
        name="vault-watchdog",
    )
    logger.info("Vault watchdog scheduled (interval from platform_settings)")
    logger.info("Service started. DB client connected. Redis ready.")

    try:
        yield
    finally:
        logger.info("Service shutdown requested. Cancelling active indexer tasks.")
        if watchdog_task is not None:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
        await app.state.indexer_service.shutdown(timeout_seconds=30)
        await db_client.close()
        await redis_client.aclose()
        logger.info("Service stopped.")


async def _rebuild_one_vault(
    state_manager: RedisStateManager,
    db_client: IndexerDBClient,
    vault_id: str,
    vault_path: str,
) -> None:
    if not os.path.isdir(vault_path):
        logger.warning(
            "Vault path not found, skipping cache rebuild: vault_id=%s path=%s",
            vault_id, vault_path,
        )
        return
    try:
        pg_docs = await db_client.get_all_documents(vault_id)
        disk_files = await asyncio.to_thread(scan_vault, vault_path)
        await state_manager.rebuild_vault_cache(vault_id, pg_docs, disk_files)
        logger.info(
            "Vault cache rebuilt: vault_id=%s pg_docs=%d disk_files=%d",
            vault_id, len(pg_docs), len(disk_files),
        )
    except Exception:
        logger.exception("Error rebuilding vault cache: vault_id=%s", vault_id)
        raise


app = FastAPI(title="RAG Indexer", lifespan=lifespan)

# Internal update-mode endpoints (resolve + apply)
app.include_router(update_mode_router)


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


@app.get("/api/v1/tasks/{task_id}/state")
async def get_task_state(task_id: str, request: Request) -> dict[str, Any]:
    """Polling endpoint: возвращает состояние задачи из Redis."""
    state_manager: RedisStateManager = request.app.state.state_manager
    raw = await state_manager.get_task_state(task_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return raw


@app.get("/tasks/{task_id}/state")
async def get_task_state_legacy(task_id: str, request: Request) -> dict[str, Any]:
    """Legacy alias for backwards compatibility."""
    return await get_task_state(task_id, request)


@app.get("/api/v1/vaults/{vault_id}/documents/all")
async def get_vault_documents(
    vault_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    db: IndexerDBClient = request.app.state.db_client
    return await db.get_all_documents(vault_id)


def _indexer_service(request: Request) -> IndexerService:
    service = getattr(request.app.state, "indexer_service", None)
    if not isinstance(service, IndexerService):
        raise HTTPException(status_code=503, detail="Indexer service is not initialized")
    return service


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=9000)
