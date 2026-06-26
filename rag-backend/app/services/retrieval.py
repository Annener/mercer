from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from app.db.models import EmbeddingModel as EmbeddingModelConfig
from app.db.models import Vault

logger = logging.getLogger(__name__)


def _sidecar_base_url(model: EmbeddingModelConfig) -> str:
    if model.base_url:
        return model.base_url.rstrip("/")
    return os.getenv("PDF_SIDECAR_URL", "http://pdf-sidecar:8765").rstrip("/")


async def embed_query(query: str, model: EmbeddingModelConfig) -> list[float]:
    if model.provider == "ollama":
        return await _embed_ollama(query, model)
    if model.provider == "openai_compatible":
        return await _embed_openai_compatible(query, model)
    if model.provider == "sidecar":
        return await _embed_sidecar(query, model)
    raise ValueError(f"Unsupported embedding provider: {model.provider}")


async def _embed_ollama(query: str, model: EmbeddingModelConfig) -> list[float]:
    base = (model.base_url or "http://ollama:11434").rstrip("/")
    async with httpx.AsyncClient(timeout=model.timeout_seconds) as client:
        response = await client.post(
            f"{base}/api/embeddings",
            json={"model": model.model_name, "prompt": query},
        )
        response.raise_for_status()
        return response.json()["embedding"]


async def _embed_openai_compatible(query: str, model: EmbeddingModelConfig) -> list[float]:
    base = (model.base_url or "").rstrip("/")
    headers = {}
    if model.api_key:
        headers["Authorization"] = f"Bearer {model.api_key}"
    async with httpx.AsyncClient(timeout=model.timeout_seconds) as client:
        response = await client.post(
            f"{base}/embeddings",
            headers=headers,
            json={"model": model.model_name, "input": query},
        )
        response.raise_for_status()
        payload = response.json()
        vector = payload.get("embedding")
        if vector is None and payload.get("data"):
            vector = payload["data"][0]["embedding"]
        return vector


async def _embed_sidecar(query: str, model: EmbeddingModelConfig) -> list[float]:
    base = _sidecar_base_url(model)
    async with httpx.AsyncClient(timeout=model.timeout_seconds) as client:
        response = await client.post(
            f"{base}/embeddings",
            json={"model": model.model_name or "BAAI/bge-m3", "input": query},
        )
        response.raise_for_status()
        payload = response.json()
        return payload["data"][0]["embedding"]


async def retrieve(
    query: str,
    vault: Vault,
    embedding_model: EmbeddingModelConfig,
    top_k: int = 10,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    from app.services.vector_store import search_vectors

    vector = await embed_query(query, embedding_model)
    results = await search_vectors(vault, vector, top_k=top_k, **kwargs)
    return results
