from __future__ import annotations

import asyncio
import logging
import uuid

from app.db_client import IndexerDBClient
from parser.state.redis_state_manager import RedisStateManager

logger = logging.getLogger(__name__)


class IndexerService:
    def __init__(self, db_client: IndexerDBClient, state_manager: RedisStateManager) -> None:
        self._db_client = db_client
        self._state_manager = state_manager
        # in-memory: только для управления asyncio.Task (cancel/done)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def start_task(
        self,
        vault_id: str,
        force_reindex: bool,
        source_paths: list[str] | None = None,
    ) -> str:
        """Start an indexing task for *vault_id*.

        Args:
            vault_id: Target vault.
            force_reindex: Re-index even if checksum unchanged.
            source_paths: When provided, only process these relative markdown
                paths inside the vault (targeted reindex).  None means full
                vault scan (existing behaviour — backward compatible).
        """
        vault = await self._db_client.get_vault(vault_id)
        if vault is None:
            raise KeyError(f"Unknown vault_id={vault_id!r}")
        if not vault["enabled"]:
            raise ValueError(f"Vault is disabled: {vault_id}")

        task_id = uuid.uuid4().hex
        async with self._lock:
            task = asyncio.create_task(
                self._run_task(task_id, vault_id, force_reindex, source_paths),
                name=f"index-{task_id}",
            )
            self._tasks[task_id] = task
            task.add_done_callback(
                lambda t, tid=task_id: self._on_task_done(tid, t)
            )
        return task_id

    async def cancel_task(self, task_id: str) -> bool:
        """Ставит Redis-флаг отмены. Worker сам завершится чисто."""
        async with self._lock:
            if task_id not in self._tasks:
                return False
        await self._state_manager.request_cancel(task_id)
        return True

    async def get_active_tasks(self) -> list[str]:
        async with self._lock:
            return [tid for tid, task in self._tasks.items() if not task.done()]

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
            logger.warning(
                "Indexer task did not finish during graceful shutdown: %s", task.get_name()
            )
            task.cancel()

    async def _run_task(
        self,
        task_id: str,
        vault_id: str,
        force_reindex: bool,
        source_paths: list[str] | None = None,
    ) -> None:
        from indexer_worker import run_indexing

        await run_indexing(
            task_id=task_id,
            vault_id=vault_id,
            force_reindex=force_reindex,
            db_client=self._db_client,
            state_manager=self._state_manager,
            source_paths=source_paths,
        )

    def _on_task_done(self, task_id: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(task_id, None)
        if task.cancelled():
            logger.info("Task cancelled: %s", task_id)
        elif exc := task.exception():
            logger.error("Task failed: %s — %s", task_id, exc)
