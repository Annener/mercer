"""Stage 8.2: tests for `load_retrieval_tool_settings`.

Uses an in-memory fake of `settings_service.get` — no DB needed. The point
is to lock the contract: defaults on missing keys, type coercion on
unknown values, and the `max_rounds` shortcut that picks the cap by
policy.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services import retrieval_tool_settings as rts
from shared_contracts.models import RetrievalPolicy


def _make_settings_service_get(values: dict[str, object]):
    """Return an async stub mirroring `SettingsService.get(key, db)`."""

    async def _fake_get(key, db=None):
        if key not in values:
            raise KeyError(key)
        return values[key]

    return _fake_get


@pytest.mark.asyncio
async def test_load_with_all_keys_present(monkeypatch):
    monkeypatch.setattr(
        rts.settings_service, "get",
        _make_settings_service_get({
            rts.KEY_TOOL_ENABLED: True,
            rts.KEY_POLICY: "grounded",
            rts.KEY_MAX_ROUNDS_GROUNDED: 3,
            rts.KEY_MAX_ROUNDS_ASSISTIVE: 1,
            rts.KEY_EVIDENCE_TOKEN_BUDGET: 8000,
        }),
    )
    s = await rts.load_retrieval_tool_settings(db=AsyncMock())
    assert s.tool_enabled is True
    assert s.policy is RetrievalPolicy.GROUNDED
    assert s.max_rounds_grounded == 3
    assert s.max_rounds_assistive == 1
    assert s.evidence_token_budget == 8000
    # max_rounds follows the active policy
    assert s.max_rounds == 3


@pytest.mark.asyncio
async def test_load_with_assistive_policy(monkeypatch):
    monkeypatch.setattr(
        rts.settings_service, "get",
        _make_settings_service_get({
            rts.KEY_TOOL_ENABLED: True,
            rts.KEY_POLICY: "assistive",
            rts.KEY_MAX_ROUNDS_GROUNDED: 2,
            rts.KEY_MAX_ROUNDS_ASSISTIVE: 1,
            rts.KEY_EVIDENCE_TOKEN_BUDGET: 4000,
        }),
    )
    s = await rts.load_retrieval_tool_settings(db=AsyncMock())
    assert s.policy is RetrievalPolicy.ASSISTIVE
    # max_rounds follows the policy: assistive -> 1
    assert s.max_rounds == 1


@pytest.mark.asyncio
async def test_load_with_missing_keys_falls_back_to_defaults(monkeypatch):
    """If every key is missing, we still get a valid, safe-to-use object."""
    monkeypatch.setattr(
        rts.settings_service, "get",
        _make_settings_service_get({}),
    )
    s = await rts.load_retrieval_tool_settings(db=AsyncMock())
    assert s.tool_enabled is True
    assert s.policy is RetrievalPolicy.GROUNDED
    assert s.max_rounds_grounded == 2
    assert s.max_rounds_assistive == 1
    assert s.evidence_token_budget == 4000
    assert s.max_rounds == 2


@pytest.mark.asyncio
async def test_load_coerces_unknown_policy_value(monkeypatch):
    """An unrecognised policy value is logged and replaced with grounded."""
    monkeypatch.setattr(
        rts.settings_service, "get",
        _make_settings_service_get({
            rts.KEY_TOOL_ENABLED: True,
            rts.KEY_POLICY: "ultra-grounded",  # not in the enum
            rts.KEY_MAX_ROUNDS_GROUNDED: 2,
            rts.KEY_MAX_ROUNDS_ASSISTIVE: 1,
            rts.KEY_EVIDENCE_TOKEN_BUDGET: 4000,
        }),
    )
    s = await rts.load_retrieval_tool_settings(db=AsyncMock())
    assert s.policy is RetrievalPolicy.GROUNDED


@pytest.mark.asyncio
async def test_load_clamps_negative_rounds_to_zero(monkeypatch):
    """Defensive: negative round caps would lead to silent retrieval skip."""
    monkeypatch.setattr(
        rts.settings_service, "get",
        _make_settings_service_get({
            rts.KEY_TOOL_ENABLED: True,
            rts.KEY_POLICY: "grounded",
            rts.KEY_MAX_ROUNDS_GROUNDED: -1,
            rts.KEY_MAX_ROUNDS_ASSISTIVE: -1,
            rts.KEY_EVIDENCE_TOKEN_BUDGET: -1,
        }),
    )
    s = await rts.load_retrieval_tool_settings(db=AsyncMock())
    assert s.max_rounds_grounded == 0
    assert s.max_rounds_assistive == 0
    assert s.evidence_token_budget == 0
    assert s.max_rounds == 0


@pytest.mark.asyncio
async def test_load_passes_underlying_exceptions_through_individually(monkeypatch):
    """Per-key fallback: if only one key throws, the others still load."""
    async def _fake_get(key, db=None):
        if key == rts.KEY_POLICY:
            raise KeyError(key)
        return {
            rts.KEY_TOOL_ENABLED: False,
            rts.KEY_MAX_ROUNDS_GROUNDED: 5,
            rts.KEY_MAX_ROUNDS_ASSISTIVE: 2,
            rts.KEY_EVIDENCE_TOKEN_BUDGET: 1500,
        }[key]

    monkeypatch.setattr(rts.settings_service, "get", _fake_get)
    s = await rts.load_retrieval_tool_settings(db=AsyncMock())
    assert s.tool_enabled is False
    assert s.policy is RetrievalPolicy.GROUNDED  # fallback
    assert s.max_rounds_grounded == 5
    assert s.evidence_token_budget == 1500
