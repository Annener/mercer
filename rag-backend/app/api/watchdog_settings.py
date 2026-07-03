"""API настройки watchdog и pending-files."""
from __future__ import annotations

import json
import logging
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["watchdog"])

logger = logging.getLogger(__name__)

SETTING_KEY_EXTENSIONS = "watchdog_auto_index_extensions"
SETTING_KEY_INTERVAL = "watchdog.interval_sec"
INDEXER_API_URL = os.getenv("INDEXER_API_URL", "http://rag-indexer:9000")


# ------------------------------------------------------------------
# Pydantic-схемы
# ------------------------------------------------------------------

class WatchdogSettings(BaseModel):
    """Payload and response for watchdog settings."""
    auto_index_extensions: list[str]
    """Ordered list of extensions, e.g. [".md", ".pdf"]"""

    interval_sec: int = Field(default=60, ge=10)
    """Scan interval in seconds. Minimum 10."""

    @field_validator("auto_index_extensions", mode="before")
    @classmethod
    def _normalise(cls, v: object) -> list[str]:
        """Accepts a list or a comma-separated string."""
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",") if ext.strip()]
        return [str(e).strip() for e in v if str(e).strip()]

    def extensions_to_db(self) -> str:
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
    """Returns current watchdog settings from PostgreSQL."""
    result = await db.execute(
        text(
            "SELECT key, value FROM platform_settings"
            " WHERE key IN (:key_ext, :key_interval)"
        ),
        {"key_ext": SETTING_KEY_EXTENSIONS, "key_interval": SETTING_KEY_INTERVAL},
    )
    rows = {row[0]: row[1] for row in result.fetchall()}

    raw_ext: str = rows.get(SETTING_KEY_EXTENSIONS, ".md,.pdf")
    raw_interval: str = rows.get(SETTING_KEY_INTERVAL, "60")

    return WatchdogSettings(
        auto_index_extensions=raw_ext,
        interval_sec=int(raw_interval),
    )


# ------------------------------------------------------------------
# PATCH /api/v1/settings/watchdog
# ------------------------------------------------------------------

@router.patch("/settings/watchdog", response_model=WatchdogSettings)
async def update_watchdog_settings(
    payload: WatchdogSettings,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WatchdogSettings:
    """Upserts watchdog settings into PostgreSQL.

    Empty extensions list is valid — means «no auto-indexing».
    Each extension must start with '.'
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
            VALUES (:key, :value, 'str', 'watchdog', 'Авто-индексация расширений', '')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """
        ),
        {"key": SETTING_KEY_EXTENSIONS, "value": payload.extensions_to_db()},
    )
    await db.execute(
        text(
            """
            INSERT INTO platform_settings (key, value, value_type, group_name, label, hint)
            VALUES (:key, :value, 'int', 'watchdog', 'Интервал сканирования (сек)', '')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """
        ),
        {"key": SETTING_KEY_INTERVAL, "value": str(payload.interval_sec)},
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
    """Returns files with index_status='pending' from Redis vault cache."""
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
    """Aggregates pending files across ALL vaults of a domain."""
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

    Uses force_reindex=True to guarantee indexing regardless of Redis cache state.
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
                    json={"vault_id": vault_id, "force_reindex": True},
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
