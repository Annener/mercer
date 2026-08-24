from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EmbeddingModelConfig(BaseModel):
    model_id: str
    provider: Literal["ollama", "openai_compatible", "sidecar"]
    model_name: str
    base_url: str
    dimensions: int = Field(gt=0)
    enabled: bool = True
    timeout_seconds: int = 30
    max_retries: int = 3
