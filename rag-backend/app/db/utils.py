from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def transactional(db: AsyncSession) -> AsyncIterator[None]:
    """Async context manager that wraps a unit of work in a DB transaction.

    - If a transaction is already active (e.g. the caller opened one),
      commits on success and rolls back on exception.
    - Otherwise delegates to db.begin() which handles commit/rollback.
    """
    if db.in_transaction():
        try:
            yield
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    else:
        async with db.begin():
            yield
