"""API настройки watchdog и pending-files."""
from __future__ import annotations

import json
import logging
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["watchdog"])

logger = logging.getLogger(__name__)

SETTING_KEY = "watchdog_auto_index_extensions"
INDEXER_API_URL = os.getenv("INDEXER_API_URL", "http://rag-indexer:9000")


# ------------------------------------------------------------------
# Pydantic-схемы
# ------------------------------------------------------------------

class WatchdogSettings(BaseModel):
    """Payload and response for watchdog settings."""
    auto_index_extensions: list[str]
    """Ордеред лист расширений, e.g. [".md", ".pdf"]"""

    @field_validator("auto_index_extensions", mode="before")
    @classmethod
    def _normalise(cls, v: object) -> list[str]:
        """Accepts a list or a comma-separated string."""
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",") if ext.strip()]
        return [str(e).strip() for e in v if str(e).strip()]

    def to_db_value(self) -> str:
        return ",".join(self.auto_index_extensions)


class PendingFilesResponse(BaseModel):
    vault_id: str
    pending_files: list[str]
    total: int


class DomainPendingFilesResponse(BaseModel):
    domain_id: str
    total_pending: int
    vaults: list[dict]  # [{vault_id, pending_count}]


class IndexResponse(BaseModel):
    domain_id: str
    queued: int  # количество задач, отправленных в очередь


# ------------------------------------------------------------------
# GET /api/v1/settings/watchdog
# ------------------------------------------------------------------

@router.get("/settings/watchdog", response_model=WatchdogSettings)
async def get_watchdog_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WatchdogSettings:
    """Returns current watchdog auto-index extensions from PostgreSQL."""
    result = await db.execute(
        text("SELECT value FROM platform_settings WHERE key = :key"),
        {"key": SETTING_KEY},
    )
    row = result.fetchone()
    raw: str = row[0] if row else ".md,.pdf"
    return WatchdogSettings(auto_index_extensions=raw)


# ------------------------------------------------------------------
# PATCH /api/v1/settings/watchdog
# ------------------------------------------------------------------

@router.patch("/settings/watchdog", response_model=WatchdogSettings)
async def update_watchdog_settings(
    payload: WatchdogSettings,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WatchdogSettings:
    """Упсертит watchdog setting в PostgreSQL.

    Пустой список допустим — означает «не отслеживать ничего».
    Extension must start with '.'
    """
    for ext in payload.auto_index_extensions:
        if not ext.startswith("."):
            raise HTTPException(
                status_code=422,
                detail=f"Extension must start with '.', got: {ext!r}",
            )

    await db.execute(
        text(
            """
            INSERT INTO platform_settings (key, value, value_type, group_name, label, hint)
            VALUES (:key, :value, 'str', 'indexing', 'Авто-индексация расширений', '')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """
        ),
        {"key": SETTING_KEY, "value": payload.to_db_value()},
    )
    await db.commit()
    return payload


# ------------------------------------------------------------------
# GET /api/v1/vaults/{vault_id}/pending-files  (per-vault, внутренний)
# ------------------------------------------------------------------

@router.get("/vaults/{vault_id}/pending-files", response_model=PendingFilesResponse)
async def get_pending_files(
    vault_id: str,
    request: Request,
) -> PendingFilesResponse:
    """Returns files with index_status='pending' from Redis vault cache.

    Reads vault:{vault_id}:files HASH directly via request.app.state.redis.
    Does NOT call rag-indexer.
    """
    r = request.app.state.redis
    raw: dict[str, str] = await r.hgetall(f"vault:{vault_id}:files")

    pending: list[str] = []
    for path, value in raw.items():
        if path == "__empty__":
            continue
        try:
            entry = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue
        if entry.get("index_status") == "pending":
            pending.append(path)

    return PendingFilesResponse(
        vault_id=vault_id,
        pending_files=sorted(pending),
        total=len(pending),
    )


# ------------------------------------------------------------------
# GET /api/v1/domains/{domain_id}/pending-files  (агрегирующий, для фронтенда)
# ------------------------------------------------------------------

@router.get("/domains/{domain_id}/pending-files", response_model=DomainPendingFilesResponse)
async def get_domain_pending_files(
    domain_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DomainPendingFilesResponse:
    """Aggregates pending files across ALL vaults of a domain.

    Fetches vault_ids for the domain from PostgreSQL,
    then reads each vault's Redis cache and sums pending counts.
    Used by the frontend pending-files banner in the chat.
    """
    result = await db.execute(
        text("SELECT vault_id FROM vaults WHERE domain_id = :domain_id"),
        {"domain_id": domain_id},
    )
    rows = result.fetchall()
    vault_ids = [row[0] for row in rows]

    r = request.app.state.redis
    vaults_summary = []
    total_pending = 0

    for vault_id in vault_ids:
        raw: dict[str, str] = await r.hgetall(f"vault:{vault_id}:files")
        count = 0
        for path, value in raw.items():
            if path == "__empty__":
                continue
            try:
                entry = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
            if entry.get("index_status") == "pending":
                count += 1
        vaults_summary.append({"vault_id": vault_id, "pending_count": count})
        total_pending += count

    return DomainPendingFilesResponse(
        domain_id=domain_id,
        total_pending=total_pending,
        vaults=vaults_summary,
    )


# ------------------------------------------------------------------
# POST /api/v1/domains/{domain_id}/index  (запуск индексации pending-файлов)
# ------------------------------------------------------------------

@router.post("/domains/{domain_id}/index", response_model=IndexResponse)
async def trigger_domain_index(
    domain_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IndexResponse:
    """Triggers indexing for all vaults of a domain via rag-indexer HTTP API.

    For each vault in the domain sends:
        POST {INDEXER_API_URL}/api/v1/tasks
        {"vault_id": "<id>", "force_reindex": false}

    Returns the number of successfully queued tasks.
    Does NOT wait for indexing to complete — fire-and-forget.
    """
    result = await db.execute(
        text("SELECT vault_id FROM vaults WHERE domain_id = :domain_id"),
        {"domain_id": domain_id},
    )
    vault_ids = [row[0] for row in result.fetchall()]

    queued = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for vault_id in vault_ids:
            try:
                resp = await client.post(
                    f"{INDEXER_API_URL}/api/v1/tasks",
                    json={"vault_id": vault_id, "force_reindex": False},
                )
                resp.raise_for_status()
                queued += 1
                logger.info(
                    "Queued indexing task: vault_id=%s task_id=%s",
                    vault_id,
                    resp.json().get("task_id", "?"),
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Indexer rejected task for vault_id=%s: status=%d body=%s",
                    vault_id, exc.response.status_code, exc.response.text,
                )
            except Exception:
                logger.warning(
                    "Failed to queue indexing task for vault_id=%s",
                    vault_id,
                    exc_info=True,
                )

    return IndexResponse(domain_id=domain_id, queued=queued)
