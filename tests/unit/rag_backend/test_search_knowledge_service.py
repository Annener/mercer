"""Stage 8.3: tests for SearchKnowledgeService.

Covers the host-side guarantees of the `search_knowledge` tool:
  - Query normalisation + dedup (case + whitespace insensitive).
  - Scope resolution: campaign with tags / no tags / no campaign.
  - Empty vault: returns 'no_vault' and never calls retrieval.
  - Per-query exceptions are swallowed and don't crash the tool.
  - Truncation to `evidence_token_budget`.
  - The result's `queries_used` reflects what the host actually ran
    (not the model's raw input).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import search_knowledge_service as sks
from app.services.search_knowledge_service import (
    SearchKnowledgeService,
    _dedupe_queries,
    _normalise_query,
    _truncate_to_budget,
)
from shared_contracts.models import SearchHit, SearchKnowledgeResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hit(
    chunk_id: str,
    text: str = "x",
    score: float = 0.5,
    document_id: str = "doc1",
) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        score=score,
        metadata={},
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_normalise_query_collapses_whitespace_and_casefolds():
    assert _normalise_query("  Foo   Bar ") == "foo bar"


def test_dedupe_queries_case_and_whitespace_insensitive():
    out = _dedupe_queries(["Foo", "foo", "  Foo ", "Bar", "bar "])
    # First occurrence wins; the second "foo" and second "bar" are skipped.
    assert out == ["Foo", "Bar"]


def test_dedupe_queries_drops_empty_strings():
    assert _dedupe_queries(["", "   ", "Foo", ""]) == ["Foo"]


def test_truncate_to_budget_zero_returns_empty():
    assert _truncate_to_budget([_hit("a", "abcd")], 0) == []


def test_truncate_to_budget_keeps_within_budget():
    # Each hit costs 1 token (ceil(1/4) = 1). Budget 3 -> at most 3 hits.
    hits = [_hit(f"id{i}", "a") for i in range(10)]
    out = _truncate_to_budget(hits, budget_tokens=3)
    assert len(out) == 3


def test_truncate_to_budget_short_circuits_after_first_overflow():
    # A 1000-char text is ~250 tokens; with budget 100 the first one is
    # already over. We must still keep it (first hit always kept).
    big = _hit("big", "a" * 1000)
    small = _hit("small", "a")
    out = _truncate_to_budget([big, small, _hit("never", "a")], budget_tokens=100)
    assert [h.chunk_id for h in out] == ["big"]


# ---------------------------------------------------------------------------
# SearchKnowledgeService.run — scope resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_no_vaults_returns_no_vault_scope():
    svc = SearchKnowledgeService()
    result = await svc.run(
        queries=["anything"],
        domain_id="dnd",
        campaign_id="c1",
        vault_ids=[],
        evidence_token_budget=4000,
        db=AsyncMock(),
    )
    assert isinstance(result, SearchKnowledgeResult)
    assert result.scope == "no_vault"
    assert result.hits == []
    assert result.queries_used == []
    assert "vault" in (result.note or "").lower()


@pytest.mark.asyncio
async def test_run_with_no_domain_id_returns_no_vault_scope():
    """Defensive: chat without a domain cannot run RAG at all."""
    svc = SearchKnowledgeService()
    result = await svc.run(
        queries=["anything"],
        domain_id=None,
        campaign_id=None,
        vault_ids=["v1"],
        evidence_token_budget=4000,
        db=AsyncMock(),
    )
    assert result.scope == "no_vault"


@pytest.mark.asyncio
async def test_run_with_empty_queries_returns_no_vault_scope():
    """No usable query -> no_vault (we never call retrieval)."""
    svc = SearchKnowledgeService()
    result = await svc.run(
        queries=["", "  ", "  \t  "],
        domain_id="dnd",
        campaign_id="c1",
        vault_ids=["v1"],
        evidence_token_budget=4000,
        db=AsyncMock(),
    )
    assert result.scope == "no_vault"
    assert "empty" in (result.note or "").lower()


# ---------------------------------------------------------------------------
# SearchKnowledgeService.run — campaign scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_campaign_with_no_tags_returns_empty_scope():
    """Per spec: campaign with no tags must NOT widen to the full domain."""
    svc = SearchKnowledgeService()

    db = AsyncMock()
    # get_allowed_tag_ids -> set()
    with patch.object(sks, "get_allowed_tag_ids", AsyncMock(return_value=set())), \
         patch.object(sks, "retrieve_multi_vault", new=AsyncMock()) as rmv:
        result = await svc.run(
            queries=["dwarf armor"],
            domain_id="dnd",
            campaign_id="c1",
            vault_ids=["v1"],
            evidence_token_budget=4000,
            db=db,
        )
    assert result.scope == "empty"
    assert result.hits == []
    assert result.queries_used == ["dwarf armor"]
    # retrieve_multi_vault must NOT have been called — empty scope is final.
    rmv.assert_not_called()


@pytest.mark.asyncio
async def test_run_campaign_with_tags_filters_by_document_ids():
    """When the campaign has tags, retrieval is bounded to its document_ids."""
    svc = SearchKnowledgeService()

    db = AsyncMock()
    captured: dict[str, Any] = {}

    async def _fake_retrieve(query, vault_ids, **kwargs):
        captured.setdefault("calls", []).append((query, kwargs))
        return [_hit("c1", "evidence-1", score=0.9)]

    with patch.object(sks, "get_allowed_tag_ids", AsyncMock(return_value={"tag-1"})), \
         patch.object(sks, "get_document_ids_by_tags", AsyncMock(return_value=["doc-A", "doc-B"])), \
         patch.object(sks, "retrieve_multi_vault", new=_fake_retrieve), \
         patch.object(sks, "rerank_hits", new=AsyncMock(side_effect=lambda q, hits, db: hits)):
        result = await svc.run(
            queries=["dwarf armor"],
            domain_id="dnd",
            campaign_id="c1",
            vault_ids=["v1"],
            evidence_token_budget=4000,
            db=db,
        )

    assert result.scope == "campaign"
    assert result.queries_used == ["dwarf armor"]
    assert len(result.hits) == 1
    # document_ids was threaded into retrieve_multi_vault
    assert captured["calls"][0][1]["document_ids"] == ["doc-A", "doc-B"]


# ---------------------------------------------------------------------------
# SearchKnowledgeService.run — dedup + per-query exception isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_dedups_queries_before_calling_retrieval():
    """The same query, written three ways, must hit retrieval only once."""
    svc = SearchKnowledgeService()

    call_count = 0

    async def _fake_retrieve(query, vault_ids, **kwargs):
        nonlocal call_count
        call_count += 1
        return [_hit(f"c{call_count}", "ev", score=0.5)]

    with patch.object(sks, "get_allowed_tag_ids", AsyncMock(return_value=set())), \
         patch.object(sks, "retrieve_multi_vault", new=_fake_retrieve), \
         patch.object(sks, "rerank_hits", new=AsyncMock(side_effect=lambda q, hits, db: hits)):
        # Force scope=domain by leaving campaign_id None.
        result = await svc.run(
            queries=["Dwarf", "dwarf", "  dwarf  ", "Elf"],
            domain_id="dnd",
            campaign_id=None,
            vault_ids=["v1"],
            evidence_token_budget=4000,
            db=AsyncMock(),
        )

    assert call_count == 2  # "Dwarf" and "Elf"
    assert result.queries_used == ["Dwarf", "Elf"]


@pytest.mark.asyncio
async def test_run_swallows_per_query_exceptions():
    """One failed query must not prevent the others from contributing hits."""
    svc = SearchKnowledgeService()

    async def _fake_retrieve(query, vault_ids, **kwargs):
        if query == "boom":
            raise RuntimeError("retrieval exploded")
        return [_hit(f"c-{query}", "ev", score=0.7)]

    with patch.object(sks, "get_allowed_tag_ids", AsyncMock(return_value=set())), \
         patch.object(sks, "retrieve_multi_vault", new=_fake_retrieve), \
         patch.object(sks, "rerank_hits", new=AsyncMock(side_effect=lambda q, hits, db: hits)):
        result = await svc.run(
            queries=["foo", "boom", "bar"],
            domain_id="dnd",
            campaign_id=None,
            vault_ids=["v1"],
            evidence_token_budget=4000,
            db=AsyncMock(),
        )

    # We still got two hits (from "foo" and "bar"); "boom" was logged and skipped.
    assert sorted(h.chunk_id for h in result.hits) == ["c-bar", "c-foo"]
    assert result.queries_used == ["foo", "boom", "bar"]


# ---------------------------------------------------------------------------
# SearchKnowledgeService.run — budget truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_truncates_to_evidence_token_budget():
    svc = SearchKnowledgeService()

    # Three large hits — each ~250 tokens.
    async def _fake_retrieve(query, vault_ids, **kwargs):
        return [
            _hit("c1", "a" * 1000, score=0.9),
            _hit("c2", "b" * 1000, score=0.8),
            _hit("c3", "c" * 1000, score=0.7),
        ]

    with patch.object(sks, "get_allowed_tag_ids", AsyncMock(return_value=set())), \
         patch.object(sks, "retrieve_multi_vault", new=_fake_retrieve), \
         patch.object(sks, "rerank_hits", new=AsyncMock(side_effect=lambda q, hits, db: hits)):
        result = await svc.run(
            queries=["big"],
            domain_id="dnd",
            campaign_id=None,
            vault_ids=["v1"],
            evidence_token_budget=300,  # only one 1000-char hit fits
            db=AsyncMock(),
        )

    assert len(result.hits) == 1
    assert result.hits[0].chunk_id == "c1"
    # evidence_tokens reflects the truncated payload
    assert 0 < result.evidence_tokens <= 300


@pytest.mark.asyncio
async def test_run_with_no_hits_returns_graceful_note():
    svc = SearchKnowledgeService()

    async def _fake_retrieve(query, vault_ids, **kwargs):
        return []

    with patch.object(sks, "get_allowed_tag_ids", AsyncMock(return_value=set())), \
         patch.object(sks, "retrieve_multi_vault", new=_fake_retrieve), \
         patch.object(sks, "rerank_hits", new=AsyncMock(side_effect=lambda q, hits, db: hits)):
        result = await svc.run(
            queries=["obscure"],
            domain_id="dnd",
            campaign_id=None,
            vault_ids=["v1"],
            evidence_token_budget=4000,
            db=AsyncMock(),
        )

    assert result.hits == []
    assert result.evidence_tokens == 0
    # Per §12.1 — the model must be told that nothing was found so it doesn't
    # hallucinate a campaign fact.
    assert result.note is not None
    assert "no evidence" in result.note.lower() or "not found" in result.note.lower()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def test_module_level_singleton_is_SearchKnowledgeService():
    assert isinstance(sks.search_knowledge_service, SearchKnowledgeService)
