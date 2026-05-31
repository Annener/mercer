from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Vault

logger = logging.getLogger(__name__)


class _VaultEntry:
    """Lightweight DTO mirroring shared_contracts.models.VaultConfigEntry."""

    __slots__ = ("vault_id", "domain_id", "enabled", "embedding_model_id",
                 "expected_dimensions", "chunk_size", "overlap",
                 "entity_aware_mode", "binding_status", "chunk_count")

    def __init__(self, row: Vault) -> None:
        self.vault_id: str = row.vault_id
        self.domain_id: str | None = row.domain_id
        self.enabled: bool = row.enabled
        self.embedding_model_id: str | None = row.embedding_model_id
        self.expected_dimensions: int | None = row.expected_dimensions
        self.chunk_size: int | None = row.chunk_size
        self.overlap: int | None = row.overlap
        self.entity_aware_mode: bool | None = row.entity_aware_mode
        self.binding_status: str = row.binding_status
        self.chunk_count: int = row.chunk_count


class VaultConfigService:
    """
    In-process vault registry.

    Usage pattern in chat.py::

        config_for_vault = VaultConfigService()           # module-level singleton

        vault_ids = [
            v.vault_id for v in config_for_vault.vaults.values()
            if v.domain_id == domain_id and v.enabled
        ]

    The ``.vaults`` dict is populated lazily on the first call to
    ``refresh(db)`` and can be refreshed at any time (e.g. after a vault
    is created / updated / deleted via the settings API).

    Because the object is used as a module-level singleton the dict is
    shared across requests; writes should always go through ``refresh``.
    """

    def __init__(self) -> None:
        # vault_id -> _VaultEntry
        self._vaults: dict[str, _VaultEntry] = {}
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def vaults(self) -> dict[str, _VaultEntry]:
        """Return the current in-memory snapshot.

        Returns an empty dict if ``refresh`` has never been called —
        callers that need fresh data should await ``refresh(db)`` first.
        """
        return self._vaults

    async def refresh(self, db: AsyncSession) -> None:
        """Reload all vaults from the database."""
        result = await db.execute(select(Vault))
        rows = result.scalars().all()
        self._vaults = {row.vault_id: _VaultEntry(row) for row in rows}
        self._loaded = True
        logger.debug("VaultConfigService: loaded %d vaults", len(self._vaults))

    async def ensure_loaded(self, db: AsyncSession) -> None:
        """Refresh only on the very first call (lazy init)."""
        if not self._loaded:
            await self.refresh(db)

    def get(self, vault_id: str) -> _VaultEntry | None:
        return self._vaults.get(vault_id)

    def enabled_for_domain(self, domain_id: str) -> list[_VaultEntry]:
        """Return all enabled vaults belonging to *domain_id*."""
        return [
            v for v in self._vaults.values()
            if v.domain_id == domain_id and v.enabled
        ]

    def invalidate(self) -> None:
        """Force a reload on the next call to ``ensure_loaded``."""
        self._loaded = False
