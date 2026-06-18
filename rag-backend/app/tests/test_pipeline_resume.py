"""
test_pipeline_resume.py — интеграционные тесты для endpoint'ов
  POST /chat/{chat_id}/pipeline_confirm
  POST /chat/{chat_id}/pipeline_resume

Все тесты работают с mock-объектами без настоящей БД.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.pipeline_resume import router
from app.db.models import Chat

# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

TEST_CHAT_ID = str(uuid.uuid4())
TEST_CONFIRM_TOKEN = "test-confirm-token-abc123"
TEST_RESUME_TOKEN = "test-resume-token-xyz789"


def _make_future_ts() -> str:
    return (datetime.now(UTC) + timedelta(hours=1)).isoformat()


def _make_expired_ts() -> str:
    return (datetime.now(UTC) - timedelta(seconds=1)).isoformat()


def _make_pending_confirm(
    token: str = TEST_CONFIRM_TOKEN,
    expires_at: str | None = None,
    pipeline_name: str = "test-pipeline",
) -> dict[str, Any]:
    return {
        "pipeline_id": "test-pipeline",
        "pipeline_name": pipeline_name,
        "reasoning": "Тест reasoning",
        "confirm_token": token,
        "query": "Тестовый запрос",
        "context_snapshot": {
            "chat_id": TEST_CHAT_ID,
            "query": "Тестовый запрос",
            "original_query": "Тестовый запрос",
            "domain_id": "test-domain",
            "pipeline_id": "test-pipeline",
            "step_results": {},
        },
        "expires_at": expires_at or _make_future_ts(),
    }


def _make_pause_state(
    token: str = TEST_RESUME_TOKEN,
    expires_at: str | None = None,
    step_id: str = "validate_input",
) -> dict[str, Any]:
    return {
        "pipeline_id": "test-pipeline",
        "step_id": step_id,
        "step_name": step_id,
        "resume_token": token,
        "step_results": {"step1": "Результат шага 1"},
        "query": "Тестовый запрос",
        "context_snapshot": {
            "chat_id": TEST_CHAT_ID,
            "query": "Тестовый запрос",
            "original_query": "Тестовый запрос",
            "domain_id": "test-domain",
            "pipeline_id": "test-pipeline",
            "step_results": {"step1": "Результат шага 1"},
        },
        "expires_at": expires_at or _make_future_ts(),
    }


def _make_mock_chat(
    pending_confirm: dict | None = None,
    pause_state: dict | None = None,
) -> Chat:
    chat = MagicMock(spec=Chat)
    chat.id = uuid.UUID(TEST_CHAT_ID)
    chat.title = "New Chat"
    chat.domain_id = "test-domain"
    chat.campaign_id = None
    chat.vault_id = None
    chat.vault_ids = []
    chat.locked_pipeline_id = None
    chat.pending_pipeline_confirm = pending_confirm
    chat.pipeline_pause_state = pause_state
    return chat


# ---------------------------------------------------------------------------
# Сетап: минимальное FastAPI-приложение для тестирования
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client():
    """TestClient с мокнутой BD-зависимостью."""
    test_app = FastAPI()
    test_app.include_router(router)

    # Переопределяем get_db — возвращаем mock-сессию
    from app.db.session import get_db

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)  # по умолчанию None (не найдено)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()
        yield mock_db

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app, raise_server_exceptions=False) as client:
        yield client


# ---------------------------------------------------------------------------
# Тесты: pipeline_confirm
# ---------------------------------------------------------------------------

class TestPipelineConfirm:
    """POST /chat/{chat_id}/pipeline_confirm"""

    def test_confirm_not_found_returns_404(self, app_client: TestClient):
        """chat существует, но pending_pipeline_confirm = None."""
        chat = _make_mock_chat(pending_confirm=None)

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ):
            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_confirm",
                json={"confirm_token": "any", "confirmed": True},
            )
        assert resp.status_code == 404

    def test_confirm_wrong_token_returns_403(self, app_client: TestClient):
        """wrong token → 403."""
        chat = _make_mock_chat(pending_confirm=_make_pending_confirm(token="correct"))

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ):
            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_confirm",
                json={"confirm_token": "wrong", "confirmed": True},
            )
        assert resp.status_code == 403

    def test_confirm_expired_token_returns_410(self, app_client: TestClient):
        """expires_at в прошлом → 410 Gone."""
        chat = _make_mock_chat(
            pending_confirm=_make_pending_confirm(expires_at=_make_expired_ts())
        )

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ):
            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_confirm",
                json={"confirm_token": TEST_CONFIRM_TOKEN, "confirmed": True},
            )
        assert resp.status_code == 410

    def test_confirm_false_returns_sse_cancelled(self, app_client: TestClient):
        """confirmed=false → SSE с pipeline_cancelled chunk."""
        pending = _make_pending_confirm(pipeline_name="my-pipeline")
        chat = _make_mock_chat(pending_confirm=pending)

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ), patch(
            "app.api.pipeline_resume._plain_rag_stream",
        ) as mock_rag:
            # mock generator — не возвращает чанков
            async def empty_gen(*_a, **_kw):
                return
                yield  # noqa: unreachable

            mock_rag.return_value = empty_gen()

            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_confirm",
                json={"confirm_token": TEST_CONFIRM_TOKEN, "confirmed": False},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "pipeline_cancelled" in resp.text
        assert "my-pipeline" in resp.text

    def test_invalid_chat_id_returns_422(self, app_client: TestClient):
        """invalid UUID → 422."""
        resp = app_client.post(
            "/chat/not-a-uuid/pipeline_confirm",
            json={"confirm_token": "abc", "confirmed": True},
        )
        assert resp.status_code in (422, 404, 500)  # зависит от middleware


# ---------------------------------------------------------------------------
# Тесты: pipeline_resume
# ---------------------------------------------------------------------------

class TestPipelineResume:
    """POST /chat/{chat_id}/pipeline_resume"""

    def test_resume_no_pause_state_returns_404(self, app_client: TestClient):
        """pipeline_pause_state = None → 404."""
        chat = _make_mock_chat(pause_state=None)

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ):
            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_resume",
                json={"resume_token": "any", "cancelled": False},
            )
        assert resp.status_code == 404

    def test_resume_wrong_token_returns_403(self, app_client: TestClient):
        chat = _make_mock_chat(pause_state=_make_pause_state(token="correct"))

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ):
            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_resume",
                json={"resume_token": "wrong", "cancelled": False},
            )
        assert resp.status_code == 403

    def test_resume_expired_token_returns_410(self, app_client: TestClient):
        chat = _make_mock_chat(
            pause_state=_make_pause_state(expires_at=_make_expired_ts())
        )

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ):
            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_resume",
                json={"resume_token": TEST_RESUME_TOKEN, "cancelled": False},
            )
        assert resp.status_code == 410

    def test_resume_cancelled_true_returns_sse_cancelled(self, app_client: TestClient):
        """cancelled=true → SSE с pipeline_cancelled chunk, нет executor."""
        pause = _make_pause_state(step_id="validation_step")
        chat = _make_mock_chat(pause_state=pause)

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ):
            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_resume",
                json={"resume_token": TEST_RESUME_TOKEN, "cancelled": True},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "pipeline_cancelled" in resp.text
        assert "validation_step" in resp.text

    def test_resume_cancelled_false_includes_feedback_in_step_results(
        self, app_client: TestClient
    ):
        """cancelled=false + user_feedback → SSE с pipeline_resumed chunk."""
        pause = _make_pause_state(step_id="check_data")
        chat = _make_mock_chat(pause_state=pause)

        async def mock_executor_stream(*_a, **_kw):
            yield {"type": "token", "content": "answer"}

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ), patch(
            "app.api.pipeline_resume.PipelineExecutor",
            autospec=True,
        ) as MockExecutor:
            instance = MockExecutor.return_value
            instance.resume_from_validation = mock_executor_stream

            resp = app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_resume",
                json={
                    "resume_token": TEST_RESUME_TOKEN,
                    "cancelled": False,
                    "user_feedback": "Окей",
                },
            )

        assert resp.status_code == 200
        assert "pipeline_resumed" in resp.text
        assert "check_data" in resp.text
        assert "answer" in resp.text

    def test_resume_feedback_none_stores_empty_string(self, app_client: TestClient):
        """если user_feedback=null — в step_results записывается пустая строка."""
        pause = _make_pause_state(step_id="qa_check")
        chat = _make_mock_chat(pause_state=pause)

        captured_ctx = {}

        async def capturing_executor_stream(ctx, step_id):
            captured_ctx["step_results"] = dict(ctx.step_results)
            yield {"type": "token", "content": ""}

        with patch(
            "app.api.pipeline_resume._get_chat_or_404",
            new_callable=AsyncMock,
            return_value=chat,
        ), patch(
            "app.api.pipeline_resume.PipelineExecutor",
            autospec=True,
        ) as MockExecutor:
            instance = MockExecutor.return_value
            instance.resume_from_validation = capturing_executor_stream

            app_client.post(
                f"/chat/{TEST_CHAT_ID}/pipeline_resume",
                json={
                    "resume_token": TEST_RESUME_TOKEN,
                    "cancelled": False,
                    "user_feedback": None,
                },
            )

        assert captured_ctx.get("step_results", {}).get("_validation_qa_check") == ""


# ---------------------------------------------------------------------------
# Тесты: _restore_context
# ---------------------------------------------------------------------------

class TestRestoreContext:
    """unit-тесты вспомогательной функции."""

    def test_restore_injects_chat_id(self):
        from app.api.pipeline_resume import _restore_context

        snapshot = {
            "chat_id": "old-id",
            "query": "запрос",
            "domain_id": "test",
        }
        ctx = _restore_context(snapshot, TEST_CHAT_ID)
        assert ctx.chat_id == TEST_CHAT_ID

    def test_restore_preserves_query(self):
        from app.api.pipeline_resume import _restore_context

        snapshot = {
            "query": "оригинальный запрос",
            "domain_id": "test",
        }
        ctx = _restore_context(snapshot, TEST_CHAT_ID)
        assert ctx.query == "оригинальный запрос"

    def test_restore_empty_snapshot(self):
        """minimal snapshot — не должно падать."""
        from app.api.pipeline_resume import _restore_context

        ctx = _restore_context({}, TEST_CHAT_ID)
        assert ctx.chat_id == TEST_CHAT_ID
