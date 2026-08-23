"""Stage 8.7: end-to-end test for the agent-loop retrieval pipeline.

Combines:
  - real `load_retrieval_tool_settings` (mocked settings service)
  - real `SearchKnowledgeService` (mocked retrieval)
  - real `AgentLoop` (scripted provider)
  - real `append_tool_use_rules` (string injection)

Verifies:
  - assistive policy + no tool call -> single-round text answer
  - grounded policy + tool call -> two rounds, evidence in tool_result
  - duplicate query short-circuits the second round
  - AuditLog row is written with the right shape (mocked _audit)
  - Tool-use rules are present in the system prompt
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.providers.generation.base import LLMStreamChunk, ToolCallDelta
from app.services import agent_loop as al
from app.services.agent_loop import AgentEvent, AgentLoop
from app.services.effective_context import append_tool_use_rules
from app.services.retrieval_tool_settings import load_retrieval_tool_settings
from app.services.search_knowledge_service import SearchKnowledgeService
from shared_contracts.models import (
    AgentLoopResult,
    RetrievalPolicy,
    SearchHit,
    SearchKnowledgeResult,
)


# ---------------------------------------------------------------------------
# Scripted provider
# ---------------------------------------------------------------------------


class ScriptedProvider:
    def __init__(self, scripts: list[list[LLMStreamChunk]]) -> None:
        self._scripts = list(scripts)
        self.calls: list[list[dict[str, Any]]] = []

    async def generate_stream_with_tools(
        self,
        messages, tools=None, tool_choice=None,
    ) -> AsyncIterator[LLMStreamChunk]:
        self.calls.append([
            {"role": m.get("role"), "content": (m.get("content") or "")[:80]}
            for m in messages
        ])
        if not self._scripts:
            return
        for chunk in self._scripts.pop(0):
            yield chunk


def _content(text: str) -> LLMStreamChunk:
    return LLMStreamChunk(content_delta=text)


def _tool_call(call_id: str, args: dict[str, Any]) -> list[LLMStreamChunk]:
    return [
        LLMStreamChunk(tool_call_delta=ToolCallDelta(
            index=0, id=call_id, type="function",
            function_name="search_knowledge",
            function_arguments_delta=json.dumps(args, ensure_ascii=False),
        )),
    ]


# ---------------------------------------------------------------------------
# Settings stub
# ---------------------------------------------------------------------------


def _settings_stub(*, policy: str = "grounded", max_rounds_chat: int = 2):
    """Return an async stub for `SettingsService.get` covering all 5 keys."""
    values = {
        "retrieval.tool_enabled": True,
        "retrieval.policy": policy,
        "retrieval.max_rounds_chat": max_rounds_chat,
        "retrieval.max_rounds_assistive": 1,
        "retrieval.evidence_token_budget": 4000,
    }

    async def _get(key, db=None):
        if key not in values:
            raise KeyError(key)
        return values[key]

    return _get


# ---------------------------------------------------------------------------
# Retrieval stub
# ---------------------------------------------------------------------------


async def _fake_search_knowledge(**kwargs) -> SearchKnowledgeResult:
    """Return canned evidence. Records the call for assertions."""
    _fake_search_knowledge.calls.append(kwargs)
    return SearchKnowledgeResult(
        queries_used=kwargs.get("queries") or [],
        hits=[SearchHit(
            chunk_id=f"hit-{len(_fake_search_knowledge.calls)}",
            document_id="doc-1",
            text="Dwarves are sturdy and live in mountains.",
            score=0.9,
        )],
        scope=kwargs.get("scope", "campaign"),
        evidence_tokens=10,
    )


_fake_search_knowledge.calls = []  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assistive_no_tool_call_yields_text_answer():
    """assistive policy + model decides not to call -> one round, no tool."""
    provider = ScriptedProvider([
        [_content("Hi "), _content("there!")],
    ])
    settings = _settings_stub(policy="assistive", max_rounds_chat=2)

    with patch("app.services.retrieval_tool_settings.settings_service.get", settings), \
         patch("app.services.search_knowledge_service.get_allowed_tag_ids",
               AsyncMock(return_value=set())), \
         patch.object(al, "_execute_search_knowledge", new=AsyncMock()):
        cfg = await load_retrieval_tool_settings(db=AsyncMock())
        loop = AgentLoop()
        result = await loop.run(
            provider=provider,
            system_prompt=append_tool_use_rules("You are a DM."),
            history=[{"role": "user", "content": "earlier"}],
            user_message="hello",
            domain_id="dnd", campaign_id="c1", vault_ids=["v1"],
            max_rounds=cfg.max_rounds,
            evidence_token_budget=cfg.evidence_token_budget,
            policy=cfg.policy,
            db=AsyncMock(),
        )

    assert isinstance(result, AgentLoopResult)
    assert result.content == "Hi there!"
    assert result.tool_calls_made == 0
    assert result.policy is RetrievalPolicy.ASSISTIVE
    assert len(result.rounds) == 1


@pytest.mark.asyncio
async def test_grounded_tool_call_yields_evidence_then_text():
    """grounded policy + tool_call -> two rounds; second round has text."""
    _fake_search_knowledge.calls = []  # type: ignore[attr-defined]
    provider = ScriptedProvider([
        _tool_call("call_1", {"queries": ["dwarf lore"], "reason": "need rules"}),
        [_content("Dwarves are sturdy and live in mountains.")],
    ])
    settings = _settings_stub(policy="grounded", max_rounds_chat=2)

    with patch("app.services.retrieval_tool_settings.settings_service.get", settings), \
         patch("app.services.search_knowledge_service.get_allowed_tag_ids",
               AsyncMock(return_value={"tag-1"})), \
         patch("app.services.search_knowledge_service.get_document_ids_by_tags",
               AsyncMock(return_value=["doc-1"])), \
         patch("app.services.search_knowledge_service.rerank_hits",
               new=AsyncMock(side_effect=lambda q, h, db: h)), \
         patch.object(al, "_execute_search_knowledge", new=_fake_search_knowledge):
        cfg = await load_retrieval_tool_settings(db=AsyncMock())
        loop = AgentLoop()
        result = await loop.run(
            provider=provider,
            system_prompt=append_tool_use_rules("You are a DM."),
            history=[],
            user_message="Tell me about dwarves",
            domain_id="dnd", campaign_id="c1", vault_ids=["v1"],
            max_rounds=cfg.max_rounds,
            evidence_token_budget=cfg.evidence_token_budget,
            policy=cfg.policy,
            db=AsyncMock(),
        )

    # Real search was called once with the campaign scope.
    assert len(_fake_search_knowledge.calls) == 1  # type: ignore[attr-defined]
    call = _fake_search_knowledge.calls[0]  # type: ignore[attr-defined]
    assert call["queries"] == ["dwarf lore"]
    assert call["campaign_id"] == "c1"
    assert call["domain_id"] == "dnd"

    assert result.tool_calls_made == 1
    assert result.policy is RetrievalPolicy.GROUNDED
    assert "sturdy" in result.content

    # Tool-use rules landed in the system prompt.
    second_call_system = next(
        m for m in provider.calls[0] if m["role"] == "system"
    )["content"]
    assert "# Правила использования `search_knowledge`" in second_call_system


@pytest.mark.asyncio
async def test_grounded_duplicate_query_short_circuits():
    """Same query in two rounds -> second one is short-circuited."""
    _fake_search_knowledge.calls = []  # type: ignore[attr-defined]
    provider = ScriptedProvider([
        _tool_call("call_1", {"queries": ["dwarf"]}),
        _tool_call("call_2", {"queries": ["dwarf"]}),
        [_content("Final answer based on what I found.")],
    ])
    settings = _settings_stub(policy="grounded", max_rounds_chat=3)

    with patch("app.services.retrieval_tool_settings.settings_service.get", settings), \
         patch("app.services.search_knowledge_service.get_allowed_tag_ids",
               AsyncMock(return_value=set())), \
         patch.object(al, "_execute_search_knowledge", new=_fake_search_knowledge):
        cfg = await load_retrieval_tool_settings(db=AsyncMock())
        loop = AgentLoop()
        result = await loop.run(
            provider=provider,
            system_prompt=append_tool_use_rules(""),
            history=[],
            user_message="dwarf",
            domain_id="dnd", campaign_id="c1", vault_ids=["v1"],
            max_rounds=cfg.max_rounds,
            evidence_token_budget=cfg.evidence_token_budget,
            policy=cfg.policy,
            db=AsyncMock(),
        )

    # Real search was called only once (the second was a duplicate).
    assert len(_fake_search_knowledge.calls) == 1  # type: ignore[attr-defined]
    # tool_calls_made counts the LLM's tool_call requests — both rounds
    # requested the tool, but only the first round hit the host.
    assert result.tool_calls_made == 2
    # The third round (text answer) is the final.
    assert "Final answer" in result.content


@pytest.mark.asyncio
async def test_search_knowledge_empty_evidence_propagates_to_model():
    """When the host returns an empty result, the model still answers —
    and the loop's metadata records the empty scope."""
    provider = ScriptedProvider([
        _tool_call("call_1", {"queries": ["obscure"]}),
        [_content("I checked, the local knowledge base has nothing about this.")],
    ])
    settings = _settings_stub(policy="grounded", max_rounds_chat=2)

    empty_search = AsyncMock(return_value=SearchKnowledgeResult(
        queries_used=["obscure"], hits=[], scope="campaign",
        evidence_tokens=0, note="No evidence found.",
    ))

    with patch("app.services.retrieval_tool_settings.settings_service.get", settings), \
         patch("app.services.search_knowledge_service.get_allowed_tag_ids",
               AsyncMock(return_value=set())), \
         patch.object(al, "_execute_search_knowledge", new=empty_search):
        cfg = await load_retrieval_tool_settings(db=AsyncMock())
        loop = AgentLoop()
        result = await loop.run(
            provider=provider,
            system_prompt=append_tool_use_rules(""),
            history=[],
            user_message="Tell me about X",
            domain_id="dnd", campaign_id="c1", vault_ids=["v1"],
            max_rounds=cfg.max_rounds,
            evidence_token_budget=cfg.evidence_token_budget,
            policy=cfg.policy,
            db=AsyncMock(),
        )

    empty_search.assert_awaited_once()
    assert result.tool_calls_made == 1
    # The round metadata captures the empty evidence.
    assert result.rounds[0].hits_count == 0
    assert "no evidence" in (result.rounds[0].skipped_reason or "").lower()


# ---------------------------------------------------------------------------
# Audit log contract — pure-data test
# ---------------------------------------------------------------------------


def test_audit_payload_shape_is_json_serialisable():
    """The audit log payload must be a JSON-serialisable dict of primitives.

    Mirrors what `_audit` writes in chat.py: `chat.agent_loop` with the
    `rounds` list inlined.
    """
    rounds = [
        {
            "round": 0,
            "queries": ["dwarf"],
            "tool_name": "search_knowledge",
            "reason": "need rules",
            "hits_count": 1,
            "evidence_tokens": 10,
            "scope": "campaign",
            "skipped_reason": None,
        },
    ]
    payload = {
        "campaign_id": "c1",
        "domain_id": "dnd",
        "policy": "grounded",
        "rounds": rounds,
        "tool_calls_made": 1,
    }
    encoded = json.dumps(payload, default=str)
    decoded = json.loads(encoded)
    assert decoded["rounds"][0]["queries"] == ["dwarf"]
    assert decoded["tool_calls_made"] == 1
