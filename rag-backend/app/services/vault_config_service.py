from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Vault
from shared_contracts.models import VaultConfigEntry

logger = logging.getLogger(__name__)


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
        # vault_id -> VaultConfigEntry
        self._vaults: dict[str, VaultConfigEntry] = {}
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def vaults(self) -> dict[str, VaultConfigEntry]:
        """Return the current in-memory snapshot.

        Returns an empty dict if ``refresh`` has never been called —
        callers that need fresh data should await ``refresh(db)`` first.
        """
        return self._vaults

    async def refresh(self, db: AsyncSession) -> None:
        """Reload all vaults from the database."""
        result = await db.execute(select(Vault))
        rows = result.scalars().all()
        self._vaults = {
            row.vault_id: VaultConfigEntry(
                vault_id=row.vault_id,
                domain_id=row.domain_id,
                enabled=row.enabled,
                embedding_model_id=row.embedding_model_id,
                expected_dimensions=row.expected_dimensions,
                chunk_size=row.chunk_size,
                overlap=row.overlap,
                entity_aware_mode=row.entity_aware_mode,
                semantic_threshold=row.semantic_threshold,
                binding_status=row.binding_status,
                chunk_count=row.chunk_count,
                git_author_name=row.git_author_name,
                git_author_email=row.git_author_email,
            )
            for row in rows
        }
        self._loaded = True
        logger.debug("VaultConfigService: loaded %d vaults", len(self._vaults))

    async def ensure_loaded(self, db: AsyncSession) -> None:
        """Refresh only on the very first call (lazy init)."""
        if not self._loaded:
            await self.refresh(db)

    def get(self, vault_id: str) -> VaultConfigEntry | None:
        return self._vaults.get(vault_id)

    def enabled_for_domain(self, domain_id: str) -> list[VaultConfigEntry]:
        """Return all enabled vaults belonging to *domain_id*."""
        return [
            v for v in self._vaults.values()
            if v.domain_id == domain_id and v.enabled
        ]

    def invalidate(self) -> None:
        """Force a reload on the next call to ``ensure_loaded``."""
        self._loaded = False
