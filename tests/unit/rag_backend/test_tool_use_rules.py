"""Stage 8.6: tests for the tool-use rule injection in `effective_context`.

The system-prompt augmentation is the host's way of telling the model
how to use `search_knowledge`. The contract:
  - Rules are appended after the existing system prompt.
  - When there's no system prompt, the rules start from the top.
  - The rules mention the spec's required triggers (facts, lore,
    named entities, exact document content) and required avoidances
    (no general knowledge, no hallucination, no duplicate queries).
"""
from __future__ import annotations

from app.services.effective_context import append_tool_use_rules


def test_rules_are_appended_to_non_empty_system_prompt():
    out = append_tool_use_rules("You are a DM.")
    assert out.startswith("You are a DM.")
    # Rules follow the system prompt with a header marker.
    assert "# Правила использования `search_knowledge`" in out
    # The system prompt and the rules must be visually separated.
    assert "You are a DM." in out
    # The rules block must appear AFTER the system prompt.
    assert out.index("You are a DM.") < out.index("# Правила использования")


def test_rules_handle_empty_system_prompt():
    out = append_tool_use_rules("")
    # When the input is empty, the rules must be returned cleanly (no leading
    # blank line, no double newlines at the top).
    assert out.startswith("# Правила использования `search_knowledge`")
    assert not out.startswith("\n")


def test_rules_call_out_must_use_triggers():
    """The rules must explicitly enumerate the must-use triggers from §12.1."""
    out = append_tool_use_rules("")
    triggers = [
        "фактов кампании",
        "именованных сущностей",
        "точного содержания документов",
    ]
    for t in triggers:
        assert t in out, f"Rule missing required trigger: {t!r}"


def test_rules_call_out_must_not_use_cases():
    """The rules must explicitly list when the model must NOT use the tool."""
    out = append_tool_use_rules("")
    must_not = [
        "общий вопрос",
        "приветствие",
    ]
    for phrase in must_not:
        assert phrase in out, f"Rule missing must-not-use case: {phrase!r}"


def test_rules_forbid_hallucination():
    """Spec §12.1: model must not invent lore when retrieval returned nothing."""
    out = append_tool_use_rules("")
    # The text explicitly warns against inventing campaign facts when
    # the host returns an empty tool result.
    assert "Не выдумывай" in out or "не выдумывай" in out
    # The phrase "пустой результат" or "no evidence" must appear.
    assert "пустой" in out.lower() or "no evidence" in out.lower()


def test_rules_forbid_duplicate_queries():
    """Spec §12.2: the host short-circuits duplicate queries; the model
    must know this is by design, not a transient error."""
    out = append_tool_use_rules("")
    assert "Не повторяй тот же запрос" in out or "не повторяй" in out.lower()


def test_rules_idempotent_when_re_appended():
    """Calling twice should produce a longer string, not break formatting."""
    once = append_tool_use_rules("P")
    twice = append_tool_use_rules(once)
    assert twice.count("# Правила использования") == 2
    assert twice.startswith("P")
