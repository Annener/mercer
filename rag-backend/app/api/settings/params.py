from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.settings_service import settings_service
from .schemas import ParamUpdateRequest

router = APIRouter()


@router.get("/params")
async def get_params(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await settings_service.get_all(db)


@router.put("/params/{key:path}")
async def update_param(key: str, req: ParamUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        await settings_service.set(key, req.value, db)
        settings_service.invalidate(key)
        value = await settings_service.get(key, db)
        return {"key": key, "value": value}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Parameter not found") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reset")
async def reset_params(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await settings_service.reset_all(db)
    return {"status": "ok"}