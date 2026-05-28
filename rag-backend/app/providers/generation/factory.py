from __future__ import annotations

from typing import Any

from app.providers.generation.base import GenerationProvider
from app.services.settings_service import settings_service


def get_generation_provider(config: Any | None = None) -> GenerationProvider:
    _ = config
    return settings_service.get_active_provider()
