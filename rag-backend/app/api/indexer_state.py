"""indexer_state.py — Redis-direct endpoints для состояния индексации.

GET /index-tasks/{task_id}/state  — состояние задачи (читает Redis напрямую)
GET /vaults/{vault_id}/index-state — сводка по vault-кэшу в Redis

rag-backend НЕ импортирует RedisStateManager из rag-indexer.
Все чтения выполняются через redis.asyncio напрямую.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(tags=["indexer-state"])


@router.get("/index-tasks/{task_id}/state")
async def get_task_state(task_id: str, request: Request) -> dict:
    """Возвращает состояние задачи индексации, читая Redis напрямую."""
    redis = request.app.state.redis

    task_data = await redis.hgetall(f"task:{task_id}")
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")

    files_raw = await redis.hgetall(f"task:{task_id}:files")
    files = {path: json.loads(data) for path, data in files_raw.items()}

    return {**task_data, "files": files}


@router.get("/vaults/{vault_id}/index-state")
async def get_vault_index_state(vault_id: str, request: Request) -> dict:
    """Возвращает сводку по состоянию файлов vault'а из Redis-кэша."""
    redis = request.app.state.redis

    files_raw = await redis.hgetall(f"vault:{vault_id}:files")
    if not files_raw:
        raise HTTPException(status_code=404, detail="Vault not found in cache")

    files = {path: json.loads(data) for path, data in files_raw.items()}

    by_status: dict[str, int] = {}
    for f in files.values():
        s = f.get("index_status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "vault_id": vault_id,
        "files_total": len(files),
        "by_status": by_status,
        "files": files,
    }
