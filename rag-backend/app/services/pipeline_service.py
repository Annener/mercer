from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Pipeline
from shared_contracts.models import FinalComposition, PipelineCreate, PipelineRead, PipelineStep, PipelineUpdate


VALID_ROLES = {"methodology", "lore", "campaign_context", "character_sheet", "session_log", "rules"}
VALID_STEP_TYPES = {"book", "world", "campaign"}


class PipelineService:
    def __init__(self) -> None:
        self._cache: dict[str, PipelineRead] = {}

    async def list_pipelines(self, db: AsyncSession, domain_id: str | None = None) -> list[PipelineRead]:
        stmt = select(Pipeline).order_by(Pipeline.pipeline_id, Pipeline.version)
        if domain_id is not None:
            stmt = stmt.where(Pipeline.domain_id == domain_id)
        result = await db.execute(stmt)
        return [self._to_read(pipeline) for pipeline in result.scalars().all()]

    async def get_active_pipelines(self, domain_id: str, db: AsyncSession) -> list[PipelineRead]:
        result = await db.execute(
            select(Pipeline).where(Pipeline.domain_id == domain_id, Pipeline.is_active == True).order_by(Pipeline.pipeline_id)
        )
        return [self._to_read(pipeline) for pipeline in result.scalars().all()]

    async def get_pipeline(self, pipeline_id: str, db: AsyncSession, version: str | None = None) -> PipelineRead | None:
        stmt = select(Pipeline).where(Pipeline.pipeline_id == pipeline_id)
        if version is None:
            stmt = stmt.where(Pipeline.is_active == True)
        else:
            stmt = stmt.where(Pipeline.version == version)
        result = await db.execute(stmt)
        pipeline = result.scalar_one_or_none()
        return self._to_read(pipeline) if pipeline is not None else None

    async def get_pipeline_by_uuid(self, pipeline_uuid: str, db: AsyncSession) -> PipelineRead | None:
        try:
            parsed = uuid.UUID(pipeline_uuid)
        except ValueError:
            return None
        pipeline = await db.get(Pipeline, parsed)
        return self._to_read(pipeline) if pipeline is not None else None

    async def create_pipeline(self, data: PipelineCreate, db: AsyncSession) -> PipelineRead:
        steps = [step.model_dump(exclude_none=True) for step in data.steps]
        final_composition = data.final_composition.model_dump()
        validate_pipeline_payload(steps, final_composition)
        pipeline = Pipeline(
            pipeline_id=data.pipeline_id,
            domain_id=data.domain_id,
            version="1.0.0",
            name=data.name,
            description=data.description,
            steps=steps,
            final_composition=final_composition,
            is_active=True,
        )
        db.add(pipeline)
        await db.commit()
        await db.refresh(pipeline)
        self.invalidate(data.pipeline_id)
        return self._to_read(pipeline)

    async def update_pipeline(self, pipeline_uuid: str, data: PipelineUpdate, db: AsyncSession) -> PipelineRead:
        parsed = uuid.UUID(pipeline_uuid)
        current = await db.get(Pipeline, parsed)
        if current is None:
            raise KeyError(pipeline_uuid)
        steps = [step.model_dump(exclude_none=True) for step in data.steps]
        final_composition = data.final_composition.model_dump()
        validate_pipeline_payload(steps, final_composition)
        await db.execute(update(Pipeline).where(Pipeline.pipeline_id == current.pipeline_id).values(is_active=False))
        replacement = Pipeline(
            pipeline_id=current.pipeline_id,
            domain_id=data.domain_id,
            version=_increment_patch(current.version),
            name=data.name,
            description=data.description,
            steps=steps,
            final_composition=final_composition,
            is_active=data.is_active,
        )
        db.add(replacement)
        await db.commit()
        await db.refresh(replacement)
        self.invalidate(current.pipeline_id)
        return self._to_read(replacement)

    async def deactivate_pipeline(self, pipeline_uuid: str, db: AsyncSession) -> None:
        parsed = uuid.UUID(pipeline_uuid)
        pipeline = await db.get(Pipeline, parsed)
        if pipeline is None:
            raise KeyError(pipeline_uuid)
        pipeline.is_active = False
        await db.commit()
        self.invalidate(pipeline.pipeline_id)

    async def activate_pipeline(self, pipeline_uuid: str, db: AsyncSession) -> None:
        parsed = uuid.UUID(pipeline_uuid)
        pipeline = await db.get(Pipeline, parsed)
        if pipeline is None:
            raise KeyError(pipeline_uuid)
        await db.execute(update(Pipeline).where(Pipeline.pipeline_id == pipeline.pipeline_id).values(is_active=False))
        pipeline.is_active = True
        await db.commit()
        self.invalidate(pipeline.pipeline_id)

    def invalidate(self, pipeline_id: str | None = None) -> None:
        if pipeline_id is None:
            self._cache.clear()
        else:
            self._cache.pop(pipeline_id, None)

    def _to_read(self, pipeline: Pipeline) -> PipelineRead:
        return PipelineRead(
            id=str(pipeline.id),
            pipeline_id=pipeline.pipeline_id,
            domain_id=pipeline.domain_id,
            version=pipeline.version,
            name=pipeline.name,
            description=pipeline.description,
            steps=[PipelineStep.model_validate(step) for step in pipeline.steps],
            final_composition=FinalComposition.model_validate(pipeline.final_composition),
            is_active=pipeline.is_active,
            created_at=pipeline.created_at,
        )


def validate_pipeline_payload(steps: list[dict[str, Any]], final_composition: dict[str, Any]) -> None:
    if not steps:
        raise ValueError("steps must be non-empty")
    orders: set[int] = set()
    for step in steps:
        for key in ("order", "type", "name", "role", "system_prompt"):
            if key not in step:
                raise ValueError(f"Pipeline step missing {key}")
        if not isinstance(step["order"], int) or step["order"] in orders:
            raise ValueError("Pipeline step order must be unique int")
        orders.add(step["order"])
        if step["type"] not in VALID_STEP_TYPES:
            raise ValueError("Invalid pipeline step type")
        if step["role"] not in VALID_ROLES:
            raise ValueError("Invalid pipeline step role")
        if "top_k" in step and step["top_k"] is not None and int(step["top_k"]) <= 0:
            raise ValueError("top_k must be positive")
        if step["type"] == "book" and not step.get("document_ids"):
            raise ValueError("book step requires document_ids")
        if step["type"] == "world" and not step.get("world_id"):
            raise ValueError("world step requires world_id")
        if step["type"] == "campaign" and not step.get("campaign_id"):
            raise ValueError("campaign step requires campaign_id")
    if not isinstance(final_composition.get("system_prompt"), str):
        raise ValueError("final_composition.system_prompt is required")


def _increment_patch(version: str) -> str:
    try:
        major, minor, patch = [int(part) for part in version.split(".")]
    except ValueError:
        return "1.0.1"
    return f"{major}.{minor}.{patch + 1}"


pipeline_service = PipelineService()
