from __future__ import annotations

from shared_contracts.models import PipelineContext, PipelineResult


async def execute(context: PipelineContext) -> PipelineResult:
    return PipelineResult(
        content=f"Pipeline rule_lookup handled query: {context.query}",
        confidence=0.5,
        sources=[chunk.chunk_id for chunk in context.context_chunks],
        metadata={"rule_reference": "dummy-v1"},
    )
