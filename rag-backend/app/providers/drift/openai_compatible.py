"""OpenAI-compatible drift provider.

Calls ``POST {base_url}/chat/completions`` with
``response_format={"type": "json_object"}`` and parses the assistant
message as a JSON object containing a ``hints`` list.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.providers.drift.base import (
    DriftInvalidResponseError,
    DriftProvider,
    DriftUnavailableError,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a context drift detector. Given recent chat messages and the "
    "current campaign state, identify facts that (1) contradict the current "
    "state, (2) add to the current state, or (3) are relevant for active "
    "list-items. Output JSON: {\"hints\": [{\"fact\": \"...\", "
    "\"contradicts_field\": \"key_or_null\", \"adds_field\": \"key_or_null\", "
    "\"msg_ref\": \"msg_index_or_null\", \"confidence\": 0.0-1.0}]}. Only "
    "include hints with confidence >= 0.5. Be conservative — false positives "
    "are worse than missed drift."
)


class OpenAICompatibleDriftProvider(DriftProvider):
    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key: str | None = None,
        timeout_seconds: int = 60,
        system_prompt: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key or ""
        self.timeout_seconds = timeout_seconds
        self.system_prompt = system_prompt or _SYSTEM_PROMPT

    async def detect_drift(
        self,
        *,
        messages: list[dict[str, str]],
        current_state: str,
        schema_hint: str | None = None,
    ) -> list[dict[str, Any]]:
        user_prompt = (
            f"## Campaign State:\n{current_state}\n\n"
            + (f"## Schema:\n{schema_hint}\n\n" if schema_hint else "")
            + "## Recent Messages:\n"
            + "\n".join(f"[{m.get('role', '?')}] {m.get('content', '')}" for m in messages)
        )

        body = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 512,
            "temperature": 0.0,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers=headers,
                )
        except (httpx.HTTPError, httpx.ConnectError, ConnectionError, OSError) as exc:
            raise DriftUnavailableError(
                f"drift provider unreachable at {self.base_url}: {exc}"
            ) from exc

        if resp.status_code >= 500:
            raise DriftUnavailableError(
                f"drift provider {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise DriftInvalidResponseError(
                f"drift provider returned non-JSON: {exc}"
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DriftInvalidResponseError(
                f"drift provider response missing choices[0].message.content: {exc}"
            ) from exc

        try:
            parsed = json.loads(content)
        except ValueError as exc:
            raise DriftInvalidResponseError(
                f"drift provider assistant content is not JSON: {exc}"
            ) from exc

        hints = parsed.get("hints")
        if not isinstance(hints, list):
            raise DriftInvalidResponseError(
                f"drift provider JSON has no list 'hints': keys={list(parsed.keys())}"
            )

        return hints
