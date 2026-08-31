from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.config_api import router as config_router
from app.api.db_management import router as db_management_router
from app.api.fulldoc_confirm import router as fulldoc_confirm_router
from app.api.indexer_state import router as indexer_state_router
from app.api.pipeline_resume import router as pipeline_resume_router
from app.api.settings import router as settings_router
from app.api.update_mode import router as update_mode_router
from app.api.watchdog_settings import router as watchdog_router
from app.db.migrations import run_migrations
from app.db.session import SessionLocal, dispose_engine
from app.logging_config import setup_logging
from app.services.context_engine.draft import CampaignStateDrafter
from app.services.context_engine.drift import DriftDetector
from app.services.context_engine.loop import DriftLoop
from app.services.domain_service import domain_service
from app.services.settings_service import settings_service

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging("backend")
    await run_migrations()
    setup_logging("backend")
    app.state.settings_service = settings_service
    app.state.domain_service = domain_service

    # Redis client — читаем напрямую, без RedisStateManager (он живёт в rag-indexer)
    redis_client = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379"),
        decode_responses=True,
    )
    app.state.redis = redis_client

    try:
        async with SessionLocal() as db:
            await settings_service.load_settings(db)
            await settings_service.load_active_provider(db)
    except Exception:
        logger.critical(
            "Failed to initialize runtime settings or active generation model.",
            exc_info=True,
        )
        sys.exit(1)
    if settings_service.get_active_provider() is None:
        logger.warning(
            "No active generation model configured. "
            "Application will start but LLM features will be unavailable."
        )

    # Phase 2b: DriftLoop — фоновый drift-detection после каждого turn-а.
    # Drift провайдер может быть недоступен — loop стартует в любом случае,
    # а detector.detect тихо возвращает None при ошибках.
    drift_detector = DriftDetector(
        db_factory=SessionLocal, redis_client=redis_client
    )
    drift_loop = DriftLoop(detector=drift_detector, redis=redis_client)

    # Phase 3: CampaignStateDrafter — план auto-draft на основе drift hints.
    # Сохраняется в Redis (TTL 3 часа). Использует активную generation-модель
    # из settings_service (может быть None при старте без настроек).
    drafter = CampaignStateDrafter(
        db_factory=SessionLocal,
        redis_client=redis_client,
        generation_provider_factory=lambda: settings_service.get_active_provider(),
    )
    drift_loop.drafter = drafter
    app.state.drafter = drafter

    app.state.drift_loop = drift_loop
    drift_loop._idle_task = asyncio.create_task(drift_loop.run_idle_scan())
    logger.info("Drift loop started")

    logger.info("Service started. Database migrations applied.")
    try:
        yield
    finally:
        drift_loop.shutdown()
        await redis_client.aclose()
        await dispose_engine()
        logger.info("Service stopped.")

app = FastAPI(title="RAG Backend", lifespan=lifespan)

# === Роутеры ===
app.include_router(chat_router)
app.include_router(pipeline_resume_router)  # Stage 5: pipeline_confirm + pipeline_resume
app.include_router(fulldoc_confirm_router)  # Stage 5: full_document_confirm
app.include_router(config_router)
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(db_management_router)
# Новые endpoint'ы глобального статуса индексации: /api/v1/indexer/tasks
app.include_router(indexer_state_router, prefix="/api/v1")
app.include_router(watchdog_router)
# Phase 2: Campaign Update Mode API
app.include_router(update_mode_router)

# === Статика ===
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def static_cache_headers(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/dist/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/static/dist/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "rag-backend"}

@app.get("/")
async def serve_index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return FileResponse(path=__file__, media_type="text/plain")
    return FileResponse(
        index_path,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
