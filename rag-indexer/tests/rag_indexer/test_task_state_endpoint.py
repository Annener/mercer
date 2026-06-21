"""Unit-тесты для polling endpoint GET /api/v1/tasks/{task_id}/state (этап 8)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock


@pytest.fixture
def app():
    """FastAPI app with mocked state — no real Redis/DB needed."""
    from app.main import app as _app
    return _app


@pytest.mark.asyncio
async def test_get_task_state_returns_state(app):
    """GET /api/v1/tasks/{task_id}/state возвращает state из RedisStateManager."""
    mock_state = {"task_id": "task-abc", "vault_id": "v1", "status": "running",
                  "files_done": 3, "files_total": 10}
    app.state.state_manager = AsyncMock()
    app.state.state_manager.get_task_state.return_value = mock_state

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/tasks/task-abc/state")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["files_done"] == 3
    app.state.state_manager.get_task_state.assert_called_once_with("task-abc")


@pytest.mark.asyncio
async def test_get_task_state_returns_404_if_not_found(app):
    """GET /api/v1/tasks/{task_id}/state возвращает 404 если задача не найдена."""
    app.state.state_manager = AsyncMock()
    app.state.state_manager.get_task_state.return_value = None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/tasks/nonexistent/state")

    assert resp.status_code == 404


def test_no_websocket_in_main():
    """main.py не импортирует WebSocket / ConnectionManager."""
    import ast
    import pathlib

    src = pathlib.Path("/app/app/main.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] + [alias.name for alias in node.names])
            )
            for name in names:
                assert "websocket" not in (name or "").lower(), (
                    f"main.py содержит WebSocket-импорт: {name}"
                )
                assert "ConnectionManager" not in (name or ""), (
                    "main.py всё ещё импортирует ConnectionManager"
                )


def test_websocket_manager_file_deleted():
    """websocket_manager.py должен быть удалён."""
    import pathlib
    ws_file = pathlib.Path("/app/app/websocket_manager.py")
    assert not ws_file.exists(), "websocket_manager.py должен быть удалён с диска"
