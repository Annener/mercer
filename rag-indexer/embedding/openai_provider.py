from __future__ import annotations

import asyncio
import logging

import httpx

from embedding.base_provider import EmbeddingProvider, ProviderUnavailableError


logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(EmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        model_name: str,
        dimensions: int,
        api_key: str,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._dimensions = dimensions
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _auth_headers(self) -> dict[str, str]:
        """Возвращает заголовок Authorization только если api_key непустой.
        Для локальных провайдеров (sidecar) без аутентификации возвращает {}."""
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._auth_headers()) as client:
            return [await self._embed_one(client, text) for text in texts]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding for SemanticChunker.

        OpenAI-compatible API accepts ``"input": list[str]`` — the entire batch is
        sent in a single HTTP request.  The response contains one embedding object
        per input text, in the same order (``data[i].embedding`` corresponds to
        ``texts[i]``).
        """
        if not texts:
            return []

        last_unavailable: Exception | None = None

        async with httpx.AsyncClient(timeout=self.timeout, headers=self._auth_headers()) as client:
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
                    results: list[list[float]] = []
                    for item in data:
                        vector = item.get("embedding") if isinstance(item, dict) else None
                        if not isinstance(vector, list) or not vector:
                            logger.warning(
                                "OpenAI-compatible batch: empty or invalid embedding for one item."
                            )
                            results.append([])
                        else:
                            results.append(self._validate_dimensions(vector))
                    return results
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
