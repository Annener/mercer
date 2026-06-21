import pytest
from unittest.mock import AsyncMock, patch
import fakeredis.aioredis
from parser.state.redis_state_manager import RedisStateManager
from parser.watchdog.vault_watchdog import _process_vault
from storage.storage_client import StorageClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def state_mgr():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisStateManager(r)


async def test_new_file_auto_indexed(state_mgr):
    """New .md file with .md in auto_extensions -> start_task called."""
    db = AsyncMock()
    db.get_document_by_path.return_value = None
    svc = AsyncMock()
    svc.start_task.return_value = "task-xyz"
    storage = AsyncMock(spec=StorageClient)

    disk_file = {
        "relative_path": "notes.md",
        "extension": ".md",
        "checksum": "abc123",
        "path": "/data/vaults/v1/notes.md",
        "last_modified": 1700000000.0,
        "size_bytes": 100,
    }

    with patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        return_value=[disk_file],
    ), patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    svc.start_task.assert_awaited_once_with("v1", force_reindex=False)


async def test_new_file_marked_pending_when_not_in_auto(state_mgr):
    """New .pdf file with only .md in auto_extensions -> marked pending."""
    db = AsyncMock()
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    disk_file = {
        "relative_path": "report.pdf",
        "extension": ".pdf",
        "checksum": "def456",
        "path": "/data/vaults/v1/report.pdf",
        "last_modified": 1700000001.0,
        "size_bytes": 200,
    }

    with patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        return_value=[disk_file],
    ), patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    svc.start_task.assert_not_awaited()
    entry = await state_mgr.get_vault_file_entry("v1", "report.pdf")
    assert entry["index_status"] == "pending"


async def test_deleted_file_removed_from_all_stores(state_mgr):
    """File in cache but not on disk -> LanceDB+PG+Redis cleanup."""
    await state_mgr.mark_file_indexed("v1", "old.md", "aaa", 3)

    db = AsyncMock()
    db.get_document_by_path.return_value = {"id": "doc-1"}
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    with patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        return_value=[],
    ), patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    storage.delete_document.assert_awaited_once()
    db.delete_document.assert_awaited_once_with("doc-1")
    entry = await state_mgr.get_vault_file_entry("v1", "old.md")
    assert entry is None


async def test_deleted_file_not_in_pg_still_cleans_redis(state_mgr):
    """File deleted from disk but was never indexed (not in PG) -> only Redis cleaned."""
    await state_mgr.mark_file_indexed("v1", "ghost.md", "bbb", 0)

    db = AsyncMock()
    db.get_document_by_path.return_value = None
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    with patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        return_value=[],
    ), patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    storage.delete_document.assert_not_awaited()
    db.delete_document.assert_not_awaited()
    entry = await state_mgr.get_vault_file_entry("v1", "ghost.md")
    assert entry is None


async def test_no_start_task_if_vault_already_indexing(state_mgr):
    """If vault is already indexing -> start_task not called."""
    await state_mgr._r.sadd("active_tasks", "task-running")
    await state_mgr._r.hset("task:task-running", mapping={
        "vault_id": "v1",
        "status": "running",
    })

    db = AsyncMock()
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    disk_file = {
        "relative_path": "notes.md",
        "extension": ".md",
        "checksum": "abc123",
        "path": "/data/vaults/v1/notes.md",
        "last_modified": 1700000000.0,
        "size_bytes": 100,
    }

    with patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        return_value=[disk_file],
    ), patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    svc.start_task.assert_not_awaited()


async def test_scan_vault_not_a_directory_is_handled(state_mgr):
    """If vault directory disappears between isdir check and scan -> warning, no crash."""
    db = AsyncMock()
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    with patch(
        "parser.watchdog.vault_watchdog.os.path.isdir",
        return_value=True,
    ), patch(
        "parser.watchdog.vault_watchdog.scan_vault",
        side_effect=FileNotFoundError("gone"),
    ):
        await _process_vault(
            vault_id="v1",
            auto_extensions={".md"},
            db_client=db,
            state_manager=state_mgr,
            indexer_service=svc,
            storage_client=storage,
        )

    svc.start_task.assert_not_awaited()
