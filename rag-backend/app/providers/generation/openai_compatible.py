from __future__ import annotations
import asyncio
import json
import logging
from collections.abc import AsyncIterator
import httpx
from app.config import GenerationModelConfig
from app.providers.generation.base import GenerationProvider, GenerationProviderUnavailableError

logger = logging.getLogger(__name__)

class OpenAICompatibleProvider(GenerationProvider):
    def __init__(self, config: GenerationModelConfig, api_key: str, max_retries: int = 3) -> None:
        self.config = config
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = httpx.Timeout(
            min(float(config.timeout_seconds), 10.0),
            connect=min(float(config.timeout_seconds), 3.0),
        )

    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{self.config.base_url.rstrip('/')}/chat/completions",
                        headers=self._headers(),
                        json={
                            "model": self.config.model_id,
                            "messages": messages,
                            "stream": True,
                        },
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            token = _parse_stream_line(line)
                            if token:
                                yield token
                        return
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning("Generation provider unavailable on attempt %s: %s", attempt + 1, exc)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_error = exc
                logger.warning("Generation request failed on attempt %s: %s", attempt + 1, exc)

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        raise GenerationProviderUnavailableError("Generation provider is unavailable.") from last_error

    async def generate(self, messages: list[dict[str, str]]) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers()) as client:
                    response = await client.post(
                        f"{self.config.base_url.rstrip('/')}/chat/completions",
                        json={
                            "model": self.config.model_id,
                            "messages": messages,
                            "stream": False,
                        },
                    )
                    response.raise_for_status()
                    return _parse_completion_response(response.json())
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning("Generation provider unavailable on attempt %s: %s", attempt + 1, exc)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                last_error = exc
                logger.warning("Generation request failed on attempt %s: %s", attempt + 1, exc)

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        raise GenerationProviderUnavailableError("Generation provider is unavailable.") from last_error

    async def generate_json(self, messages: list[dict[str, str]], fallback: dict | None = None) -> dict:
        """
        Вызывает LLM с требованием вернуть валидный JSON.
        Используется агентом-планировщиком для выбора шагов/инструментов.
        """
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers()) as client:
                    response = await client.post(
                        f"{self.config.base_url.rstrip('/')}/chat/completions",
                        json={
                            "model": self.config.model_id,
                            "messages": messages,
                            "stream": False,
                            "response_format": {"type": "json_object"},
                            "temperature": 0.2,
                        },
                    )
                    response.raise_for_status()
                    content = _parse_completion_response(response.json())
                    return json.loads(content)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning("JSON generation failed on attempt %s: %s", attempt + 1, exc)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                last_error = exc
                logger.warning("JSON request failed on attempt %s: %s", attempt + 1, exc)

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        if fallback:
            logger.warning("JSON generation exhausted retries, returning fallback")
            return fallback
        raise GenerationProviderUnavailableError("JSON generation provider is unavailable.") from last_error

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def _parse_stream_line(line: str) -> str:
    if not line.startswith("data: "):
        return ""
    payload = line.removeprefix("data: ").strip()
    if not payload or payload == "[DONE]":
        return ""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def _parse_completion_response(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Generation response has no choices.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("Generation response choice has no message.")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("Generation response message has no content.")
    return content.strip()