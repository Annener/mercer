"""Vault Watchdog — фоновый asyncio-луп обнаружения изменений vault.

Алгоритм:
  1. Запросить все активные vault из БД (только enabled=true)
  2. Для каждого vault: скан диска, diff с Redis-кэшем
  3. Удалённые → атомарно: LanceDB + PG + Redis
  4. Изменённые/новые → авто-индексация или пометка pending
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from parser.scanning.vault_scanner import scan_vault
from parser.state.redis_state_manager import RedisStateManager
from storage.storage_client import StorageClient

if TYPE_CHECKING:
    from app.db_client import IndexerDBClient
    from app.indexer_service import IndexerService

logger = logging.getLogger(__name__)

VAULT_DATA_ROOT = os.getenv("VAULT_DATA_ROOT", "/data/vaults")
WATCHDOG_SETTING_KEY = "watchdog_auto_index_extensions"
WATCHDOG_INTERVAL_KEY = "watchdog.interval_sec"
WATCHDOG_DEFAULT_INTERVAL = 60
WATCHDOG_MIN_INTERVAL = 10


async def watchdog_loop(
    db_client: "IndexerDBClient",
    state_manager: RedisStateManager,
    indexer_service: "IndexerService",
    storage_client: StorageClient,
) -> None:
    """Background loop. Started via asyncio.create_task in lifespan.

    Reads interval_sec from platform_settings on every iteration,
    so changes made via UI take effect on the next cycle without restart.
    """
    logger.info("Vault watchdog started (interval from DB, key=%s)", WATCHDOG_INTERVAL_KEY)
    while True:
        try:
            await _run_once(db_client, state_manager, indexer_service, storage_client)
        except asyncio.CancelledError:
            logger.info("Vault watchdog stopped.")
            return
        except Exception:
            logger.exception("Vault watchdog iteration failed, will retry")

        interval_sec = await _read_interval(db_client)
        await asyncio.sleep(interval_sec)


async def _read_interval(db_client: "IndexerDBClient") -> int:
    """Reads watchdog.interval_sec from DB. Falls back to default on any error."""
    try:
        raw = await db_client.get_setting(WATCHDOG_INTERVAL_KEY)
        if raw is not None:
            value = int(raw)
            return max(value, WATCHDOG_MIN_INTERVAL)
    except Exception:
        logger.warning(
            "Watchdog: failed to read interval from DB, using default=%d",
            WATCHDOG_DEFAULT_INTERVAL,
            exc_info=True,
        )
    return WATCHDOG_DEFAULT_INTERVAL


async def _run_once(
    db_client: "IndexerDBClient",
    state_manager: RedisStateManager,
    indexer_service: "IndexerService",
    storage_client: StorageClient,
) -> None:
    """One watchdog iteration across all enabled vaults."""
    # get_setting возвращает None если ключ не найден ИЛИ value=""
    # (сценарий 3 — только ручная индексация): используем `or ""` как guard.
    raw_setting: str = await db_client.get_setting(WATCHDOG_SETTING_KEY) or ""
    auto_extensions: set[str] = {
        ext.strip() for ext in raw_setting.split(",") if ext.strip()
    }

    # get_all_vaults возвращает только enabled=true вольты
    vaults = await db_client.get_all_vaults()

    for vault in vaults:
        vault_id = vault["vault_id"]
        try:
            await _process_vault(
                vault_id=vault_id,
                auto_extensions=auto_extensions,
                db_client=db_client,
                state_manager=state_manager,
                indexer_service=indexer_service,
                storage_client=storage_client,
            )
        except Exception:
            logger.exception("Watchdog: error processing vault_id=%s", vault_id)


async def _process_vault(
    vault_id: str,
    auto_extensions: set[str],
    db_client: "IndexerDBClient",
    state_manager: RedisStateManager,
    indexer_service: "IndexerService",
    storage_client: StorageClient,
) -> None:
    # vault_path строится из env, т.к. vault_path — не колонка в БД
    vault_path = f"{VAULT_DATA_ROOT}/{vault_id}"
    if not os.path.isdir(vault_path):
        return

    try:
        disk_files: list[dict[str, Any]] = await asyncio.to_thread(scan_vault, vault_path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        logger.warning(
            "Watchdog: vault directory unavailable vault_id=%s: %s",
            vault_id, exc,
        )
        return

    disk_index = {f["relative_path"]: f for f in disk_files}

    cache = await state_manager.get_all_vault_file_entries(vault_id)

    deleted_paths = [p for p in cache if p not in disk_index]
    for path in deleted_paths:
        await _handle_deleted(
            vault_id=vault_id,
            relative_path=path,
            db_client=db_client,
            state_manager=state_manager,
            storage_client=storage_client,
        )

    changed: list[dict[str, Any]] = []
    for path, disk_file in disk_index.items():
        entry = cache.get(path)
        if entry is None:
            changed.append(disk_file)
        elif disk_file["checksum"] != entry.get("indexed_md5", ""):
            changed.append(disk_file)

    if not changed:
        return

    to_auto = [f for f in changed if f["extension"] in auto_extensions]
    to_mark = [f for f in changed if f["extension"] not in auto_extensions]

    for f in to_mark:
        await state_manager.mark_file_pending(vault_id, f["relative_path"])
        logger.debug(
            "Watchdog: marked pending vault_id=%s path=%s",
            vault_id, f["relative_path"],
        )

    if to_auto:
        already_indexing = await state_manager.is_vault_indexing(vault_id)
        if not already_indexing:
            logger.info(
                "Watchdog: vault_id=%s changed=%d files",
                vault_id, len(changed),
            )
            try:
                task_id = await indexer_service.start_task(vault_id, force_reindex=False)
                logger.info(
                    "Watchdog: started task task_id=%s vault_id=%s files=%d",
                    task_id, vault_id, len(to_auto),
                )
            except (KeyError, ValueError) as exc:
                logger.warning(
                    "Watchdog: could not start task vault_id=%s: %s",
                    vault_id, exc,
                )
        else:
            logger.debug(
                "Watchdog: vault_id=%s already indexing, skip auto-start",
                vault_id,
            )


async def _handle_deleted(
    vault_id: str,
    relative_path: str,
    db_client: "IndexerDBClient",
    state_manager: RedisStateManager,
    storage_client: StorageClient,
) -> None:
    """Atomically remove a deleted file from LanceDB + PostgreSQL + Redis.

    Order: LanceDB → PG → Redis.
    Redis удаляется последним — при сбое на предыдущих шагах
    следующая итерация watchdog повторит попытку.
    """
    logger.info(
        "Watchdog: file deleted vault_id=%s path=%s",
        vault_id, relative_path,
    )
    doc = await db_client.get_document_by_path(vault_id, relative_path)
    if doc is not None:
        document_id = str(doc["id"])
        try:
            await storage_client.delete_document(document_id, vault_id)
        except Exception:
            logger.warning(
                "Watchdog: failed to delete LanceDB chunks document_id=%s",
                document_id, exc_info=True,
            )
        try:
            await db_client.delete_document(document_id)
        except Exception:
            logger.warning(
                "Watchdog: failed to delete PG document document_id=%s",
                document_id, exc_info=True,
            )

    await state_manager.remove_file_from_vault_cache(vault_id, relative_path)
