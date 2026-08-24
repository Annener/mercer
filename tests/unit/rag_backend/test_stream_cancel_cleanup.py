"""Regression test: SSE stream cleanup on client disconnect (Stop button).

Background:
  Клиент нажимает «Стоп» → AbortController.abort() рвёт соединение.
  Starlette/SQLAlchemy cleanup должен корректно завершиться,
  не оставляя CancelledError в логах.

Главный регресс: `_save_partial_answer` должен swallow CancelledError,
потому что при disconnect клиента db.commit() бросает CancelledError,
и если пробросить его дальше — SQLAlchemy pool получит необработанное
исключение в do_terminate() (issue: «Exception terminating connection»).
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_mock_chat() -> MagicMock:
    chat = MagicMock()
    chat.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    return chat


class TestSavePartialAnswerCancelSafety:
    """Главный регресс: _save_partial_answer swallow'ит CancelledError."""

    def test_cancellederror_in_db_commit_is_swallowed(self):
        """Если db.commit() бросает CancelledError (disconnect клиента),
        _save_partial_answer НЕ должен пробрасывать его дальше —
        иначе SQLAlchemy pool cleanup получает CancelledError в terminate()."""
        from app.api.chat import _save_partial_answer

        mock_db = AsyncMock()
        # Симулируем что commit() падает с CancelledError (asyncio.CancelledError)
        mock_db.commit = AsyncMock(side_effect=asyncio.CancelledError())
        mock_chat = _make_mock_chat()

        # Не должно бросить CancelledError наружу
        try:
            asyncio.run(_save_partial_answer(mock_db, mock_chat, "partial answer", "query"))
        except asyncio.CancelledError:
            pytest.fail(
                "_save_partial_answer пробрасывает CancelledError — "
                "SQLAlchemy pool получит необработанное исключение в terminate()"
            )
        except Exception:
            # Другие исключения OK (например, логирование)
            pass

    def test_normal_db_commit_succeeds(self):
        """Нормальный commit не должен бросать."""
        from app.api.chat import _save_partial_answer

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_chat = _make_mock_chat()

        asyncio.run(_save_partial_answer(mock_db, mock_chat, "full answer", "query"))

        # Должен был вызваться commit (минимум один раз: для assistant_msg + title)
        assert mock_db.commit.await_count >= 1
        # И добавить сообщение
        assert mock_db.add.called

    def test_empty_answer_skips_commit(self):
        """Пустой ответ — не делаем commit, не сохраняем."""
        from app.api.chat import _save_partial_answer

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_chat = _make_mock_chat()

        asyncio.run(_save_partial_answer(mock_db, mock_chat, "", "query"))

        assert not mock_db.commit.called
        assert not mock_db.add.called
