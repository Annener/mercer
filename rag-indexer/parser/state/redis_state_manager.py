"""Redis-базированное хранилище состояния задач индексации.

Заменяет файловый state_manager.py. Все методы async.

Redis-ключи:
  task:{task_id}          HASH  — метаданные задачи (TTL 86400с)
  task:{task_id}:files    HASH  — статус каждого файла (TTL 86400с)
  vault:{vault_id}:files  HASH  — кэш vault'а (без TTL)
  active_tasks            SET   — активные task_id
  cancel:{task_id}        STRING — флаг отмены (TTL 3600с)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

TASK_TTL = 86400  # 24ч для task:* ключей
CANCEL_TTL = 3600  # 1ч для cancel:* ключей


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RedisStateManager:
    """Стате-менеджер на базе Redis.

    Ожидает redis.asyncio.Redis с decode_responses=True.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis

    # ------------------------------------------------------------------
    # Задачи индексации (TTL 24ч)
    # ------------------------------------------------------------------

    async def create_task(
        self,
        task_id: str,
        vault_id: str,
        files_to_index: list[dict],
        files_skipped: int,
        files_total: int,
    ) -> None:
        """Создаёт task:{task_id} HASH и task:{task_id}:files HASH.

        Устанавливает TTL 86400с на оба ключа.
        Добавляет task_id в SET active_tasks.
        """
        task_key = f"task:{task_id}"
        files_key = f"task:{task_id}:files"

        task_data: dict[str, str] = {
            "status": "running",
            "vault_id": vault_id,
            "started_at": _now_iso(),
            "finished_at": "",
            "files_total": str(files_total),
            "files_skipped": str(files_skipped),
            "files_to_index": str(len(files_to_index)),
            "files_done": "0",
            "error": "",
        }

        pipe = self._r.pipeline()
        pipe.hset(task_key, mapping=task_data)  # type: ignore[arg-type]
        pipe.expire(task_key, TASK_TTL)

        for file_info in files_to_index:
            relative_path = str(file_info.get("relative_path", "")).strip()
            if not relative_path:
                continue
            file_data = json.dumps(
                {
                    "stage": "pending",
                    "chunks_total": 0,
                    "chunks_done": 0,
                    "checksum_md5": str(file_info.get("checksum", "")),
                    "error": None,
                },
                ensure_ascii=False,
            )
            pipe.hset(files_key, relative_path, file_data)

        pipe.expire(files_key, TASK_TTL)
        pipe.sadd("active_tasks", task_id)
        await pipe.execute()

    async def update_file_stage(
        self,
        task_id: str,
        relative_path: str,
        stage: str,
        chunks_total: int = 0,
        chunks_done: int = 0,
        checksum_md5: str = "",
        error: str | None = None,
    ) -> None:
        """Обновляет поле файла в task:{task_id}:files HASH."""
        files_key = f"task:{task_id}:files"
        existing_raw = await self._r.hget(files_key, relative_path)
        if existing_raw:
            existing = json.loads(existing_raw)
        else:
            existing = {"stage": "pending", "chunks_total": 0, "chunks_done": 0, "checksum_md5": "", "error": None}

        existing["stage"] = stage
        existing["chunks_total"] = chunks_total
        existing["chunks_done"] = chunks_done
        if checksum_md5:
            existing["checksum_md5"] = checksum_md5
        existing["error"] = error

        await self._r.hset(files_key, relative_path, json.dumps(existing, ensure_ascii=False))

    async def increment_files_done(self, task_id: str) -> None:
        """HINCRBY task:{task_id} files_done 1."""
        await self._r.hincrby(f"task:{task_id}", "files_done", 1)

    async def mark_task_done(self, task_id: str, error: str | None = None) -> None:
        """Устанавливает status=done/error, finished_at. SREM active_tasks."""
        task_key = f"task:{task_id}"
        status = "error" if error else "done"
        pipe = self._r.pipeline()
        pipe.hset(task_key, mapping={  # type: ignore[arg-type]
            "status": status,
            "finished_at": _now_iso(),
            "error": error or "",
        })
        pipe.srem("active_tasks", task_id)
        await pipe.execute()

    async def mark_task_cancelled(self, task_id: str) -> None:
        """Устанавливает status=cancelled. SREM active_tasks."""
        task_key = f"task:{task_id}"
        pipe = self._r.pipeline()
        pipe.hset(task_key, mapping={  # type: ignore[arg-type]
            "status": "cancelled",
            "finished_at": _now_iso(),
        })
        pipe.srem("active_tasks", task_id)
        await pipe.execute()

    async def get_task_state(self, task_id: str) -> dict[str, Any] | None:
        """Возвращает task HASH + files HASH или None.

        Структура: {"status": ..., "vault_id": ..., ..., "files": {"path": {...}}}
        """
        task_key = f"task:{task_id}"
        files_key = f"task:{task_id}:files"

        task_data = await self._r.hgetall(task_key)
        if not task_data:
            return None

        files_raw = await self._r.hgetall(files_key)
        files: dict[str, Any] = {}
        for path, raw in files_raw.items():
            try:
                files[path] = json.loads(raw)
            except json.JSONDecodeError:
                files[path] = {"stage": "unknown", "error": "parse error"}

        return {**task_data, "files": files}

    # ------------------------------------------------------------------
    # Vault cache (без TTL)
    # ------------------------------------------------------------------

    async def rebuild_vault_cache(
        self,
        vault_id: str,
        pg_documents: list[dict],
        disk_files: list[dict],
    ) -> None:
        """Рестроит vault:{vault_id}:files HASH из PostgreSQL + диска.

        Логика index_status:
          нет на диске                          -> "deleted"
          нет в pg или status != indexed        -> "pending"
          disk.checksum == pg.md5 и indexed   -> "indexed"
          иначе                                -> "stale"
        """
        vault_key = f"vault:{vault_id}:files"

        pg_index: dict[str, dict] = {}
        for doc in pg_documents:
            path = doc.get("relative_path") or doc.get("source_path", "")
            pg_index[path] = doc

        disk_index: dict[str, dict] = {}
        for f in disk_files:
            path = f.get("relative_path", "")
            disk_index[path] = f

        all_paths = set(pg_index) | set(disk_index)

        if not all_paths:
            await self._r.delete(vault_key)
            await self._r.hset(vault_key, "__empty__", "1")
            return

        pipe = self._r.pipeline()
        pipe.delete(vault_key)

        for path in all_paths:
            in_disk = path in disk_index
            pg_doc = pg_index.get(path)

            if not in_disk:
                index_status = "deleted"
            elif pg_doc is None or pg_doc.get("status") != "indexed":
                index_status = "pending"
            elif disk_index[path].get("checksum") == pg_doc.get("md5"):
                index_status = "indexed"
            else:
                index_status = "stale"

            entry = {
                "md5": pg_doc.get("md5", "") if pg_doc else "",
                "index_status": index_status,
                "indexed_md5": pg_doc.get("md5", "") if (pg_doc and index_status == "indexed") else "",
                "chunks_total": pg_doc.get("chunks_count", 0) if pg_doc else 0,
            }
            pipe.hset(vault_key, path, json.dumps(entry, ensure_ascii=False))

        await pipe.execute()

    async def mark_file_indexed(
        self,
        vault_id: str,
        relative_path: str,
        md5: str,
        chunks_total: int,
    ) -> None:
        """Обновляет запись в vault:{vault_id}:files."""
        vault_key = f"vault:{vault_id}:files"
        existing_raw = await self._r.hget(vault_key, relative_path)
        if existing_raw and existing_raw != "1":
            try:
                existing = json.loads(existing_raw)
            except json.JSONDecodeError:
                existing = {}
        else:
            existing = {}

        existing["index_status"] = "indexed"
        existing["indexed_md5"] = md5
        existing["md5"] = md5
        existing["chunks_total"] = chunks_total

        await self._r.hset(vault_key, relative_path, json.dumps(existing, ensure_ascii=False))

    async def mark_file_pending(
        self,
        vault_id: str,
        relative_path: str,
    ) -> None:
        """Sets index_status='pending' in vault:{vault_id}:files.

        Preserves existing md5/indexed_md5/chunks_total fields.
        Does NOT remove the file from vault cache.
        """
        vault_key = f"vault:{vault_id}:files"
        existing_raw = await self._r.hget(vault_key, relative_path)
        if existing_raw and existing_raw != "1":
            try:
                existing = json.loads(existing_raw)
            except json.JSONDecodeError:
                existing = {}
        else:
            existing = {}

        existing["index_status"] = "pending"
        await self._r.hset(
            vault_key, relative_path, json.dumps(existing, ensure_ascii=False)
        )

    async def remove_file_from_vault_cache(
        self,
        vault_id: str,
        relative_path: str,
    ) -> None:
        """HDEL vault:{vault_id}:files relative_path."""
        await self._r.hdel(f"vault:{vault_id}:files", relative_path)

    async def get_vault_file_entry(
        self,
        vault_id: str,
        relative_path: str,
    ) -> dict[str, Any] | None:
        """Returns parsed entry from vault:{vault_id}:files or None."""
        raw = await self._r.hget(f"vault:{vault_id}:files", relative_path)
        if not raw or raw == "1":
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def get_all_vault_file_entries(
        self,
        vault_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Returns all file entries from vault:{vault_id}:files.

        Skips the __empty__ sentinel.
        Returns {relative_path: entry_dict}.
        """
        raw = await self._r.hgetall(f"vault:{vault_id}:files")
        result: dict[str, dict[str, Any]] = {}
        for path, value in raw.items():
            if path == "__empty__":
                continue
            try:
                result[path] = json.loads(value)
            except json.JSONDecodeError:
                result[path] = {"index_status": "unknown"}
        return result

    async def get_vault_state(self, vault_id: str) -> dict[str, Any] | None:
        """Возвращает все файлы + счётчики по статусам."""
        vault_key = f"vault:{vault_id}:files"
        raw = await self._r.hgetall(vault_key)
        if not raw:
            return None

        files: dict[str, Any] = {}
        counts: dict[str, int] = {"indexed": 0, "pending": 0, "stale": 0, "deleted": 0}
        for path, value in raw.items():
            if path == "__empty__":
                continue
            try:
                entry = json.loads(value)
            except json.JSONDecodeError:
                entry = {"index_status": "unknown"}
            files[path] = entry
            status = entry.get("index_status", "unknown")
            if status in counts:
                counts[status] += 1

        return {"files": files, "counts": counts}

    async def is_vault_indexing(self, vault_id: str) -> bool:
        """Returns True if there is a running task for this vault in Redis.

        Uses pipeline to fetch all active task metadata in one round-trip.
        """
        active_ids = await self._r.smembers("active_tasks")
        if not active_ids:
            return False
        pipe = self._r.pipeline()
        for task_id in active_ids:
            pipe.hmget(f"task:{task_id}", "vault_id", "status")
        results = await pipe.execute()
        for values in results:
            if values[0] == vault_id and values[1] == "running":
                return True
        return False

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    async def request_cancel(self, task_id: str) -> None:
        """SET cancel:{task_id} 1 EX 3600."""
        await self._r.set(f"cancel:{task_id}", "1", ex=CANCEL_TTL)

    async def is_cancelled(self, task_id: str) -> bool:
        """Ехистс cancel:{task_id}."""
        return bool(await self._r.exists(f"cancel:{task_id}"))

    async def clear_cancel(self, task_id: str) -> None:
        """DEL cancel:{task_id}."""
        await self._r.delete(f"cancel:{task_id}")
