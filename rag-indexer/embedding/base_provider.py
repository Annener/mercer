from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderUnavailableError(Exception):
    """Raised when an embedding provider cannot be reached after retries."""


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, using [] for per-text failures."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the expected embedding vector size."""
