"""Unit-тесты для pdf-sidecar/agent/agent.py — host-agent.

Мокаются subprocess и файл-операции. Никаких внешних процессов не запускается.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def host_agent(monkeypatch):
    """Сбрасывает env и импортирует agent.py в изоляции."""
    monkeypatch.delenv("HOST_AGENT_TOKEN", raising=False)
    monkeypatch.delenv("HOST_AGENT_PORT", raising=False)
    monkeypatch.delenv("SIDECAR_DIR", raising=False)

    # agent.py лежит в pdf-sidecar/agent/agent.py (без __init__.py рядом —
    # namespace package). conftest ставит в sys.path pdf-sidecar/,
    # поэтому `import agent` находит pdf-sidecar/agent/ как namespace
    # package, но не сам agent.py. Добавляем pdf-sidecar/agent/ в sys.path.
    agent_dir = str(Path(__file__).resolve().parents[3] / "pdf-sidecar" / "agent")
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)

    # Очищаем кэш модуля agent и всех субмодулей, чтобы reload работал чисто
    for mod_name in list(sys.modules):
        if mod_name == "agent" or mod_name.startswith("agent."):
            del sys.modules[mod_name]
    import agent

    importlib.reload(agent)
    yield agent


class TestReadPid:
    def test_returns_none_when_file_missing(self, host_agent, monkeypatch):
        # Подменяем PIDFILE на MagicMock, чтобы можно было контролировать exists/read_text
        mock_pidfile = MagicMock()
        mock_pidfile.exists.return_value = False
        monkeypatch.setattr(host_agent, "PIDFILE", mock_pidfile)
        assert host_agent._read_pid() is None

    def test_returns_int_when_file_has_valid_pid(self, host_agent, monkeypatch):
        mock_pidfile = MagicMock()
        mock_pidfile.exists.return_value = True
        mock_pidfile.read_text.return_value = "12345"
        monkeypatch.setattr(host_agent, "PIDFILE", mock_pidfile)
        assert host_agent._read_pid() == 12345

    def test_returns_none_when_file_has_garbage(self, host_agent, monkeypatch):
        mock_pidfile = MagicMock()
        mock_pidfile.exists.return_value = True
        mock_pidfile.read_text.return_value = "not-a-pid"
        monkeypatch.setattr(host_agent, "PIDFILE", mock_pidfile)
        assert host_agent._read_pid() is None

    def test_returns_none_on_oserror(self, host_agent, monkeypatch):
        mock_pidfile = MagicMock()
        mock_pidfile.exists.return_value = True
        mock_pidfile.read_text.side_effect = OSError("disk error")
        monkeypatch.setattr(host_agent, "PIDFILE", mock_pidfile)
        assert host_agent._read_pid() is None


class TestIsRunning:
    def test_true_when_kill_zero_succeeds(self, host_agent):
        with patch("os.kill") as mock_kill:
            mock_kill.return_value = None
            assert host_agent._is_running(12345) is True

    def test_false_when_process_not_found(self, host_agent):
        with patch("os.kill", side_effect=ProcessLookupError):
            assert host_agent._is_running(99999) is False

    def test_false_on_permission_error(self, host_agent):
        # PermissionError означает что PID существует но принадлежит другому пользователю
        # — для host-agent это считается "не наш процесс"
        with patch("os.kill", side_effect=PermissionError):
            assert host_agent._is_running(1) is False


class TestAuthDependency:
    def test_no_token_env_allows_request(self, host_agent):
        # HOST_AGENT_TOKEN не задан → auth отключена, любой запрос проходит
        host_agent.AGENT_TOKEN = None
        # Просто вызываем — должна вернуть None без raise
        result = host_agent.check_token(x_agent_token=None)
        assert result is None

    def test_correct_token_passes(self, host_agent):
        host_agent.AGENT_TOKEN = "secret123"
        result = host_agent.check_token(x_agent_token="secret123")
        assert result is None

    def test_wrong_token_rejected(self, host_agent):
        host_agent.AGENT_TOKEN = "secret123"
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            host_agent.check_token(x_agent_token="wrong")
        assert exc_info.value.status_code == 401

    def test_missing_token_rejected_when_token_set(self, host_agent):
        host_agent.AGENT_TOKEN = "secret123"
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            host_agent.check_token(x_agent_token=None)
        assert exc_info.value.status_code == 401


class TestHealthEndpoint:
    def test_returns_health_payload(self, host_agent):
        from fastapi.testclient import TestClient

        with patch.object(host_agent, "_read_pid", return_value=None), \
             patch.object(host_agent, "_is_running", return_value=False):
            client = TestClient(host_agent.app)
            response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "host-agent"
        assert "sidecar" in body
        assert "installed" in body["sidecar"]
        assert "running" in body["sidecar"]
        assert "sidecar_dir" in body["sidecar"]


class TestSidecarStatusEndpoint:
    def test_status_returns_not_running_when_no_pid(self, host_agent):
        from fastapi.testclient import TestClient

        with patch.object(host_agent, "_read_pid", return_value=None):
            client = TestClient(host_agent.app)
            response = client.get("/sidecar/status")
        assert response.status_code == 200
        body = response.json()
        assert body["running"] is False
        assert body["pid"] is None

    def test_status_detects_running_pid(self, host_agent):
        from fastapi.testclient import TestClient

        with patch.object(host_agent, "_read_pid", return_value=12345), \
             patch.object(host_agent, "_is_running", return_value=True):
            client = TestClient(host_agent.app)
            response = client.get("/sidecar/status")
        assert response.status_code == 200
        body = response.json()
        assert body["running"] is True
        assert body["pid"] == 12345


class TestSidecarStartEndpoint:
    def test_start_invokes_start_sh(self, host_agent):
        """POST /sidecar/start запускает start.sh через bash и возвращает ok=true при успехе."""
        from fastapi.testclient import TestClient

        # Мокаем _read_pid и _is_running (start должен увидеть что sidecar не запущен)
        with patch.object(host_agent, "_read_pid", return_value=None), \
             patch.object(host_agent, "_is_running", return_value=False):
            # Мокаем _run_script — это внутренний хелпер, который запускает bash start.sh
            async def mock_run_script(script, timeout=30):
                return {"exit_code": 0, "output": "started OK", "ok": True}

            host_agent._run_script = mock_run_script
            client = TestClient(host_agent.app)
            response = client.post("/sidecar/start")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["message"] == "Started"
        assert body["output"] == "started OK"

    def test_start_refuses_when_already_running(self, host_agent):
        """Если sidecar уже работает — endpoint возвращает ok=false без запуска скрипта."""
        from fastapi.testclient import TestClient

        async def fail_run_script(*_args, **_kw):
            raise AssertionError("_run_script не должен вызываться когда sidecar уже запущен")

        host_agent._run_script = fail_run_script
        with patch.object(host_agent, "_read_pid", return_value=12345), \
             patch.object(host_agent, "_is_running", return_value=True):
            client = TestClient(host_agent.app)
            response = client.post("/sidecar/start")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "12345" in body["message"]

    def test_start_returns_500_when_script_fails(self, host_agent):
        from fastapi.testclient import TestClient

        async def mock_fail(script, timeout=30):
            return {"exit_code": 1, "output": "start.sh failed", "ok": False}

        host_agent._run_script = mock_fail
        with patch.object(host_agent, "_read_pid", return_value=None), \
             patch.object(host_agent, "_is_running", return_value=False):
            client = TestClient(host_agent.app)
            response = client.post("/sidecar/start")
        assert response.status_code == 500
        assert "start.sh failed" in response.json()["detail"]


class TestSidecarStopEndpoint:
    def test_stop_runs_stop_sh(self, host_agent):
        from fastapi.testclient import TestClient

        async def mock_stop_script(script, timeout=30):
            assert script == "stop.sh"
            return {"exit_code": 0, "output": "stopped", "ok": True}

        host_agent._run_script = mock_stop_script
        client = TestClient(host_agent.app)
        response = client.post("/sidecar/stop")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["output"] == "stopped"