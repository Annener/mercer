"""Unit-тесты для Redis-direct endpoints rag-backend (этапы 9-10).

Запуск:
    pytest tests/rag_backend/test_redis_endpoints.py -v
"""
from __future__ import annotations

import json
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# GET /index-tasks/{task_id}/state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_task_state_running():
    """Возвращает состояние бегущей задачи."""
    task_hash = {"status": "running", "vault_id": "v1", "files_total": "10", "files_done": "3"}
    files_hash = {"a.pdf": json.dumps({"stage": "indexing", "chunks_done": 5, "chunks_total": 20})}

    redis_mock = AsyncMock()
    redis_mock.hgetall.side_effect = [task_hash, files_hash]
    app.state.redis = redis_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/index-tasks/task-1/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert "a.pdf" in data["files"]
    assert data["files"]["a.pdf"]["stage"] == "indexing"


@pytest.mark.asyncio
async def test_get_task_state_not_found():
    """404 если task_id не существует в Redis."""
    redis_mock = AsyncMock()
    redis_mock.hgetall.return_value = {}
    app.state.redis = redis_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/index-tasks/ghost/state")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /vaults/{vault_id}/index-state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_vault_index_state():
    """Возвращает сводку по статусам файлов vault'а."""
    vault_files = {
        "a.pdf": json.dumps({"md5": "aaa", "index_status": "indexed", "chunks_total": 5}),
        "b.pdf": json.dumps({"md5": "bbb", "index_status": "stale", "chunks_total": 3}),
        "c.pdf": json.dumps({"md5": "ccc", "index_status": "indexed", "chunks_total": 8}),
    }
    redis_mock = AsyncMock()
    redis_mock.hgetall.return_value = vault_files
    app.state.redis = redis_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/vaults/vault-1/index-state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["files_total"] == 3
    assert data["by_status"]["indexed"] == 2
    assert data["by_status"]["stale"] == 1


@pytest.mark.asyncio
async def test_get_vault_index_state_not_found():
    """404 если vault не найден в Redis."""
    redis_mock = AsyncMock()
    redis_mock.hgetall.return_value = {}
    app.state.redis = redis_mock

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/vaults/ghost-vault/index-state")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Проверка отсутствия WebSocket в rag-backend
# ---------------------------------------------------------------------------

def test_no_websocket_in_rag_backend():
    """В rag-backend нет WebSocket-кода после рефакторинга."""
    import subprocess
    result = subprocess.run(
        ["grep", "-r", "websocket", "rag-backend/", "--include=*.py", "-l"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", f"Найдены WS-файлы: {result.stdout}"
