"""Unit-тесты для embedding_pipeline.

Покрывают:
  - uses_batch_api: OpenAI-compatible → True, Ollama → False
  - embed_chunks batch-path: проверка количества HTTP-вызовов и order-preserving
  - embed_chunks per-chunk-path: cancellation через state_manager
  - empty input → empty result
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from embedding.ollama_provider import OllamaEmbeddingProvider
from embedding.openai_provider import OpenAICompatibleProvider
from embedding_pipeline import embed_chunks, uses_batch_api


def _model(provider: str = "ollama") -> SimpleNamespace:
    return SimpleNamespace(
        model_id="em1",
        provider=provider,
        timeout_seconds=30,
        max_retries=3,
    )


def _chunk(text: str = "x", embedding_text: str | None = None):
    c = MagicMock()
    c.text = text
    c.metadata = {"embedding_text": embedding_text or text}
    return c


def test_uses_batch_api_openai_compatible():
    provider = OpenAICompatibleProvider(
        base_url="http://x", model_name="m", dimensions=4, api_key="",
    )
    assert uses_batch_api(provider) is True


def test_uses_batch_api_ollama():
    provider = OllamaEmbeddingProvider(
        base_url="http://x", model_name="m", dimensions=4,
    )
    assert uses_batch_api(provider) is False


@pytest.mark.asyncio
async def test_embed_chunks_empty_input_returns_empty_no_http():
    provider = MagicMock()
    provider.embed_batch = AsyncMock()
    result = await embed_chunks([], _model(), provider)
    assert result == []
    provider.embed_batch.assert_not_called()


@pytest.mark.asyncio
async def test_embed_chunks_ollama_per_chunk_preserves_order():
    """Ollama: идём почанково, results в порядке входа."""
    provider = OllamaEmbeddingProvider(
        base_url="http://x", model_name="m", dimensions=4,
    )

    async def _embed_one(texts: list[str]) -> list[list[float]]:
        # index encoded in the text: "text-N" → N
        return [[float(int(texts[0].split("-")[1]))] * 4]

    provider.embed = AsyncMock(side_effect=_embed_one)  # type: ignore[method-assign]
    chunks = [_chunk(f"text-{i}") for i in range(3)]
    vectors = await embed_chunks(chunks, _model(), provider)
    assert vectors == [[0.0] * 4, [1.0] * 4, [2.0] * 4]
    assert provider.embed.await_count == 3


@pytest.mark.asyncio
async def test_embed_chunks_openai_batch_uses_embed_batch():
    """OpenAI-compatible: 1 вызов embed_batch на все чанки."""
    provider = OpenAICompatibleProvider(
        base_url="http://x", model_name="m", dimensions=4, api_key="",
    )
    provider.embed_batch = AsyncMock(  # type: ignore[method-assign]
        return_value=[[1.0] * 4, [2.0] * 4, [3.0] * 4]
    )
    chunks = [_chunk(f"text-{i}") for i in range(3)]
    vectors = await embed_chunks(chunks, _model("openai_compatible"), provider)
    assert vectors == [[1.0] * 4, [2.0] * 4, [3.0] * 4]
    provider.embed_batch.assert_awaited_once()


@pytest.mark.asyncio
async def test_embed_chunks_ollama_cancellation_via_state_manager():
    """state_manager.is_cancelled → asyncio.CancelledError пробрасывается."""
    state_manager = MagicMock()
    state_manager.is_cancelled = AsyncMock(return_value=True)
    provider = OllamaEmbeddingProvider(
        base_url="http://x", model_name="m", dimensions=4,
    )
    provider.embed = AsyncMock(return_value=[[0.0] * 4])  # type: ignore[method-assign]
    chunks = [_chunk(f"text-{i}") for i in range(3)]
    with pytest.raises(asyncio.CancelledError):
        await embed_chunks(
            chunks, _model(), provider,
            task_id="t1", file_path="x.md", state_manager=state_manager,
        )


@pytest.mark.asyncio
async def test_embed_chunks_openai_empty_vector_raises():
    provider = OpenAICompatibleProvider(
        base_url="http://x", model_name="m", dimensions=4, api_key="",
    )
    provider.embed_batch = AsyncMock(return_value=[[], [1.0] * 4])  # type: ignore[method-assign]
    chunks = [_chunk(f"text-{i}") for i in range(2)]
    with pytest.raises(ValueError, match="empty vector"):
        await embed_chunks(chunks, _model("openai_compatible"), provider)


@pytest.mark.asyncio
async def test_embed_chunks_ollama_empty_vector_raises():
    provider = OllamaEmbeddingProvider(
        base_url="http://x", model_name="m", dimensions=4,
    )
    provider.embed = AsyncMock(return_value=[])  # type: ignore[method-assign]
    chunks = [_chunk("text-0")]
    with pytest.raises(ValueError, match="empty vector"):
        await embed_chunks(chunks, _model(), provider)
