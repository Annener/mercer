from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.dialects.postgresql import insert

from app.db.models import VaultBinding
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)

DEFAULT_BINDINGS_PATH = Path("/app/state/vault_bindings.json")


async def run_migrations() -> None:
    await asyncio.to_thread(_upgrade_head)


async def migrate_vault_bindings_from_json(path: Path = DEFAULT_BINDINGS_PATH) -> None:
    if not path.exists():
        return

    try:
        with path.open("r", encoding="utf-8") as bindings_file:
            payload = json.load(bindings_file)
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read vault bindings JSON: %s", path, exc_info=True)
        return

    if not isinstance(payload, dict):
        logger.warning("Vault bindings JSON must contain an object: %s", path)
        return

    async with SessionLocal() as db:
        for binding in payload.values():
            if not isinstance(binding, dict):
                continue
            statement = insert(VaultBinding).values(
                vault_id=str(binding["vault_id"]),
                embedding_model_id=str(binding["embedding_model_id"]),
                expected_dimensions=int(binding["expected_dimensions"]),
                locked=bool(binding.get("locked", False)),
                status=str(binding.get("status", "unbound")),
                chunk_count=int(binding.get("chunk_count", 0)),
            )
            statement = statement.on_conflict_do_nothing(index_elements=[VaultBinding.vault_id])
            await db.execute(statement)
        await db.commit()

    backup_path = path.with_suffix(".json.bak")
    try:
        path.replace(backup_path)
        logger.info("Migrated vault bindings JSON to PostgreSQL and moved backup to %s", backup_path)
    except OSError:
        logger.warning("Migrated vault bindings JSON but failed to move backup: %s", path, exc_info=True)


def _upgrade_head() -> None:
    config = Config("/app/alembic.ini")
    command.upgrade(config, "head")
