"""Tests for `DELETE /api/chats/{chat_id}` cleanup behaviour.

When a chat is deleted we also drop its `update_mode:{chat_id}` Redis
key. Otherwise the next chat created with the same id inherits a stale
session and the proposal flow breaks (3-hour TTL).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from app.api.chat import router as chat_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_app(redis: AsyncMock, db_session: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.state.redis = redis

    from app.db.session import get_db

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


def _build_db_session(chat_id: uuid.UUID) -> AsyncMock:
    """Mock the AsyncSession enough for `_get_chat_or_404` + `db.delete` +
    `db.commit` to succeed. We resolve to a Chat ORM instance via `db.get`.
    """
    from app.db.models import Chat as ChatModel

    chat = ChatModel(
        id=chat_id,
        title="To delete",
        domain_id="work",
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)
    session.delete = AsyncMock(return_value=None)
    session.commit = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_delete_chat_clears_update_mode_redis_key() -> None:
    """The chat DELETE endpoint must remove `update_mode:{chat_id}` from
    Redis so the next chat with the same id starts clean.
    """
    chat_id = uuid.uuid4()
    db_session = _build_db_session(chat_id)
    redis = AsyncMock()
    redis.delete = AsyncMock(return_value=1)
    app = _make_app(redis, db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete(f"/chat/{chat_id}")

    assert resp.status_code == 204
    redis.delete.assert_any_await(f"update_mode:{chat_id}")


@pytest.mark.asyncio
async def test_delete_chat_succeeds_when_redis_unavailable() -> None:
    """A Redis outage must not block chat deletion. The DB row goes, the
    stale Redis key will time out on its own.
    """
    chat_id = uuid.uuid4()
    db_session = _build_db_session(chat_id)
    redis = AsyncMock()
    redis.delete = AsyncMock(side_effect=ConnectionError("redis down"))
    app = _make_app(redis, db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete(f"/chat/{chat_id}")

    assert resp.status_code == 204