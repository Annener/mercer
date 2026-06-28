from __future__ import annotations

import asyncio
import logging

import httpx

from embedding.base_provider import EmbeddingProvider, ProviderUnavailableError


logger = logging.getLogger(__name__)

# TODO: expose via EmbeddingModelConfig, UI and DB so users can tune
# batch size to match their hardware capabilities.
_DEFAULT_BATCH_SIZE = 10


class OpenAICompatibleProvider(EmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        model_name: str,
        dimensions: int,
        api_key: str,
        timeout: int = 30,
        max_retries: int = 3,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._dimensions = dimensions
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        # Number of texts per HTTP request. Keep low on memory-constrained
        # hosts; will become a per-model DB setting in a future release.
        self.batch_size = batch_size

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _auth_headers(self) -> dict[str, str]:
        """Return Authorization header only when api_key is non-empty.
        Local / sidecar providers without auth return {}."""
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._auth_headers()) as client:
            return [await self._embed_one(client, text) for text in texts]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding split into sub-batches of self.batch_size.

        Sends multiple POST requests each containing at most ``batch_size``
        texts instead of one giant request. This prevents OOM on the sidecar
        when the caller (e.g. SemanticChunker) passes thousands of sentences
        at once.

        Contract identical to base class: [] for per-text failures, order preserved.
        """
        if not texts:
            return []

        results: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._auth_headers()) as client:
            for start in range(0, len(texts), self.batch_size):
                sub = texts[start : start + self.batch_size]
                sub_results = await self._embed_sub_batch(client, sub)
                results.extend(sub_results)
        return results

    async def _embed_sub_batch(
        self, client: httpx.AsyncClient, texts: list[str]
    ) -> list[list[float]]:
        """Send a single HTTP request for a sub-batch with retries."""
        last_unavailable: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model_name, "input": texts},
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data")
                if not isinstance(data, list) or len(data) != len(texts):
                    logger.warning(
                        "OpenAI-compatible batch response has unexpected shape: "
                        "expected %d items, got %s",
                        len(texts),
                        len(data) if isinstance(data, list) else type(data).__name__,
                    )
                    return [[] for _ in texts]
                sub_results: list[list[float]] = []
                for item in data:
                    vector = item.get("embedding") if isinstance(item, dict) else None
                    if not isinstance(vector, list) or not vector:
                        logger.warning(
                            "OpenAI-compatible batch: empty or invalid embedding for one item."
                        )
                        sub_results.append([])
                    else:
                        sub_results.append(self._validate_dimensions(vector))
                return sub_results
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
                last_unavailable = exc
                logger.warning(
                    "OpenAI-compatible provider unavailable on attempt %s: %s", attempt + 1, exc
                )
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.warning(
                    "OpenAI-compatible batch request failed on attempt %s: %s", attempt + 1, exc
                )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        if last_unavailable is not None:
            raise ProviderUnavailableError(
                "OpenAI-compatible embedding provider is unavailable."
            ) from last_unavailable
        return [[] for _ in texts]

    async def _embed_one(self, client: httpx.AsyncClient, text: str) -> list[float]:
        last_unavailable: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model_name, "input": text},
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data")
                vector = data[0].get("embedding") if isinstance(data, list) and data else None
                if not isinstance(vector, list) or not vector:
                    logger.warning("OpenAI-compatible provider returned an empty or invalid embedding.")
                    return []
                return self._validate_dimensions(vector)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
                last_unavailable = exc
                logger.warning("OpenAI-compatible provider unavailable on attempt %s: %s", attempt + 1, exc)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.warning("OpenAI-compatible embedding request failed on attempt %s: %s", attempt + 1, exc)

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        if last_unavailable is not None:
            raise ProviderUnavailableError("OpenAI-compatible embedding provider is unavailable.") from last_unavailable
        return []

    def _validate_dimensions(self, vector: list[object]) -> list[float]:
        if len(vector) != self._dimensions:
            logger.error(
                "OpenAI-compatible vector dimension mismatch: expected %s, got %s",
                self._dimensions,
                len(vector),
            )
            return []
        try:
            return [float(value) for value in vector]
        except (TypeError, ValueError):
            logger.error("OpenAI-compatible vector contains non-numeric values.")
            return []
