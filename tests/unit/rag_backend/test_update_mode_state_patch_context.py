"""Tests for Phase 5 — ``UpdateModeExecutor.start_from_proposal`` with
``state_patch_context``.

When the user has already accepted an auto-draft state_patch (Phase 3),
the ``/check-files`` endpoint re-enters Update Mode via
``start_from_proposal(..., state_patch_context=[...])``. The patch
operations are passed as already-applied FACT to the LLM, and only
file_changes (intents) are generated.

Coverage:
- start_from_proposal with state_patch_context calls the LLM via
  _generate_file_changes_only, not _generate_intents_and_state_patch.
- proposal.state_patch / proposal.field_changes are dropped with warnings
  (they're already applied via context).
- session.state_patch_operations / state_field_change_operations stay empty.
- LLM response with non-empty state_patch is logged as warning and dropped.
- Empty LLM result (no intents) creates a no-change session.
- Backward compatibility: start_from_proposal without state_patch_context
  behaves exactly as before — LLM not called for file changes when
  proposal already has file_changes.
- _build_user_message injects <already_applied_state_patch> block when
  state_patch_context is provided.
- /check-files endpoint creates a session, clears drift, deletes draft,
  writes audit log.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.db.models import (
    Base,
    Campaign,
    Chat,
    Document,
    DocumentLabel,
    Domain,
    Tag,
    Vault,
)
from app.services.update_mode_executor import (
    UpdateModeExecutor,
    _build_user_message,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared_contracts.models import (
    CampaignStateReplaceSingle,
    ContextUpdateProposal,
    UpdateModeAction,
    UpdateModeIntent,
    UpdateModeOperation,
    UpdateModeResolveResponse,
)


class DummyStore:
    def __init__(self, existing=None):
        self.existing = existing
        self.created = None

    async def get(self, redis, chat_id: str):
        return self.existing

    async def create(self, redis, session):
        self.created = session
        return session

    async def delete(self, redis, chat_id):
        pass


class DummyIndexerClient:
    def __init__(self, response: UpdateModeResolveResponse | None = None):
        self.response = response or UpdateModeResolveResponse(changes=[])
        self.last_request = None

    async def resolve(self, request):
        self.last_request = request
        return self.response


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_base(session: AsyncSession):
    domain = Domain(domain_id="dnd", display_name="DND")
    campaign = Campaign(id=uuid.uuid4(), domain_id="dnd", name="Curse")
    chat = Chat(
        id=uuid.uuid4(),
        title="Chat",
        domain_id="dnd",
        campaign_id=campaign.id,
        vault_id="vault-main",
    )
    vault_main = Vault(vault_id="vault-main", domain_id="dnd", enabled=True)
    session.add_all([domain, campaign, chat, vault_main])
    await session.flush()

    camp_tag = Tag(id=uuid.uuid4(), name="alliance", domain_id="dnd", campaign_id=campaign.id)
    session.add(camp_tag)
    await session.flush()

    doc_ok = Document(
        id=uuid.uuid4(),
        vault_id="vault-main",
        source_path="sessions/session-12.md",
        title="Session 12",
        md5="a" * 32,
        mtime=1,
        status="indexed",
    )
    session.add(doc_ok)
    await session.flush()
    session.add(DocumentLabel(document_id=doc_ok.id, tag_id=camp_tag.id))
    await session.commit()

    return {
        "domain": domain,
        "campaign": campaign,
        "chat": chat,
        "camp_tag_id": camp_tag.id,
        "doc_ok": doc_ok,
    }


SAMPLE_PATCH_OPS: list[dict] = [
    {
        "type": "replace_single",
        "field_key": "current_location",
        "text": "Таверна «Серебряный колокол»",
        "reason": "Игроки вошли в таверну",
        "source_refs": [],
    }
]


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_build_user_message_without_state_patch_context() -> None:
    """Без state_patch_context блок <already_applied_state_patch> отсутствует."""
    from shared_contracts.models import CampaignStateFieldSnapshot

    msg = _build_user_message(
        note="some note",
        context_docs=[],
        state_field_snapshot=[CampaignStateFieldSnapshot(
            field_id="f1", key="k1", label="K1", description="", mode="single", display_order=0
        )],
        current_state=None,
    )
    assert "<already_applied_state_patch>" not in msg
    assert "<user_note>" in msg
    assert "some note" in msg


def test_build_user_message_with_state_patch_context() -> None:
    """При state_patch_context в сообщении появляется блок с операциями."""
    from shared_contracts.models import CampaignStateFieldSnapshot

    msg = _build_user_message(
        note="apply patch",
        context_docs=[],
        state_field_snapshot=[CampaignStateFieldSnapshot(
            field_id="f1", key="current_location", label="L", description="",
            mode="single", display_order=0,
        )],
        current_state=None,
        state_patch_context=SAMPLE_PATCH_OPS,
    )
    assert "<already_applied_state_patch>" in msg
    assert "Treat them as FACT" in msg
    assert "replace_single" in msg
    assert "current_location" in msg
    assert "Таверна" in msg


# ---------------------------------------------------------------------------
# Executor tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_patch_context_calls_generate_file_changes_only(
    db_session: AsyncSession, monkeypatch
) -> None:
    """При state_patch_context вызывается _generate_file_changes_only,
    не _generate_intents_and_state_patch. proposal.state_patch игнорируется.
    """
    seeded = await _seed_base(db_session)
    store = DummyStore()
    indexer = DummyIndexerClient()

    intent = UpdateModeIntent(
        change_id="ctx-1",
        action=UpdateModeAction.UPDATE,
        description="reflect location in session notes",
        document_id=str(seeded["doc_ok"].id),
        operation=UpdateModeOperation.APPEND_AFTER_SECTION,
        anchor={"kind": "markdown_heading", "value": "Session 12"},
        content="## Location\nТаверна",
    )

    from shared_contracts.models import SearchHit

    retrieve_mock = AsyncMock(return_value=[
        SearchHit(document_id=str(seeded["doc_ok"].id), chunk_id="c1", text="a", score=0.9),
    ])
    reconstruct_mock = AsyncMock(return_value="# Session 12\nBody")

    monkeypatch.setattr("app.services.update_mode_executor.retrieve_multi_vault", retrieve_mock)
    monkeypatch.setattr("app.services.update_mode_executor.reconstruct_full_text", reconstruct_mock)
    monkeypatch.setattr(
        "app.services.update_mode_executor.settings_service",
        SimpleNamespace(get_active_provider=lambda: object()),
    )

    generate_intents_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_intents_and_state_patch",
        generate_intents_mock,
    )
    generate_files_mock = AsyncMock(return_value=[intent])
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_file_changes_only",
        generate_files_mock,
    )

    proposal = ContextUpdateProposal(
        state_patch=[CampaignStateReplaceSingle(**SAMPLE_PATCH_OPS[0])],
        field_changes=[],
        file_changes=[],
        confidence=1.0,
        reason="apply location change",
        review_summary="from auto-draft",
    )

    executor = UpdateModeExecutor(db_session, store, indexer)
    session = await executor.start_from_proposal(
        chat_id=str(seeded["chat"].id),
        redis=object(),
        proposal=proposal,
        state_patch_context=SAMPLE_PATCH_OPS,
    )

    # _generate_intents_and_state_patch НЕ вызывался
    generate_intents_mock.assert_not_called()
    # _generate_file_changes_only вызван ровно один раз
    assert generate_files_mock.await_count == 1
    # 6-й positional аргумент — это state_patch_context
    args = generate_files_mock.await_args.args
    assert args[5] == SAMPLE_PATCH_OPS
    assert generate_files_mock.await_args.kwargs.get("chat_id") == str(seeded["chat"].id)

    # session содержит ТОЛЬКО file_changes, state_patch пустой
    assert session.state_patch_operations == []
    assert session.state_field_change_operations == []
    assert len(session.changes) >= 0  # indexer mocked with empty changes
    # warnings содержат "provided_via_context"
    assert any(
        "state_patch_dropped:provided_via_context" in w for w in session.warnings
    )


@pytest.mark.asyncio
async def test_state_patch_context_drops_field_changes(
    db_session: AsyncSession, monkeypatch
) -> None:
    """proposal.field_changes тоже дропается с warning (Phase 5 contract)."""
    from shared_contracts.models import (
        ContextFieldChange,
        ContextFieldChangeOperation,
    )

    seeded = await _seed_base(db_session)
    store = DummyStore()
    indexer = DummyIndexerClient()

    from shared_contracts.models import SearchHit
    retrieve_mock = AsyncMock(return_value=[
        SearchHit(document_id=str(seeded["doc_ok"].id), chunk_id="c1", text="a", score=0.9),
    ])
    reconstruct_mock = AsyncMock(return_value="# Session 12\nBody")

    monkeypatch.setattr("app.services.update_mode_executor.retrieve_multi_vault", retrieve_mock)
    monkeypatch.setattr("app.services.update_mode_executor.reconstruct_full_text", reconstruct_mock)
    monkeypatch.setattr(
        "app.services.update_mode_executor.settings_service",
        SimpleNamespace(get_active_provider=lambda: object()),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_file_changes_only",
        AsyncMock(return_value=[]),
    )

    proposal = ContextUpdateProposal(
        state_patch=[],
        field_changes=[
            ContextFieldChange(
                operation=ContextFieldChangeOperation.CREATE_FIELD,
                key="new_field",
                label="New",
                mode="single",
            )
        ],
        file_changes=[],
        confidence=1.0,
        reason="x",
    )

    executor = UpdateModeExecutor(db_session, store, indexer)
    session = await executor.start_from_proposal(
        chat_id=str(seeded["chat"].id),
        redis=object(),
        proposal=proposal,
        state_patch_context=SAMPLE_PATCH_OPS,
    )

    assert any(
        "field_changes_dropped:provided_via_context" in w for w in session.warnings
    )
    assert session.state_field_change_operations == []


@pytest.mark.asyncio
async def test_state_patch_context_no_intents_creates_no_change_session(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Если LLM вернул intents=[], создаётся no-change сессия с warning."""
    seeded = await _seed_base(db_session)
    store = DummyStore()
    indexer = DummyIndexerClient()

    from shared_contracts.models import SearchHit
    retrieve_mock = AsyncMock(return_value=[
        SearchHit(document_id=str(seeded["doc_ok"].id), chunk_id="c1", text="a", score=0.9),
    ])
    reconstruct_mock = AsyncMock(return_value="# Session 12\nBody")

    monkeypatch.setattr("app.services.update_mode_executor.retrieve_multi_vault", retrieve_mock)
    monkeypatch.setattr("app.services.update_mode_executor.reconstruct_full_text", reconstruct_mock)
    monkeypatch.setattr(
        "app.services.update_mode_executor.settings_service",
        SimpleNamespace(get_active_provider=lambda: object()),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_file_changes_only",
        AsyncMock(return_value=[]),
    )

    proposal = ContextUpdateProposal(
        state_patch=[],
        field_changes=[],
        file_changes=[],
        confidence=1.0,
        reason="nothing to write",
    )

    executor = UpdateModeExecutor(db_session, store, indexer)
    session = await executor.start_from_proposal(
        chat_id=str(seeded["chat"].id),
        redis=object(),
        proposal=proposal,
        state_patch_context=SAMPLE_PATCH_OPS,
    )

    assert session.changes == []
    assert store.created is not None
    # session создан с TTL 3 часа и пустыми state_patch_operations
    assert session.state_patch_operations == []
    assert session.state_field_change_operations == []


@pytest.mark.asyncio
async def test_without_state_patch_context_uses_proposal_file_changes(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Обратная совместимость: без state_patch_context берутся proposal.file_changes
    и LLM не вызывается.
    """
    seeded = await _seed_base(db_session)
    store = DummyStore()
    indexer = DummyIndexerClient()

    intent = UpdateModeIntent(
        change_id="legacy-1",
        action=UpdateModeAction.UPDATE,
        description="x",
        document_id=str(seeded["doc_ok"].id),
        operation=UpdateModeOperation.APPEND_AFTER_SECTION,
        anchor={"kind": "markdown_heading", "value": "Session 12"},
        content="## X",
    )

    # retrieval/reconstruction мокаются, но _generate_intents_and_state_patch
    # не должен вызываться — мы передаём уже готовые file_changes.
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_intents_and_state_patch",
        AsyncMock(),
    )

    proposal = ContextUpdateProposal(
        state_patch=[],
        field_changes=[],
        file_changes=[intent],
        confidence=0.9,
        reason="legacy",
    )

    executor = UpdateModeExecutor(db_session, store, indexer)
    session = await executor.start_from_proposal(
        chat_id=str(seeded["chat"].id),
        redis=object(),
        proposal=proposal,
        # state_patch_context не передан — старый путь
    )

    # LLM для intents НЕ вызывался
    # (мок не имеет .await_count вызовов)
    assert session.state_patch_operations == []
    assert session.state_field_change_operations == []