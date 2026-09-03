"""Drift provider interface and exceptions.

Drift detection compares recent chat messages against the current
campaign state and emits hints describing contradictions / additions.
Providers are pluggable: the default backend is ``host_sidecar``
(QVikhr-3-1.7B-Instruct-noreasoning running inside pdf-sidecar),
but external OpenAI-compatible endpoints can be used through
``openai_compatible``.

Provider implementations MUST raise ``DriftUnavailableError`` when the
backend is unreachable and ``DriftInvalidResponseError`` when the
response shape is unexpected. Callers treat both as non-fatal —
drift-detection failures must not break chat.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DriftProviderError(Exception):
    """Base error for all drift providers."""


class DriftUnavailableError(DriftProviderError):
    """Raised when the drift backend cannot be reached."""


class DriftInvalidResponseError(DriftProviderError):
    """Raised when the response is unreachable or has an invalid shape."""


class DriftProvider(ABC):
    """Abstract drift provider.

    Implementations MUST return a list of hint dicts with the following
    shape::

        {
            "fact": str,
            "contradicts_field": str | None,
            "adds_field": str | None,
            "msg_ref": str | None,
            "confidence": float,  # 0.0 .. 1.0
        }

    Empty list ``[]`` is a valid result (no drift detected).
    Implementations MUST NOT raise generic exceptions — they should
    translate network / parse errors into :class:`DriftUnavailableError`
    or :class:`DriftInvalidResponseError` so that the caller can react
    gracefully.
    """

    @abstractmethod
    async def detect_drift(
        self,
        *,
        messages: list[dict[str, str]],
        current_state: str,
        schema_hint: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return drift hints for the supplied conversation context.

        :param messages: Recent chat messages as ``[{"role": "user"|"assistant", "content": str}, ...]``.
        :param current_state: Compiled Campaign State block.
        :param schema_hint: Optional free-form description of state fields (for hint generation).
        :returns: List of hint dicts (possibly empty).
        :raises DriftUnavailableError: Backend cannot be reached.
        :raises DriftInvalidResponseError: Response cannot be parsed.
        """
