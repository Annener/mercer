from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Domain, Vault
from app.db.session import get_db
from app.services.domain_service import domain_service
from .schemas import ClarificationFieldRequest, DomainCreateRequest, DomainUpdateRequest, PromptUpdateRequest

router = APIRouter()
DOMAIN_ID_RE = re.compile(r"^[a-z0-9_]{3,32}$")


@router.get("/domains")
async def list_domains(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    domains = await domain_service.list_domains(db)
    for d in domains:
        if not d.get("enabled"):
            stmt = (
                select(func.count()).select_from(Vault)
                .where(Vault.domain_id == d["domain_id"], Vault.enabled == True)
            )
            result = await db.execute(stmt)
            if result.scalar_one() > 0:
                d["enabled"] = True
                try:
                    await domain_service.update_domain(d["domain_id"], {"enabled": True}, db)
                except Exception:
                    pass
    return domains


@router.post("/domains", status_code=status.HTTP_201_CREATED)
async def create_domain(req: DomainCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if DOMAIN_ID_RE.fullmatch(req.domain_id) is None:
        raise HTTPException(status_code=422, detail="domain_id must match [a-z0-9_]{3,32}")
    try:
        return await domain_service.create_domain(req.model_dump(), db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/domains/{domain_id}")
async def get_domain(domain_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    domain = await db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return {
        "domain_id": domain.domain_id,
        "display_name": domain.display_name,
        "description": domain.description,
        "enabled": domain.enabled,
        "is_system": domain.is_system,
    }


@router.put("/domains/{domain_id}")
async def update_domain(domain_id: str, req: DomainUpdateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await domain_service.update_domain(domain_id, req.model_dump(exclude_unset=True), db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc


@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(domain_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await domain_service.delete_domain(domain_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/domains/{domain_id}/prompts")
async def get_domain_prompts(domain_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    if await db.get(Domain, domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return {
        prompt_type: await domain_service.get_prompt(domain_id, prompt_type, db)
        for prompt_type in ["system", "clarification", "planner", "pipeline_router"]
    }


@router.put("/domains/{domain_id}/prompts/{prompt_type}")
async def update_domain_prompt(
    domain_id: str, prompt_type: str, req: PromptUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if prompt_type not in ["system", "clarification", "planner", "pipeline_router"]:
        raise HTTPException(status_code=422, detail="Invalid prompt type")
    try:
        await domain_service.update_prompts(domain_id, {prompt_type: req.content}, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc
    return {"status": "ok"}


@router.get("/domains/{domain_id}/fields")
async def get_domain_fields(domain_id: str, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    if await db.get(Domain, domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return await domain_service.get_clarification_fields(domain_id, db)


@router.put("/domains/{domain_id}/fields")
async def update_domain_fields(
    domain_id: str, fields: list[ClarificationFieldRequest], db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        await domain_service.update_clarification_fields(
            domain_id, [field.model_dump() for field in fields], db
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Domain not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok"}