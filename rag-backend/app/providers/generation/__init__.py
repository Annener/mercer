from __future__ import annotations

from app.providers.generation.base import GenerationProvider, GenerationProviderUnavailableError
from app.providers.generation.openai_compatible import OpenAICompatibleProvider


def get_generation_provider(config: object | None = None) -> GenerationProvider:
    """Return the active generation provider or raise if not configured."""
    from app.services.settings_service import settings_service

    provider = settings_service.get_active_provider()
    if provider is None:
        raise GenerationProviderUnavailableError("No active generation model configured")
    return provider


__all__ = [
    "GenerationProvider",
    "GenerationProviderUnavailableError",
    "OpenAICompatibleProvider",
    "get_generation_provider",
]
