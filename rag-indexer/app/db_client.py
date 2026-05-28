from __future__ import annotations

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

    async def get_embedding_model(self, model_id: str) -> dict[str, Any] | None:
        row = await self._fetchrow("SELECT * FROM embedding_models WHERE model_id = $1 AND enabled = true", model_id)
        return dict(row) if row is not None else None

    async def get_worlds_for_vault(self, vault_id: str) -> list[dict[str, Any]]:
        rows = await self._fetch(
            "SELECT * FROM worlds WHERE vault_id = $1 AND is_active = true ORDER BY path_prefix DESC",
            vault_id,
        )
        return [dict(row) for row in rows]

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
