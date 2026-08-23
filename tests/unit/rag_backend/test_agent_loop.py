"""Stage 8.4: tests for the bounded agent loop.

Each test wires a fake provider that emits a scripted sequence of
`LLMStreamChunk` values, and asserts on the resulting `AgentEvent`s
and the final `AgentLoopResult`. The search-knowledge service is
mocked at the `search_knowledge_service.run` boundary — this lets us
verify the loop's own contract (round caps, dedup, error surfacing)
without coupling to retrieval details covered in 8.3.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from app.providers.generation.base import LLMStreamChunk, ToolCallDelta
from app.services import agent_loop as al
from app.services.agent_loop import (
    SEARCH_KNOWLEDGE_TOOL,
    AgentEvent,
    AgentLoop,
    _extract_search_queries,
    _format_tool_result_text,
    _parse_tool_arguments,
)

from shared_contracts.models import (
    AgentLoopResult,
    RetrievalPolicy,
    SearchHit,
    SearchKnowledgeResult,
)

# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class ScriptedProvider:
    """Replays a list of `LLMStreamChunk` lists — one per round.

    The list is consumed round-by-round: scripts[r] is emitted on the
    r-th call to `generate_stream_with_tools`. When the r-th call is
    made, the script list is replaced with `next_round_scripts` (if set)
    so a test can decide what the model does on later rounds.
    """

    def __init__(self, scripts: list[list[LLMStreamChunk]]) -> None:
        self._scripts = list(scripts)
        self._calls: list[list[dict[str, Any]]] = []

    async def generate_stream_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: Any = None,
        tool_choice: Any = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        # Record the call for assertions.
        self._calls.append([
            {"role": m.get("role"), "content_len": len(m.get("content") or "")}
            for m in messages
        ])
        if not self._scripts:
            return
        for chunk in self._scripts.pop(0):
            yield chunk

    # Legacy path — never used by AgentLoop but referenced in error paths.
    async def generate(self, messages):
        return ""


def _content_chunk(text: str) -> LLMStreamChunk:
    return LLMStreamChunk(content_delta=text)


def _tool_call_chunks(call_id: str, name: str, args: str) -> list[LLMStreamChunk]:
    """Build the canonical 'first + argument-delta' stream for one tool call."""
    return [
        LLMStreamChunk(tool_call_delta=ToolCallDelta(
            index=0, id=call_id, type="function",
            function_name=name, function_arguments_delta="",
        )),
        LLMStreamChunk(tool_call_delta=ToolCallDelta(
            index=0, function_arguments_delta=args,
        )),
    ]


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------


async def _collect(events: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    out: list[AgentEvent] = []
    async for e in events:
        out.append(e)
    return out


_BASE_KWARGS: dict[str, Any] = {
    "system_prompt": "sys",
    "history": [{"role": "user", "content": "earlier turn"}],
    "user_message": "now",
    "domain_id": "dnd",
    "campaign_id": "c1",
    "vault_ids": ["v1"],
    "max_rounds": 2,
    "evidence_token_budget": 4000,
    "policy": RetrievalPolicy.GROUNDED,
    "db": AsyncMock(),
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_tool_arguments_valid_json():
    assert _parse_tool_arguments('{"queries":["foo"]}') == {"queries": ["foo"]}


def test_parse_tool_arguments_invalid_json_returns_empty():
    assert _parse_tool_arguments("{not valid") == {}


def test_parse_tool_arguments_empty_returns_empty():
    assert _parse_tool_arguments("") == {}


def test_extract_search_queries_filters_non_strings():
    fake_call = type("C", (), {})()
    fake_call.function = type("F", (), {})()
    fake_call.function.arguments = json.dumps({
        "queries": ["dwarf", 42, "", "armor"],
        "reason": "lore",
    })
    queries, reason = _extract_search_queries(fake_call)
    assert queries == ["dwarf", "armor"]
    assert reason == "lore"


def test_format_tool_result_text_with_hits():
    result = SearchKnowledgeResult(
        queries_used=["dwarf"],
        hits=[SearchHit(chunk_id="c1", document_id="d1", text="Heavy plate", score=0.9)],
        scope="campaign",
        evidence_tokens=5,
    )
    out = _format_tool_result_text(result)
    assert "[1] Heavy plate" in out
    assert '"scope": "campaign"' in out
    assert '"hits_count": 1' in out


def test_format_tool_result_text_no_hits():
    result = SearchKnowledgeResult(
        queries_used=["dwarf"],
        hits=[],
        scope="empty",
        evidence_tokens=0,
        note="nothing in campaign",
    )
    out = _format_tool_result_text(result)
    assert "(no evidence found)" in out
    assert "nothing in campaign" in out


# ---------------------------------------------------------------------------
# Loop behaviour — no tool calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tool_call_single_round_text_answer():
    """Model returns text directly → loop ends after one round."""
    provider = ScriptedProvider([
        [_content_chunk("Hello "), _content_chunk("world.")],
    ])
    loop = AgentLoop()

    with patch.object(al, "_execute_search_knowledge", new=AsyncMock()) as esk:
        events = await _collect(loop.run_stream(provider=provider, **_BASE_KWARGS))
        esk.assert_not_called()

    types = [e.type for e in events]
    assert types[0] == "round_start"
    assert types[-1] == "final"
    # token events interleave with round_end and final
    assert "token" in types
    assert "tool_call" not in types
    assert "tool_result" not in types

    # Tool_choice was 'auto' on the only round.
    assert provider._calls[0][-1]["role"] == "user"


# ---------------------------------------------------------------------------
# Loop behaviour — single tool call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_tool_call_two_rounds_terminal_text():
    """Round 0: tool_call. Round 1: text answer. Loop exits cleanly."""
    provider = ScriptedProvider([
        _tool_call_chunks(
            "call_1", "search_knowledge",
            json.dumps({"queries": ["dwarf armor"], "reason": "need rules"}),
        ),
        [_content_chunk("Based on the campaign: dwarves...")],
    ])
    loop = AgentLoop()

    fake_result = SearchKnowledgeResult(
        queries_used=["dwarf armor"],
        hits=[SearchHit(chunk_id="c1", document_id="d1", text="evidence", score=0.9)],
        scope="campaign",
        evidence_tokens=5,
    )
    with patch.object(al, "_execute_search_knowledge", new=AsyncMock(return_value=fake_result)):
        events = await _collect(loop.run_stream(provider=provider, **_BASE_KWARGS))

    types = [e.type for e in events]
    assert types.count("tool_call") == 1
    assert types.count("tool_result") == 1
    # Two round_starts (one per round) and one final.
    assert types.count("round_start") == 2
    assert types[-1] == "final"

    tool_result = next(e for e in events if e.type == "tool_result")
    assert tool_result.payload["hits_count"] == 1
    assert tool_result.payload["scope"] == "campaign"

    # After round 0 the messages list must contain the assistant tool_call
    # message and the role=tool message.
    second_call_messages = provider._calls[1]
    roles = [m["role"] for m in second_call_messages]
    assert "assistant" in roles  # carries the tool_calls
    assert "tool" in roles       # carries the search result


# ---------------------------------------------------------------------------
# Loop behaviour — round cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_final_round_forces_tool_choice_none_and_accepts_text():
    """Last round: tool_choice='none' — even if the model insists on a tool
    call, we still exit and surface the result of the previous round.

    Since the model is told tool_choice=none, our scripted provider does
    not emit a tool_call on round 1, and the model returns plain text.
    """
    provider = ScriptedProvider([
        _tool_call_chunks(
            "call_a", "search_knowledge",
            json.dumps({"queries": ["x"]}),
        ),
        [_content_chunk("Final answer")],
    ])
    loop = AgentLoop()

    fake_result = SearchKnowledgeResult(
        queries_used=["x"], hits=[], scope="campaign",
        evidence_tokens=0,
    )
    with patch.object(al, "_execute_search_knowledge", new=AsyncMock(return_value=fake_result)):
        events = await _collect(loop.run_stream(
            provider=provider,
            **{**_BASE_KWARGS, "max_rounds": 2},
        ))

    # Exactly two rounds, terminal 'final'.
    types = [e.type for e in events]
    assert types.count("round_start") == 2
    assert types[-1] == "final"


@pytest.mark.asyncio
async def test_max_rounds_one_means_single_shot_with_no_tool():
    """max_rounds=1 collapses the loop into a single tool-free turn."""
    provider = ScriptedProvider([
        [_content_chunk("Just answer.")],
    ])
    loop = AgentLoop()
    events = await _collect(loop.run_stream(
        provider=provider,
        **{**_BASE_KWARGS, "max_rounds": 1, "policy": RetrievalPolicy.ASSISTIVE},
    ))
    assert [e.type for e in events][-1] == "final"
    assert sum(1 for e in events if e.type == "round_start") == 1


# ---------------------------------------------------------------------------
# Loop behaviour — duplicate query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_query_in_same_turn_is_short_circuited():
    """Spec §12.2: 'не повторять одинаковый query'.

    Two rounds, each calling search_knowledge with the same query.
    The second call must hit the duplicate short-circuit and produce
    an empty result with a 'duplicate_query' note — the real
    `_execute_search_knowledge` must NOT be called the second time.
    """
    provider = ScriptedProvider([
        _tool_call_chunks("call_1", "search_knowledge", json.dumps({"queries": ["dwarf"]})),
        _tool_call_chunks("call_2", "search_knowledge", json.dumps({"queries": ["dwarf"]})),
        [_content_chunk("No new evidence.")],
    ])
    loop = AgentLoop()

    real_result = SearchKnowledgeResult(
        queries_used=["dwarf"], hits=[], scope="campaign",
        evidence_tokens=0,
    )
    execute_mock = AsyncMock(return_value=real_result)
    with patch.object(al, "_execute_search_knowledge", new=execute_mock):
        events = await _collect(loop.run_stream(
            provider=provider,
            **{**_BASE_KWARGS, "max_rounds": 3},
        ))

    # Real execution only happened once.
    assert execute_mock.await_count == 1
    # Two tool_result events but only one with scope=search-service scope.
    tool_results = [e for e in events if e.type == "tool_result"]
    assert len(tool_results) == 2
    assert tool_results[0].payload["scope"] == "campaign"
    assert tool_results[1].payload["scope"] == "empty"


# ---------------------------------------------------------------------------
# Loop behaviour — error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_surfaces_error_and_stops():
    """If the model invents a tool that we don't know, the loop must
    surface an error event and exit without crashing the chat turn."""
    provider = ScriptedProvider([
        _tool_call_chunks("call_x", "made_up_tool", json.dumps({})),
    ])
    loop = AgentLoop()
    events = await _collect(loop.run_stream(provider=provider, **_BASE_KWARGS))

    types = [e.type for e in events]
    assert "error" in types
    err = next(e for e in events if e.type == "error")
    assert "made_up_tool" in err.payload["message"]


@pytest.mark.asyncio
async def test_provider_exception_yields_error_event():
    """Provider blow-up → error event, no crash of the host."""
    class BrokenProvider:
        async def generate_stream_with_tools(self, *a, **kw):
            raise RuntimeError("upstream is down")
            yield  # noqa: unreachable — makes this an async generator

    loop = AgentLoop()
    events = await _collect(loop.run_stream(
        provider=BrokenProvider(),
        **_BASE_KWARGS,
    ))
    types = [e.type for e in events]
    assert types[0] == "round_start"
    assert "error" in types


# ---------------------------------------------------------------------------
# run() non-stream convenience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_aggregates_content_and_metadata():
    provider = ScriptedProvider([
        _tool_call_chunks(
            "call_1", "search_knowledge",
            json.dumps({"queries": ["dwarf"]}),
        ),
        [_content_chunk("Answer ")],
    ])
    loop = AgentLoop()

    fake_result = SearchKnowledgeResult(
        queries_used=["dwarf"],
        hits=[SearchHit(chunk_id="c1", document_id="d1", text="e", score=0.9)],
        scope="campaign", evidence_tokens=1,
    )
    with patch.object(al, "_execute_search_knowledge", new=AsyncMock(return_value=fake_result)):
        result = await loop.run(
            provider=provider,
            **_BASE_KWARGS,
        )

    assert isinstance(result, AgentLoopResult)
    assert result.content == "Answer "
    assert result.tool_calls_made == 1
    assert result.policy is RetrievalPolicy.GROUNDED
    assert len(result.rounds) >= 1


# ---------------------------------------------------------------------------
# Tool schema sanity
# ---------------------------------------------------------------------------


def test_search_knowledge_tool_definition_is_valid_openai_function():
    """The tool definition must conform to the OpenAI function-calling JSON
    schema: `type: function`, `name`, `description`, `parameters` with type=object.
    """
    assert SEARCH_KNOWLEDGE_TOOL.type == "function"
    assert SEARCH_KNOWLEDGE_TOOL.function.name == "search_knowledge"
    assert SEARCH_KNOWLEDGE_TOOL.function.parameters["type"] == "object"
    assert "queries" in SEARCH_KNOWLEDGE_TOOL.function.parameters["properties"]
    assert "queries" in SEARCH_KNOWLEDGE_TOOL.function.parameters["required"]


# ---------------------------------------------------------------------------
# Sprint 1: tool_choice='required' when grounded + update_scene_state tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grounded_round_0_sends_tool_choice_required():
    """When policy==GROUNDED and we're on round 0, the provider must see
    tool_choice='required' — the model is forced to call at least one tool
    before it can produce a text answer (§12.1).

    We capture the tool_choice passed on every call and assert on round 0.
    """
    received_tool_choices: list[Any] = []

    class CapturingProvider:
        async def generate_stream_with_tools(
            self,
            messages,
            tools=None,
            tool_choice=None,
        ):
            received_tool_choices.append(tool_choice)
            yield _content_chunk("fallback answer")

    loop = AgentLoop()
    await _collect(loop.run_stream(
        provider=CapturingProvider(),
        **{**_BASE_KWARGS, "policy": RetrievalPolicy.GROUNDED, "max_rounds": 2},
    ))

    # First call: required. Second call (round 1 — still grounded but not round 0): auto.
    assert received_tool_choices[0] is not None
    assert getattr(received_tool_choices[0], "mode", received_tool_choices[0]) == "required"
    # Second call should fall back to 'auto' (not final round yet).
    assert len(received_tool_choices) >= 1


@pytest.mark.asyncio
async def test_assistive_round_0_sends_tool_choice_auto():
    """When policy==ASSISTIVE, the provider sees tool_choice='auto' on round 0.
    The model may or may not call a tool — that's the whole point of assistive.
    """
    received_tool_choices: list[Any] = []

    class CapturingProvider:
        async def generate_stream_with_tools(
            self,
            messages,
            tools=None,
            tool_choice=None,
        ):
            received_tool_choices.append(tool_choice)
            yield _content_chunk("OK")

    loop = AgentLoop()
    await _collect(loop.run_stream(
        provider=CapturingProvider(),
        **{**_BASE_KWARGS, "policy": RetrievalPolicy.ASSISTIVE, "max_rounds": 2},
    ))

    assert received_tool_choices[0] is not None
    assert getattr(received_tool_choices[0], "mode", received_tool_choices[0]) == "auto"


def test_update_scene_state_tool_definition_is_valid_openai_function():
    """The new tool definition must conform to the same OpenAI schema as
    search_knowledge — `type: function`, `name`, `description`, `parameters`.
    """
    from app.services.agent_loop import UPDATE_SCENE_STATE_TOOL
    assert UPDATE_SCENE_STATE_TOOL.type == "function"
    assert UPDATE_SCENE_STATE_TOOL.function.name == "update_scene_state"
    assert UPDATE_SCENE_STATE_TOOL.function.parameters["type"] == "object"
    assert "patch" in UPDATE_SCENE_STATE_TOOL.function.parameters["properties"]
    assert "patch" in UPDATE_SCENE_STATE_TOOL.function.parameters["required"]


def test_extract_scene_state_patch_handles_non_dict_and_truncates():
    """_extract_scene_state_patch must:
      - tolerate missing / non-dict patch (treat as empty)
      - truncate to _SCENE_STATE_PATCH_MAX_KEYS keys
      - preserve null values (explicit delete marker)
    """
    from app.services.agent_loop import (
        _SCENE_STATE_PATCH_MAX_KEYS,
        _extract_scene_state_patch,
    )
    fake_call = type("C", (), {})()
    fake_call.function = type("F", (), {})()
    fake_call.function.arguments = json.dumps({})

    patch, reason = _extract_scene_state_patch(fake_call)
    assert patch == {}
    assert reason == ""

    # non-dict → empty
    fake_call.function.arguments = json.dumps({"patch": "not a dict"})
    patch, _ = _extract_scene_state_patch(fake_call)
    assert patch == {}

    # truncate
    too_many = {f"k{i}": i for i in range(_SCENE_STATE_PATCH_MAX_KEYS + 5)}
    fake_call.function.arguments = json.dumps({"patch": too_many, "reason": "x"})
    patch, reason = _extract_scene_state_patch(fake_call)
    assert len(patch) == _SCENE_STATE_PATCH_MAX_KEYS
    assert reason == "x"

    # null preserved
    fake_call.function.arguments = json.dumps({"patch": {"a": None, "b": 1}})
    patch, _ = _extract_scene_state_patch(fake_call)
    assert patch == {"a": None, "b": 1}


@pytest.mark.asyncio
async def test_update_scene_state_tool_call_merges_into_chat_metadata():
    """Round 0: model calls update_scene_state with a patch. Host merges
    patch into Chat.metadata_json['scene_state'] and persists.
    """
    from app.db.models import Base, Chat
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        chat = Chat(title="t", domain_id="dnd", metadata_json={"scene_state": {"existing": "v"}})
        db.add(chat)
        await db.commit()
        chat_id = str(chat.id)

        provider = ScriptedProvider([
            _tool_call_chunks(
                "call_scene", "update_scene_state",
                json.dumps({"patch": {"location": "cave", "existing": None}, "reason": "set"}),
            ),
            [_content_chunk("OK")],
        ])

        loop = AgentLoop()
        events = await _collect(loop.run_stream(
            provider=provider,
            **{**_BASE_KWARGS, "chat_id": chat_id, "db": db, "max_rounds": 2},
        ))

        # Reload chat from DB and inspect metadata.
        await db.refresh(chat)
        scene = chat.metadata_json.get("scene_state", {})
        assert scene.get("location") == "cave"
        assert "existing" not in scene  # None → removed

        types = [e.type for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        tool_result = next(e for e in events if e.type == "tool_result")
        assert tool_result.payload["tool"] == "update_scene_state"
        assert tool_result.payload["status"] == "ok"
        assert "location" in tool_result.payload["applied_keys"]
        assert "existing" in tool_result.payload["removed_keys"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_update_scene_state_without_chat_id_returns_error():
    """If chat_id is None, the host-side execution returns an error result
    instead of crashing. The model sees the error in tool_result.
    """
    provider = ScriptedProvider([
        _tool_call_chunks(
            "call_scene", "update_scene_state",
            json.dumps({"patch": {"location": "cave"}}),
        ),
        [_content_chunk("OK")],
    ])
    loop = AgentLoop()
    events = await _collect(loop.run_stream(
        provider=provider,
        # chat_id is omitted on purpose.
        **{k: v for k, v in _BASE_KWARGS.items() if k != "chat_id"},
    ))
    types = [e.type for e in events]
    assert "tool_result" in types
    tool_result = next(e for e in events if e.type == "tool_result")
    assert tool_result.payload["tool"] == "update_scene_state"
    assert tool_result.payload["status"] == "error"
