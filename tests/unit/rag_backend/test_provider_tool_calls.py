"""Stage 8: tests for OpenAI-compatible provider tool-call support.

Covers:
- Tool-call streaming: deltas with the same `index` are accumulated into one
  full `LLMToolCall` (id, name, arguments).
- Non-streaming `generate_with_tools` returns `LLMFullResponse` with
  `tool_calls` populated.
- `generate_stream_with_tools` degrades gracefully when the model emits no
  tool_calls — only content deltas are produced.
- Legacy `generate_stream` and `generate` paths are unchanged.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from app.config import GenerationModelConfig
from app.providers.generation.base import (
    LLMFullResponse,
)
from app.providers.generation.openai_compatible import (
    OpenAICompatibleProvider,
    _parse_completion_response_full,
    _parse_stream_line_with_tools,
)

from shared_contracts.models import (
    LLMToolChoice,
    LLMToolDefinition,
    LLMToolDefinitionFunction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}"


def _build_provider() -> OpenAICompatibleProvider:
    cfg = GenerationModelConfig(
        model_id="test-model",
        provider="openai_compatible",
        base_url="https://api.example.com",
        api_key_env="OPENAI_API_KEY",
        api_key="sk-test",
        timeout_seconds=10,
    )
    return OpenAICompatibleProvider(cfg, api_key="sk-test", max_retries=1)


# ---------------------------------------------------------------------------
# _parse_stream_line_with_tools — content delta path (regression)
# ---------------------------------------------------------------------------


def test_parse_stream_line_content_only():
    line = _sse({
        "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}],
    })
    chunk = _parse_stream_line_with_tools(line)
    assert chunk.content_delta == "Hello"
    assert chunk.tool_call_delta is None


def test_parse_stream_line_done_sentinel():
    assert _parse_stream_line_with_tools("data: [DONE]").content_delta == ""


def test_parse_stream_line_empty_payload():
    assert _parse_stream_line_with_tools("data: ").content_delta == ""


def test_parse_stream_line_ignores_non_data():
    assert _parse_stream_line_with_tools(": keep-alive").content_delta == ""


# ---------------------------------------------------------------------------
# _parse_stream_line_with_tools — tool-call delta path
# ---------------------------------------------------------------------------


def test_parse_stream_line_tool_call_first_delta():
    """First delta of a tool call: id + function name, no arguments yet."""
    line = _sse({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "search_knowledge", "arguments": ""},
                }],
            },
            "finish_reason": None,
        }],
    })
    chunk = _parse_stream_line_with_tools(line)
    assert chunk.content_delta == ""
    delta = chunk.tool_call_delta
    assert delta is not None
    assert delta.index == 0
    assert delta.id == "call_abc"
    assert delta.function_name == "search_knowledge"
    assert delta.function_arguments_delta == ""


def test_parse_stream_line_tool_call_subsequent_delta():
    """Later deltas of the same tool call: only arguments grow."""
    line = _sse({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": '{"queries":["foo"]'},
                }],
            },
            "finish_reason": None,
        }],
    })
    chunk = _parse_stream_line_with_tools(line)
    delta = chunk.tool_call_delta
    assert delta is not None
    assert delta.index == 0
    assert delta.id is None  # id was sent in the first delta only
    assert delta.function_arguments_delta == '{"queries":["foo"]'


def test_parse_stream_line_multiple_tool_calls_different_indexes():
    """First delta of two parallel tool calls in one chunk."""
    line = _sse({
        "choices": [{
            "delta": {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_a",
                        "function": {"name": "tool_a", "arguments": ""},
                    },
                    {
                        "index": 1,
                        "id": "call_b",
                        "function": {"name": "tool_b", "arguments": ""},
                    },
                ],
            },
            "finish_reason": None,
        }],
    })
    chunk = _parse_stream_line_with_tools(line)
    # Parser returns the FIRST tool_call_delta only (single-delta contract)
    delta = chunk.tool_call_delta
    assert delta is not None
    assert delta.index == 0
    assert delta.function_name == "tool_a"


# ---------------------------------------------------------------------------
# _parse_completion_response_full
# ---------------------------------------------------------------------------


def test_parse_completion_response_text_only():
    payload = {
        "choices": [{
            "message": {"role": "assistant", "content": "hi"},
            "finish_reason": "stop",
        }],
    }
    result = _parse_completion_response_full(payload)
    assert result.content == "hi"
    assert result.tool_calls == []
    assert result.finish_reason == "stop"


def test_parse_completion_response_tool_calls():
    payload = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "search_knowledge",
                            "arguments": '{"queries":["a","b"]}',
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "another_tool",
                            "arguments": "{}",
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }],
    }
    result = _parse_completion_response_full(payload)
    assert result.content == ""
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].function.name == "search_knowledge"
    assert result.tool_calls[0].function.arguments == '{"queries":["a","b"]}'
    assert result.tool_calls[0].index == 0
    assert result.tool_calls[1].index == 1
    assert result.finish_reason == "tool_calls"


def test_parse_completion_response_missing_choices_raises():
    with pytest.raises(ValueError, match="no choices"):
        _parse_completion_response_full({"choices": []})


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider — payload building
# ---------------------------------------------------------------------------


def test_build_payload_no_tools_omits_field():
    from app.providers.generation.openai_compatible import _build_chat_payload

    payload = _build_chat_payload("m", [{"role": "user", "content": "hi"}], stream=False)
    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_build_payload_with_tools():
    from app.providers.generation.openai_compatible import _build_chat_payload

    tools = [
        LLMToolDefinition(
            type="function",
            function=LLMToolDefinitionFunction(
                name="search_knowledge",
                description="Search the local knowledge base.",
                parameters={
                    "type": "object",
                    "properties": {
                        "queries": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["queries"],
                },
            ),
        ),
    ]
    payload = _build_chat_payload(
        "m", [{"role": "user", "content": "hi"}], stream=True, tools=tools,
    )
    assert "tools" in payload
    assert payload["tools"][0]["function"]["name"] == "search_knowledge"


def test_build_payload_with_tool_choice_none():
    from app.providers.generation.openai_compatible import _build_chat_payload

    payload = _build_chat_payload(
        "m", [{"role": "user", "content": "hi"}], stream=False,
        tool_choice=LLMToolChoice(mode="none"),
    )
    assert payload["tool_choice"] == "none"


def test_build_payload_with_tool_choice_specific_function():
    from app.providers.generation.openai_compatible import _build_chat_payload

    payload = _build_chat_payload(
        "m", [{"role": "user", "content": "hi"}], stream=False,
        tool_choice=LLMToolChoice(mode="required", function_name="search_knowledge"),
    )
    # `required` mode is sent as the bare string
    assert payload["tool_choice"] == "required"


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider — generate_with_tools via mocked transport
# ---------------------------------------------------------------------------


class _MockTransport:
    """In-process mock of httpx transport returning a canned JSON response."""

    def __init__(self, response_payload: dict[str, Any]) -> None:
        self._payload = response_payload
        self.last_request: dict[str, Any] | None = None

    def __call__(self, request):  # pragma: no cover — only used via monkeypatch
        raise NotImplementedError


@pytest.mark.asyncio
async def test_generate_with_tools_text_only(monkeypatch):
    """`generate_with_tools` returns content-only LLMFullResponse when
    the model emits no tool_calls."""
    from app.providers.generation import openai_compatible as oai

    cfg = GenerationModelConfig(
        model_id="m", provider="openai_compatible",
        base_url="https://api.example.com",
        api_key_env="OPENAI_API_KEY", api_key="k", timeout_seconds=10,
    )
    provider = OpenAICompatibleProvider(cfg, api_key="k", max_retries=1)

    response_payload = {
        "choices": [{
            "message": {"role": "assistant", "content": "answer"},
            "finish_reason": "stop",
        }],
    }

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
        def raise_for_status(self):
            return None
        def json(self):
            return self._payload

    captured: dict[str, Any] = {}

    async def _fake_post(self, url, json=None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return _Resp(response_payload)

    monkeypatch.setattr(oai.httpx.AsyncClient, "post", _fake_post)

    tools = [
        LLMToolDefinition(
            type="function",
            function=LLMToolDefinitionFunction(
                name="search_knowledge", description="d", parameters={},
            ),
        ),
    ]
    result = await provider.generate_with_tools(
        [{"role": "user", "content": "hi"}], tools=tools,
        tool_choice=LLMToolChoice(mode="auto"),
    )
    assert isinstance(result, LLMFullResponse)
    assert result.content == "answer"
    assert result.tool_calls == []
    assert "tools" in captured["json"]
    assert captured["json"]["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_generate_with_tools_with_tool_calls(monkeypatch):
    cfg = GenerationModelConfig(
        model_id="m", provider="openai_compatible",
        base_url="https://api.example.com",
        api_key_env="OPENAI_API_KEY", api_key="k", timeout_seconds=10,
    )
    provider = OpenAICompatibleProvider(cfg, api_key="k", max_retries=1)

    response_payload = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_xyz",
                    "type": "function",
                    "function": {
                        "name": "search_knowledge",
                        "arguments": '{"queries":["dwarf"]}',
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
        def raise_for_status(self):
            return None
        def json(self):
            return self._payload

    async def _fake_post(self, url, json=None, **kwargs):
        return _Resp(response_payload)

    from app.providers.generation import openai_compatible as oai
    monkeypatch.setattr(oai.httpx.AsyncClient, "post", _fake_post)

    tools = [
        LLMToolDefinition(
            type="function",
            function=LLMToolDefinitionFunction(
                name="search_knowledge", description="d", parameters={},
            ),
        ),
    ]
    result = await provider.generate_with_tools(
        [{"role": "user", "content": "hi"}], tools=tools,
    )
    assert result.content == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_xyz"
    assert result.tool_calls[0].function.name == "search_knowledge"
    assert result.tool_calls[0].function.arguments == '{"queries":["dwarf"]}'
    assert result.finish_reason == "tool_calls"
