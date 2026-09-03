"""Tests for round_start payload in agent_loop.py.

Этап 2: payload `round_start` event расширен полями
`phase`, `effective_grounded`, `tool_choice`, чтобы чат-слой мог показать
осмысленный статус вместо жаргонного «Round X/Y (grounded)».
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.providers.generation.base import LLMStreamChunk, ToolCallDelta
from app.services import agent_loop as al
from app.services.agent_loop import AgentLoop, RetrievalPolicy
from app.services.search_knowledge_service import SearchKnowledgeResult


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


async def _collect(agen):
    out = []
    async for ev in agen:
        out.append(ev)
    return out


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


class _ScriptedProvider:
    """Replays a list of `LLMStreamChunk` lists — one per round."""

    def __init__(self, scripts: list[list[LLMStreamChunk]]):
        self._scripts = scripts
        self._call_idx = 0
        self._calls: list[list[dict[str, Any]]] = []

    async def generate_stream_with_tools(self, messages, *, tools, tool_choice):
        self._calls.append(messages)
        if self._call_idx >= len(self._scripts):
            return
        round_chunks = self._scripts[self._call_idx]
        self._call_idx += 1
        for c in round_chunks:
            yield c


_FAKE_RESULT = SearchKnowledgeResult(
    queries_used=["x"], hits=[], scope="campaign", evidence_tokens=0,
)


@pytest.mark.asyncio
async def test_round_start_payload_initial_then_final_grounded():
    """policy=GROUNDED, max_rounds=2:
       round 0: phase=initial, effective_grounded=True, tool_choice=required.
       round 1: phase=final, effective_grounded=False, tool_choice=none.
    """
    loop = AgentLoop()
    provider = _ScriptedProvider([
        _tool_call_chunks("c0", "search_knowledge", json.dumps({"queries": ["x"]})),
        [_content_chunk("final answer")],
    ])
    with patch.object(al, "_execute_search_knowledge", new=AsyncMock(return_value=_FAKE_RESULT)):
        events = await _collect(loop.run_stream(provider=provider, **_BASE_KWARGS))

    round_starts = [e for e in events if e.type == "round_start"]
    assert len(round_starts) == 2
    p0 = round_starts[0].payload
    assert p0["phase"] == "initial"
    assert p0["effective_grounded"] is True
    assert p0["tool_choice"] == "required"
    assert p0["policy"] == "grounded"
    assert p0["max_rounds"] == 2

    p1 = round_starts[1].payload
    assert p1["phase"] == "final"
    assert p1["effective_grounded"] is False
    assert p1["tool_choice"] == "none"
    assert p1["policy"] == "grounded"


@pytest.mark.asyncio
async def test_round_start_payload_initial_not_grounded_when_assistive_round0():
    """policy=ASSISTIVE, max_rounds=2:
       round 0: effective_grounded=False, tool_choice=auto → phase='followup'
                (ASSISTIVE не делает 'initial' — только grounded с required).
       round 1: phase=final, tool_choice=none.
    """
    loop = AgentLoop()
    provider = _ScriptedProvider([
        _tool_call_chunks("c0", "search_knowledge", json.dumps({"queries": ["x"]})),
        [_content_chunk("answer")],
    ])
    with patch.object(al, "_execute_search_knowledge", new=AsyncMock(return_value=_FAKE_RESULT)):
        events = await _collect(loop.run_stream(
            provider=provider,
            **{**_BASE_KWARGS, "policy": RetrievalPolicy.ASSISTIVE, "max_rounds": 2},
        ))

    round_starts = [e for e in events if e.type == "round_start"]
    assert len(round_starts) == 2
    p0 = round_starts[0].payload
    assert p0["phase"] == "followup"
    assert p0["effective_grounded"] is False
    assert p0["tool_choice"] == "auto"
    assert p0["policy"] == "assistive"

    p1 = round_starts[1].payload
    assert p1["phase"] == "final"
    assert p1["tool_choice"] == "none"


@pytest.mark.asyncio
async def test_round_start_payload_single_round_assistive_is_final():
    """policy=ASSISTIVE, max_rounds=1 → единственный round phase=final."""
    loop = AgentLoop()
    provider = _ScriptedProvider([
        [_content_chunk("Just answer.")],
    ])
    events = await _collect(loop.run_stream(
        provider=provider,
        **{**_BASE_KWARGS, "policy": RetrievalPolicy.ASSISTIVE, "max_rounds": 1},
    ))
    round_starts = [e for e in events if e.type == "round_start"]
    assert len(round_starts) == 1
    p = round_starts[0].payload
    assert p["phase"] == "final"
    assert p["tool_choice"] == "none"
    assert p["effective_grounded"] is False
    assert p["policy"] == "assistive"


@pytest.mark.asyncio
async def test_round_start_payload_three_rounds_has_followup_phase():
    """policy=GROUNDED, max_rounds=3 → фазы: initial, followup, final."""
    loop = AgentLoop()
    provider = _ScriptedProvider([
        _tool_call_chunks("c0", "search_knowledge", json.dumps({"queries": ["x"]})),
        _tool_call_chunks("c1", "search_knowledge", json.dumps({"queries": ["y"]})),
        [_content_chunk("done")],
    ])
    with patch.object(al, "_execute_search_knowledge", new=AsyncMock(return_value=_FAKE_RESULT)):
        events = await _collect(loop.run_stream(
            provider=provider,
            **{**_BASE_KWARGS, "max_rounds": 3, "policy": RetrievalPolicy.GROUNDED},
        ))

    round_starts = [e for e in events if e.type == "round_start"]
    assert len(round_starts) == 3, [e.type for e in events]
    phases = [r.payload["phase"] for r in round_starts]
    assert phases == ["initial", "followup", "final"]
    tool_choices = [r.payload["tool_choice"] for r in round_starts]
    assert tool_choices == ["required", "auto", "none"]
    grounded = [r.payload["effective_grounded"] for r in round_starts]
    assert grounded == [True, True, False]


@pytest.mark.asyncio
async def test_round_start_payload_legacy_keys_preserved_for_backcompat():
    """Legacy frontend/audit-поля `max_rounds` и `policy` сохраняются в
    payload — дополняем, ничего не удаляем (back-compat)."""
    loop = AgentLoop()
    provider = _ScriptedProvider([
        _tool_call_chunks("c0", "search_knowledge", json.dumps({"queries": ["x"]})),
        [_content_chunk("answer")],
    ])
    with patch.object(al, "_execute_search_knowledge", new=AsyncMock(return_value=_FAKE_RESULT)):
        events = await _collect(loop.run_stream(provider=provider, **_BASE_KWARGS))
    p0 = [e for e in events if e.type == "round_start"][0].payload
    assert "max_rounds" in p0
    assert "policy" in p0
    assert "phase" in p0
    assert "effective_grounded" in p0
    assert "tool_choice" in p0
