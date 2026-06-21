"""Unit-тесты для _rebuild_one_vault (шаг 5).

Запуск:
    pytest tests/rag_indexer/test_startup_vault_rebuild.py -v
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.main import _rebuild_one_vault


@pytest.mark.asyncio
async def test_rebuild_skipped_if_path_not_exists() -> None:
    """Если путь vault'а не существует — rebuild пропускается без ошибки."""
    state_manager = AsyncMock()
    db_client = AsyncMock()
    await _rebuild_one_vault(state_manager, db_client, "v1", "/nonexistent/path")
    state_manager.rebuild_vault_cache.assert_not_called()
    db_client.get_all_documents.assert_not_called()


@pytest.mark.asyncio
async def test_rebuild_calls_state_manager(tmp_path: object) -> None:
    """Вызывает rebuild_vault_cache с данными из pg и disk."""
    import pathlib
    vault_path = str(pathlib.Path(str(tmp_path)))

    state_manager = AsyncMock()
    db_client = AsyncMock()
    pg_docs = [{"relative_path": "a.pdf", "md5": "aaa", "status": "indexed", "chunks_count": 5}]
    db_client.get_all_documents.return_value = pg_docs
    mock_disk = [{"relative_path": "a.pdf", "checksum": "aaa"}]

    with patch("app.main.scan_vault", return_value=mock_disk):
        await _rebuild_one_vault(state_manager, db_client, "v1", vault_path)

    state_manager.rebuild_vault_cache.assert_called_once_with("v1", pg_docs, mock_disk)
    db_client.get_all_documents.assert_called_once_with("v1")


@pytest.mark.asyncio
async def test_rebuild_error_propagates_to_caller(tmp_path: object) -> None:
    """Ошибка в rebuild_vault_cache пробрасывается наверх (caller перехватывает через return_exceptions=True)."""
    import pathlib
    vault_path = str(pathlib.Path(str(tmp_path)))

    state_manager = AsyncMock()
    state_manager.rebuild_vault_cache.side_effect = RuntimeError("Redis down")
    db_client = AsyncMock()
    db_client.get_all_documents.return_value = []

    with patch("app.main.scan_vault", return_value=[]):
        with pytest.raises(RuntimeError, match="Redis down"):
            await _rebuild_one_vault(state_manager, db_client, "v1", vault_path)
