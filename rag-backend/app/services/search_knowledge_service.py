"""Stage 8.3: host-side implementation of the `search_knowledge` tool.

The LLM produces a list of queries; this service:
  1. Normalises and deduplicates them (case-folded, whitespace-collapsed).
  2. Resolves the active campaign's allowed tag IDs and computes the
     document filter — same logic as `_fallback_retrieve` in `chat.py`.
  3. Runs each query in parallel against `retrieve_multi_vault`.
  4. Merges hits, runs a single final rerank, and truncates to the
     `evidence_token_budget` cap.
  5. Returns a `SearchKnowledgeResult` that the agent loop turns into a
     `role=tool` message for the model.

Scope contract (per §12 of the spec):
  - The host always fixes the scope — model cannot widen or narrow it.
  - If `campaign_id` is set and the campaign has zero tags, we return
    `scope='empty'` instead of falling back to the full domain. The
    spec is explicit: «не расширяться на весь домен» (§12 / RAG rules).
  - If there are no enabled vaults, the result is `scope='no_vault'`.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.campaign_state_compiler import default_token_counter
from app.services.retrieval import (
    format_context,
    get_allowed_tag_ids,
    get_document_ids_by_tags,
    rerank_hits,
    retrieve_multi_vault,
)
from app.services.settings_service import settings_service
from shared_contracts.models import SearchHit, SearchKnowledgeResult

logger = logging.getLogger(__name__)


def _normalise_query(raw: str) -> str:
    """Lower-case, collapse whitespace, strip.

    Used as the dedup key so that "Dwarf" and " dwarf " collapse to the
    same query. Original casing is preserved in the query string we send
    to the retriever — we only dedup by the normalised form.
    """
    return re.sub(r"\s+", " ", raw).strip().lower()


def _dedupe_queries(queries: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in queries:
        if not q or not q.strip():
            continue
        key = _normalise_query(q)
        if key in seen:
            continue
        seen.add(key)
        out.append(q.strip())
    return out


async def _resolve_document_ids(
    domain_id: str | None,
    campaign_id: str | None,
    db: AsyncSession,
) -> tuple[list[str] | None, str]:
    """Return (document_ids, scope).

    - `campaign_id` set + tags present  -> (filtered_ids, 'campaign')
    - `campaign_id` set + no tags       -> ([], 'empty')  ← do NOT widen
    - `campaign_id` None + domain set   -> (None, 'domain')  ← full domain
    - nothing                           -> (None, 'no_vault')
    """
    if not domain_id:
        return None, "no_vault"
    if campaign_id:
        allowed = await get_allowed_tag_ids(domain_id, campaign_id, db)
        if not allowed:
            return [], "empty"
        document_ids = await get_document_ids_by_tags(list(allowed), domain_id, db)
        return document_ids, "campaign"
    return None, "domain"


def _truncate_to_budget(
    hits: list[SearchHit],
    budget_tokens: int,
) -> list[SearchHit]:
    """Drop hits from the tail until the formatted context fits the budget.

    Greedy in the score order produced by `retrieve_multi_vault` (descending).
    """
    if not hits or budget_tokens <= 0:
        return []
    kept: list[SearchHit] = []
    running = 0
    for hit in hits:
        # Cost of adding this hit. We use the per-hit text length with the
        # same heuristic as `default_token_counter`. The [n] prefix is
        # negligible (single digit).
        cost = default_token_counter(hit.text)
        if running + cost > budget_tokens and kept:
            # Budget exhausted and we already have at least one hit — stop.
            break
        kept.append(hit)
        running += cost
    return kept


class SearchKnowledgeService:
    """Stateless facade. The agent loop instantiates one per turn."""

    async def run(
        self,
        *,
        queries: list[str],
        domain_id: str | None,
        campaign_id: str | None,
        vault_ids: list[str],
        evidence_token_budget: int,
        db: AsyncSession,
    ) -> SearchKnowledgeResult:
        if not vault_ids:
            logger.info(
                "search_knowledge: no enabled vault for domain_id=%s, campaign_id=%s",
                domain_id, campaign_id,
            )
            return SearchKnowledgeResult(
                queries_used=[],
                hits=[],
                scope="no_vault",
                evidence_tokens=0,
                note="No vault is enabled for this domain.",
            )

        unique = _dedupe_queries(queries)
        if not unique:
            return SearchKnowledgeResult(
                queries_used=[],
                hits=[],
                scope="no_vault",
                evidence_tokens=0,
                note="All queries were empty after normalisation.",
            )

        document_ids, scope = await _resolve_document_ids(
            domain_id, campaign_id, db,
        )
        if scope == "empty":
            logger.info(
                "search_knowledge: campaign_id=%s has no tags, refusing to widen scope",
                campaign_id,
            )
            return SearchKnowledgeResult(
                queries_used=unique,
                hits=[],
                scope="empty",
                evidence_tokens=0,
                note=(
                    "The active campaign has no tags configured, so the host "
                    "refused to widen the search to the full domain."
                ),
            )
        if scope == "domain":
            document_ids = None  # explicit: full domain

        top_k = int(await settings_service.get("retrieval.top_k", db))

        # Parallelise the per-query retrieval. The inner call already runs
        # multi-vault, so the fan-out is bounded by `len(unique)`.
        import asyncio

        per_query = await asyncio.gather(
            *[
                retrieve_multi_vault(
                    query, vault_ids,
                    document_ids=document_ids,
                    top_k=top_k,
                    strategy="hybrid",
                    db=db,
                    skip_rerank=True,
                )
                for query in unique
            ],
            return_exceptions=True,
        )

        merged: dict[str, SearchHit] = {}
        for query, hits_or_exc in zip(unique, per_query):
            if isinstance(hits_or_exc, Exception):
                logger.warning(
                    "search_knowledge: retrieve_multi_vault failed for query=%r: %s",
                    query, hits_or_exc,
                )
                continue
            for hit in hits_or_exc:
                # Dedup by chunk_id; keep the highest score.
                existing = merged.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    merged[hit.chunk_id] = hit

        all_hits = sorted(merged.values(), key=lambda h: h.score, reverse=True)
        reranked = await rerank_hits(unique[0], all_hits, db) if all_hits else all_hits
        capped = _truncate_to_budget(reranked, evidence_token_budget)
        evidence_tokens = sum(default_token_counter(h.text) for h in capped)

        logger.info(
            "search_knowledge: queries=%d scope=%s raw_hits=%d after_rerank=%d "
            "after_budget=%d evidence_tokens=%d",
            len(unique), scope, len(all_hits), len(reranked), len(capped), evidence_tokens,
        )

        return SearchKnowledgeResult(
            queries_used=unique,
            hits=capped,
            scope=scope,  # type: ignore[arg-type]
            evidence_tokens=evidence_tokens,
            note=(
                None
                if capped
                else "No evidence found in the campaign's allowed sources for the provided queries."
            ),
        )


# Module-level singleton — stateless.
search_knowledge_service = SearchKnowledgeService()


__all__ = [
    "SearchKnowledgeService",
    # Re-exported for tests and direct callers.
    "format_context",
    "search_knowledge_service",
]
