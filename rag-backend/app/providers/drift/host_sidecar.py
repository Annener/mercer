"""Drift provider that delegates to pdf-sidecar ``POST /drift``.

This is the default backend — QVikhr-3-1.7B-Instruct-noreasoning
(Q4_K_M, ~1.1 GB) running inside the pdf-sidecar process on the host.
On macOS M-series the model is loaded onto Metal GPU by default
(``DRIFT_FORCE_CPU=0``). See ``pdf-sidecar/drift.py`` for the handler
implementation.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.providers.drift.base import (
    DriftInvalidResponseError,
    DriftProvider,
    DriftUnavailableError,
)

logger = logging.getLogger(__name__)


class HostSidecarDriftProvider(DriftProvider):
    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        timeout_seconds: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    async def detect_drift(
        self,
        *,
        messages: list[dict[str, str]],
        current_state: str,
        schema_hint: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "current_state": current_state,
            "schema_hint": schema_hint,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(f"{self.base_url}/drift", json=payload)
        except (httpx.HTTPError, httpx.ConnectError, ConnectionError, OSError) as exc:
            raise DriftUnavailableError(
                f"drift sidecar unreachable at {self.base_url}: {exc}"
            ) from exc

        if resp.status_code >= 500:
            raise DriftUnavailableError(
                f"drift sidecar {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise DriftInvalidResponseError(
                f"drift sidecar returned non-JSON: {exc}"
            ) from exc

        hints = data.get("hints")
        if not isinstance(hints, list):
            raise DriftInvalidResponseError(
                f"drift sidecar payload has no list 'hints': keys={list(data.keys())}"
            )

        return hints
