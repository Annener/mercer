from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from api.index import router as index_router
from config_loader import get_storage_config
from logging_config import setup_logging
from storage.lancedb_store import LanceDBStore


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging("storage")
    app.state.config = get_storage_config()
    app.state.store = LanceDBStore(app.state.config.lancedb.data_path)
    app.state.store.connect()
    logger.info("Service started. Config and LanceDB connection loaded.")
    yield
    logger.info("Service stopped.")


app = FastAPI(title="DB API Server", lifespan=lifespan)
app.include_router(index_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "db-api-server"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
