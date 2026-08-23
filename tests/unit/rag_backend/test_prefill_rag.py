"""Sprint 2 — _prefill_rag helper tests.

The prefill path is the one that runs before the model gets to see the
system prompt in grounded mode. We mock `retrieve_multi_vault` and
`get_allowed_tag_ids` so the test runs without PostgreSQL/LanceDB.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.api.chat import _prefill_rag
from app.db.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared_contracts.models import SearchHit


@pytest.fixture()
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _hit(chunk_id: str, text: str, score: float = 0.5, document_id: str = "d1") -> SearchHit:
    return SearchHit(chunk_id=chunk_id, document_id=document_id, text=text, score=score)


@pytest.mark.asyncio
async def test_prefill_rag_returns_empty_when_no_vaults(db_session: AsyncSession):
    queries, block = await _prefill_rag(
        original_query="Beholder",
        vault_ids=[],
        domain_id="dnd",
        campaign_id=str(uuid.uuid4()),
        db=db_session,
    )
    assert queries == []
    assert block == ""


@pytest.mark.asyncio
async def test_prefill_rag_returns_empty_when_no_domain(db_session: AsyncSession):
    queries, block = await _prefill_rag(
        original_query="Beholder",
        vault_ids=["v1"],
        domain_id=None,
        campaign_id=str(uuid.uuid4()),
        db=db_session,
    )
    assert queries == []
    assert block == ""


@pytest.mark.asyncio
async def test_prefill_rag_returns_empty_for_blank_query(db_session: AsyncSession):
    queries, block = await _prefill_rag(
        original_query="   ",
        vault_ids=["v1"],
        domain_id="dnd",
        campaign_id=str(uuid.uuid4()),
        db=db_session,
    )
    assert queries == []
    assert block == ""


@pytest.mark.asyncio
async def test_prefill_rag_runs_retrieval_and_formats_block(
    db_session: AsyncSession,
):
    fake_hits = [
        _hit("c1", "Beholder — большая aberration", 0.9, document_id="d1"),
        _hit("c2", "Имеет много глаз-лучей", 0.7, document_id="d2"),
    ]

    with (
        patch(
            "app.api.chat.get_allowed_tag_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "app.api.chat.retrieve_multi_vault",
            new=AsyncMock(return_value=fake_hits),
        ),
    ):
        queries, block = await _prefill_rag(
            original_query="Beholder",
            vault_ids=["v1"],
            domain_id="dnd",
            campaign_id=str(uuid.uuid4()),
            db=db_session,
        )

    assert queries == ["Beholder"]
    assert "[1] Beholder — большая aberration" in block
    assert "[2] Имеет много глаз-лучей" in block


@pytest.mark.asyncio
async def test_prefill_rag_respects_token_budget(
    db_session: AsyncSession,
):
    """Long hits are dropped once the budget is exhausted."""
    # Each hit ~ 100 chars → 25 tokens. Default budget 6000 → all fit.
    # We patch settings_service.get to return a tiny budget.
    big_text = "x" * 400  # ~100 tokens
    fake_hits = [
        _hit(f"c{i}", big_text, document_id=f"d{i}") for i in range(5)
    ]

    from app.api import chat as chat_module
    with (
        patch(
            "app.api.chat.get_allowed_tag_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "app.api.chat.retrieve_multi_vault",
            new=AsyncMock(return_value=fake_hits),
        ),
        patch.object(
            chat_module.settings_service,
            "get",
            new=AsyncMock(side_effect=lambda key, db=None: {
                "retrieval.top_k": 10,
                "retrieval.evidence_token_budget": 250,  # 2.5 hits at 100 tok each
            }.get(key)),
        ),
    ):
        queries, block = await _prefill_rag(
            original_query="q",
            vault_ids=["v1"],
            domain_id="dnd",
            campaign_id=str(uuid.uuid4()),
            db=db_session,
        )

    # Should keep at most ~2-3 hits. We only check >0 and <=3.
    assert queries == ["q"]
    assert "[1]" in block
    # Count blocks in formatted context — should be < 5.
    block_count = block.count("\n\n[")
    assert block_count <= 3


@pytest.mark.asyncio
async def test_prefill_rag_dedups_hits_by_chunk_id(
    db_session: AsyncSession,
):
    """Same chunk_id returned by both EN and RU queries — only the
    higher-scoring copy wins."""
    same_chunk = _hit("c1", "Beholder", 0.7, document_id="d1")
    other = _hit("c2", "Другой чанк", 0.6, document_id="d2")

    call_count = {"n": 0}

    async def fake_retrieve(query, vault_ids, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [same_chunk, other]
        return [same_chunk]  # duplicate

    with (
        patch(
            "app.api.chat.get_allowed_tag_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch("app.api.chat.retrieve_multi_vault", new=fake_retrieve),
    ):
        queries, block = await _prefill_rag(
            original_query="Beholder",
            vault_ids=["v1"],
            domain_id="dnd",
            campaign_id=str(uuid.uuid4()),
            db=db_session,
            provider=AsyncMock(
                generate=AsyncMock(return_value="Бехолдер")
            ),
        )

    # queries should be original + RU
    assert queries == ["Beholder", "Бехолдер"]
    # Only one [c1] block in the formatted output.
    assert block.count("[1]") == 1
    # And we should have other chunk too.
    assert "[2] Другой чанк" in block


@pytest.mark.asyncio
async def test_prefill_rag_returns_queries_with_empty_block_when_no_hits(
    db_session: AsyncSession,
):
    """If retrieval returned no hits, the function still emits the queries
    (so the UI can show 'we tried these and found nothing') but the block
    is empty so we don't add a useless RAG section to system_prompt.
    """
    with (
        patch(
            "app.api.chat.get_allowed_tag_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "app.api.chat.retrieve_multi_vault",
            new=AsyncMock(return_value=[]),
        ),
    ):
        queries, block = await _prefill_rag(
            original_query="Beholder",
            vault_ids=["v1"],
            domain_id="dnd",
            campaign_id=str(uuid.uuid4()),
            db=db_session,
        )
    assert queries == ["Beholder"]
    assert block == ""


@pytest.mark.asyncio
async def test_prefill_rag_uses_full_domain_when_campaign_has_no_tags(
    db_session: AsyncSession,
):
    """If `get_allowed_tag_ids` returns an empty set, document_ids is None
    and we fall back to full-domain search. We assert by capturing the
    `document_ids` argument passed to retrieve_multi_vault.
    """
    captured_kwargs: dict = {}

    async def fake_retrieve(query, vault_ids, **kwargs):
        captured_kwargs.update(kwargs)
        return [_hit("c1", "Beholder")]

    with (
        patch(
            "app.api.chat.get_allowed_tag_ids",
            new=AsyncMock(return_value=set()),  # no tags
        ),
        patch("app.api.chat.retrieve_multi_vault", new=fake_retrieve),
    ):
        await _prefill_rag(
            original_query="Beholder",
            vault_ids=["v1"],
            domain_id="dnd",
            campaign_id=str(uuid.uuid4()),
            db=db_session,
        )

    # document_ids should be None (full domain).
    assert captured_kwargs.get("document_ids") is None


@pytest.mark.asyncio
async def test_prefill_rag_uses_campaign_scope_when_tags_present(
    db_session: AsyncSession,
):
    """If the campaign has tags, document_ids is restricted to those docs.
    We assert by capturing the `document_ids` argument.
    """
    tag_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    captured_kwargs: dict = {}

    async def fake_retrieve(query, vault_ids, **kwargs):
        captured_kwargs.update(kwargs)
        return [_hit("c1", "Beholder")]

    with (
        patch(
            "app.api.chat.get_allowed_tag_ids",
            new=AsyncMock(return_value={tag_id}),
        ),
        patch(
            "app.api.chat.get_document_ids_by_tags",
            new=AsyncMock(return_value=[doc_id]),
        ),
        patch("app.api.chat.retrieve_multi_vault", new=fake_retrieve),
    ):
        await _prefill_rag(
            original_query="Beholder",
            vault_ids=["v1"],
            domain_id="dnd",
            campaign_id=str(uuid.uuid4()),
            db=db_session,
        )

    assert captured_kwargs.get("document_ids") == [doc_id]


@pytest.mark.asyncio
async def test_prefill_rag_swallows_retrieval_exception(
    db_session: AsyncSession,
):
    """If anything in the retrieval path raises, we return queries (so the
    UI can show 'we tried these') but no block (no fake evidence injected
    into system_prompt). The host must not crash the chat turn.
    """
    with (
        patch(
            "app.api.chat.get_allowed_tag_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "app.api.chat.retrieve_multi_vault",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ),
    ):
        queries, block = await _prefill_rag(
            original_query="Beholder",
            vault_ids=["v1"],
            domain_id="dnd",
            campaign_id=str(uuid.uuid4()),
            db=db_session,
        )
    # Queries were already built (cheap LLM call) before retrieval, so
    # the UI can still report them; the block is empty so we don't put
    # garbage into system_prompt.
    assert queries == ["Beholder"]
    assert block == ""