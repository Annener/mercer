"""Unit-тесты для provider_factory.

Покрывают:
  - build_embedding_model_config: парсинг DB row в Pydantic
  - build_provider: выбор правильного провайдера по provider-строке
"""
from __future__ import annotations

import pytest
from embedding.ollama_provider import OllamaEmbeddingProvider
from embedding.openai_provider import OpenAICompatibleProvider
from provider_factory import build_embedding_model_config, build_provider


def test_build_embedding_model_config_full():
    row = {
        "model_id": "em1",
        "provider": "ollama",
        "model_name": "nomic",
        "base_url": "http://localhost:11434",
        "dimensions": 768,
        "enabled": True,
        "timeout_seconds": 30,
        "max_retries": 3,
    }
    cfg = build_embedding_model_config(row)
    assert cfg.model_id == "em1"
    assert cfg.provider == "ollama"
    assert cfg.dimensions == 768
    assert cfg.timeout_seconds == 30
    assert cfg.max_retries == 3
    assert cfg.enabled is True


def test_build_embedding_model_config_with_defaults():
    """Без опциональных полей — дефолты."""
    row = {
        "model_id": "em1",
        "provider": "ollama",
        "model_name": "nomic",
        "base_url": "http://localhost:11434",
        "dimensions": 768,
    }
    cfg = build_embedding_model_config(row)
    assert cfg.enabled is True
    assert cfg.timeout_seconds == 30
    assert cfg.max_retries == 3


def test_build_embedding_model_config_casts_types():
    """Приводит типы: dimensions/timeout/max_retries → int, enabled → bool."""
    row = {
        "model_id": "em1",
        "provider": "ollama",
        "model_name": "nomic",
        "base_url": "http://x",
        "dimensions": "768",  # строка в БД
        "enabled": 1,
        "timeout_seconds": "60",
        "max_retries": "5",
    }
    cfg = build_embedding_model_config(row)
    assert cfg.dimensions == 768
    assert cfg.enabled is True
    assert cfg.timeout_seconds == 60
    assert cfg.max_retries == 5


def test_build_provider_ollama():
    cfg = build_embedding_model_config({
        "model_id": "em1", "provider": "ollama", "model_name": "n",
        "base_url": "http://localhost:11434", "dimensions": 768,
    })
    provider = build_provider(cfg, api_key="")
    assert isinstance(provider, OllamaEmbeddingProvider)


def test_build_provider_openai_compatible():
    cfg = build_embedding_model_config({
        "model_id": "em1", "provider": "openai_compatible", "model_name": "n",
        "base_url": "http://api.openai.com", "dimensions": 1536,
    })
    provider = build_provider(cfg, api_key="sk-test")
    assert isinstance(provider, OpenAICompatibleProvider)


def test_build_provider_sidecar():
    """sidecar — это openai_compatible с пустым api_key."""
    cfg = build_embedding_model_config({
        "model_id": "em1", "provider": "sidecar", "model_name": "st",
        "base_url": "http://sidecar:8081", "dimensions": 768,
    })
    provider = build_provider(cfg, api_key="")
    assert isinstance(provider, OpenAICompatibleProvider)


def test_build_provider_unknown_raises():
    """Provider, не входящий в Literal, отклоняется на этапе Pydantic-валидации."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        build_embedding_model_config({
            "model_id": "em1", "provider": "mystery", "model_name": "n",
            "base_url": "http://x", "dimensions": 768,
        })
