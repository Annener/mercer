from __future__ import annotations
import asyncio
import json
import logging
from collections.abc import AsyncIterator
import httpx
from app.config import GenerationModelConfig
from app.providers.generation.base import GenerationProvider, GenerationProviderUnavailableError

logger = logging.getLogger(__name__)

# Заголовки идентификации приложения для OpenRouter
# (рекомендуется документацией proxyapi.ru/openrouter)
_APP_SITE_URL = "http://mercer.local"
_APP_TITLE = "Mercer RAG"


class OpenAICompatibleProvider(GenerationProvider):
    def __init__(self, config: GenerationModelConfig, api_key: str, max_retries: int = 3) -> None:
        self.config = config
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = httpx.Timeout(
            float(config.timeout_seconds),
            connect=min(float(config.timeout_seconds), 10.0),
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
                        json=_build_chat_payload(self.config.model_id, messages, stream=True),
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            token = _parse_stream_line(line)
                            if token:
                                yield token
                        return
            except StreamProviderError as exc:
                # Ошибка внутри SSE-потока (напр., finish_reason=error от OpenRouter)
                last_error = exc
                logger.warning("Stream provider error on attempt %s: %s", attempt + 1, exc)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning("Generation provider unavailable on attempt %s: %s", attempt + 1, exc)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError):
                    logger.warning(
                        "Generation request failed on attempt %s: HTTP %s %s — body: %s",
                        attempt + 1, exc.response.status_code, exc.request.url, exc.response.text[:500]
                    )
                else:
                    logger.warning("Generation request failed on attempt %s: %s %r", attempt + 1, type(exc).__name__, exc)
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
                        json=_build_chat_payload(self.config.model_id, messages, stream=False),
                    )
                    response.raise_for_status()
                    return _parse_completion_response(response.json())
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
                last_error = exc
                logger.warning("Generation provider unavailable on attempt %s: %s", attempt + 1, exc)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError):
                    logger.warning(
                        "Generation request failed on attempt %s: HTTP %s %s — body: %s",
                        attempt + 1, exc.response.status_code, exc.request.url, exc.response.text[:500],
                    )
                else:
                    logger.warning(
                        "Generation request failed on attempt %s: %s %r",
                        attempt + 1, type(exc).__name__, str(exc) or "(no message)",
                    )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        raise GenerationProviderUnavailableError("Generation provider is unavailable.") from last_error

    async def generate_json(self, messages: list[dict[str, str]], fallback: dict | None = None) -> dict:
        """
        Вызывает LLM с требованием вернуть валидный JSON.
        Используется агентом-планировщиком для выбора шагов/инструментов.

        ВАЖНО: response_format={"type": "json_object"} намеренно НЕ используется.
        OpenRouter не поддерживает это поле для всех моделей (в частности DeepSeek),
        и при его наличии падает с внутренней ошибкой 'str' object has no attribute 'get'.
        JSON-режим обеспечивается инъекцией системного промпта — универсальный подход
        для любого OpenAI-совместимого провайдера.
        """
        # Инъецируем системный промпт, требующий JSON, если его ещё нет
        json_system = {"role": "system", "content": "You must respond with valid JSON only. No markdown, no explanation, no code fences — just the raw JSON object."}
        if messages and messages[0].get("role") == "system":
            enriched = list(messages)
            enriched[0] = {
                "role": "system",
                "content": enriched[0]["content"] + "\n\nIMPORTANT: Respond with valid JSON only.",
            }
        else:
            enriched = [json_system] + list(messages)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers()) as client:
                    response = await client.post(
                        f"{self.config.base_url.rstrip('/')}/chat/completions",
                        json=_build_chat_payload(self.config.model_id, enriched, stream=False, temperature=0.2),
                    )
                    response.raise_for_status()
                    content = _parse_completion_response(response.json())
                    # Снимаем возможные code-fences если модель всё равно их добавила
                    stripped = content.strip()
                    if stripped.startswith("```"):
                        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                    return json.loads(stripped)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning("JSON generation failed on attempt %s: %s", attempt + 1, exc)
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError):
                    logger.warning(
                        "JSON request failed on attempt %s: HTTP %s %s — body: %s",
                        attempt + 1, exc.response.status_code, exc.request.url, exc.response.text[:500],
                    )
                else:
                    logger.warning(
                        "JSON request failed on attempt %s: %s %r",
                        attempt + 1, type(exc).__name__, str(exc) or "(no message)",
                    )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2**attempt)

        if fallback:
            logger.warning("JSON generation exhausted retries, returning fallback")
            return fallback
        raise GenerationProviderUnavailableError("JSON generation provider is unavailable.") from last_error

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            # Идентификация приложения для OpenRouter / ProxyAPI
            # https://proxyapi.ru/docs/openrouter
            "HTTP-Referer": _APP_SITE_URL,
            "X-Title": _APP_TITLE,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class StreamProviderError(Exception):
    """Ошибка, переданная провайдером внутри SSE-потока (finish_reason=error)."""


def _build_chat_payload(
    model_id: str,
    messages: list[dict[str, str]],
    *,
    stream: bool,
    temperature: float | None = None,
) -> dict:
    payload: dict = {
        "model": model_id,
        "messages": messages,
        "stream": stream,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


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

    choice = choices[0]

    # OpenRouter при ошибке провайдера возвращает чанк с finish_reason="error"
    # вместо HTTP-ошибки. Нужно явно пробросить исключение, чтобы ретрай отработал.
    finish_reason = choice.get("finish_reason")
    if finish_reason == "error":
        error_info = data.get("error") or choice.get("error") or {}
        error_msg = (
            error_info.get("message") or error_info.get("code") or str(error_info)
            if isinstance(error_info, dict)
            else str(error_info)
        )
        raise StreamProviderError(f"OpenRouter stream error: {error_msg}")

    delta = choice.get("delta")
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
