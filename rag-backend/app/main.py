from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.config_api import router as config_router
from app.api.db_management import router as db_management_router
from app.config import AppConfig
from app.config_loader import get_config
from app.db.migrations import run_migrations
from app.db.session import dispose_engine
from app.domains.registry import DomainRegistry
from app.logging_config import setup_logging
from app.pipelines.registry import PipelineHotReloader, PipelineRegistry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging("backend")
    app.state.config = get_config()
    await run_migrations()
    setup_logging("backend")
    app.state.domain_registry = DomainRegistry()
    app.state.domain_registry.load()
    app.state.pipeline_registry = PipelineRegistry(app.state.config.pipelines.path)
    app.state.pipeline_reloader = PipelineHotReloader(
        registry=app.state.pipeline_registry,
        interval_seconds=app.state.config.pipelines.reload_interval_seconds,
        debounce_seconds=app.state.config.pipelines.debounce_seconds,
    )
    if app.state.config.pipelines.enabled:
        await app.state.pipeline_reloader.start()
    logger.info("Service started. Config loaded. Database migrations applied.")
    try:
        yield
    finally:
        if getattr(app.state, "pipeline_reloader", None) is not None:
            await app.state.pipeline_reloader.stop()
        await dispose_engine()
        logger.info("Service stopped.")


app = FastAPI(title="RAG Backend", lifespan=lifespan)

app.include_router(chat_router)
app.include_router(config_router)
app.include_router(db_management_router)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
async def health(config: AppConfig = Depends(get_config)) -> dict[str, str]:
    _ = config
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
