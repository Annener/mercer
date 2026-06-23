from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderUnavailableError(Exception):
    """Raised when an embedding provider cannot be reached after retries."""


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, using [] for per-text failures."""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, optimised for batch processing.

        Implementations should minimise the number of HTTP round-trips:
        - Ollama: N parallel requests via asyncio.gather (no native batch endpoint).
        - OpenAI-compatible: single POST with ``"input": list[str]``.

        Contract identical to ``embed``: [] for per-text failures, order preserved.
        """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the expected embedding vector size."""
