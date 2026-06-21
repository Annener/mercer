"""Unit-тесты для indexer_worker.py после рефакторинга на RedisStateManager (этап 6)."""
from __future__ import annotations

import inspect
import pytest
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis as fakeredis

from parser.state.redis_state_manager import RedisStateManager

# Полный набор ключей, которые читает run_indexing из settings
PLATFORM_SETTINGS = {
    "chunking.chunk_size": 512,
    "chunking.overlap": 64,
    "chunking.entity_aware_mode": False,
    "pdf_sidecar.url": "http://sidecar:8081",
    "pdf_sidecar.timeout_seconds": "60",
    "pdf_sidecar.fallback_to_pdfminer": "true",
}


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def state_manager(fake_redis):
    return RedisStateManager(fake_redis)


def test_worker_no_broadcaster_attribute(state_manager):
    """run_indexing не принимает broadcast-параметр — его нет в сигнатуре."""
    from indexer_worker import run_indexing
    sig = inspect.signature(run_indexing)
    assert "broadcast" not in sig.parameters, "broadcast должен быть удалён из run_indexing"
    assert "broadcaster" not in sig.parameters, "broadcaster должен быть удалён из run_indexing"


def test_run_indexing_accepts_state_manager(state_manager):
    """run_indexing принимает state_manager: RedisStateManager."""
    from indexer_worker import run_indexing
    sig = inspect.signature(run_indexing)
    assert "state_manager" in sig.parameters


def test_no_chunk_ids_in_update_file_stage(state_manager):
    """update_file_stage не принимает chunk_ids."""
    sig = inspect.signature(state_manager.update_file_stage)
    assert "chunk_ids" not in sig.parameters, "chunk_ids не должен быть в update_file_stage"


def test_no_is_cancelled_sync_in_worker():
    """indexer_worker не использует синхронный callable is_cancelled."""
    from indexer_worker import run_indexing
    sig = inspect.signature(run_indexing)
    assert "is_cancelled" not in sig.parameters, "is_cancelled-callable должен быть удалён"


@pytest.mark.asyncio
async def test_cancel_before_processing(state_manager):
    """Если задача отменена до запуска цикла, worker должен завершиться со статусом cancelled."""
    await state_manager.create_task(
        task_id="t1",
        vault_id="v1",
        files_to_index=[{"relative_path": "doc.pdf"}],
        files_skipped=0,
        files_total=1,
    )
    await state_manager.request_cancel("t1")

    db_client = AsyncMock()
    # Полный набор ключей, run_indexing читает всё до проверки отмены
    db_client.get_platform_settings.return_value = PLATFORM_SETTINGS
    db_client.get_vault.return_value = {
        "enabled": True, "embedding_model_id": "em1",
        "chunk_size": 512, "overlap": 64,
        "entity_aware_mode": False, "domain_id": None,
    }
    db_client.get_embedding_model.return_value = {
        "model_id": "em1", "provider": "ollama", "model_name": "nomic",
        "base_url": "http://localhost:11434", "dimensions": 768,
        "enabled": True, "timeout_seconds": 30, "max_retries": 3,
        "encrypted_api_key": None,
    }
    db_client.decrypt_api_key.return_value = ""
    db_client.update_vault_binding_status = AsyncMock()
    # get_document_by_path должен быть доступен (для предварительного разделения skipped/new)
    db_client.get_document_by_path.return_value = None

    # scan_vault патчим напрямую; asyncio.to_thread не патчим —
    # scan_vault уже заменён до run_indexing вызывает asyncio.to_thread(scan_vault, ...)
    with patch("indexer_worker.scan_vault", return_value=[{
        "relative_path": "doc.pdf", "path": "/data/vaults/v1/doc.pdf",
        "checksum": "abc123", "last_modified": 0, "extension": ".pdf",
    }]):
        from indexer_worker import run_indexing
        await run_indexing(
            task_id="t1",
            vault_id="v1",
            force_reindex=True,
            db_client=db_client,
            state_manager=state_manager,
        )

    task_state = await state_manager.get_task_state("t1")
    assert task_state is not None
    assert task_state["status"] == "cancelled", (
        f"Expected 'cancelled', got {task_state['status']!r}. "
        "Check that request_cancel was set before run_indexing."
    )


@pytest.mark.asyncio
async def test_mark_file_indexed_called_after_success(state_manager):
    """После успешного процессинга файла вызывается mark_file_indexed."""
    await state_manager.create_task(
        task_id="t2",
        vault_id="v2",
        files_to_index=[{"relative_path": "doc.md"}],
        files_skipped=0,
        files_total=1,
    )

    sm_spy = AsyncMock(wraps=state_manager)

    db_client = AsyncMock()
    db_client.get_platform_settings.return_value = PLATFORM_SETTINGS
    db_client.get_vault.return_value = {
        "enabled": True, "embedding_model_id": "em1",
        "chunk_size": None, "overlap": None,
        "entity_aware_mode": None, "domain_id": None,
    }
    db_client.get_embedding_model.return_value = {
        "model_id": "em1", "provider": "ollama", "model_name": "nomic",
        "base_url": "http://localhost:11434", "dimensions": 768,
        "enabled": True, "timeout_seconds": 30, "max_retries": 3,
        "encrypted_api_key": None,
    }
    db_client.decrypt_api_key.return_value = ""
    db_client.update_vault_binding_status = AsyncMock()
    db_client.get_document_by_path.return_value = None
    db_client.create_document.return_value = {"id": "doc-uuid-1"}
    db_client.update_document_status = AsyncMock()
    db_client.update_vault_chunk_count = AsyncMock()

    with patch("indexer_worker.scan_vault", return_value=[{
        "relative_path": "doc.md", "path": "/data/vaults/v2/doc.md",
        "checksum": "md5abc", "last_modified": 0, "extension": ".md",
    }]):
        with patch("indexer_worker._process_file", new_callable=AsyncMock, return_value=(5, "doc-uuid-1")):
            from indexer_worker import run_indexing
            await run_indexing(
                task_id="t2",
                vault_id="v2",
                force_reindex=True,
                db_client=db_client,
                state_manager=sm_spy,
            )

    sm_spy.mark_file_indexed.assert_called_once_with("v2", "doc.md", "md5abc", 5)
    sm_spy.mark_task_done.assert_called_once_with("t2")
