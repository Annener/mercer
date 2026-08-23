from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import (
    Base,
    Campaign,
    Chat,
    Document,
    DocumentLabel,
    Domain,
    Tag,
    Vault,
    campaign_tags,
)
from app.services.update_mode_executor import (
    UpdateModeCampaignDomainMismatchError,
    UpdateModeCampaignRequiredError,
    UpdateModeExecutor,
    UpdateModeGenerationProviderUnavailableError,
    UpdateModeInvalidGenerationOutputError,
    UpdateModeNoEnabledVaultsError,
    UpdateModeNoIndexedMarkdownError,
    UpdateModeNoUsableContextError,
    UpdateModeSessionAlreadyActiveError,
)
from shared_contracts.models import (
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeChangeStatus,
    UpdateModeIntent,
    UpdateModeOperation,
    UpdateModeResolveResponse,
)


class DummyStore:
    def __init__(self, existing=None, fail_create: bool = False):
        self.existing = existing
        self.fail_create = fail_create
        self.created = None

    async def get(self, redis, chat_id: str):
        return self.existing

    async def create(self, redis, session):
        if self.fail_create:
            raise RuntimeError("redis down")
        self.created = session
        return session


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
    vault_side = Vault(vault_id="vault-side", domain_id="dnd", enabled=True)
    vault_other = Vault(vault_id="vault-other", domain_id="other", enabled=True)
    session.add_all([domain, campaign, chat, vault_main, vault_side, vault_other])
    await session.flush()

    camp_tag = Tag(id=uuid.uuid4(), name="alliance", domain_id="dnd", campaign_id=campaign.id)
    global_tag = Tag(id=uuid.uuid4(), name="city", domain_id="dnd", campaign_id=None)
    session.add_all([camp_tag, global_tag])
    await session.flush()
    await session.execute(
        campaign_tags.insert().values(campaign_id=campaign.id, tag_id=global_tag.id)
    )

    doc_ok = Document(
        id=uuid.uuid4(),
        vault_id="vault-main",
        source_path="sessions/session-12.md",
        title="Session 12",
        md5="a" * 32,
        mtime=1,
        status="indexed",
    )
    doc_ok_2 = Document(
        id=uuid.uuid4(),
        vault_id="vault-side",
        source_path="notes/city.md",
        title="City",
        md5="b" * 32,
        mtime=1,
        status="indexed",
    )
    doc_pdf = Document(
        id=uuid.uuid4(),
        vault_id="vault-main",
        source_path="files/scan.pdf",
        title="Scan",
        md5="c" * 32,
        mtime=1,
        status="indexed",
    )
    doc_pending = Document(
        id=uuid.uuid4(),
        vault_id="vault-main",
        source_path="drafts/todo.md",
        title="Todo",
        md5="d" * 32,
        mtime=1,
        status="pending",
    )
    doc_other_domain = Document(
        id=uuid.uuid4(),
        vault_id="vault-other",
        source_path="other/foreign.md",
        title="Foreign",
        md5="e" * 32,
        mtime=1,
        status="indexed",
    )
    session.add_all([doc_ok, doc_ok_2, doc_pdf, doc_pending, doc_other_domain])
    await session.flush()

    session.add_all([
        DocumentLabel(document_id=doc_ok.id, tag_id=camp_tag.id),
        DocumentLabel(document_id=doc_ok_2.id, tag_id=global_tag.id),
        DocumentLabel(document_id=doc_pdf.id, tag_id=camp_tag.id),
        DocumentLabel(document_id=doc_pending.id, tag_id=camp_tag.id),
        DocumentLabel(document_id=doc_other_domain.id, tag_id=camp_tag.id),
    ])
    await session.commit()

    return {
        "domain": domain,
        "campaign": campaign,
        "chat": chat,
        "camp_tag_id": camp_tag.id,
        "doc_ok": doc_ok,
        "doc_ok_2": doc_ok_2,
        "doc_pdf": doc_pdf,
        "doc_pending": doc_pending,
        "doc_other_domain": doc_other_domain,
    }


@pytest.mark.asyncio
async def test_start_blocks_existing_session(db_session: AsyncSession, monkeypatch):
    await _seed_base(db_session)
    store = DummyStore(existing=object())
    executor = UpdateModeExecutor(db_session, store, DummyIndexerClient())

    with pytest.raises(UpdateModeSessionAlreadyActiveError):
        await executor.start("9f7c11a2-2c9e-46c6-b278-9cfe5c2d7ca4", object(), "note")


@pytest.mark.asyncio
async def test_start_requires_campaign(db_session: AsyncSession):
    domain = Domain(domain_id="dnd", display_name="DND")
    chat = Chat(id=uuid.uuid4(), title="Chat", domain_id="dnd", campaign_id=None)
    db_session.add_all([domain, chat])
    await db_session.commit()

    executor = UpdateModeExecutor(db_session, DummyStore(), DummyIndexerClient())
    with pytest.raises(UpdateModeCampaignRequiredError):
        await executor.start(str(chat.id), object(), "note")


@pytest.mark.asyncio
async def test_start_detects_campaign_domain_mismatch(db_session: AsyncSession):
    domain = Domain(domain_id="dnd", display_name="DND")
    other = Domain(domain_id="other", display_name="Other")
    campaign = Campaign(id=uuid.uuid4(), domain_id="other", name="Bad")
    chat = Chat(id=uuid.uuid4(), title="Chat", domain_id="dnd", campaign_id=campaign.id)
    db_session.add_all([domain, other, campaign, chat])
    await db_session.commit()

    executor = UpdateModeExecutor(db_session, DummyStore(), DummyIndexerClient())
    with pytest.raises(UpdateModeCampaignDomainMismatchError):
        await executor.start(str(chat.id), object(), "note")


@pytest.mark.asyncio
async def test_start_requires_enabled_vaults(db_session: AsyncSession):
    domain = Domain(domain_id="dnd", display_name="DND")
    campaign = Campaign(id=uuid.uuid4(), domain_id="dnd", name="Camp")
    chat = Chat(id=uuid.uuid4(), title="Chat", domain_id="dnd", campaign_id=campaign.id)
    tag = Tag(id=uuid.uuid4(), name="alliance", domain_id="dnd", campaign_id=campaign.id)
    db_session.add_all([domain, campaign, chat, tag])
    await db_session.commit()

    executor = UpdateModeExecutor(db_session, DummyStore(), DummyIndexerClient())
    with pytest.raises(UpdateModeNoEnabledVaultsError):
        await executor.start(str(chat.id), object(), "note")


@pytest.mark.asyncio
async def test_start_requires_indexed_markdown_docs(db_session: AsyncSession):
    seeded = await _seed_base(db_session)
    await db_session.delete(seeded["doc_ok"])
    await db_session.delete(seeded["doc_ok_2"])
    await db_session.commit()

    executor = UpdateModeExecutor(db_session, DummyStore(), DummyIndexerClient())
    with pytest.raises(UpdateModeNoIndexedMarkdownError):
        await executor.start(str(seeded["chat"].id), object(), "note")


@pytest.mark.asyncio
async def test_start_passes_only_allowed_doc_ids_and_vault_ids(db_session: AsyncSession, monkeypatch):
    """Только разрешённые doc_ids (campaign-scoped, .md, indexed) и активные vault'ы
    передаются в retrieve_multi_vault и в indexer.

    По seed-данным только doc_ok помечен campaign-тегом и попадает в allowed.
    PDF, pending и foreign-domain документы отфильтрованы.
    """
    seeded = await _seed_base(db_session)
    store = DummyStore()
    indexer = DummyIndexerClient(
        UpdateModeResolveResponse(
            changes=[
                ResolvedUpdateModeChange(
                    change_id="chg-1",
                    vault_id="vault-main",
                    document_id=str(seeded["doc_ok"].id),
                    file_path="sessions/session-12.md",
                    action=UpdateModeAction.UPDATE,
                    description="append alliance",
                    proposed_content="## Alliance\nText",
                    unified_diff="diff",
                    status=UpdateModeChangeStatus.PENDING,
                )
            ]
        )
    )

    # Retrieve возвращает несколько hit'ов, но в allowed попадает только doc_ok.
    from shared_contracts.models import SearchHit
    retrieve_mock = AsyncMock(return_value=[
        SearchHit(document_id=str(seeded["doc_ok"].id), chunk_id="c1", text="a", score=0.9),
    ])
    reconstruct_mock = AsyncMock(side_effect=lambda document_id, vault_id, db_api_url: {
        str(seeded["doc_ok"].id): "# Session 12\nBody",
    }.get(document_id, ""))

    intent = UpdateModeIntent(
        change_id="chg-1",
        action=UpdateModeAction.UPDATE,
        description="append alliance",
        document_id=str(seeded["doc_ok"].id),
        operation=UpdateModeOperation.APPEND_AFTER_SECTION,
        anchor={"kind": "markdown_heading", "value": "Session 12"},
        content="## Alliance\nText",
    )

    monkeypatch.setattr("app.services.update_mode_executor.retrieve_multi_vault", retrieve_mock)
    monkeypatch.setattr("app.services.update_mode_executor.reconstruct_full_text", reconstruct_mock)
    monkeypatch.setattr(
        "app.services.update_mode_executor.settings_service",
        SimpleNamespace(get_active_provider=lambda: object()),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_intents_and_state_patch",
        AsyncMock(return_value=SimpleNamespace(intents=[intent], no_change_reason=None, state_patch=[])),
    )

    executor = UpdateModeExecutor(db_session, store, indexer)
    session = await executor.start(str(seeded["chat"].id), object(), "alliance note")

    # retrieve_multi_vault получил query, vault_ids (positional) и document_ids (kw).
    retrieve_args = retrieve_mock.await_args.args
    retrieve_kwargs = retrieve_mock.await_args.kwargs
    assert retrieve_args[1] == ["vault-main", "vault-side"]
    allowed_doc_ids = set(retrieve_kwargs["document_ids"])
    # Только doc_ok помечен campaign-тегом (camp_tag.campaign_id == chat.campaign_id),
    # остальные документы отфильтрованы по одному из критериев.
    assert allowed_doc_ids == {str(seeded["doc_ok"].id)}
    assert str(seeded["doc_pdf"].id) not in allowed_doc_ids  # не .md
    assert str(seeded["doc_other_domain"].id) not in allowed_doc_ids  # другой домен
    assert str(seeded["doc_pending"].id) not in allowed_doc_ids  # не indexed
    # Indexer получил только активные vault'ы и разрешённые документы
    assert set(indexer.last_request.vault_ids) == {"vault-main", "vault-side"}
    assert indexer.last_request.candidate_document_ids == [str(seeded["doc_ok"].id)]
    # Session содержит только разрешённые doc_ids
    assert session.candidate_document_ids == [str(seeded["doc_ok"].id)]


@pytest.mark.asyncio
async def test_start_skips_oversized_document_and_sets_warning(db_session: AsyncSession, monkeypatch):
    """Документ, превышающий per-doc token limit, отбрасывается с warning;
    остальные документы из allowed остаются в session.candidate_document_ids.
    """
    seeded = await _seed_base(db_session)

    # Добавляем второй документ, помеченный тем же campaign-тегом —
    # чтобы после отбрасывания oversized doc остался хотя бы один usable.
    from app.db.models import Document, DocumentLabel, Tag
    extra_doc = Document(
        id=uuid.uuid4(),
        vault_id="vault-main",
        source_path="sessions/session-13.md",
        title="Session 13",
        md5="f" * 32,
        mtime=1,
        status="indexed",
    )
    db_session.add(extra_doc)
    await db_session.flush()
    db_session.add(DocumentLabel(document_id=extra_doc.id, tag_id=seeded["camp_tag_id"]))
    await db_session.commit()

    store = DummyStore()
    indexer = DummyIndexerClient()

    from shared_contracts.models import SearchHit
    retrieve_mock = AsyncMock(return_value=[
        SearchHit(document_id=str(seeded["doc_ok"].id), chunk_id="c1", text="a", score=0.9),
        SearchHit(document_id=str(extra_doc.id), chunk_id="c2", text="b", score=0.8),
    ])
    big_text = "x" * (4 * 200_000)  # 200K токенов — больше _PER_DOC_TOKEN_LIMIT

    async def _reconstruct(document_id, vault_id, db_api_url):
        if document_id == str(seeded["doc_ok"].id):
            return big_text
        if document_id == str(extra_doc.id):
            return "# Session 13\nBody"
        return ""

    reconstruct_mock = AsyncMock(side_effect=_reconstruct)

    # Intent ссылается на extra_doc, потому что doc_ok отбрасывается как oversized.
    intent = UpdateModeIntent(
        change_id="chg-1",
        action=UpdateModeAction.UPDATE,
        description="append alliance",
        document_id=str(extra_doc.id),
        operation=UpdateModeOperation.APPEND_AFTER_SECTION,
        anchor={"kind": "markdown_heading", "value": "Session 13"},
        content="## Alliance\nText",
    )

    monkeypatch.setattr("app.services.update_mode_executor.retrieve_multi_vault", retrieve_mock)
    monkeypatch.setattr("app.services.update_mode_executor.reconstruct_full_text", reconstruct_mock)
    monkeypatch.setattr(
        "app.services.update_mode_executor.settings_service",
        SimpleNamespace(get_active_provider=lambda: object()),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_intents_and_state_patch",
        AsyncMock(return_value=SimpleNamespace(intents=[intent], no_change_reason=None, state_patch=[])),
    )

    executor = UpdateModeExecutor(db_session, store, indexer)
    session = await executor.start(str(seeded["chat"].id), object(), "note")

    assert any(w.startswith("document_too_large_for_update_mode:") for w in session.warnings)
    # Oversized документ отброшен
    assert str(seeded["doc_ok"].id) not in session.candidate_document_ids
    # Другие разрешённые документы остались
    assert str(extra_doc.id) in session.candidate_document_ids


@pytest.mark.asyncio
async def test_start_fails_when_no_usable_context(db_session: AsyncSession, monkeypatch):
    seeded = await _seed_base(db_session)

    monkeypatch.setattr(
        "app.services.update_mode_executor.retrieve_multi_vault",
        AsyncMock(return_value=[SimpleNamespace(document_id=str(seeded["doc_ok"].id))]),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor.reconstruct_full_text",
        AsyncMock(return_value=""),
    )

    executor = UpdateModeExecutor(db_session, DummyStore(), DummyIndexerClient())
    with pytest.raises(UpdateModeNoUsableContextError):
        await executor.start(str(seeded["chat"].id), object(), "note")


@pytest.mark.asyncio
async def test_start_requires_active_provider(db_session: AsyncSession, monkeypatch):
    seeded = await _seed_base(db_session)
    monkeypatch.setattr(
        "app.services.update_mode_executor.retrieve_multi_vault",
        AsyncMock(return_value=[SimpleNamespace(document_id=str(seeded["doc_ok"].id))]),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor.reconstruct_full_text",
        AsyncMock(return_value="# Session 12\nBody"),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor.settings_service",
        SimpleNamespace(get_active_provider=lambda: None),
    )

    executor = UpdateModeExecutor(db_session, DummyStore(), DummyIndexerClient())
    with pytest.raises(UpdateModeGenerationProviderUnavailableError):
        await executor.start(str(seeded["chat"].id), object(), "note")


@pytest.mark.asyncio
async def test_start_rejects_unknown_document_id_from_llm(db_session: AsyncSession, monkeypatch):
    seeded = await _seed_base(db_session)
    monkeypatch.setattr(
        "app.services.update_mode_executor.retrieve_multi_vault",
        AsyncMock(return_value=[SimpleNamespace(document_id=str(seeded["doc_ok"].id))]),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor.reconstruct_full_text",
        AsyncMock(return_value="# Session 12\nBody"),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor.settings_service",
        SimpleNamespace(get_active_provider=lambda: object()),
    )
    bad_intent = UpdateModeIntent(
        change_id="bad-1",
        action=UpdateModeAction.UPDATE,
        description="bad target",
        document_id=str(uuid.uuid4()),
        operation=UpdateModeOperation.APPEND_AFTER_SECTION,
        anchor={"kind": "markdown_heading", "value": "Session 12"},
        content="## X\nY",
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_intents_and_state_patch",
        AsyncMock(return_value=SimpleNamespace(intents=[bad_intent], no_change_reason=None, state_patch=[])),
    )

    executor = UpdateModeExecutor(db_session, DummyStore(), DummyIndexerClient())
    with pytest.raises(UpdateModeInvalidGenerationOutputError):
        await executor.start(str(seeded["chat"].id), object(), "note")


@pytest.mark.asyncio
async def test_start_no_change_creates_empty_session(db_session: AsyncSession, monkeypatch):
    seeded = await _seed_base(db_session)
    store = DummyStore()
    monkeypatch.setattr(
        "app.services.update_mode_executor.retrieve_multi_vault",
        AsyncMock(return_value=[SimpleNamespace(document_id=str(seeded["doc_ok"].id))]),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor.reconstruct_full_text",
        AsyncMock(return_value="# Session 12\nBody"),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor.settings_service",
        SimpleNamespace(get_active_provider=lambda: object()),
    )
    monkeypatch.setattr(
        "app.services.update_mode_executor._generate_intents_and_state_patch",
        AsyncMock(return_value=SimpleNamespace(intents=[], no_change_reason="nothing actionable", state_patch=[])),
    )

    executor = UpdateModeExecutor(db_session, store, DummyIndexerClient())
    session = await executor.start(str(seeded["chat"].id), object(), "note")

    assert session.changes == []
    assert any(w == "no_change:nothing actionable" for w in session.warnings)
    assert store.created is not None
    assert int((session.expires_at - session.created_at).total_seconds()) == 3 * 3600
