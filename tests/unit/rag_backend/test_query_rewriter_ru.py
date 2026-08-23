"""Sprint 2 — cross-language query expansion in `query_rewriter.build_search_queries`.

The rewriter is intentionally cheap: a heuristic decides if the query is
already in Russian, and only non-Russian queries trigger an LLM translation.
Tests cover:
  - Cyrillic detection (heuristic)
  - EN query → EN + RU pair
  - RU query → RU only (no extra call)
  - Provider failure → fallback to original
  - Dedup when translation equals the original
"""
from __future__ import annotations

import pytest

from app.services.query_rewriter import (
    QueryRewriter,
    _cyrillic_ratio,
    is_cyrillic_query,
    query_rewriter,
)


# ---------------------------------------------------------------------------
# Pure heuristics
# ---------------------------------------------------------------------------


def test_cyrillic_ratio_empty_string():
    assert _cyrillic_ratio("") == 0.0


def test_cyrillic_ratio_pure_english():
    assert _cyrillic_ratio("Beholder stats") == 0.0


def test_cyrillic_ratio_pure_russian():
    assert _cyrillic_ratio("Бехолдер характеристики") == 1.0


def test_cyrillic_ratio_mixed_majority_russian():
    # "Бехолдер Beholder" — 7 cyrillic / 15 letters = 0.467
    assert _cyrillic_ratio("Бехолдер Beholder") > 0.4


def test_cyrillic_ratio_pure_digits():
    assert _cyrillic_ratio("123 456") == 0.0


def test_is_cyrillic_query_threshold():
    # Below threshold → not cyrillic.
    assert is_cyrillic_query("Beholder") is False
    # Above threshold (default 0.4) → cyrillic.
    assert is_cyrillic_query("Бехолдер") is True
    # Mixed query with majority cyrillic → still cyrillic.
    assert is_cyrillic_query("Бехолдер Beholder") is True


# ---------------------------------------------------------------------------
# build_search_queries
# ---------------------------------------------------------------------------


class _ScriptedProvider:
    """Returns a fixed string for any prompt. Used to short-circuit the
    LLM-based translation step.
    """

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    async def generate(self, messages):
        # Record what we got asked.
        self.calls.append(messages[0]["content"])
        return self._response


class _BoomProvider:
    async def generate(self, messages):
        raise RuntimeError("provider offline")


@pytest.mark.asyncio
async def test_build_search_queries_en_query_with_provider():
    provider = _ScriptedProvider("Бехолдер характеристики")
    out = await query_rewriter.build_search_queries(
        "Beholder stats", provider=provider
    )
    assert out == ["Beholder stats", "Бехолдер характеристики"]
    assert len(provider.calls) == 1  # one LLM call for the translation


@pytest.mark.asyncio
async def test_build_search_queries_ru_query_skips_translation():
    provider = _ScriptedProvider("другой перевод")
    out = await query_rewriter.build_search_queries(
        "Бехолдер характеристики", provider=provider
    )
    assert out == ["Бехолдер характеристики"]
    assert provider.calls == []  # no LLM call when already RU


@pytest.mark.asyncio
async def test_build_search_queries_no_provider_returns_only_original():
    out = await query_rewriter.build_search_queries("Beholder", provider=None)
    assert out == ["Beholder"]


@pytest.mark.asyncio
async def test_build_search_queries_provider_failure_falls_back():
    out = await query_rewriter.build_search_queries("Beholder", provider=_BoomProvider())
    assert out == ["Beholder"]


@pytest.mark.asyncio
async def test_build_search_queries_empty_query_returns_empty_list():
    out = await query_rewriter.build_search_queries("", provider=_ScriptedProvider("X"))
    assert out == []
    out = await query_rewriter.build_search_queries("   ", provider=_ScriptedProvider("X"))
    assert out == []


@pytest.mark.asyncio
async def test_build_search_queries_dedup_when_translation_equals_original():
    """If the LLM returns the same text (case-folded / whitespace-collapsed),
    we keep only one entry."""
    provider = _ScriptedProvider("Beholder stats")  # identical to input
    out = await query_rewriter.build_search_queries("Beholder stats", provider=provider)
    assert out == ["Beholder stats"]


@pytest.mark.asyncio
async def test_build_search_queries_strips_quotes_from_translation():
    """Provider sometimes wraps the answer in quotes. We strip them."""
    provider = _ScriptedProvider('"Бехолдер характеристики"')
    out = await query_rewriter.build_search_queries("Beholder stats", provider=provider)
    assert out == ["Beholder stats", "Бехолдер характеристики"]


@pytest.mark.asyncio
async def test_build_search_queries_translation_empty_string_falls_back():
    """If provider returns empty string, just return the original."""
    provider = _ScriptedProvider("   ")
    out = await query_rewriter.build_search_queries("Beholder stats", provider=provider)
    assert out == ["Beholder stats"]


@pytest.mark.asyncio
async def test_build_search_queries_respects_max_queries():
    """Even if provider returns multiple lines, we cap at max_queries."""
    class MultiProvider:
        async def generate(self, messages):
            return "Бехолдер\nДракон\nПодземелье"

    out = await query_rewriter.build_search_queries(
        "Beholder stats", provider=MultiProvider(), max_queries=2
    )
    # Original + first line of multi-line translation (we don't split).
    assert len(out) <= 2


# ---------------------------------------------------------------------------
# _normalise (dedup key)
# ---------------------------------------------------------------------------


def test_query_rewriter_normalise():
    n = QueryRewriter._normalise
    assert n("  Beholder  Stats  ") == "beholder stats"
    assert n("BEHOLDER") == "beholder"
    assert n("") == ""
    assert n("  ") == ""
    assert n("Бехолдер") == "бехолдер"