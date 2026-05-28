from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.db_client import IndexerDBClient


logger = logging.getLogger(__name__)

BroadcastCallable = Callable[[str, dict[str, Any]], Awaitable[None]]


class IndexerService:
    def __init__(self, db_client: IndexerDBClient, broadcaster: BroadcastCallable) -> None:
        self.db_client = db_client
        self.broadcaster = broadcaster
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_flags: dict[str, bool] = {}
        self._lock = asyncio.Lock()

    async def start_task(self, vault_id: str, force_reindex: bool) -> str:
        vault = await self.db_client.get_vault(vault_id)
        if vault is None:
            raise KeyError(f"Unknown vault_id={vault_id!r}")
        if not vault["enabled"]:
            raise ValueError(f"Vault is disabled: {vault_id}")

        task_id = uuid.uuid4().hex
        async with self._lock:
            self._cancel_flags[task_id] = False
            task = asyncio.create_task(self._run_task(task_id, vault_id, force_reindex), name=f"index-{task_id}")
            self._tasks[task_id] = task
            task.add_done_callback(lambda done_task, done_task_id=task_id: self._on_task_done(done_task_id, done_task))
        return task_id

    async def cancel_task(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.done():
                return False
            # Ставим флаг — run_indexing проверяет его между файлами и в heartbeat-цикле.
            self._cancel_flags[task_id] = True
            # Также отменяем asyncio.Task напрямую — это прервёт любой await
            # (в том числе asyncio.sleep, broadcast, save_cache).
            # asyncio.to_thread и ProcessPoolExecutor всё равно дождутся завершения
            # текущей операции в потоке/процессе, но не запустят следующее.
            task.cancel()
            return True

    def is_cancelled(self, task_id: str) -> bool:
        return self._cancel_flags.get(task_id, False)

    async def get_active_tasks(self) -> list[str]:
        async with self._lock:
            return [task_id for task_id, task in self._tasks.items() if not task.done()]

    async def shutdown(self, timeout_seconds: int = 30) -> None:
        active_task_ids = await self.get_active_tasks()
        for task_id in active_task_ids:
            await self.cancel_task(task_id)

        async with self._lock:
            active_tasks = [task for task in self._tasks.values() if not task.done()]

        if not active_tasks:
            return

        done, pending = await asyncio.wait(active_tasks, timeout=timeout_seconds)
        for task in done:
            try:
                task.result()
            except Exception:
                logger.error("Indexer task failed during shutdown.", exc_info=True)
        for task in pending:
            logger.warning("Indexer task did not finish during graceful shutdown: %s", task.get_name())
            task.cancel()

    async def _run_task(self, task_id: str, vault_id: str, force_reindex: bool) -> None:
        from indexer_worker import run_indexing

        await run_indexing(
            task_id=task_id,
            vault_id=vault_id,
            force_reindex=force_reindex,
            db_client=self.db_client,
            is_cancelled=self.is_cancelled,
            broadcast=self.broadcaster,
        )

    def _on_task_done(self, task_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(task_id, None)
        self._cancel_flags.pop(task_id, None)
        if task.cancelled():
            logger.info("Indexer task cancelled: %s", task_id)
            return
        try:
            task.result()
        except Exception:
            logger.error("Indexer task crashed: %s", task_id, exc_info=True)
