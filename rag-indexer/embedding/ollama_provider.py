from __future__ import annotations

import asyncio
import logging

import httpx

from embedding.base_provider import EmbeddingProvider, ProviderUnavailableError


logger = logging.getLogger(__name__)


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        model_name: str,
        dimensions: int,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._dimensions = dimensions
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return [await self._embed_one(client, text) for text in texts]

    async def _embed_one(self, client: httpx.AsyncClient, text: str) -> list[float]:
        last_unavailable: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model_name, "prompt": text},
                )
                response.raise_for_status()
                payload = response.json()
                vector = payload.get("embedding")
                if not isinstance(vector, list) or not vector:
                    logger.warning("Ollama returned an empty or invalid embedding.")
                    return []
                return self._validate_dimensions(vector)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
                last_unavailable = exc
                logger.warning("Ollama provider unavailable on attempt %s: %s", attempt + 1, exc)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.warning("Ollama embedding request failed on attempt %s: %s", attempt + 1, exc)

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        if last_unavailable is not None:
            raise ProviderUnavailableError("Ollama embedding provider is unavailable.") from last_unavailable
        return []

    def _validate_dimensions(self, vector: list[object]) -> list[float]:
        if len(vector) != self._dimensions:
            logger.error("Ollama vector dimension mismatch: expected %s, got %s", self._dimensions, len(vector))
            return []
        try:
            return [float(value) for value in vector]
        except (TypeError, ValueError):
            logger.error("Ollama vector contains non-numeric values.")
            return []
