from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from shared_contracts.models import LLMToolCall, LLMToolDefinition, LLMToolChoice


class GenerationProviderUnavailableError(Exception):
    """Raised when the generation provider cannot produce a response."""


@dataclass(slots=True)
class LLMStreamChunk:
    """Atomic stream chunk from the provider.

    Exactly one of `content_delta` and `tool_call_delta` is set per chunk.
    During tool-call streaming the host accumulates `tool_call_delta`s by
    their `index` and assembles full `LLMToolCall`s at the end of the stream.
    """

    content_delta: str = ""
    tool_call_delta: "ToolCallDelta | None" = None
    finish_reason: str | None = None


@dataclass(slots=True)
class ToolCallDelta:
    """Partial tool call information from a single stream delta.

    OpenAI streams tool calls in pieces: first the `id`+`name`, then `arguments`
    one character at a time. The host accumulates these by `index` and builds
    a complete `LLMToolCall` once the assistant message finishes.
    """

    index: int
    id: str | None = None
    type: str | None = None
    function_name: str | None = None
    function_arguments_delta: str = ""


@dataclass(slots=True)
class LLMFullResponse:
    """Result of a non-streaming LLM call with optional tool calls."""

    content: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    finish_reason: str | None = None


class GenerationProvider(ABC):
    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """Yield response text fragments for a chat completion.

        Kept for backward compatibility: this is the legacy text-only path.
        New code that needs tool support should call `generate_stream_with_tools`.
        """
        if False:
            yield ""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
    ) -> str:
        """Return a complete response for non-streaming use cases."""

    async def generate_stream_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[LLMToolDefinition],
        tool_choice: LLMToolChoice | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Yield stream chunks including tool-call deltas.

        Default implementation degrades gracefully for providers that do not
        support tools: it calls `generate_stream` and returns content-only
        chunks. Subclasses that support tool-calling must override this method
        to actually emit `LLMStreamChunk` instances with `tool_call_delta` set.
        """
        del tools, tool_choice
        async for token in self.generate_stream(messages):
            yield LLMStreamChunk(content_delta=token)

    async def generate_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[LLMToolDefinition],
        tool_choice: LLMToolChoice | None = None,
    ) -> LLMFullResponse:
        """Non-streaming variant with tool support.

        Default implementation degrades to plain `generate` for providers
        without tool support.
        """
        del tools, tool_choice
        content = await self.generate(messages)
        return LLMFullResponse(content=content, tool_calls=[], finish_reason="stop")


__all__ = [
    "GenerationProvider",
    "GenerationProviderUnavailableError",
    "LLMStreamChunk",
    "LLMFullResponse",
    "ToolCallDelta",
]
