"""Tests for GET /chat/list endpoint with campaign_id filter.

Covers the new filter logic added to support campaign-scoped chat lists:
- `campaign_id=<UUID>` → only chats in that campaign
- `campaign_id=__none__` → only chats without campaign_id (general mode)
- `campaign_id` invalid → 422
- No `campaign_id` param → all chats (in domain)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.api.chat import router
from app.db.models import Base, Chat, Domain
from app.db.session import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture()
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture()
def app_client(db_session):
    """TestClient with overridden get_db dependency."""
    test_app = FastAPI()
    test_app.include_router(router)

    async def override_get_db():
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db
    client = TestClient(test_app)
    yield client
    client.close()


async def _seed_domain(session: AsyncSession, domain_id: str) -> Domain:
    domain = Domain(
        domain_id=domain_id,
        display_name=domain_id.upper(),
        is_system=False,
    )
    session.add(domain)
    await session.commit()
    return domain


async def _seed_chat(
    session: AsyncSession,
    domain_id: str,
    campaign_id: uuid.UUID | None,
    title: str = "Test",
) -> Chat:
    chat = Chat(
        title=title,
        domain_id=domain_id,
        campaign_id=campaign_id,
    )
    session.add(chat)
    await session.commit()
    return chat


@pytest.mark.asyncio
async def test_list_chats_no_filter_returns_all_in_domain(db_session, app_client):
    """Без фильтра возвращаются все чаты домена."""
    await _seed_domain(db_session, "dnd")
    campaign_a = uuid.uuid4()
    campaign_b = uuid.uuid4()
    await _seed_chat(db_session, "dnd", campaign_a, "Chat A")
    await _seed_chat(db_session, "dnd", campaign_b, "Chat B")
    await _seed_chat(db_session, "dnd", None, "Chat General")
    # Чат в другом домене — не должен попасть в выдачу
    await _seed_domain(db_session, "work")
    await _seed_chat(db_session, "work", None, "Chat Work")

    with patch("app.api.chat.settings_service.get", new_callable=AsyncMock, return_value=False):
        resp = app_client.get("/chat/list?domain_id=dnd")

    assert resp.status_code == 200
    data = resp.json()
    titles = sorted([c["title"] for c in data["chats"]])
    assert titles == ["Chat A", "Chat B", "Chat General"]


@pytest.mark.asyncio
async def test_list_chats_filter_by_campaign_id(db_session, app_client):
    """Фильтр по конкретному UUID кампании."""
    await _seed_domain(db_session, "dnd")
    campaign_a = uuid.uuid4()
    campaign_b = uuid.uuid4()
    await _seed_chat(db_session, "dnd", campaign_a, "Chat A")
    await _seed_chat(db_session, "dnd", campaign_b, "Chat B")
    await _seed_chat(db_session, "dnd", None, "Chat General")

    with patch("app.api.chat.settings_service.get", new_callable=AsyncMock, return_value=False):
        resp = app_client.get(f"/chat/list?domain_id=dnd&campaign_id={campaign_a}")

    assert resp.status_code == 200
    data = resp.json()
    titles = [c["title"] for c in data["chats"]]
    assert titles == ["Chat A"]


@pytest.mark.asyncio
async def test_list_chats_filter_by_none_sentinel_returns_general_only(
    db_session, app_client
):
    """Sentinel '__none__' возвращает только чаты без campaign_id (общий режим)."""
    await _seed_domain(db_session, "dnd")
    campaign_a = uuid.uuid4()
    await _seed_chat(db_session, "dnd", campaign_a, "Chat A")
    await _seed_chat(db_session, "dnd", None, "Chat General 1")
    await _seed_chat(db_session, "dnd", None, "Chat General 2")

    with patch("app.api.chat.settings_service.get", new_callable=AsyncMock, return_value=False):
        resp = app_client.get("/chat/list?domain_id=dnd&campaign_id=__none__")

    assert resp.status_code == 200
    data = resp.json()
    titles = sorted([c["title"] for c in data["chats"]])
    assert titles == ["Chat General 1", "Chat General 2"]


@pytest.mark.asyncio
async def test_list_chats_invalid_campaign_id_returns_422(db_session, app_client):
    """Невалидный UUID для campaign_id → 422."""
    await _seed_domain(db_session, "dnd")

    with patch("app.api.chat.settings_service.get", new_callable=AsyncMock, return_value=False):
        resp = app_client.get("/chat/list?domain_id=dnd&campaign_id=not-a-uuid")

    assert resp.status_code == 422
    detail = resp.json().get("detail", "")
    assert "Invalid campaign_id" in str(detail)


@pytest.mark.asyncio
async def test_list_chats_combined_domain_and_campaign_filter(db_session, app_client):
    """Фильтр по домену + campaign_id работает совместно."""
    await _seed_domain(db_session, "dnd")
    await _seed_domain(db_session, "work")
    campaign = uuid.uuid4()
    # В dnd: чат в этой кампании + чат без кампании + чат в другой кампании
    await _seed_chat(db_session, "dnd", campaign, "DND Chat in campaign")
    await _seed_chat(db_session, "dnd", None, "DND Chat no campaign")
    await _seed_chat(db_session, "dnd", uuid.uuid4(), "DND Chat other campaign")
    # В work: чат в той же кампании (не должен попасть)
    await _seed_chat(db_session, "work", campaign, "Work Chat in same campaign")

    with patch("app.api.chat.settings_service.get", new_callable=AsyncMock, return_value=False):
        resp = app_client.get(
            f"/chat/list?domain_id=dnd&campaign_id={campaign}"
        )

    assert resp.status_code == 200
    data = resp.json()
    titles = [c["title"] for c in data["chats"]]
    assert titles == ["DND Chat in campaign"]
