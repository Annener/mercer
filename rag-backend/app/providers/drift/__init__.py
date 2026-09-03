"""Drift providers — Phase 2a of context-engine refactor.

A drift provider compares recent chat messages against the current
campaign state and emits *drift hints* — facts that contradict or add to
the state. The provider is intentionally small/fast: by default we use
QVikhr-3-1.7B-Instruct-noreasoning (Q4_K_M) running inside pdf-sidecar,
but the same interface supports an OpenAI-compatible external endpoint.
"""
from __future__ import annotations

from app.providers.drift.base import (
    DriftProvider,
    DriftUnavailableError,
    DriftInvalidResponseError,
)
from app.providers.drift.host_sidecar import HostSidecarDriftProvider
from app.providers.drift.openai_compatible import OpenAICompatibleDriftProvider

__all__ = [
    "DriftProvider",
    "DriftUnavailableError",
    "DriftInvalidResponseError",
    "HostSidecarDriftProvider",
    "OpenAICompatibleDriftProvider",
]
