from __future__ import annotations

import os

from app.config import AppConfig, GenerationModelConfig
from app.providers.generation.base import GenerationProvider
from app.providers.generation.openai_compatible import OpenAICompatibleProvider


def get_generation_provider(config: AppConfig) -> GenerationProvider:
    model_config = _select_generation_model(config)
    if model_config.provider == "openai_compatible":
        return OpenAICompatibleProvider(
            config=model_config,
            api_key=os.getenv(model_config.api_key_env, ""),
            max_retries=1,
        )
    raise ValueError(f"Unsupported generation provider: {model_config.provider}")


def _select_generation_model(config: AppConfig) -> GenerationModelConfig:
    for model_config in config.generation_models.values():
        if model_config.enabled:
            return model_config
    raise ValueError("No enabled generation model configured.")
