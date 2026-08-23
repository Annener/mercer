"""Tests for the unified sources flow: Source/SourceGroup/MessageSource contracts
and helpers in source_utils, plus integration points where they are emitted
(AgentLoop tool_result, pipeline_executor final_composition, resume flows).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.providers.generation.base import LLMStreamChunk, ToolCallDelta
from app.services.source_utils import (
    MAX_SOURCES_PER_TOOL_RESULT,
    dedup_sources,
    full_doc_hits_to_sources,
    hits_to_sources,
    merge_sources,
    sources_to_message_sources,
)

from shared_contracts.models import (
    SearchHit,
    Source,
    SourceGroup,
)

# ---------------------------------------------------------------------------
# Source/SourceGroup/MessageSource contract tests
# ---------------------------------------------------------------------------


def test_source_minimal_required_fields():
    s = Source(path="docs/a.md")
    assert s.path == "docs/a.md"
    assert s.page is None
    assert s.vault_id is None
    assert s.document_id is None
    assert s.chunk_id is None
    assert s.score is None
    assert s.source_kind == "chunk"


def test_source_full_kind():
    s = Source(
        path="docs/whole.pdf",
        vault_id="v1",
        document_id="d1",
        source_kind="full_document",
    )
    assert s.source_kind == "full_document"


def test_source_group_with_steps():
    g = SourceGroup(
        step_id="step1",
        step_name="Search lore",
        sources=[
            Source(path="a.md", chunk_id="c1"),
            Source(path="b.md", page=2),
        ],
    )
    assert g.step_id == "step1"
    assert len(g.sources) == 2


# ---------------------------------------------------------------------------
# hits_to_sources
# ---------------------------------------------------------------------------


def _hit(
    chunk_id: str,
    document_id: str = "d1",
    path: str | None = None,
    page: int | None = None,
    vault_id: str | None = None,
    score: float = 0.5,
) -> SearchHit:
    md: dict[str, Any] = {}
    if path:
        md["source_path"] = path
    if page is not None:
        md["page_number"] = page
    if vault_id is not None:
        md["vault_id"] = vault_id
    return SearchHit(
        chunk_id=chunk_id,
        document_id=document_id,
        text=f"text-{chunk_id}",
        metadata=md,
        score=score,
    )


def test_hits_to_sources_dedup_by_chunk_id():
    h1 = _hit("c1", path="docs/a.md", page=3)
    h2 = _hit("c1", path="docs/a.md", page=3, score=0.99)  # duplicate
    out = hits_to_sources([h1, h2])
    assert len(out) == 1
    assert out[0].chunk_id == "c1"
    assert out[0].path == "docs/a.md"
    assert out[0].page == 3


def test_hits_to_sources_keeps_different_chunks():
    h1 = _hit("c1", path="docs/a.md", page=1)
    h2 = _hit("c2", path="docs/a.md", page=1)  # same file, different chunk
    out = hits_to_sources([h1, h2])
    assert len(out) == 2


def test_hits_to_sources_keeps_different_pages_same_chunk_id():
    # Defensive: if chunk_id duplicates across pages, keep both (uniqueness)
    h1 = _hit("c1", path="docs/a.pdf", page=1)
    h2 = _hit("c1", path="docs/a.pdf", page=2)
    out = hits_to_sources([h1, h2])
    # Both kept: dedup key is (path, page, vault_id, chunk_id)
    assert len(out) == 2


def test_hits_to_sources_md_file_no_page():
    """Markdown files have no page_number in metadata — поле page=None."""
    h = _hit("c1", path="docs/lore.md")
    out = hits_to_sources([h])
    assert len(out) == 1
    assert out[0].path == "docs/lore.md"
    assert out[0].page is None
    assert out[0].source_kind == "chunk"


def test_hits_to_sources_pdf_with_page():
    """PDF files обычно имеют page_number."""
    h = _hit("c1", path="docs/book.pdf", page=12, vault_id="v1")
    out = hits_to_sources([h])
    assert len(out) == 1
    assert out[0].page == 12
    assert out[0].vault_id == "v1"


def test_hits_to_sources_missing_source_path_uses_document_id():
    """Если metadata пустое — path = document_id."""
    h = SearchHit(chunk_id="c1", document_id="doc-uuid", text="x", score=0.1)
    out = hits_to_sources([h])
    assert out[0].path == "doc-uuid"


def test_hits_to_sources_cap():
    """При cap>0 — обрезается до первых N уникальных."""
    hits = [_hit(f"c{i}", path=f"a{i}.md") for i in range(10)]
    out = hits_to_sources(hits, cap=3)
    assert len(out) == 3


def test_hits_to_sources_empty():
    assert hits_to_sources([]) == []


# ---------------------------------------------------------------------------
# full_doc_hits_to_sources
# ---------------------------------------------------------------------------


def test_full_doc_hits_to_sources_one_per_document():
    """Несколько чанков одного документа → одна запись source_kind='full_document'."""
    hits = [
        _hit("c1", document_id="d1", path="book.pdf", page=1),
        _hit("c2", document_id="d1", path="book.pdf", page=2),
        _hit("c3", document_id="d2", path="other.md"),
    ]
    out = full_doc_hits_to_sources(hits)
    assert len(out) == 2
    assert all(s.source_kind == "full_document" for s in out)
    paths = {s.path for s in out}
    assert paths == {"book.pdf", "other.md"}


def test_full_doc_hits_to_sources_md_without_page():
    out = full_doc_hits_to_sources([_hit("c1", document_id="d1", path="lore.md")])
    assert len(out) == 1
    assert out[0].page is None
    assert out[0].chunk_id is None


# ---------------------------------------------------------------------------
# dedup_sources, merge_sources
# ---------------------------------------------------------------------------


def test_dedup_sources_drops_exact_duplicates():
    s = Source(path="a.md", chunk_id="c1")
    out = dedup_sources([s, s, s])
    assert len(out) == 1


def test_dedup_sources_different_chunk_kept():
    a = Source(path="a.md", chunk_id="c1")
    b = Source(path="a.md", chunk_id="c2")
    out = dedup_sources([a, b])
    assert len(out) == 2


def test_merge_sources_combines_with_dedup():
    a = [Source(path="a.md", chunk_id="c1")]
    b = [Source(path="a.md", chunk_id="c1"), Source(path="b.md", chunk_id="c2")]
    out = merge_sources(a, b)
    assert len(out) == 2


# ---------------------------------------------------------------------------
# sources_to_message_sources
# ---------------------------------------------------------------------------


def test_sources_to_message_sources_drops_score():
    s = Source(path="a.md", chunk_id="c1", score=0.95)
    out = sources_to_message_sources([s])
    assert len(out) == 1
    # MessageSource does not have `score` field
    assert "score" not in out[0].model_dump()
    assert out[0].path == "a.md"
    assert out[0].chunk_id == "c1"


def test_sources_to_message_sources_keeps_source_kind():
    s = Source(path="a.pdf", source_kind="full_document", document_id="d1")
    out = sources_to_message_sources([s])
    assert out[0].source_kind == "full_document"


# ---------------------------------------------------------------------------
# AgentLoop — tool_result event теперь содержит sources
# ---------------------------------------------------------------------------


def _content_chunk(text: str) -> LLMStreamChunk:
    return LLMStreamChunk(content_delta=text)


def _tool_call_chunks(call_id: str, name: str, args: str) -> list[LLMStreamChunk]:
    return [
        LLMStreamChunk(
            tool_call_delta=ToolCallDelta(
                index=0,
                id=call_id,
                type="function",
                function_name=name,
                function_arguments_delta="",
            )
        ),
        LLMStreamChunk(
            tool_call_delta=ToolCallDelta(
                index=0,
                function_arguments_delta=args,
            )
        ),
    ]


class _OneCallProvider:
    """Provider that on round 0 emits a tool_call, on round 1 emits text answer."""

    def __init__(self) -> None:
        self._calls = 0

    async def generate_stream_with_tools(self, messages, tools=None, tool_choice=None):
        self._calls += 1
        if self._calls == 1:
            for c in _tool_call_chunks(
                "call_1", "search_knowledge", json.dumps({"queries": ["dwarf"]})
            ):
                yield c
            return
        # Final answer
        for c in [_content_chunk("Answer.")]:
            yield c

    async def generate(self, messages):
        return ""


async def _collect(events: AsyncIterator[Any]) -> list[Any]:
    out: list[Any] = []
    async for e in events:
        out.append(e)
    return out


@pytest.mark.asyncio
async def test_agent_loop_tool_result_emits_sources():
    """tool_result event должен содержать sources список."""
    from app.services.agent_loop import AgentLoop

    provider = _OneCallProvider()

    fake_result = MagicMock()
    fake_result.queries_used = ["dwarf"]
    fake_result.hits = [
        _hit("c1", path="docs/a.md", page=2),
        _hit("c2", path="docs/b.md"),
    ]
    fake_result.scope = "campaign"
    fake_result.evidence_tokens = 10
    fake_result.note = None

    with patch("app.services.agent_loop.search_knowledge_service") as mock_svc:
        mock_svc.run = AsyncMock(return_value=fake_result)
        loop = AgentLoop()
        events = await _collect(
            loop.run_stream(
                provider=provider,
                system_prompt="sys",
                history=[],
                user_message="q",
                domain_id="dnd",
                campaign_id="c1",
                vault_ids=["v1"],
                max_rounds=2,
                evidence_token_budget=4000,
                policy=__import__(
                    "shared_contracts.models", fromlist=["RetrievalPolicy"]
                ).RetrievalPolicy.GROUNDED,
                db=AsyncMock(),
            )
        )

    tool_results = [e for e in events if e.type == "tool_result"]
    assert len(tool_results) == 1
    sources_payload = tool_results[0].payload["sources"]
    assert len(sources_payload) == 2
    paths = sorted([s["path"] for s in sources_payload])
    assert paths == ["docs/a.md", "docs/b.md"]
    # Page только у pdf/md-хита который его имеет
    page_a = next(s for s in sources_payload if s["path"] == "docs/a.md")
    assert page_a["page"] == 2
    page_b = next(s for s in sources_payload if s["path"] == "docs/b.md")
    assert page_b["page"] is None


@pytest.mark.asyncio
async def test_agent_loop_tool_result_caps_sources():
    """При MAX_SOURCES_PER_TOOL_RESULT+ hits — sources обрезается."""
    from app.services.agent_loop import AgentLoop

    provider = _OneCallProvider()

    fake_result = MagicMock()
    fake_result.queries_used = ["x"]
    fake_result.hits = [
        _hit(f"c{i}", path=f"a{i}.md") for i in range(MAX_SOURCES_PER_TOOL_RESULT + 5)
    ]
    fake_result.scope = "domain"
    fake_result.evidence_tokens = 0
    fake_result.note = None

    with patch("app.services.agent_loop.search_knowledge_service") as mock_svc:
        mock_svc.run = AsyncMock(return_value=fake_result)
        loop = AgentLoop()
        events = await _collect(
            loop.run_stream(
                provider=provider,
                system_prompt="sys",
                history=[],
                user_message="q",
                domain_id="d1",
                campaign_id=None,
                vault_ids=["v1"],
                max_rounds=2,
                evidence_token_budget=4000,
                policy=__import__(
                    "shared_contracts.models", fromlist=["RetrievalPolicy"]
                ).RetrievalPolicy.GROUNDED,
                db=AsyncMock(),
            )
        )

    tool_result = next(e for e in events if e.type == "tool_result")
    assert len(tool_result.payload["sources"]) == MAX_SOURCES_PER_TOOL_RESULT


@pytest.mark.asyncio
async def test_agent_loop_final_event_includes_round_sources():
    """final event должен содержать rounds с sources в AgentRoundResult."""
    from app.services.agent_loop import AgentLoop

    from shared_contracts.models import RetrievalPolicy

    provider = _OneCallProvider()

    fake_result = MagicMock()
    fake_result.queries_used = ["dwarf"]
    fake_result.hits = [_hit("c1", path="docs/a.md")]
    fake_result.scope = "campaign"
    fake_result.evidence_tokens = 5
    fake_result.note = None

    with patch("app.services.agent_loop.search_knowledge_service") as mock_svc:
        mock_svc.run = AsyncMock(return_value=fake_result)
        loop = AgentLoop()
        events = await _collect(
            loop.run_stream(
                provider=provider,
                system_prompt="sys",
                history=[],
                user_message="q",
                domain_id="dnd",
                campaign_id="c1",
                vault_ids=["v1"],
                max_rounds=2,
                evidence_token_budget=4000,
                policy=RetrievalPolicy.GROUNDED,
                db=AsyncMock(),
            )
        )

    final = next(e for e in events if e.type == "final")
    rounds = final.payload["rounds"]
    assert len(rounds) >= 1
    # Найдём round, который вызывал tool (его queries_used == ["dwarf"])
    search_round = next(
        (
            r
            for r in rounds
            if r.get("queries_used") == ["dwarf"] or r.get("queries") == ["dwarf"]
        ),
        None,
    )
    assert search_round is not None
    assert "sources" in search_round
    assert len(search_round["sources"]) == 1
    assert search_round["sources"][0]["path"] == "docs/a.md"


# ---------------------------------------------------------------------------
# pipeline_executor — _collect_step_sources
# ---------------------------------------------------------------------------


def test_collect_step_sources_groups_by_step():
    """Каждый retrieval-шаг → SourceGroup с правильными источниками."""
    from app.services.pipeline_executor import _collect_step_sources

    from shared_contracts.models import PipelineExecutionContext, PipelineStep

    h1 = _hit("c1", path="a.md", page=1)
    h2 = _hit("c2", path="b.pdf", page=5)

    step1 = PipelineStep(
        step_id="retrieve_1",
        name="Search lore",
        type="retrieval",
        system_prompt="",
    )
    step2 = PipelineStep(
        step_id="retrieve_2",
        name="Search rules",
        type="retrieval",
        system_prompt="",
    )

    ctx = PipelineExecutionContext.model_construct(
        chat_id="c1",
        message_id="m1",
        query="q",
        domain_id="d1",
        campaign_id=None,
        vault_ids=["v1"],
        pipeline_id="p1",
        pipeline_version="v1",
        steps=[step1, step2],
        final_composition=None,
        history=[],
        metadata={},
        retrieval_strategy=None,
        confidence=None,
        reasoning=None,
        mode=None,
        step_results={
            "_hits_retrieve_1": [h1.model_dump()],
            "_hits_retrieve_2": [h2.model_dump()],
        },
    )

    groups = _collect_step_sources(ctx)
    assert len(groups) == 2
    g1, g2 = groups
    assert g1.step_id == "retrieve_1"
    assert len(g1.sources) == 1
    assert g1.sources[0].path == "a.md"
    assert g2.step_id == "retrieve_2"
    assert g2.sources[0].path == "b.pdf"


def test_collect_step_sources_includes_fulldoc():
    """send_full_document шаг → SourceGroup с source_kind='full_document'."""
    from app.services.pipeline_executor import _collect_step_sources

    from shared_contracts.models import PipelineExecutionContext, PipelineStep

    full_doc_source = Source(
        path="book.pdf",
        document_id="d1",
        source_kind="full_document",
    )

    step = PipelineStep(
        step_id="retrieve_fulldoc",
        name="Send full document",
        type="retrieval",
        system_prompt="",
        send_full_document=True,
    )

    ctx = PipelineExecutionContext.model_construct(
        chat_id="c1",
        message_id="m1",
        query="q",
        domain_id="d1",
        campaign_id=None,
        vault_ids=["v1"],
        pipeline_id="p1",
        pipeline_version="v1",
        steps=[step],
        final_composition=None,
        history=[],
        metadata={},
        retrieval_strategy=None,
        confidence=None,
        reasoning=None,
        mode=None,
        step_results={
            "_fulldoc_sources_retrieve_fulldoc": [full_doc_source.model_dump()],
        },
    )

    groups = _collect_step_sources(ctx)
    assert len(groups) == 1
    assert groups[0].sources[0].source_kind == "full_document"


def test_collect_step_sources_skips_steps_without_hits():
    """Шаг без hits и без fulldoc_sources — пропускается."""
    from app.services.pipeline_executor import _collect_step_sources

    from shared_contracts.models import PipelineExecutionContext, PipelineStep

    step_no_hits = PipelineStep(
        step_id="empty_step",
        name="Empty",
        type="retrieval",
        system_prompt="",
    )

    ctx = PipelineExecutionContext.model_construct(
        chat_id="c1",
        message_id="m1",
        query="q",
        domain_id="d1",
        campaign_id=None,
        vault_ids=["v1"],
        pipeline_id="p1",
        pipeline_version="v1",
        steps=[step_no_hits],
        final_composition=None,
        history=[],
        metadata={},
        retrieval_strategy=None,
        confidence=None,
        reasoning=None,
        mode=None,
        step_results={},
    )

    groups = _collect_step_sources(ctx)
    assert groups == []
