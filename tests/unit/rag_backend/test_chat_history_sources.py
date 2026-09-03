"""Tests for `GET /api/chat/{chat_id}/history` returning `Message.sources`.

Фикс: история должна возвращать sources для каждого сообщения, чтобы
после reload чата UI мог отрисовать блок "Источники" под ответом
ассистента.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_app(db_session: AsyncMock) -> FastAPI:
    from app.api.chat import router as chat_router

    app = FastAPI()
    app.include_router(chat_router)

    from app.db.session import get_db

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


def _make_chat(chat_id: uuid.UUID) -> MagicMock:
    """Mock-Chat c атрибутами для `ChatRecord.model_validate(from_attributes=True)`."""
    chat = MagicMock()
    chat.id = chat_id
    chat.title = "t"
    chat.domain_id = "dnd"
    chat.vault_id = None
    chat.campaign_id = None
    chat.locked_pipeline_id = None
    chat.pipeline_versions = None
    chat.pipeline_pause_state = None
    chat.pending_pipeline_confirm = None
    chat.full_document_mode_enabled = False
    chat.sent_full_document_ids = []
    chat.metadata_json = {}
    chat.context_update_mode = False
    chat.rag_prefill_enabled = False
    chat.created_at = datetime.now(UTC)
    chat.updated_at = datetime.now(UTC)
    return chat


def _make_message(
    msg_id: uuid.UUID, chat_id: uuid.UUID, sources: list | None
) -> MagicMock:
    msg = MagicMock()
    msg.id = msg_id
    msg.chat_id = chat_id
    msg.role = "assistant"
    msg.content = "ответ"
    msg.created_at = datetime.now(UTC)
    msg.pipeline_id = None
    msg.sources = sources
    return msg


def _build_db_session(chat: MagicMock, messages: list[MagicMock]) -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = messages
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=result_mock)
    return session


import pytest


@pytest.mark.asyncio
async def test_history_returns_sources_for_assistant_message() -> None:
    """Когда Message.sources заполнен — API должен вернуть их в ChatMessage.sources."""
    chat_id = uuid.uuid4()
    msg_id = uuid.uuid4()

    chat = _make_chat(chat_id)
    sources_payload = [
        {"path": "/vault/dnd/file1.md", "page": 1},
        {"path": "/vault/dnd/file2.md", "page": None},
    ]
    msg = _make_message(msg_id, chat_id, sources_payload)
    db_session = _build_db_session(chat, [msg])
    app = _make_app(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/chat/{chat_id}/history")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "messages" in body
    assert len(body["messages"]) == 1
    sources = body["messages"][0]["sources"]
    assert isinstance(sources, list)
    assert len(sources) == 2
    paths = sorted(s["path"] for s in sources)
    assert paths == ["/vault/dnd/file1.md", "/vault/dnd/file2.md"]
    pages = [s.get("page") for s in sources]
    assert 1 in pages
    assert None in pages


@pytest.mark.asyncio
async def test_history_returns_empty_sources_when_message_has_none() -> None:
    """Если Message.sources пустой/None — API возвращает пустой список."""
    chat_id = uuid.uuid4()
    msg_id = uuid.uuid4()

    chat = _make_chat(chat_id)
    msg = _make_message(msg_id, chat_id, None)
    db_session = _build_db_session(chat, [msg])
    app = _make_app(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/chat/{chat_id}/history")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["messages"][0]["sources"] == []


@pytest.mark.asyncio
async def test_history_skips_invalid_source_dicts() -> None:
    """Если в БД мусорные dict — API их молча пропускает, валидные оставляет."""
    chat_id = uuid.uuid4()
    msg_id = uuid.uuid4()

    chat = _make_chat(chat_id)
    msg = _make_message(
        msg_id,
        chat_id,
        [
            {"path": "/vault/ok.md"},
            {"no_path_field": True},  # invalid — MessageSource требует path
            "not a dict",  # invalid
        ],
    )
    db_session = _build_db_session(chat, [msg])
    app = _make_app(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/chat/{chat_id}/history")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    sources = body["messages"][0]["sources"]
    assert len(sources) == 1
    assert sources[0]["path"] == "/vault/ok.md"
