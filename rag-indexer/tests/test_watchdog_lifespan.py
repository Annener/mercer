import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from storage.storage_client import StorageClient
from parser.watchdog.vault_watchdog import watchdog_loop

pytestmark = pytest.mark.asyncio


async def test_watchdog_loop_stops_on_cancel():
    db = AsyncMock()
    db.get_setting.return_value = ".md,.pdf"
    db.get_all_vaults.return_value = []
    state = AsyncMock()
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    task = asyncio.create_task(
        watchdog_loop(
            db_client=db,
            state_manager=state,
            indexer_service=svc,
            storage_client=storage,
            interval_sec=9999,
        )
    )
    await asyncio.sleep(0)  # даём loop запуститься
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    assert task.done()


async def test_watchdog_loop_calls_run_once():
    """After one iteration, _run_once is called at least once."""
    call_count = 0

    async def fake_run_once(db, state, svc, storage):
        nonlocal call_count
        call_count += 1

    db = AsyncMock()
    state = AsyncMock()
    svc = AsyncMock()
    storage = AsyncMock(spec=StorageClient)

    with patch(
        "parser.watchdog.vault_watchdog._run_once",
        side_effect=fake_run_once,
    ):
        task = asyncio.create_task(
            watchdog_loop(
                db_client=db,
                state_manager=state,
                indexer_service=svc,
                storage_client=storage,
                interval_sec=0,  # без задержки между итерациями
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert call_count >= 1
