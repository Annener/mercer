"""Embedding provider factory.

Pure functions: no I/O, no async, no DB.

Public API
----------
build_embedding_model_config(raw_row)   — DB row → EmbeddingModelConfig
build_provider(model, api_key)         — model → EmbeddingProvider

Поддерживаемые значения provider:
  - "ollama"            — Ollama POST /api/embeddings (один текст за запрос)
  - "openai_compatible" — OpenAI-совместимый POST /embeddings (нативный батч)
  - "sidecar"           — pdf-sidecar POST /embeddings (OpenAI-совместимый,
                          нативный батч через sentence-transformers).
                          api_key не требуется — sidecar работает без аутентификации.
"""
from __future__ import annotations

from typing import Any

from embedding.base_provider import EmbeddingProvider
from embedding.ollama_provider import OllamaEmbeddingProvider
from embedding.openai_provider import OpenAICompatibleProvider

from config import EmbeddingModelConfig


def build_embedding_model_config(model: dict[str, Any]) -> EmbeddingModelConfig:
    """Преобразовать строку из БД в Pydantic-модель EmbeddingModelConfig."""
    return EmbeddingModelConfig(
        model_id=model["model_id"],
        provider=model["provider"],
        model_name=model["model_name"],
        base_url=model["base_url"],
        dimensions=int(model["dimensions"]),
        enabled=bool(model.get("enabled", True)),
        timeout_seconds=int(model.get("timeout_seconds", 30)),
        max_retries=int(model.get("max_retries", 3)),
    )


def build_provider(
    embedding_model: EmbeddingModelConfig, api_key: str = ""
) -> EmbeddingProvider:
    """Создать провайдера эмбеддингов по конфигурации модели."""
    if embedding_model.provider == "ollama":
        return OllamaEmbeddingProvider(
            base_url=embedding_model.base_url,
            model_name=embedding_model.model_name,
            dimensions=embedding_model.dimensions,
            timeout=embedding_model.timeout_seconds,
            max_retries=embedding_model.max_retries,
        )
    if embedding_model.provider in ("openai_compatible", "sidecar"):
        return OpenAICompatibleProvider(
            base_url=embedding_model.base_url,
            model_name=embedding_model.model_name,
            dimensions=embedding_model.dimensions,
            api_key=api_key,
            timeout=embedding_model.timeout_seconds,
            max_retries=embedding_model.max_retries,
        )
    raise ValueError(f"Unsupported embedding provider: {embedding_model.provider}")
