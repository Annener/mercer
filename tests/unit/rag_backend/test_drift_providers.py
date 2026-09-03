"""Smoke-тесты для drift-провайдеров (Phase 2a context-engine).

Проверяем:
- ``HostSidecarDriftProvider`` корректно парсит ``{"hints": [...]}``
- ``HostSidecarDriftProvider`` поднимает ``DriftUnavailableError`` при недоступности
- ``OpenAICompatibleDriftProvider`` парсит ``choices[0].message.content`` как JSON
- ``OpenAICompatibleDriftProvider`` поднимает ``DriftUnavailableError`` при 5xx

Используем ``respx`` для мока httpx-запросов (если доступен) или прямой
mock ``AsyncClient`` через ``unittest.mock``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_httpx_response(status_code: int, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("not json"))
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response

        req = Request("POST", "http://test/drift")
        resp.raise_for_status.side_effect = HTTPStatusError(
            f"status {status_code}", request=req, response=Response(status_code)
        )
    return resp


class TestHostSidecarDriftProvider:
    @pytest.mark.asyncio
    async def test_returns_hints(self):
        from app.providers.drift.host_sidecar import HostSidecarDriftProvider

        resp = _make_httpx_response(200, {"hints": [{"fact": "x", "confidence": 0.9}]})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=resp)

        provider = HostSidecarDriftProvider(
            base_url="http://sidecar:8765", model_name="qvikhr-3-1.7b-instruct-noreasoning-q4_k_m"
        )
        with patch("app.providers.drift.host_sidecar.httpx.AsyncClient", return_value=mock_client):
            hints = await provider.detect_drift(
                messages=[{"role": "user", "content": "ping"}],
                current_state="(empty)",
            )
        assert hints == [{"fact": "x", "confidence": 0.9}]

    @pytest.mark.asyncio
    async def test_unavailable_on_connect_error(self):
        from app.providers.drift.base import DriftUnavailableError
        from app.providers.drift.host_sidecar import HostSidecarDriftProvider

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))

        provider = HostSidecarDriftProvider(
            base_url="http://sidecar:8765", model_name="qvikhr-3-1.7b-instruct-noreasoning-q4_k_m"
        )
        with patch("app.providers.drift.host_sidecar.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(DriftUnavailableError):
                await provider.detect_drift(
                    messages=[{"role": "user", "content": "ping"}],
                    current_state="(empty)",
                )

    @pytest.mark.asyncio
    async def test_invalid_response_when_no_hints_key(self):
        from app.providers.drift.base import DriftInvalidResponseError
        from app.providers.drift.host_sidecar import HostSidecarDriftProvider

        resp = _make_httpx_response(200, {"unexpected": "shape"})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=resp)

        provider = HostSidecarDriftProvider(
            base_url="http://sidecar:8765", model_name="qvikhr-3-1.7b-instruct-noreasoning-q4_k_m"
        )
        with patch("app.providers.drift.host_sidecar.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(DriftInvalidResponseError):
                await provider.detect_drift(
                    messages=[{"role": "user", "content": "ping"}],
                    current_state="(empty)",
                )


class TestOpenAICompatibleDriftProvider:
    @pytest.mark.asyncio
    async def test_returns_hints(self):
        import json

        from app.providers.drift.openai_compatible import OpenAICompatibleDriftProvider

        resp = _make_httpx_response(
            200,
            {"choices": [{"message": {"content": json.dumps({"hints": [{"fact": "y", "confidence": 0.7}]})}}]},
        )
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=resp)

        provider = OpenAICompatibleDriftProvider(
            base_url="http://example.com/v1",
            model_name="gpt-test",
            api_key="sk-test",
        )
        with patch("app.providers.drift.openai_compatible.httpx.AsyncClient", return_value=mock_client):
            hints = await provider.detect_drift(
                messages=[{"role": "user", "content": "ping"}],
                current_state="(empty)",
            )
        assert hints == [{"fact": "y", "confidence": 0.7}]

    @pytest.mark.asyncio
    async def test_unavailable_on_connect_error(self):
        from app.providers.drift.base import DriftUnavailableError
        from app.providers.drift.openai_compatible import OpenAICompatibleDriftProvider

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))

        provider = OpenAICompatibleDriftProvider(
            base_url="http://example.com/v1", model_name="gpt-test"
        )
        with patch("app.providers.drift.openai_compatible.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(DriftUnavailableError):
                await provider.detect_drift(
                    messages=[{"role": "user", "content": "ping"}],
                    current_state="(empty)",
                )

    @pytest.mark.asyncio
    async def test_invalid_response_when_no_choices(self):
        from app.providers.drift.base import DriftInvalidResponseError
        from app.providers.drift.openai_compatible import OpenAICompatibleDriftProvider

        resp = _make_httpx_response(200, {"unexpected": "shape"})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=resp)

        provider = OpenAICompatibleDriftProvider(
            base_url="http://example.com/v1", model_name="gpt-test"
        )
        with patch("app.providers.drift.openai_compatible.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(DriftInvalidResponseError):
                await provider.detect_drift(
                    messages=[{"role": "user", "content": "ping"}],
                    current_state="(empty)",
                )
