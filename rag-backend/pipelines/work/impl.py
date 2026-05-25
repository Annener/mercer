from __future__ import annotations

from shared_contracts.models import PipelineContext, PipelineResult


async def execute(context: PipelineContext) -> PipelineResult:
    return PipelineResult(
        content=f"Pipeline work_lookup handled query: {context.query}",
        confidence=0.5,
        sources=[chunk.chunk_id for chunk in context.context_chunks],
        metadata={"work_reference": "dummy-v1"},
    )
