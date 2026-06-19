"""
test_settings_service_td02.py — TD-02

Проверяем, что API-ключ передаётся напрямую через model.api_key,
а не через os.environ, устраняя гонку при конкурентных запросах.

Тесты:
  TestBuildEmbeddingConfig
    [1] api_key берётся из decrypt_api_key, а не из os.environ
    [2] api_key_env всегда пустая строка (не пишем в env)
    [3] encrypted_api_key=None → api_key=""
    [4] os.environ не мутируется
    [5] остальные поля (model_id, base_url, dimensions) копируются корректно

  TestEmbedOpenAICompatible
    [6] Authorization-заголовок формируется из model.api_key
    [7] api_key="" → заголовок Authorization не добавляется
    [8] конкурентные запросы с разными ключами не перезаписывают друг друга
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import EmbeddingModelConfig
from app.services.settings_service import SettingsService
from app.services.retrieval import _embed_openai_compatible


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orm_model(
    model_id: str = "emb-1",
    provider: str = "openai_compatible",
    model_name: str = "text-embedding-3-small",
    base_url: str = "https://api.openai.com/v1",
    dimensions: int = 1536,
    encrypted_api_key: str | None = None,
    enabled: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.model_id = model_id
    m.provider = provider
    m.model_name = model_name
    m.base_url = base_url
    m.dimensions = dimensions
    m.encrypted_api_key = encrypted_api_key
    m.timeout_seconds = 30
    m.max_retries = 3
    m.enabled = enabled
    return m


def _make_config(
    api_key: str = "",
    api_key_env: str = "",
    dimensions: int = 4,
    max_retries: int = 1,
) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        model_id="emb-test",
        provider="openai_compatible",
        model_name="test-model",
        base_url="https://api.example.com/v1",
        dimensions=dimensions,
        api_key=api_key,
        api_key_env=api_key_env,
        max_retries=max_retries,
    )


def _mock_httpx_response(vector: list[float]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"data": [{"embedding": vector}]})
    return resp


# ---------------------------------------------------------------------------
# SettingsService._build_embedding_config
# ---------------------------------------------------------------------------

class TestBuildEmbeddingConfig:
    """Unit-тесты _build_embedding_config без БД и Fernet."""

    def _svc(self, decrypted: str = "sk-secret") -> SettingsService:
        svc = SettingsService()
        svc.decrypt_api_key = MagicMock(return_value=decrypted)
        return svc

    def test_api_key_from_decrypt(self):
        """api_key берётся из decrypt_api_key."""
        svc = self._svc(decrypted="sk-secret")
        cfg = svc._build_embedding_config(_make_orm_model(encrypted_api_key="enc"))
        assert cfg.api_key == "sk-secret"

    def test_api_key_env_is_empty(self):
        """api_key_env всегда пустая строка — не читаем os.environ."""
        svc = self._svc()
        cfg = svc._build_embedding_config(_make_orm_model(encrypted_api_key="enc"))
        assert cfg.api_key_env == ""

    def test_no_encrypted_key_gives_empty_api_key(self):
        """encrypted_api_key=None → api_key=''."""
        svc = self._svc()
        cfg = svc._build_embedding_config(_make_orm_model(encrypted_api_key=None))
        assert cfg.api_key == ""

    def test_os_environ_not_mutated(self):
        """_build_embedding_config не пишет в os.environ."""
        svc = self._svc()
        before = dict(os.environ)
        svc._build_embedding_config(_make_orm_model(encrypted_api_key="enc"))
        assert dict(os.environ) == before

    def test_fields_copied_correctly(self):
        """model_id, base_url, dimensions копируются без изменений."""
        svc = self._svc(decrypted="key")
        orm = _make_orm_model(
            model_id="emb-42",
            base_url="https://custom.api/v1",
            dimensions=768,
            encrypted_api_key="enc",
        )
        cfg = svc._build_embedding_config(orm)
        assert cfg.model_id == "emb-42"
        assert cfg.base_url == "https://custom.api/v1"
        assert cfg.dimensions == 768


# ---------------------------------------------------------------------------
# _embed_openai_compatible: ключ берётся из model.api_key
# ---------------------------------------------------------------------------

class TestEmbedOpenAICompatible:
    """Проверяем что Authorization-заголовок формируется из model.api_key."""

    @pytest.mark.asyncio
    async def test_auth_header_uses_model_api_key(self):
        """Authorization: Bearer <key> формируется из model.api_key."""
        config = _make_config(api_key="sk-direct", dimensions=4)

        with patch("app.services.retrieval.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(
                return_value=_mock_httpx_response([0.1, 0.2, 0.3, 0.4])
            )
            mock_cls.return_value = mock_instance

            await _embed_openai_compatible("test query", config)

        # headers передаются в __init__ AsyncClient, а не в .post()
        init_kwargs = mock_cls.call_args.kwargs
        assert init_kwargs.get("headers", {}).get("Authorization") == "Bearer sk-direct"

    @pytest.mark.asyncio
    async def test_no_auth_header_when_key_empty(self):
        """api_key='' и api_key_env='' → заголовок Authorization не добавляется."""
        config = _make_config(api_key="", api_key_env="", dimensions=4)

        with patch("app.services.retrieval.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(
                return_value=_mock_httpx_response([0.1, 0.2, 0.3, 0.4])
            )
            mock_cls.return_value = mock_instance

            await _embed_openai_compatible("test query", config)

        init_kwargs = mock_cls.call_args.kwargs
        assert "Authorization" not in init_kwargs.get("headers", {})

    @pytest.mark.asyncio
    async def test_concurrent_requests_independent_keys(self):
        """
        Два одновременных вызова с разными api_key не влияют друг на друга.
        Суть TD-02: если бы ключ шёл через os.environ — второй вызов
        перезаписал бы переменную первого.
        """
        config_a = _make_config(api_key="sk-aaa", dimensions=4)
        config_b = _make_config(api_key="sk-bbb", dimensions=4)

        with patch("app.services.retrieval.httpx.AsyncClient") as mock_cls:

            async def run(config: EmbeddingModelConfig) -> str:
                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_instance.post = AsyncMock(
                    return_value=_mock_httpx_response([0.1, 0.2, 0.3, 0.4])
                )
                mock_cls.return_value = mock_instance
                await _embed_openai_compatible("query", config)
                return mock_cls.call_args.kwargs.get("headers", {}).get("Authorization", "")

            r_a, r_b = await asyncio.gather(run(config_a), run(config_b))

        # Оба вызова используют свой ключ
        assert "Bearer sk-aaa" in (r_a, r_b)
        assert "Bearer sk-bbb" in (r_a, r_b)
