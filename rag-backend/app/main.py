from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.config_api import router as config_router
from app.api.db_management import router as db_management_router
from app.api.settings import router as settings_router
from app.db.migrations import run_migrations
from app.db.session import SessionLocal, dispose_engine
from app.logging_config import setup_logging
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

    logger.info("Service started. Database migrations applied.")
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("Service stopped.")


app = FastAPI(title="RAG Backend", lifespan=lifespan)

# === Роутеры ===
app.include_router(chat_router)
app.include_router(config_router)

# Settings API — согласно спецификации V3.0: /api/settings/*
app.include_router(
    settings_router,
    prefix="/api/settings",
    tags=["settings"],
)

# DB Management API — роутер без префикса.
# Пути внутри роутера: /api/db/*, /index-tasks/*, /vaults/*, /ws/*
# (разные префиксы нельзя задать одним include_router)
app.include_router(db_management_router)

# === Статика ===
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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