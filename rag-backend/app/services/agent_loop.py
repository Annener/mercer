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
from app.services.update_mode_store import update_mode_store
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


UPDATE_SCENE_STATE_TOOL = LLMToolDefinition(
    type="function",
    function=LLMToolDefinitionFunction(
        name="update_scene_state",
        description=(
            "Update the chat's inline scene-state memory with a small JSON "
            "patch. Use this to persist short-lived context that should "
            "survive between turns but is NOT a permanent campaign fact "
            "(e.g. current location, NPCs in the room, active sub-plot, "
            "user's last query). The patch is merged into the existing "
            "scene-state; pass `null` to clear a key. Do NOT use this for "
            "long-term facts, lore, rules, or campaign state — for those, "
            "use `propose_context_update` (when available) or ask the user "
            "to run the dedicated Update Mode flow."
        ),
        parameters={
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": (
                        "JSON object whose keys are merged into the chat's "
                        "scene-state. Pass `{\"key\": null}` to delete a key, "
                        "or `{\"key\": \"value\"}` to set/overwrite it."
                    ),
                    "additionalProperties": True,
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Short free-text justification of why this scene-state "
                        "update is needed. Helps the user understand the "
                        "model's reasoning."
                    ),
                },
            },
            "required": ["patch"],
        },
    ),
)


# Sprint 3: tool that the model uses to propose a context update.
# The proposal is host-validated and stored as a Review session in Redis
# — the user must explicitly accept/reject via the existing Update Mode UI
# before anything is applied.
PROPOSE_CONTEXT_UPDATE_TOOL = LLMToolDefinition(
    type="function",
    function=LLMToolDefinitionFunction(
        name="propose_context_update",
        description=(
            "Propose a context update for the current campaign. Use this "
            "when the user has expressed a long-term fact, decision, rule, "
            "NPC, location, or other durable piece of information that "
            "should persist across chat turns. The proposal is shown to the "
            "user for review; nothing is applied without their explicit "
            "approval.\n\n"
            "Existing field keys are listed in the Campaign State block of "
            "your system prompt (e.g. `current_status (key=current_status, "
            "mode=single)`). Copy the `key` EXACTLY when referencing an "
            "existing field in `field_changes[].key` or "
            "`state_patch[].field_key`. mode is immutable for update_field.\n\n"
            "The proposal can include up to four sections (submit only the "
            "ones that apply):\n"
            "1. field_changes[] — schema operations (create_field / "
            "update_field). Each item REQUIRED: operation, key, label, "
            "mode. Optional: description, enabled, display_order.\n"
            "2. state_patch[] — value operations on existing fields. Each "
            "item REQUIRED: type, field_key, reason. `type` must be one of: "
            "replace_single, clear_single, add_list_item, update_list_item, "
            "resolve_list_item, remove_list_item. `text` is REQUIRED (non-"
            "empty) for replace_single / update_list_item / add_list_item. "
            "`item_key` is REQUIRED for update_list_item / "
            "resolve_list_item / remove_list_item.\n"
            "3. file_changes[] — edits to .md documents in the vault. Each "
            "item REQUIRED: action (update|create), operation, "
            "description. `document_id` required for action=update; "
            "`parent_document_id` and `suggested_filename` optional for "
            "action=create.\n"
            "4. confidence (0..1) — required. Below 0.5 the host rejects "
            "the entire proposal.\n"
            "5. reason (string) — required, surfaced in the UI.\n\n"
            "Without all required fields per item the host rejects the "
            "entire proposal and nothing is applied."
        ),
        parameters={
            "type": "object",
            "properties": {
                "field_changes": {
                    "type": "array",
                    "description": (
                        "Schema operations on Campaign State fields. "
                        "Each item: {operation, key, label, description, "
                        "mode, enabled, display_order}. Use only when you "
                        "want to change the schema (add a new field, or "
                        "edit label/description/enabled/display_order of "
                        "an existing field). For setting values in existing "
                        "fields use state_patch instead."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["create_field", "update_field"],
                                "description": (
                                    "create_field adds a new field; "
                                    "update_field edits an existing field "
                                    "(mode is IMMUTABLE — drop the proposal "
                                    "if you need to change mode)."
                                ),
                            },
                            "key": {
                                "type": "string",
                                "pattern": r"^[a-z][a-z0-9_]*$",
                                "maxLength": 64,
                                "description": (
                                    "Stable technical identifier: lowercase "
                                    "+ digits + underscore, starts with a "
                                    "letter. Immutable after creation."
                                ),
                            },
                            "label": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 256,
                            },
                            "description": {
                                "type": "string",
                                "maxLength": 8192,
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["single", "list"],
                                "description": (
                                    "Storage shape. 'single' = free-text "
                                    "value, 'list' = ordered checklist of "
                                    "items with stable item_keys."
                                ),
                            },
                            "enabled": {
                                "type": "boolean",
                                "default": True,
                            },
                            "display_order": {
                                "type": "integer",
                                "minimum": 0,
                                "default": 1000,
                            },
                        },
                        "required": ["operation", "key", "label", "mode"],
                        "additionalProperties": False,
                    },
                },
                "state_patch": {
                    "type": "array",
                    "description": (
                        "Value operations on existing Campaign State "
                        "fields. Each item: {type, field_key, item_key?, "
                        "text?, reason, source_refs?}. Use to record "
                        "specific facts into fields created by this "
                        "proposal or already present in the snapshot."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "replace_single",
                                    "clear_single",
                                    "add_list_item",
                                    "update_list_item",
                                    "resolve_list_item",
                                    "remove_list_item",
                                ],
                                "description": (
                                    "Operation kind. replace_single/"
                                    "clear_single only on mode=single fields; "
                                    "add_list_item/update_list_item/"
                                    "resolve_list_item/remove_list_item "
                                    "only on mode=list fields."
                                ),
                            },
                            "field_key": {
                                "type": "string",
                                "description": (
                                    "Key of an existing field, or a key "
                                    "created in this proposal via "
                                    "field_changes."
                                ),
                            },
                            "item_key": {
                                "type": "string",
                                "description": (
                                    "Required for update_list_item/"
                                    "resolve_list_item/remove_list_item."
                                ),
                            },
                            "text": {
                                "type": "string",
                                "description": (
                                    "Required (non-empty) for "
                                    "replace_single/update_list_item/"
                                    "add_list_item."
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 1024,
                            },
                            "source_refs": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["type", "field_key", "reason"],
                        "additionalProperties": False,
                    },
                },
                "file_changes": {
                    "type": "array",
                    "description": (
                        "Edits to .md documents in the vault. Each item is "
                        "an UpdateModeIntent. Use only for factual updates "
                        "to indexed files."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "change_id": {"type": "string"},
                            "action": {
                                "type": "string",
                                "enum": ["update", "create"],
                            },
                            "document_id": {
                                "type": "string",
                                "description": (
                                    "Required for action=update. Must be "
                                    "an indexed .md document ID provided "
                                    "in the context."
                                ),
                            },
                            "parent_document_id": {
                                "type": "string",
                                "description": (
                                    "For action=create: optional parent "
                                    "document; new file is created next "
                                    "to it."
                                ),
                            },
                            "description": {"type": "string"},
                            "operation": {
                                "type": "string",
                                "enum": [
                                    "append_after_section",
                                    "append_to_file",
                                    "replace_unique_text",
                                    "create_file",
                                ],
                            },
                            "anchor": {"type": "object"},
                            "suggested_filename": {
                                "type": "string",
                                "maxLength": 512,
                            },
                            "content": {"type": "string"},
                        },
                        "required": ["action", "operation", "description"],
                        "additionalProperties": False,
                    },
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "0..1 — your confidence that the proposed change "
                        "is justified. 0.5+ is recommended; below 0.5 the "
                        "host will reject."
                    ),
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Short free-text explanation of why this update is "
                        "proposed. Surfaced in the UI."
                    ),
                },
                "source_message_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "IDs of user messages that justify the proposal. "
                        "Used for audit trail."
                    ),
                },
                "review_summary": {
                    "type": "string",
                    "description": (
                        "One-line summary shown in the review card."
                    ),
                },
            },
            "required": ["confidence", "reason"],
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
# update_scene_state — host-controlled chat-scoped memory tool
# ---------------------------------------------------------------------------


# Максимум ключей в одном patch — защищает от спама и раздувания metadata.
_SCENE_STATE_PATCH_MAX_KEYS = 16


def _extract_scene_state_patch(call: LLMToolCall) -> tuple[dict[str, Any], str]:
    """Pull patch + reason out of an update_scene_state tool call.

    Patch нормализуется:
    - не dict → пустой dict
    - больше _SCENE_STATE_PATCH_MAX_KEYS ключей → отбрасывается хвост
      (модель может это увидеть в tool_result и скорректировать)

    `null`-значения сохраняются как явный маркер удаления ключа.
    """
    args = _parse_tool_arguments(call.function.arguments)
    raw_patch = args.get("patch")
    if not isinstance(raw_patch, dict):
        raw_patch = {}
    patch: dict[str, Any] = {}
    for i, (k, v) in enumerate(raw_patch.items()):
        if not isinstance(k, str) or not k:
            continue
        if i >= _SCENE_STATE_PATCH_MAX_KEYS:
            logger.warning(
                "agent_loop: scene_state patch truncated to %d keys (model sent %d)",
                _SCENE_STATE_PATCH_MAX_KEYS,
                len(raw_patch),
            )
            break
        patch[k] = v
    reason = args.get("reason", "")
    if not isinstance(reason, str):
        reason = ""
    return patch, reason


_SCENE_STATE_OK_STATUS = "ok"
_SCENE_STATE_ERROR_STATUS = "error"


async def _execute_update_scene_state(
    *,
    chat_id: str | None,
    patch: dict[str, Any],
    db: Any,
) -> dict[str, Any]:
    """Merge patch into Chat.metadata['scene_state'].explicit.

    Phase 2b: LLM-driven scene state lives under ``scene_state.explicit``;
    the ``scene_state.drift`` sub-space is owned by DriftDetector and never
    touched from here. Persistence is delegated to
    ``context_engine.scene_memory.merge_explicit``.

    Returns a dict shaped like a SearchKnowledgeResult-style envelope so the
    rest of the loop can reuse `_format_tool_result_text`-style plumbing.
    Keys:
      - status: 'ok' | 'error'
      - note:  free-text for the model
      - scene_state: the post-merge dict (only on success)
      - applied_keys: list of keys that were changed
      - removed_keys: list of keys that were deleted (value was None)
    """
    if not chat_id:
        return {
            "status": _SCENE_STATE_ERROR_STATUS,
            "note": "chat_id is required for update_scene_state",
            "scene_state": {},
            "applied_keys": [],
            "removed_keys": [],
        }
    if not patch:
        return {
            "status": _SCENE_STATE_OK_STATUS,
            "note": "patch was empty; no changes applied",
            "scene_state": {},
            "applied_keys": [],
            "removed_keys": [],
        }

    try:
        from app.services.context_engine.scene_memory import merge_explicit
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_loop: failed to import merge_explicit: %s", exc
        )
        return {
            "status": _SCENE_STATE_ERROR_STATUS,
            "note": f"scene_state backend unavailable: {exc}",
            "scene_state": {},
            "applied_keys": [],
            "removed_keys": [],
        }

    # Compute applied/removed keys for the model-facing envelope BEFORE
    # the merge so we can describe what changed. merge_explicit handles
    # legacy migration (flat scene_state → {explicit, drift}) internally.
    try:
        from app.services.context_engine.scene_memory import read_scene_state

        before = await read_scene_state(chat_id, db)
        before_explicit = (before.get("explicit") or {}) if isinstance(before, dict) else {}
        legacy_flat = (
            isinstance(before, dict)
            and before
            and "explicit" not in before
            and "drift" not in before
        )
    except Exception:
        before_explicit = {}
        legacy_flat = False

    applied: list[str] = []
    removed: list[str] = []
    for key, value in patch.items():
        if not isinstance(key, str) or not key:
            continue
        if value is None:
            baseline = set(before_explicit.keys()) if not legacy_flat else set(before.keys())
            if key in baseline:
                removed.append(key)
        else:
            applied.append(key)

    try:
        merged_scene = await merge_explicit(chat_id, patch, db)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_loop: merge_explicit failed chat_id=%s: %s", chat_id, exc
        )
        return {
            "status": _SCENE_STATE_ERROR_STATUS,
            "note": f"failed to persist scene_state: {exc}",
            "scene_state": {},
            "applied_keys": [],
            "removed_keys": [],
        }

    logger.info(
        "agent_loop: scene_state.explicit updated chat_id=%s applied=%s removed=%s",
        chat_id,
        applied,
        removed,
    )
    return {
        "status": _SCENE_STATE_OK_STATUS,
        "note": (
            f"applied {len(applied)} key(s), removed {len(removed)} key(s)"
            if applied or removed
            else "no-op (patch was a no-op after merge)"
        ),
        "scene_state": merged_scene,
        "applied_keys": applied,
        "removed_keys": removed,
    }


# ---------------------------------------------------------------------------
# propose_context_update — model-driven campaign context updates
# ---------------------------------------------------------------------------


# Min confidence below which we drop the proposal entirely (UI never sees it).
PROPOSAL_MIN_CONFIDENCE = 0.5


def _extract_proposal(call: LLMToolCall):
    """Pull proposal fields out of a propose_context_update tool call.

    Returns (proposal_or_None, reason_str, error_str_or_None). On any
    structural error we return (None, "", "...") so the host can return a
    tool_result to the model and continue.
    """
    args = _parse_tool_arguments(call.function.arguments)
    if not isinstance(args, dict):
        return None, "", "tool arguments must be a JSON object"

    field_changes = args.get("field_changes") or []
    state_patch = args.get("state_patch") or []
    file_changes = args.get("file_changes") or []

    if not isinstance(field_changes, list):
        return None, "", "field_changes must be a list"
    if not isinstance(state_patch, list):
        return None, "", "state_patch must be a list"
    if not isinstance(file_changes, list):
        return None, "", "file_changes must be a list"

    confidence = args.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        return None, "", "confidence must be a number"
    confidence = float(confidence)

    reason = args.get("reason", "")
    if not isinstance(reason, str):
        reason = ""
    review_summary = args.get("review_summary", "")
    if not isinstance(review_summary, str):
        review_summary = ""
    source_message_ids = args.get("source_message_ids", [])
    if not isinstance(source_message_ids, list):
        source_message_ids = []

    return {
        "field_changes": field_changes,
        "state_patch": state_patch,
        "file_changes": file_changes,
        "confidence": confidence,
        "reason": reason,
        "review_summary": review_summary,
        "source_message_ids": [
            str(x) for x in source_message_ids if isinstance(x, (str, int))
        ],
    }, reason, None


async def _execute_propose_context_update(
    *,
    chat_id: str | None,
    campaign_id: str | None,
    db: Any,
    redis: Any | None,
    proposal_dict: dict[str, Any],
) -> dict[str, Any]:
    """Validate proposal + create Update Mode session via start_from_proposal.

    Never raises. Returns a dict shaped like other tool_results.
    """
    if not chat_id:
        return {
            "status": "error",
            "note": "chat_id is required for propose_context_update",
        }
    if not campaign_id:
        return {
            "status": "error",
            "note": "campaign_id is required for propose_context_update",
        }
    if redis is None:
        return {
            "status": "error",
            "note": "redis is not available; cannot store proposal",
        }
    if proposal_dict["confidence"] < PROPOSAL_MIN_CONFIDENCE:
        return {
            "status": "rejected",
            "note": (
                f"confidence {proposal_dict['confidence']:.2f} is below the "
                f"minimum {PROPOSAL_MIN_CONFIDENCE}; not surfaced to the user"
            ),
        }

    # Validate + build the typed proposal.
    from shared_contracts.models import (
        ContextFieldChange,
        ContextUpdateProposal,
    )
    try:
        proposal = ContextUpdateProposal(
            field_changes=[
                ContextFieldChange.model_validate(fc)
                for fc in proposal_dict["field_changes"]
            ],
            state_patch=proposal_dict["state_patch"],
            file_changes=proposal_dict["file_changes"],
            confidence=proposal_dict["confidence"],
            reason=proposal_dict["reason"],
            source_message_ids=proposal_dict["source_message_ids"],
            review_summary=proposal_dict["review_summary"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_loop: propose_context_update invalid proposal: %s", exc
        )
        return {
            "status": "error",
            "note": f"proposal validation failed: {exc}",
        }

    # Empty proposal — nothing to do.
    if (
        not proposal.field_changes
        and not proposal.state_patch
        and not proposal.file_changes
    ):
        return {
            "status": "skipped",
            "note": "proposal was empty; nothing to review",
        }

    # Create session via executor.start_from_proposal.
    # We need an indexer_client for the executor. If we don't have one
    # wired in, we still proceed — file_changes won't resolve but the
    # session will be created with state+schema ops.
    from app.services.indexer_client import (
        indexer_client,
    )
    from app.services.update_mode_executor import (
        UpdateModeExecutor,
    )

    executor = UpdateModeExecutor(
        db=db,
        store=update_mode_store,  # imported below at module level
        indexer_client=indexer_client,
    )

    try:
        session = await executor.start_from_proposal(
            chat_id=chat_id, redis=redis, proposal=proposal
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_loop: propose_context_update start_from_proposal failed: %s",
            exc,
        )
        return {
            "status": "error",
            "note": f"failed to create proposal session: {exc}",
        }

    return {
        "status": "ok",
        "session_id": session.session_id,
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
        "field_changes_count": len(proposal.field_changes),
        "state_patch_count": len(proposal.state_patch),
        "file_changes_count": len(session.changes),
        "note": (
            f"proposal created with {len(proposal.field_changes)} field_change(s), "
            f"{len(proposal.state_patch)} state_patch op(s), "
            f"{len(session.changes)} file_change(s); awaiting user review"
        ),
    }


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
        chat_id: str | None = None,
        vault_ids: list[str],
        max_rounds: int,
        evidence_token_budget: int,
        policy: RetrievalPolicy,
        effective_grounded: bool | None = None,
        db: Any,
        context_update_mode_enabled: bool = False,
        redis: Any | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Drive the LLM ↔ tool cycle and yield AgentEvents.

        The last emitted event is always of type 'final' (or 'error' if the
        provider failed). Content tokens are emitted in 'token' events.
        Tool invocations are surfaced as 'tool_call' + 'tool_result' pairs.

        `chat_id` is required when the agent exposes tools that mutate chat
        state (e.g. `update_scene_state`). When `None`, scene-state tools are
        still registered but host execution will return a structured error.

        `context_update_mode_enabled` (Sprint 3) controls whether the
        `propose_context_update` tool is registered. Requires a campaign_id
        (proposals without an active campaign don't make sense) AND a
        `redis` client (the proposal is stored in Redis as a Review session).

        `effective_grounded` is a per-call override for whether round 0
        should force a tool call. When `None` (default), falls back to the
        `policy` argument (i.e. global PlatformSetting `retrieval.policy`).
        When set explicitly, controls the tool_choice for round 0 regardless
        of the global policy. Subsequent rounds always use `tool_choice='auto'`
        so the model may finish answering before exhausting all rounds.
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

        tools: list[LLMToolDefinition] = [
            SEARCH_KNOWLEDGE_TOOL,
            UPDATE_SCENE_STATE_TOOL,
        ]
        if (
            context_update_mode_enabled
            and campaign_id
            and redis is not None
        ):
            tools.append(PROPOSE_CONTEXT_UPDATE_TOOL)
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
            if is_final_round:
                # Final round — модель обязана дать текстовый ответ.
                tool_choice = LLMToolChoice(mode="none")
            else:
                # Resolve effective "must-call-tool" predicate for round 0.
                # Per-chat override (`effective_grounded`) takes precedence
                # over the global PlatformSetting `policy`. When neither is
                # supplied, default to grounded (legacy behaviour).
                if effective_grounded is not None:
                    force_tool_round_zero = effective_grounded
                else:
                    force_tool_round_zero = policy == RetrievalPolicy.GROUNDED
                if round_idx == 0 and force_tool_round_zero:
                    # Round 0, tool_choice=required — модель ОБЯЗАНА вызвать
                    # хотя бы один tool перед тем, как писать ответ
                    # (см. §12.1 спецификации). Дальнейшие раунды остаются
                    # auto: модель может добрать evidence или начать отвечать.
                    tool_choice = LLMToolChoice(mode="required")
                else:
                    tool_choice = LLMToolChoice(mode="auto")

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
                elif call.function.name == UPDATE_SCENE_STATE_TOOL.function.name:
                    patch, reason = _extract_scene_state_patch(call)
                    yield AgentEvent(
                        type="tool_call",
                        round=round_idx,
                        payload={
                            "tool": call.function.name,
                            "patch": patch,
                            "reason": reason,
                        },
                    )

                    scene_result = await _execute_update_scene_state(
                        chat_id=chat_id,
                        patch=patch,
                        db=db,
                    )

                    tool_calls_made += 1
                    rounds_meta.append(
                        AgentRoundResult(
                            round=round_idx,
                            queries=[],
                            tool_name=call.function.name,
                            reason=reason or None,
                            hits_count=0,
                            evidence_tokens=0,
                            scope="domain",
                            skipped_reason=(
                                None
                                if scene_result["status"] == _SCENE_STATE_OK_STATUS
                                else scene_result.get("note")
                            ),
                        )
                    )

                    yield AgentEvent(
                        type="tool_result",
                        round=round_idx,
                        payload={
                            "tool": call.function.name,
                            "status": scene_result["status"],
                            "applied_keys": scene_result["applied_keys"],
                            "removed_keys": scene_result["removed_keys"],
                            "note": scene_result["note"],
                        },
                    )

                    messages.append(
                        LLMToolMessage(
                            role="tool",
                            tool_call_id=call.id,
                            content=json.dumps(
                                {
                                    "status": scene_result["status"],
                                    "applied_keys": scene_result["applied_keys"],
                                    "removed_keys": scene_result["removed_keys"],
                                    "note": scene_result["note"],
                                },
                                ensure_ascii=False,
                            ),
                        ).model_dump(exclude_none=True)
                    )
                elif call.function.name == PROPOSE_CONTEXT_UPDATE_TOOL.function.name:
                    proposal_dict, reason, parse_err = _extract_proposal(call)
                    if parse_err is not None or proposal_dict is None:
                        tool_result_payload = {
                            "tool": call.function.name,
                            "status": "error",
                            "note": parse_err or "invalid proposal",
                        }
                        yield AgentEvent(
                            type="tool_call",
                            round=round_idx,
                            payload={
                                "tool": call.function.name,
                                "reason": reason,
                            },
                        )
                        yield AgentEvent(
                            type="tool_result",
                            round=round_idx,
                            payload=tool_result_payload,
                        )
                        messages.append(
                            LLMToolMessage(
                                role="tool",
                                tool_call_id=call.id,
                                content=json.dumps(
                                    tool_result_payload, ensure_ascii=False
                                ),
                            ).model_dump(exclude_none=True)
                        )
                        tool_calls_made += 1
                        rounds_meta.append(
                            AgentRoundResult(
                                round=round_idx,
                                queries=[],
                                tool_name=call.function.name,
                                reason=reason or None,
                                hits_count=0,
                                evidence_tokens=0,
                                scope="domain",
                                skipped_reason=parse_err,
                            )
                        )
                        continue

                    yield AgentEvent(
                        type="tool_call",
                        round=round_idx,
                        payload={
                            "tool": call.function.name,
                            "confidence": proposal_dict["confidence"],
                            "field_changes_count": len(proposal_dict["field_changes"]),
                            "state_patch_count": len(proposal_dict["state_patch"]),
                            "file_changes_count": len(proposal_dict["file_changes"]),
                            "reason": reason,
                        },
                    )

                    propose_result = await _execute_propose_context_update(
                        chat_id=chat_id,
                        campaign_id=campaign_id,
                        db=db,
                        redis=redis,
                        proposal_dict=proposal_dict,
                    )

                    tool_calls_made += 1
                    rounds_meta.append(
                        AgentRoundResult(
                            round=round_idx,
                            queries=[],
                            tool_name=call.function.name,
                            reason=reason or None,
                            hits_count=0,
                            evidence_tokens=0,
                            scope="domain",
                            skipped_reason=(
                                None
                                if propose_result["status"] == "ok"
                                else propose_result.get("note")
                            ),
                        )
                    )

                    yield AgentEvent(
                        type="tool_result",
                        round=round_idx,
                        payload={
                            "tool": call.function.name,
                            "status": propose_result["status"],
                            "session_id": propose_result.get("session_id"),
                            "field_changes_count": propose_result.get("field_changes_count"),
                            "state_patch_count": propose_result.get("state_patch_count"),
                            "file_changes_count": propose_result.get("file_changes_count"),
                            "note": propose_result["note"],
                        },
                    )

                    messages.append(
                        LLMToolMessage(
                            role="tool",
                            tool_call_id=call.id,
                            content=json.dumps(
                                {
                                    "status": propose_result["status"],
                                    "session_id": propose_result.get("session_id"),
                                    "note": propose_result["note"],
                                },
                                ensure_ascii=False,
                            ),
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
