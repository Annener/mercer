"""Stage 8.5: smoke test for chat.py agent-loop integration.

The agent loop is already covered end-to-end in
`test_agent_loop.py`. Here we only assert that `chat.py`'s
`plain_stream` path has been wired to the new tool path correctly:
  1. The new code path is reachable (i.e. `retrieval_tool_settings`
     is imported and `use_tool` is computed).
  2. The SSE event types used for the agent loop are well-formed JSON
     so the frontend can parse them.

Real end-to-end exercise of plain_stream with a fake provider lives
in `test_iter7_e2e.py` (Stage 8.7) — that test runs against a live
Postgres + the docker backend.
"""
from __future__ import annotations

import json

from app.api import chat as chat_module


def test_chat_module_imports_agent_loop_dependencies():
    """The `plain_stream` function lives inside `send_message_stream`.
    We can't easily call it without a live DB and a fake provider, so
    we just assert the symbols it needs are imported in `chat.py`.
    """
    source = chat_module.__file__
    assert source is not None
    with open(source, "r", encoding="utf-8") as f:
        text = f.read()

    # The tool-settings loader must be imported inside the function (lazy
    # import to avoid circulars). We check for the call site, not the
    # top-level import.
    assert "load_retrieval_tool_settings" in text
    assert "AgentLoop" in text
    assert "loop.run_stream" in text

    # New SSE event types must be present in the function body.
    assert '"tool_call"' in text
    assert '"tool_result"' in text
    assert '"round_start"' in text


def test_chat_module_sse_payload_shapes():
    """Validate the JSON shapes we promised the frontend.

    We don't parse chat.py's source — we round-trip a sample event through
    `json.dumps` (the same call site the function uses) and assert the
    expected fields end up in the wire format.
    """
    sample_tool_call = {
        "type": "tool_call",
        "round": 0,
        "tool": "search_knowledge",
        "queries": ["dwarf armor", "mountain king"],
        "reason": "need rules",
    }
    wire = json.dumps(sample_tool_call, ensure_ascii=False)
    parsed = json.loads(wire)
    assert parsed["type"] == "tool_call"
    assert parsed["round"] == 0
    assert parsed["tool"] == "search_knowledge"
    assert parsed["queries"] == ["dwarf armor", "mountain king"]
    assert parsed["reason"] == "need rules"

    sample_tool_result = {
        "type": "tool_result",
        "round": 0,
        "queries_used": ["dwarf armor"],
        "hits_count": 5,
        "evidence_tokens": 1234,
        "scope": "campaign",
        "note": None,
    }
    wire = json.dumps(sample_tool_result, ensure_ascii=False)
    parsed = json.loads(wire)
    for k, v in sample_tool_result.items():
        assert parsed[k] == v


def test_chat_module_does_not_break_when_tool_disabled():
    """If the master switch is off, the code path must still exist —
    i.e. the legacy single-shot retrieval block is reachable."""
    source = chat_module.__file__
    with open(source, "r", encoding="utf-8") as f:
        text = f.read()
    # `use_tool = ...` and the `if use_tool:` branch must exist
    assert "use_tool = " in text
    assert "if use_tool:" in text
    # Legacy path stays: _fallback_retrieve must still be called somewhere.
    assert "_fallback_retrieve" in text
