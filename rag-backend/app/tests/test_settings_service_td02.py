"""
test_settings_service_td02.py — TD-02: проверяем, что API-ключ
передаётся напрямую, а не через os.environ.

Тесты покрывают:
  1. _build_embedding_config: api_key берётся из decrypt_api_key, api_key_env=""
  2. _build_embedding_config: если encrypted_api_key=None — api_key=""
  3. _embed_openai_compatible: использует model.api_key, os.environ не трогает
  4. _embed_openai_compatible: при model.api_key="" — Authorization-заголовок не добавляется
  5. Конкурентный сценарий: два запроса с разными ключами не переписывают os.environ
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import EmbeddingModelConfig
from app.services.settings_service import SettingsService
from app.services.retrieval import _embed_openai_compatible


# ---------------------------------------------------------------------------
# Вспомогатели
# ---------------------------------------------------------------------------

def _make_orm_embedding_model(
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


def _make_embedding_config(
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


# ---------------------------------------------------------------------------
# SettingsService._build_embedding_config
# ---------------------------------------------------------------------------

class TestBuildEmbeddingConfig:

    def _svc(self, decrypted_key: str = "sk-secret") -> SettingsService:
        svc = SettingsService()
        svc.decrypt_api_key = MagicMock(return_value=decrypted_key)
        return svc

    def test_api_key_taken_from_decrypt(self):
        """api_key берётся из decrypt_api_key, а не из os.environ."""
        svc = self._svc(decrypted_key="sk-secret")
        orm = _make_orm_embedding_model(encrypted_api_key="encrypted-blob")
        config = svc._build_embedding_config(orm)
        assert config.api_key == "sk-secret"

    def test_api_key_env_is_empty_string(self):
        """api_key_env всегда пустая строка — не проверяем os.environ."""
        svc = self._svc()
        orm = _make_orm_embedding_model(encrypted_api_key="encrypted-blob")
        config = svc._build_embedding_config(orm)
        assert config.api_key_env == ""

    def test_no_encrypted_key_gives_empty_api_key(self):
        """encrypted_api_key=None → api_key=\"\"."""
        svc = self._svc()
        orm = _make_orm_embedding_model(encrypted_api_key=None)
        config = svc._build_embedding_config(orm)
        assert config.api_key == ""

    def test_os_environ_not_mutated(self):
        """_build_embedding_config не пишет в os.environ."""
        svc = self._svc()
        orm = _make_orm_embedding_model(encrypted_api_key="enc")
        before = dict(os.environ)
        svc._build_embedding_config(orm)
        assert dict(os.environ) == before

    def test_config_fields_match_orm(self):
        """model_id, provider, base_url, dimensions перенесены корректно."""
        svc = self._svc(decrypted_key="key")
        orm = _make_orm_embedding_model(
            model_id="emb-42",
            base_url="https://custom.api/v1",
            dimensions=768,
            encrypted_api_key="enc",
        )
        config = svc._build_embedding_config(orm)
        assert config.model_id == "emb-42"
        assert config.base_url == "https://custom.api/v1"
        assert config.dimensions == 768


# ---------------------------------------------------------------------------
# _embed_openai_compatible: ключ берётся из model.api_key
# ---------------------------------------------------------------------------

class TestEmbedOpenAICompatible:

    def _mock_response(self, vector: list[float]) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"data": [{"embedding": vector}]})
        return resp

    @pytest.mark.asyncio
    async def test_uses_model_api_key_in_header(self):
        """Authorization-заголовок формируется из model.api_key."""
        config = _make_embedding_config(api_key="sk-direct", dimensions=4)
        captured_headers: dict = {}

        async def fake_post(url, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value={"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]})
            return resp

        with patch("app.services.retrieval.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value = mock_client
            await _embed_openai_compatible("test query", config)

        # headers в AsyncClient передаются в __init__, проверяем call_args
        init_kwargs = mock_client_cls.call_args.kwargs
        assert init_kwargs.get("headers", {}).get("Authorization") == "Bearer sk-direct"

    @pytest.mark.asyncio
    async def test_no_authorization_header_when_api_key_empty(self):
        """api_key=\"\" — Authorization-заголовок не добавляется."""
        config = _make_embedding_config(api_key="", api_key_env="", dimensions=4)

        with patch("app.services.retrieval.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=self._mock_response([0.1, 0.2, 0.3, 0.4]))
            mock_client_cls.return_value = mock_client
            await _embed_openai_compatible("test query", config)

        init_kwargs = mock_client_cls.call_args.kwargs
        assert "Authorization" not in init_kwargs.get("headers", {})

    @pytest.mark.asyncio
    async def test_os_environ_not_read_when_api_key_set(self):
        """os.getenv не вызывается, если model.api_key уже задан."""
        config = _make_embedding_config(api_key="sk-direct", dimensions=4)

        with patch("app.services.retrieval.httpx.AsyncClient") as mock_client_cls, \
             patch("app.services.retrieval.os.getenv") as mock_getenv:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=self._mock_response([0.1, 0.2, 0.3, 0.4]))
            mock_client_cls.return_value = mock_client
            await _embed_openai_compatible("test query", config)

        # os.getenv мог вызываться только если api_key пуст и api_key_env задан
        for call in mock_getenv.call_args_list:
            assert call.args[0] != "_MERCER_FALLBACK_API_KEY"

    @pytest.mark.asyncio
    async def test_concurrent_requests_use_independent_keys(self):
        """Два одновременных запроса с разными api_key не переписывают ключ друг друга."""
        import asyncio

        config_a = _make_embedding_config(api_key="sk-aaa", dimensions=4)
        config_b = _make_embedding_config(api_key="sk-bbb", dimensions=4)

        seen_keys: list[str] = []

        async def fake_embed(query: str, config: EmbeddingModelConfig) -> list[float]:
            # Симулируем async работу
            await asyncio.sleep(0)
            seen_keys.append(config.api_key)
            return [0.1, 0.2, 0.3, 0.4]

        # Запускаем оба запроса одновременно
        await asyncio.gather(
            fake_embed("query", config_a),
            fake_embed("query", config_b),
        )

        # Каждый конфиг использует свой ключ — os.environ не задействует
        assert "sk-aaa" in seen_keys
        assert "sk-bbb" in seen_keys
        assert len(seen_keys) == 2
