"""Tests for documents list endpoint — focus on tag_ids filter (list, OR-logic)."""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.api.settings.documents import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient with mocked db.execute/db.get."""
    fake_vault_id = uuid.uuid4()
    captured: dict[str, Any] = {"calls": [], "current_index": 0}

    async def fake_execute(stmt):
        captured["calls"].append(("execute", stmt))
        idx = captured["current_index"]
        captured["current_index"] += 1
        result = AsyncMock()
        if idx == 0:
            # Первый запрос: SELECT Vault.vault_id WHERE domain_id == ?
            result.all = lambda: [(fake_vault_id,)]
        else:
            # Последующие запросы: SELECT Document... — пусто.
            scalars_mock = AsyncMock()
            scalars_mock.all = list
            result.scalars = lambda: scalars_mock
        # scalar_one_or_none() — для lookup Vault в replace_document_labels.
        result.scalar_one_or_none = lambda: None
        return result

    async def fake_get_db():
        db = AsyncMock()
        db.execute = fake_execute
        db.get = AsyncMock(return_value=None)
        yield db

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")

    async def _fake_get_db():
        async for x in fake_get_db():
            yield x

    from app.db.session import get_db
    app.dependency_overrides[get_db] = _fake_get_db

    def _reset():
        captured["current_index"] = 0
        captured["calls"] = []

    return TestClient(app), captured, _reset


def test_list_documents_with_single_tag_id_returns_200(client):
    cli, captured, reset = client
    reset()
    r = cli.get(
        f"/api/settings/documents?domain_id=d-1&status=indexed&tag_id={uuid.uuid4()}"
    )
    assert r.status_code == 200
    # Был вызван db.execute минимум 2 раза (vault_ids + documents).
    assert sum(1 for kind, _ in captured["calls"] if kind == "execute") >= 2


def test_list_documents_with_repeated_tag_id_query_param_parses_as_list(client):
    """FastAPI должен распарсить повторяющийся ?tag_id=...&tag_id=... как list[str]."""
    cli, _captured, reset = client
    reset()
    tag1 = str(uuid.uuid4())
    tag2 = str(uuid.uuid4())
    r = cli.get(
        f"/api/settings/documents?domain_id=d-1&status=indexed&tag_id={tag1}&tag_id={tag2}"
    )
    assert r.status_code == 200


def test_list_documents_with_invalid_tag_id_returns_422(client):
    cli, _captured, reset = client
    reset()
    r = cli.get(
        "/api/settings/documents?domain_id=d-1&status=indexed&tag_id=not-a-uuid"
    )
    # 422 на парсинге UUID-параметра, до запроса в БД.
    assert r.status_code == 422


def test_list_documents_with_invalid_tag_ids_returns_422(client):
    """tag_ids (список) тоже валидируется как UUID."""
    cli, _captured, reset = client
    reset()
    r = cli.get(
        f"/api/settings/documents?domain_id=d-1&status=indexed&tag_id={uuid.uuid4()}&tag_id=garbage"
    )
    assert r.status_code == 422
