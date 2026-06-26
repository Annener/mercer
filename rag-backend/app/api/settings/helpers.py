from __future__ import annotations

import os

import httpx

from app.db.models import EmbeddingModel


def _sidecar_base_url(model: EmbeddingModel) -> str:
    """Resolve sidecar base URL: model.base_url -> env PDF_SIDECAR_URL -> default."""
    if model.base_url:
        return model.base_url.rstrip("/")
    return os.getenv("PDF_SIDECAR_URL", "http://pdf-sidecar:8765").rstrip("/")


async def _check_embedding_provider(model: EmbeddingModel) -> list[float]:
    async with httpx.AsyncClient(timeout=model.timeout_seconds) as client:
        if model.provider == "ollama":
            base = (model.base_url or "http://ollama:11434").rstrip("/")
            response = await client.post(
                f"{base}/api/embeddings",
                json={"model": model.model_name, "prompt": "test"},
            )
            response.raise_for_status()
            return response.json()["embedding"]

        if model.provider == "openai_compatible":
            base = (model.base_url or "").rstrip("/")
            headers = {}
            if model.api_key:
                headers["Authorization"] = f"Bearer {model.api_key}"
            response = await client.post(
                f"{base}/embeddings",
                headers=headers,
                json={"model": model.model_name, "input": "test"},
            )
            response.raise_for_status()
            payload = response.json()
            vector = payload.get("embedding")
            if vector is None and payload.get("data"):
                vector = payload["data"][0]["embedding"]
            return vector

        if model.provider == "sidecar":
            base = _sidecar_base_url(model)
            response = await client.post(
                f"{base}/embeddings",
                json={"model": model.model_name or "BAAI/bge-m3", "input": "test"},
            )
            response.raise_for_status()
            payload = response.json()
            return payload["data"][0]["embedding"]

        raise ValueError(f"Unsupported embedding provider: {model.provider}")
