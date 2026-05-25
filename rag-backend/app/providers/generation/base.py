from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class GenerationProviderUnavailableError(Exception):
    """Raised when the generation provider cannot produce a response."""


class GenerationProvider(ABC):
    @abstractmethod
    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield response text fragments for a chat completion."""
        if False:
            yield ""

    @abstractmethod
    async def generate(self, messages: list[dict[str, str]]) -> str:
        """Return a complete response for non-streaming use cases."""
