"""Sprint 1 — Chat.metadata (scene_state) + Chat.context_update_mode tests.

Covers the model-side contract:
- `metadata_json` defaults to {} when column is absent
- `context_update_mode` defaults to False
- ChatRecord round-trips both fields correctly via validation_alias
- context_update_mode is editable through UpdateChatRequest
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.db.models import Base, Chat
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared_contracts.models import ChatRecord

# ---------------------------------------------------------------------------
# Async DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# ORM defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_metadata_default_is_empty_dict(db_session: AsyncSession):
    """When metadata_json is unset on construction, it must default to {}."""
    chat = Chat(title="t", domain_id="dnd")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    assert chat.metadata_json == {}
    assert chat.context_update_mode is False


@pytest.mark.asyncio
async def test_chat_metadata_json_persists(db_session: AsyncSession):
    chat = Chat(
        title="t",
        domain_id="dnd",
        metadata_json={"scene_state": {"location": "cave"}, "foo": "bar"},
    )
    db_session.add(chat)
    await db_session.commit()
    chat_id = chat.id
    db_session.expire_all()

    reloaded = await db_session.get(Chat, chat_id)
    assert reloaded is not None
    assert reloaded.metadata_json == {"scene_state": {"location": "cave"}, "foo": "bar"}


@pytest.mark.asyncio
async def test_chat_context_update_mode_default_is_false(db_session: AsyncSession):
    chat = Chat(title="t", domain_id="dnd")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    assert chat.context_update_mode is False


@pytest.mark.asyncio
async def test_chat_context_update_mode_can_be_toggled(db_session: AsyncSession):
    chat = Chat(title="t", domain_id="dnd", context_update_mode=True)
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    assert chat.context_update_mode is True


# ---------------------------------------------------------------------------
# ChatRecord roundtrip via Pydantic ORMModel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_record_picks_up_metadata_and_context_update_mode(
    db_session: AsyncSession,
):
    """ChatRecord.model_validate(chat, from_attributes=True) must populate
    both `metadata` and `context_update_mode` from the ORM (with the
    validation_alias -> metadata_json shim).
    """
    chat = Chat(
        title="t",
        domain_id="dnd",
        metadata_json={"scene_state": {"location": "cave"}},
        context_update_mode=True,
    )
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)

    rec = ChatRecord.model_validate(chat, from_attributes=True)
    assert rec.metadata == {"scene_state": {"location": "cave"}}
    assert rec.context_update_mode is True
    assert isinstance(rec.id, str)


def test_chat_record_accepts_dict_construction_with_metadata():
    """Dict-style construction (used in tests) honours the public field names."""
    rec = ChatRecord(
        id=str(uuid.uuid4()),
        title="t",
        domain_id="dnd",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        metadata={"scene_state": {"location": "cave"}},
        context_update_mode=True,
    )
    assert rec.metadata == {"scene_state": {"location": "cave"}}
    assert rec.context_update_mode is True


# ---------------------------------------------------------------------------
# UpdateChatRequest
# ---------------------------------------------------------------------------


def test_update_chat_request_accepts_context_update_mode():
    from app.api.chat import UpdateChatRequest

    req = UpdateChatRequest(context_update_mode=True)
    assert req.context_update_mode is True
    assert req.campaign_id is None
    assert req.full_document_mode_enabled is None


def test_update_chat_request_accepts_all_none():
    from app.api.chat import UpdateChatRequest

    req = UpdateChatRequest()
    assert req.context_update_mode is None
    assert req.campaign_id is None
    assert req.full_document_mode_enabled is None