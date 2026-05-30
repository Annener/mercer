from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Domain, Pipeline
from app.db.session import get_db
from .helpers import _get_pipeline_by_uuid, _validate_pipeline_json, _increment_patch, pipeline_dict
from .schemas import PipelineCreateRequest, PipelineUpdateRequest

router = APIRouter()
SLUG_RE = re.compile(r"^[a-z0-9-]{3,64}$")


@router.get("/pipelines")
async def list_pipelines(domain_id: str | None = None, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    stmt = select(Pipeline).order_by(Pipeline.pipeline_id, Pipeline.version)
    if domain_id:
        stmt = stmt.where(Pipeline.domain_id == domain_id)
    result = await db.execute(stmt)
    return [pipeline_dict(pipeline) for pipeline in result.scalars().all()]


@router.post("/pipelines", status_code=status.HTTP_201_CREATED)
async def create_pipeline(req: PipelineCreateRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if SLUG_RE.fullmatch(req.pipeline_id) is None:
        raise HTTPException(status_code=422, detail="pipeline_id must be a slug with 3-64 characters")
    if await db.get(Domain, req.domain_id) is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    _validate_pipeline_json(req.steps, req.final_composition)
    duplicate = await db.execute(select(Pipeline).where(Pipeline.pipeline_id == req.pipeline_id, Pipeline.version == "1.0.0"))
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Pipeline version already exists")
    pipeline = Pipeline(**req.model_dump(), version="1.0.0")
    db.add(pipeline)
    await db.commit()
    await db.refresh(pipeline)
    return pipeline_dict(pipeline)


@router.put("/pipelines/{pipeline_uuid}")
async def update_pipeline(
    pipeline_uuid: str, req: PipelineUpdateRequest, db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    pipeline = await _get_pipeline_by_uuid(pipeline_uuid, db)
    payload = req.model_dump(exclude_unset=True)
    steps = payload.get("steps", pipeline.steps)
    final_composition = payload.get("final_composition", pipeline.final_composition)
    _validate_pipeline_json(steps, final_composition)
    new_version = _increment_patch(pipeline.version)
    await db.execute(update(Pipeline).where(Pipeline.pipeline_id == pipeline.pipeline_id).values(is_active=False))
    new_pipeline = Pipeline(
        pipeline_id=pipeline.pipeline_id,
        domain_id=payload.get("domain_id", pipeline.domain_id),
        version=new_version,
        name=payload.get("name", pipeline.name),
        description=payload.get("description", pipeline.description),
        steps=steps,
        final_composition=final_composition,
        is_active=payload.get("is_active", True),
    )
    db.add(new_pipeline)
    await db.commit()
    await db.refresh(new_pipeline)
    return pipeline_dict(new_pipeline)


@router.delete("/pipelines/{pipeline_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(pipeline_uuid: str, db: AsyncSession = Depends(get_db)) -> Response:
    pipeline = await _get_pipeline_by_uuid(pipeline_uuid, db)
    await db.delete(pipeline)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/pipelines/{pipeline_uuid}/activate")
async def activate_pipeline(pipeline_uuid: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    pipeline = await _get_pipeline_by_uuid(pipeline_uuid, db)
    await db.execute(update(Pipeline).where(Pipeline.pipeline_id == pipeline.pipeline_id).values(is_active=False))
    pipeline.is_active = True
    await db.commit()
    return {"status": "ok"}


@router.post("/pipelines/{pipeline_uuid}/deactivate")
async def deactivate_pipeline(pipeline_uuid: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    pipeline = await _get_pipeline_by_uuid(pipeline_uuid, db)
    pipeline.is_active = False
    await db.commit()
    return {"status": "ok"}