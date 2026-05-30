from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmbeddingModel, Vault
from app.db.session import get_db
from app.services.settings_service import settings_service
from .helpers import _check_pdf_sidecar

router = APIRouter()


@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    has_active_generation_model = settings_service.get_active_provider() is not None
    embedding_count = await db.execute(
        select(func.count()).select_from(Vault)
        .join(EmbeddingModel, Vault.embedding_model_id == EmbeddingModel.model_id)
        .where(Vault.embedding_model_id.is_not(None), EmbeddingModel.enabled == True)
    )
    vault_count = await db.execute(select(func.count()).select_from(Vault).where(Vault.enabled == True))
    try:
        sidecar_url = await settings_service.get("pdf_sidecar.url", db)
    except KeyError as exc:
        raise HTTPException(status_code=500, detail="pdf_sidecar.url not configured") from exc
    return {
        "has_active_generation_model": has_active_generation_model,
        "has_active_embedding_model": embedding_count.scalar_one() > 0,
        "pdf_sidecar_available": await _check_pdf_sidecar(str(sidecar_url)),
        "has_vaults": vault_count.scalar_one() > 0,
    }