from __future__ import annotations

import asyncio
import logging

from alembic import command
from alembic.config import Config


logger = logging.getLogger(__name__)


async def run_migrations() -> None:
    await asyncio.to_thread(_upgrade_head)


def _upgrade_head() -> None:
    config = Config("/app/alembic.ini")
    command.upgrade(config, "head")
