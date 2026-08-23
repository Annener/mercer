"""Stage 8.4: bounded agent loop that drives the LLM ↔ tool cycle.

Public entry point: `AgentLoop.run_stream(...)` returning an async iterator of
`AgentEvent` instances. The chat SSE layer (Stage 8.5) translates these
events into the existing wire format.

Loop contract (spec §12.2):
  - Round 0: `tool_choice='auto'`, model may or may not call the tool.
  - Round N (1 ≤ N < max_rounds): same as round 0, model may call again.
  - Final round: `tool_choice='none'`, model MUST produce a text answer.
  - Same normalised query twice in one turn is treated as a no-op:
    the host returns an empty tool result with `note='duplicate_query'`
    so the model can recognise the dead end.
  - When the model returns only tool_calls and no text content, the host
    keeps going. When the model returns text content, the host streams
    it and exits the loop.
  - `AgentLoopResult` (final dataclass) carries the assembled content +
    per-round metadata + the resolved `policy`.

The loop is provider-agnostic: it only relies on
`GenerationProvider.generate_stream_with_tools`. The legacy
`generate_stream` path is used as a fallback when the provider does not
support tool calls (default-degrade in `GenerationProvider`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.services.search_knowledge_service import search_knowledge_service
from app.services.source_utils import (
    MAX_SOURCES_PER_TOOL_RESULT,
    hits_to_sources,
    sources_to_message_sources,
)
from shared_contracts.models import (
    AgentLoopResult,
    AgentRoundResult,
    LLMAssistantMessage,
    LLMToolCall,
    LLMToolCallFunction,
    LLMToolChoice,
    LLMToolDefinition,
    LLMToolDefinitionFunction,
    LLMToolMessage,
    RetrievalPolicy,
    SearchKnowledgeResult,
    Source,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public tool schema: search_knowledge
# ---------------------------------------------------------------------------


SEARCH_KNOWLEDGE_TOOL = LLMToolDefinition(
    type="function",
    function=LLMToolDefinitionFunction(
        name="search_knowledge",
        description=(
            "Search the local knowledge base (campaign documents and indexed "
            "sources) for evidence relevant to the user's question. Use this "
            "whenever the answer depends on specific campaign facts, lore, "
            "rules, named entities, history, or exact document content that is "
            "not already in the conversation. Do NOT use it for general world "
            "knowledge, casual chit-chat, or questions you can answer from "
            "the system prompt and the recent chat history alone."
        ),
        parameters={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": (
                        "One or more independent search queries. Each query "
                        "should focus on a different facet of the missing "
                        "evidence (e.g. rules, entities, scene constraints)."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Short free-text justification of why this search is "
                        "needed. Helps the user understand the model's reasoning."
                    ),
                },
            },
            "required": ["queries"],
        },
    ),
)


# ---------------------------------------------------------------------------
# AgentEvent — wire-neutral event the SSE layer (Stage 8.5) translates
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AgentEvent:
    """One event in the agent loop stream. UI-agnostic."""

    type: str  # 'round_start' | 'tool_call' | 'tool_result' | 'token' | 'round_end' | 'final' | 'error'
    round: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool argument parsing
# ---------------------------------------------------------------------------


def _parse_tool_arguments(raw: str) -> dict[str, Any]:
    """Parse the LLM-emitted tool-call arguments JSON.

    The model may return invalid JSON; we never want the host to crash on
    that, so we degrade to `{}` and surface the raw text in the error
    payload. The model itself will then see a malformed tool result and
    can reformulate.
    """
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("agent_loop: invalid tool arguments JSON: %r", raw[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_search_queries(call: LLMToolCall) -> tuple[list[str], str]:
    """Pull queries + reason out of a search_knowledge tool call."""
    args = _parse_tool_arguments(call.function.arguments)
    raw_queries = args.get("queries")
    queries: list[str] = []
    if isinstance(raw_queries, list):
        queries = [q for q in raw_queries if isinstance(q, str) and q.strip()]
    reason = args.get("reason", "")
    if not isinstance(reason, str):
        reason = ""
    return queries, reason


def _format_tool_result_text(result: SearchKnowledgeResult) -> str:
    """Compose the user-visible text the model will read as `role=tool`.

    The structured metadata is also embedded as a fenced JSON block so the
    model can reason about scope/hits_count without the host having to
    reformat on the next round.
    """
    parts: list[str] = []
    if result.hits:
        body = "\n\n".join(f"[{i + 1}] {hit.text}" for i, hit in enumerate(result.hits))
        parts.append(body)
    else:
        parts.append("(no evidence found)")
    meta = {
        "queries_used": result.queries_used,
        "scope": result.scope,
        "hits_count": len(result.hits),
        "evidence_tokens": result.evidence_tokens,
    }
    if result.note:
        meta["note"] = result.note
    parts.append(f"\n<!-- meta: {json.dumps(meta, ensure_ascii=False)} -->")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tool execution (host-controlled — model cannot widen scope)
# ---------------------------------------------------------------------------


async def _execute_search_knowledge(
    *,
    queries: list[str],
    domain_id: str | None,
    campaign_id: str | None,
    vault_ids: list[str],
    evidence_token_budget: int,
    db: Any,
) -> SearchKnowledgeResult:
    return await search_knowledge_service.run(
        queries=queries,
        domain_id=domain_id,
        campaign_id=campaign_id,
        vault_ids=vault_ids,
        evidence_token_budget=evidence_token_budget,
        db=db,
    )


# ---------------------------------------------------------------------------
# AgentLoop
# ---------------------------------------------------------------------------


class AgentLoop:
    """Bounded, provider-agnostic agent loop.

    State: stateless across turns. All mutable state is local to one call
    to `run_stream`.
    """

    async def run_stream(
        self,
        *,
        provider: Any,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
        domain_id: str | None,
        campaign_id: str | None,
        vault_ids: list[str],
        max_rounds: int,
        evidence_token_budget: int,
        policy: RetrievalPolicy,
        db: Any,
    ) -> AsyncIterator[AgentEvent]:
        """Drive the LLM ↔ tool cycle and yield AgentEvents.

        The last emitted event is always of type 'final' (or 'error' if the
        provider failed). Content tokens are emitted in 'token' events.
        Tool invocations are surfaced as 'tool_call' + 'tool_result' pairs.
        """
        if max_rounds <= 0:
            # Defensive: a misconfigured policy with zero rounds should not
            # block the user — emit the answer as a single-shot call.
            logger.warning(
                "agent_loop: max_rounds=0, falling back to a single tool-free turn. "
                "policy=%s campaign_id=%s",
                policy,
                campaign_id,
            )
            max_rounds = 1

        tools: list[LLMToolDefinition] = [SEARCH_KNOWLEDGE_TOOL]
        # Normalised queries we've already executed this turn — used to
        # detect duplicates and short-circuit wasted retrieval.
        seen_queries_norm: set[str] = set()
        rounds_meta: list[AgentRoundResult] = []
        tool_calls_made = 0
        final_content_parts: list[str] = []

        # History is appended to messages in place. We start from a fresh
        # messages list with the system prompt + history + user message.
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for entry in history:
            messages.append({"role": entry["role"], "content": entry["content"]})
        messages.append({"role": "user", "content": user_message})

        for round_idx in range(max_rounds):
            is_final_round = round_idx == max_rounds - 1
            tool_choice = (
                LLMToolChoice(mode="none")
                if is_final_round
                else LLMToolChoice(mode="auto")
            )

            yield AgentEvent(
                type="round_start",
                round=round_idx,
                payload={
                    "max_rounds": max_rounds,
                    "policy": policy.value,
                },
            )

            # Drive the model for one round.
            buffer_content: list[str] = []
            tool_call_deltas: dict[int, dict[str, Any]] = {}

            try:
                async for chunk in provider.generate_stream_with_tools(
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                ):
                    if chunk.content_delta:
                        buffer_content.append(chunk.content_delta)
                        yield AgentEvent(
                            type="token",
                            round=round_idx,
                            payload={
                                "content": chunk.content_delta,
                            },
                        )

                    if chunk.tool_call_delta is not None:
                        d = chunk.tool_call_delta
                        slot = tool_call_deltas.setdefault(
                            d.index,
                            {
                                "id": d.id,
                                "type": d.type or "function",
                                "name": None,
                                "arguments": [],
                            },
                        )
                        if d.id is not None:
                            slot["id"] = d.id
                        if d.type is not None:
                            slot["type"] = d.type
                        if d.function_name is not None:
                            slot["name"] = d.function_name
                        if d.function_arguments_delta:
                            slot["arguments"].append(d.function_arguments_delta)
            except Exception as exc:
                logger.exception(
                    "agent_loop: provider error on round=%d, policy=%s",
                    round_idx,
                    policy,
                )
                yield AgentEvent(
                    type="error",
                    round=round_idx,
                    payload={
                        "message": str(exc),
                    },
                )
                return

            # Materialise deltas into full LLMToolCall objects.
            full_calls: list[LLMToolCall] = []
            for idx in sorted(tool_call_deltas):
                slot = tool_call_deltas[idx]
                arguments = "".join(slot["arguments"])
                # Skip calls missing required fields — degraded model output.
                if not slot["id"] or not slot["name"]:
                    logger.warning(
                        "agent_loop: dropping incomplete tool_call at index=%d (id=%r name=%r)",
                        idx,
                        slot["id"],
                        slot["name"],
                    )
                    continue
                full_calls.append(
                    LLMToolCall(
                        id=slot["id"],
                        type="function",
                        index=idx,
                        function=LLMToolCallFunction(
                            name=slot["name"],
                            arguments=arguments,
                        ),
                    )
                )

            round_content = "".join(buffer_content)

            if not full_calls:
                # Model answered with text. This is the terminal state.
                final_content_parts.append(round_content)
                rounds_meta.append(
                    AgentRoundResult(
                        round=round_idx,
                        queries=[],
                        tool_name=None,
                        reason=None,
                        hits_count=0,
                        evidence_tokens=0,
                        scope="domain",  # placeholder; retrieval didn't run
                    )
                )
                yield AgentEvent(
                    type="round_end",
                    round=round_idx,
                    payload={
                        "content_chars": len(round_content),
                        "finish_reason": "stop",
                    },
                )
                break

            # Round produced tool_calls — append the assistant message with
            # those tool_calls exactly as the OpenAI schema requires.
            assistant_msg = LLMAssistantMessage(
                role="assistant",
                content=round_content,
                tool_calls=full_calls,
            )
            messages.append(assistant_msg.model_dump(exclude_none=True))

            # Execute each tool call. Per spec, the host controls scope;
            # the model cannot widen or narrow it.
            for call in full_calls:
                if call.function.name == SEARCH_KNOWLEDGE_TOOL.function.name:
                    queries, reason = _extract_search_queries(call)
                    yield AgentEvent(
                        type="tool_call",
                        round=round_idx,
                        payload={
                            "tool": call.function.name,
                            "queries": queries,
                            "reason": reason,
                        },
                    )

                    # Per spec §12.2: don't repeat a normalised query.
                    new_norm = {q.strip().lower() for q in queries}
                    duplicate = new_norm & seen_queries_norm
                    seen_queries_norm.update(new_norm)

                    if duplicate and not new_norm - duplicate:
                        # Every query in this call is a duplicate.
                        result = SearchKnowledgeResult(
                            queries_used=[],
                            hits=[],
                            scope="empty",
                            evidence_tokens=0,
                            note=(
                                "duplicate_query: the same query was already "
                                "executed earlier in this turn. Formulate a "
                                "different query to find missing evidence."
                            ),
                        )
                        tool_round_meta = AgentRoundResult(
                            round=round_idx,
                            queries=queries,
                            tool_name=call.function.name,
                            reason=reason or None,
                            hits_count=0,
                            evidence_tokens=0,
                            scope="empty",
                            skipped_reason="duplicate_query",
                        )
                    else:
                        result = await _execute_search_knowledge(
                            queries=queries,
                            domain_id=domain_id,
                            campaign_id=campaign_id,
                            vault_ids=vault_ids,
                            evidence_token_budget=evidence_token_budget,
                            db=db,
                        )
                        round_sources: list[Source] = hits_to_sources(
                            result.hits,
                            cap=MAX_SOURCES_PER_TOOL_RESULT,
                        )
                        tool_round_meta = AgentRoundResult(
                            round=round_idx,
                            queries=result.queries_used,
                            tool_name=call.function.name,
                            reason=reason or None,
                            hits_count=len(result.hits),
                            evidence_tokens=result.evidence_tokens,
                            scope=result.scope,
                            skipped_reason=result.note if not result.hits else None,
                            sources=sources_to_message_sources(round_sources),
                        )

                    tool_calls_made += 1
                    rounds_meta.append(tool_round_meta)

                    # Прокидываем sources в tool_result event — чат-слой
                    # аггрегирует их и эмитит финальный `sources` event.
                    yield AgentEvent(
                        type="tool_result",
                        round=round_idx,
                        payload={
                            "tool": call.function.name,
                            "queries_used": result.queries_used,
                            "hits_count": len(result.hits),
                            "evidence_tokens": result.evidence_tokens,
                            "scope": result.scope,
                            "note": result.note,
                            "sources": [
                                s.model_dump(mode="json")
                                for s in hits_to_sources(
                                    result.hits,
                                    cap=MAX_SOURCES_PER_TOOL_RESULT,
                                )
                            ],
                        },
                    )

                    # Append role=tool message for this call.
                    tool_text = _format_tool_result_text(result)
                    messages.append(
                        LLMToolMessage(
                            role="tool",
                            tool_call_id=call.id,
                            content=tool_text,
                        ).model_dump(exclude_none=True)
                    )
                else:
                    # Unknown tool — surface a structured error and stop.
                    logger.warning(
                        "agent_loop: model requested unknown tool %r",
                        call.function.name,
                    )
                    yield AgentEvent(
                        type="error",
                        round=round_idx,
                        payload={
                            "message": f"unknown tool: {call.function.name}",
                        },
                    )
                    rounds_meta.append(
                        AgentRoundResult(
                            round=round_idx,
                            queries=[],
                            tool_name=call.function.name,
                            reason=None,
                            hits_count=0,
                            evidence_tokens=0,
                            scope="domain",
                            skipped_reason="unknown_tool",
                        )
                    )
                    break

            yield AgentEvent(
                type="round_end",
                round=round_idx,
                payload={
                    "finish_reason": "tool_calls",
                    "tool_calls_in_round": len(full_calls),
                },
            )
            logger.info(
                "AGENT_LOOP_ROUND round=%d tool_calls=%d",
                round_idx,
                len(full_calls),
            )

        final_content = "".join(final_content_parts)
        logger.info(
            "AGENT_LOOP_DONE campaign_id=%s domain_id=%s policy=%s "
            "rounds=%d tool_calls=%d content_chars=%d",
            campaign_id,
            domain_id,
            policy.value,
            len(rounds_meta),
            tool_calls_made,
            len(final_content),
        )
        yield AgentEvent(
            type="final",
            payload={
                "content_chars": len(final_content),
                "rounds": [r.model_dump() for r in rounds_meta],
                "tool_calls_made": tool_calls_made,
            },
        )

    async def run(
        self,
        **kwargs: Any,
    ) -> AgentLoopResult:
        """Non-streaming convenience wrapper around `run_stream`.

        Collects content from 'token' events and aggregates round metadata
        from 'final' events. Useful for tests and for non-streaming endpoints
        (e.g. background jobs) that don't need incremental updates.
        """
        content_parts: list[str] = []
        rounds_meta: list[AgentRoundResult] = []
        tool_calls_made = 0
        policy = kwargs.get("policy", RetrievalPolicy.ASSISTIVE)

        async for event in self.run_stream(**kwargs):
            if event.type == "token":
                content_parts.append(event.payload.get("content", ""))
            elif event.type == "final":
                rounds_meta = [
                    AgentRoundResult.model_validate(r)
                    for r in event.payload.get("rounds", [])
                ]
                tool_calls_made = event.payload.get("tool_calls_made", 0)

        return AgentLoopResult(
            content="".join(content_parts),
            rounds=rounds_meta,
            tool_calls_made=tool_calls_made,
            policy=policy,
        )


__all__ = [
    "SEARCH_KNOWLEDGE_TOOL",
    "AgentEvent",
    "AgentLoop",
]
