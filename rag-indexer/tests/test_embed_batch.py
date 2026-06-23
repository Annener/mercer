"""Tests for EmbeddingProvider.embed_batch implementations.

All HTTP calls are mocked — no real network requests are made.

Key assertions:
- Ollama:  N texts → N parallel asyncio tasks (not sequential)
- OpenAI:  N texts → exactly 1 HTTP request (native batch)
- Both:    response order matches input order
- Both:    empty input → empty result (no HTTP call)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from embedding.ollama_provider import OllamaEmbeddingProvider
from embedding.openai_provider import OpenAICompatibleProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vec(seed: int, dim: int = 4) -> list[float]:
    """Deterministic fake vector for testing."""
    return [float(seed + i) for i in range(dim)]


DIM = 4
TEXTS = ["first sentence", "second sentence", "third sentence"]
VECS = [_make_vec(i, DIM) for i in range(len(TEXTS))]


# ---------------------------------------------------------------------------
# OllamaEmbeddingProvider
# ---------------------------------------------------------------------------

class TestOllamaEmbedBatch:
    """embed_batch for Ollama sends N parallel requests (one per text)."""

    def _make_provider(self) -> OllamaEmbeddingProvider:
        return OllamaEmbeddingProvider(
            base_url="http://localhost:11434",
            model_name="nomic-embed-text",
            dimensions=DIM,
        )

    def _make_response(self, vec: list[float]) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"embedding": vec}
        resp.raise_for_status = MagicMock()
        return resp

    @pytest.mark.asyncio
    async def test_returns_vectors_in_order(self) -> None:
        provider = self._make_provider()
        call_order: list[str] = []

        async def fake_post(url: str, json: dict, **kwargs) -> MagicMock:  # noqa: ARG001
            text = json["prompt"]
            idx = TEXTS.index(text)
            call_order.append(text)
            return self._make_response(VECS[idx])

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            result = await provider.embed_batch(TEXTS)

        assert result == VECS

    @pytest.mark.asyncio
    async def test_parallel_not_sequential(self) -> None:
        """All N tasks are launched via asyncio.gather — not awaited one-by-one."""
        provider = self._make_provider()
        # Track concurrent "in-flight" requests
        in_flight: list[int] = []
        peak: list[int] = [0]
        active = 0

        async def fake_post(url: str, json: dict, **kwargs) -> MagicMock:  # noqa: ARG001
            nonlocal active
            active += 1
            if active > peak[0]:
                peak[0] = active
            await asyncio.sleep(0)  # yield so others can start
            active -= 1
            text = json["prompt"]
            idx = TEXTS.index(text)
            return self._make_response(VECS[idx])

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            await provider.embed_batch(TEXTS)

        # With asyncio.gather all tasks are scheduled before any completes —
        # peak concurrent should equal len(TEXTS) (or at least > 1).
        assert peak[0] > 1, (
            f"Expected parallel execution (peak > 1), got peak={peak[0]}. "
            "embed_batch must use asyncio.gather, not sequential awaits."
        )

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_no_http(self) -> None:
        provider = self._make_provider()
        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            result = await provider.embed_batch([])
        assert result == []
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider
# ---------------------------------------------------------------------------

class TestOpenAIEmbedBatch:
    """embed_batch for OpenAI sends exactly 1 HTTP request for N texts."""

    def _make_provider(self) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            base_url="http://localhost:8080",
            model_name="text-embedding-3-small",
            dimensions=DIM,
            api_key="test-key",
        )

    def _make_response(self, vecs: list[list[float]]) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {
            "data": [{"embedding": v, "index": i} for i, v in enumerate(vecs)]
        }
        resp.raise_for_status = MagicMock()
        return resp

    @pytest.mark.asyncio
    async def test_single_http_request_for_batch(self) -> None:
        """N texts must produce exactly 1 POST request (native OpenAI batch)."""
        provider = self._make_provider()
        call_count = 0

        async def fake_post(url: str, json: dict, **kwargs) -> MagicMock:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            assert isinstance(json["input"], list), "input must be a list for batch requests"
            assert json["input"] == TEXTS
            return self._make_response(VECS)

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            result = await provider.embed_batch(TEXTS)

        assert call_count == 1, (
            f"embed_batch must make exactly 1 HTTP request, made {call_count}."
        )
        assert result == VECS

    @pytest.mark.asyncio
    async def test_returns_vectors_in_order(self) -> None:
        provider = self._make_provider()

        async def fake_post(url: str, json: dict, **kwargs) -> MagicMock:  # noqa: ARG001
            return self._make_response(VECS)

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            result = await provider.embed_batch(TEXTS)

        assert result == VECS

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_no_http(self) -> None:
        provider = self._make_provider()
        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            result = await provider.embed_batch([])
        assert result == []
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_mismatched_response_length_returns_empty_vectors(self) -> None:
        """If the API returns fewer embeddings than requested, return [] per text."""
        provider = self._make_provider()

        async def fake_post(url: str, json: dict, **kwargs) -> MagicMock:  # noqa: ARG001
            # Return only 1 item for 3-text input
            return self._make_response([VECS[0]])

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            result = await provider.embed_batch(TEXTS)

        assert result == [[] for _ in TEXTS]
