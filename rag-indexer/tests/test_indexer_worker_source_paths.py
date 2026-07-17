"""Unit tests for source_paths filtering in run_indexing (Phase 4 gap-3).

These tests mock scan_vault and all downstream I/O so no real vault
filesystem or embedding models are needed.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scanned_files() -> list[dict]:
    return [
        {
            "relative_path": "docs/plan.md",
            "path": "/data/vaults/v1/docs/plan.md",
            "checksum": "aaaa",
            "last_modified": 1000,
            "extension": ".md",
        },
        {
            "relative_path": "docs/brief.md",
            "path": "/data/vaults/v1/docs/brief.md",
            "checksum": "bbbb",
            "last_modified": 2000,
            "extension": ".md",
        },
        {
            "relative_path": "other/notes.md",
            "path": "/data/vaults/v1/other/notes.md",
            "checksum": "cccc",
            "last_modified": 3000,
            "extension": ".md",
        },
    ]


def _make_db_client(vault_enabled: bool = True) -> MagicMock:
    db = AsyncMock()
    db.get_platform_settings.return_value = {
        "pdf_sidecar.url": "http://sidecar:8000",
        "pdf_sidecar.timeout_seconds": "180",
        "pdf_sidecar.fallback_to_pdfminer": "true",
    }
    db.get_vault.return_value = {
        "id": "v1",
        "enabled": vault_enabled,
        "embedding_model_id": "em1",
        "domain_id": "dom1",
        "semantic_threshold": 0.3,
    }
    db.get_embedding_model.return_value = {
        "model_id": "em1",
        "provider": "openai_compatible",
        "model_name": "text-embedding-3-small",
        "base_url": "http://embed:8000",
        "dimensions": 1536,
        "enabled": True,
        "timeout_seconds": 30,
        "max_retries": 3,
        "encrypted_api_key": None,
    }
    db.decrypt_api_key.return_value = "test-key"
    db.get_document_by_path.return_value = None
    db.create_document.return_value = {"id": "doc-1"}
    db.update_document_status = AsyncMock()
    db.update_vault_binding_status = AsyncMock()
    db.update_vault_chunk_count = AsyncMock()
    db.update_document_size = AsyncMock()
    return db


def _make_state_manager() -> MagicMock:
    sm = AsyncMock()
    sm.is_cancelled.return_value = False
    sm.create_task = AsyncMock()
    sm.mark_task_done = AsyncMock()
    sm.mark_task_cancelled = AsyncMock()
    sm.increment_files_done = AsyncMock()
    sm.mark_file_indexed = AsyncMock()
    sm.update_file_stage = AsyncMock()
    return sm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_paths_filters_to_matching_files():
    """Only files listed in source_paths are passed to _process_file."""
    db = _make_db_client()
    sm = _make_state_manager()
    processed: list[str] = []

    async def fake_process_file(**kwargs):
        processed.append(kwargs["file_info"]["relative_path"])
        return (2, "doc-1")

    with (
        patch("indexer_worker.scan_vault", return_value=_make_scanned_files()),
        patch("indexer_worker._process_file", new=fake_process_file),
        patch("indexer_worker._build_provider", return_value=MagicMock()),
        patch("indexer_worker.StorageClient", return_value=MagicMock()),
    ):
        from indexer_worker import run_indexing

        await run_indexing(
            task_id="t1",
            vault_id="v1",
            force_reindex=True,
            db_client=db,
            state_manager=sm,
            source_paths=["docs/plan.md"],
        )

    assert processed == ["docs/plan.md"]


@pytest.mark.asyncio
async def test_source_paths_none_processes_all_files():
    """Without source_paths (None), all vault files are processed."""
    db = _make_db_client()
    sm = _make_state_manager()
    processed: list[str] = []

    async def fake_process_file(**kwargs):
        processed.append(kwargs["file_info"]["relative_path"])
        return (1, "doc-x")

    with (
        patch("indexer_worker.scan_vault", return_value=_make_scanned_files()),
        patch("indexer_worker._process_file", new=fake_process_file),
        patch("indexer_worker._build_provider", return_value=MagicMock()),
        patch("indexer_worker.StorageClient", return_value=MagicMock()),
    ):
        from indexer_worker import run_indexing

        await run_indexing(
            task_id="t2",
            vault_id="v1",
            force_reindex=True,
            db_client=db,
            state_manager=sm,
            source_paths=None,
        )

    assert set(processed) == {"docs/plan.md", "docs/brief.md", "other/notes.md"}


@pytest.mark.asyncio
async def test_source_paths_empty_match_marks_task_done():
    """If source_paths has no matching files, task is marked done immediately."""
    db = _make_db_client()
    sm = _make_state_manager()
    processed: list[str] = []

    async def fake_process_file(**kwargs):
        processed.append(kwargs["file_info"]["relative_path"])
        return (0, "doc-x")

    with (
        patch("indexer_worker.scan_vault", return_value=_make_scanned_files()),
        patch("indexer_worker._process_file", new=fake_process_file),
        patch("indexer_worker._build_provider", return_value=MagicMock()),
        patch("indexer_worker.StorageClient", return_value=MagicMock()),
    ):
        from indexer_worker import run_indexing

        await run_indexing(
            task_id="t3",
            vault_id="v1",
            force_reindex=True,
            db_client=db,
            state_manager=sm,
            source_paths=["nonexistent/file.md"],
        )

    assert processed == []
    sm.mark_task_done.assert_awaited_once_with("t3")


@pytest.mark.asyncio
async def test_source_paths_leading_slash_normalised():
    """Leading slashes in source_paths are stripped before comparison."""
    db = _make_db_client()
    sm = _make_state_manager()
    processed: list[str] = []

    async def fake_process_file(**kwargs):
        processed.append(kwargs["file_info"]["relative_path"])
        return (1, "doc-1")

    with (
        patch("indexer_worker.scan_vault", return_value=_make_scanned_files()),
        patch("indexer_worker._process_file", new=fake_process_file),
        patch("indexer_worker._build_provider", return_value=MagicMock()),
        patch("indexer_worker.StorageClient", return_value=MagicMock()),
    ):
        from indexer_worker import run_indexing

        await run_indexing(
            task_id="t4",
            vault_id="v1",
            force_reindex=True,
            db_client=db,
            state_manager=sm,
            source_paths=["/docs/plan.md"],  # leading slash
        )

    assert processed == ["docs/plan.md"]
