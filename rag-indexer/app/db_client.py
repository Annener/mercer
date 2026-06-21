from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg
from cryptography.fernet import Fernet


class IndexerDBClient:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None
        self._fernet: Fernet | None = None

    async def connect(self, database_url: str, encryption_key: str) -> None:
        if not database_url:
            raise RuntimeError("DATABASE_URL is not configured")
        if not encryption_key:
            raise RuntimeError("ENCRYPTION_KEY is not configured")
        self._fernet = Fernet(encryption_key.encode("utf-8"))
        self.pool = await asyncpg.create_pool(
            dsn=database_url.replace("postgresql+asyncpg://", "postgresql://"),
            min_size=1,
            max_size=4,
        )

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def get_platform_settings(self) -> dict[str, Any]:
        rows = await self._fetch("SELECT key, value, value_type FROM platform_settings")
        return {row["key"]: self._cast_value(row["value"], row["value_type"]) for row in rows}

    async def get_vault(self, vault_id: str) -> dict[str, Any] | None:
        row = await self._fetchrow("SELECT * FROM vaults WHERE vault_id = $1", vault_id)
        return dict(row) if row is not None else None

    async def get_all_vaults(self) -> list[dict[str, Any]]:
        """Возвращает все enabled vault'ы. Используется при rebuild_vault_cache."""
        rows = await self._fetch(
            "SELECT vault_id, enabled, vault_path FROM vaults WHERE enabled = true"
        )
        return [dict(row) for row in rows]

    async def get_embedding_model(self, model_id: str) -> dict[str, Any] | None:
        row = await self._fetchrow("SELECT * FROM embedding_models WHERE model_id = $1 AND enabled = true", model_id)
        return dict(row) if row is not None else None

    async def update_vault_chunk_count(self, vault_id: str, delta: int) -> None:
        await self._execute(
            "UPDATE vaults SET chunk_count = GREATEST(chunk_count + $2, 0), updated_at = NOW() WHERE vault_id = $1",
            vault_id,
            delta,
        )

    async def update_vault_binding_status(self, vault_id: str, status: str) -> None:
        await self._execute(
            "UPDATE vaults SET binding_status = $2, updated_at = NOW() WHERE vault_id = $1",
            vault_id,
            status,
        )

    def decrypt_api_key(self, encrypted: str | None) -> str:
        if not encrypted:
            return ""
        if self._fernet is None:
            raise RuntimeError("DB client is not connected")
        return self._fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")

    # -------------------------------------------------------------------------
    # documents registry
    # -------------------------------------------------------------------------

    async def get_document_by_path(
        self, vault_id: str, source_path: str
    ) -> dict[str, Any] | None:
        row = await self._fetchrow(
            "SELECT * FROM documents WHERE vault_id = $1 AND source_path = $2",
            vault_id,
            source_path,
        )
        return dict(row) if row is not None else None

    async def create_document(
        self,
        vault_id: str,
        source_path: str,
        md5: str,
        mtime: int,
    ) -> dict[str, Any]:
        row = await self._fetchrow(
            """
            INSERT INTO documents (vault_id, source_path, md5, mtime, status)
            VALUES ($1, $2, $3, $4, 'pending')
            RETURNING *
            """,
            vault_id,
            source_path,
            md5,
            mtime,
        )
        if row is None:
            raise RuntimeError(f"Failed to insert document: {vault_id}/{source_path}")
        return dict(row)

    async def update_document_status(
        self,
        document_id: str,
        status: str,
        md5: str | None = None,
        mtime: int | None = None,
        indexed_at: datetime | None = None,
    ) -> None:
        sets = ["status = $2"]
        params: list[Any] = [document_id, status]
        idx = 3
        if md5 is not None:
            sets.append(f"md5 = ${idx}")
            params.append(md5)
            idx += 1
        if mtime is not None:
            sets.append(f"mtime = ${idx}")
            params.append(mtime)
            idx += 1
        if indexed_at is not None:
            sets.append(f"indexed_at = ${idx}")
            params.append(indexed_at)
            idx += 1
        await self._execute(
            f"UPDATE documents SET {', '.join(sets)} WHERE id = $1",
            *params,
        )

    async def get_all_documents(self, vault_id: str) -> list[dict[str, Any]]:
        """Возвращает все документы vault'а из PostgreSQL.

        Используется при rebuild_vault_cache для инициализации
        vault:{vault_id}:files в Redis.
        Поля: source_path, md5, mtime, status, indexed_at.
        """
        rows = await self._fetch(
            """
            SELECT source_path, md5, mtime, status, indexed_at
            FROM documents
            WHERE vault_id = $1
            """,
            vault_id,
        )
        return [
            {
                "source_path": row["source_path"],
                "relative_path": row["source_path"],  # alias для rebuild_vault_cache
                "md5": row["md5"],
                "mtime": row["mtime"],
                "status": row["status"],
                "indexed_at": row["indexed_at"].isoformat() if row["indexed_at"] is not None else None,
            }
            for row in rows
        ]

    # -------------------------------------------------------------------------
    # internal helpers
    # -------------------------------------------------------------------------

    async def _fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        if self.pool is None:
            raise RuntimeError("DB client is not connected")
        async with self.pool.acquire() as conn:
            return list(await conn.fetch(query, *args))

    async def _fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        if self.pool is None:
            raise RuntimeError("DB client is not connected")
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def _execute(self, query: str, *args: Any) -> None:
        if self.pool is None:
            raise RuntimeError("DB client is not connected")
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

    def _cast_value(self, value: str, value_type: str) -> Any:
        if value_type == "bool":
            return value.lower() in {"true", "1", "yes", "on"}
        if value_type == "int":
            return int(value)
        if value_type == "float":
            return float(value)
        if value_type == "str":
            return value or None
        return value
