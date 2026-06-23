from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat
from app.services.pipeline_dag import get_execution_levels
from app.services.query_rewriter import query_rewriter
from app.services.retrieval import (
    format_context_with_role,
    get_document_ids_by_tags,
    retrieve,
    retrieve_multi_vault,
)
from app.services.settings_service import settings_service
from shared_contracts.models import (
    PipelineExecutionContext,
    PipelineStep,
    SearchHit,
)

logger = logging.getLogger(__name__)


def _status(text: str) -> dict:
    """Emits a step_status chunk for displaying progress in the frontend."""
    return {"type": "step_status", "text": text}


# Validation token lives 1 hour.
_VALIDATION_TTL = timedelta(hours=1)


# =============================================================================
# Module-level shim
# =============================================================================

def _build_levels(steps: list[PipelineStep]) -> list[list[PipelineStep]]:
    """Shim: redirects to get_execution_levels() from pipeline_dag.

    Kept for backward compatibility with tests.
    """
    return get_execution_levels(steps)


def _resolve_prompt(template: str, ctx: PipelineExecutionContext) -> str:
    """Substitute {query}, {STEP_ID.result}, {STEP_ID.key} in prompt template."""
    result = template.replace("{query}", ctx.query)
    for step_id, value in ctx.step_results.items():
        if step_id.startswith("_"):
            continue
        result = result.replace(f"{{{step_id}.result}}", str(value))
        if isinstance(value, dict):
            for k, v in value.items():
                result = result.replace(f"{{{step_id}.{k}}}", str(v))
    return result


# =============================================================================
# PipelineExecutor
# =============================================================================

class PipelineExecutor:
    """Executes pipeline DAG with validation-pause support.

    Public API:
        run_stream(ctx)                  -> AsyncIterator[dict]
        resume_from_validation(ctx, sid) -> AsyncIterator[dict]
    """

    def __init__(
        self,
        db: AsyncSession,
        session_factory=None,
    ) -> None:
        self.db = db
        self._session_factory = session_factory

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def run_stream(
        self,
        ctx: PipelineExecutionContext,
    ) -> AsyncIterator[dict[str, Any]]:
        """Start pipeline from DAG level 0."""
        async for chunk in self._dag_execute(ctx, start_after_step=None):
            yield chunk

    async def resume_from_validation(
        self,
        ctx: PipelineExecutionContext,
        validated_step_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Continue pipeline after user response to a validation step."""
        async for chunk in self._dag_execute(ctx, start_after_step=validated_step_id):
            yield chunk

    # -------------------------------------------------------------------------
    # Core DAG async generator
    # -------------------------------------------------------------------------

    async def _dag_execute(
        self,
        ctx: PipelineExecutionContext,
        start_after_step: str | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        provider = settings_service.get_active_provider()
        if provider is None:
            yield {"type": "error", "message": "No active model configured"}
            return

        yield {"type": "pipeline_selected", "pipeline_id": ctx.pipeline_id}

        levels = get_execution_levels(ctx.steps)

        start_level = 0
        if start_after_step is not None:
            for lvl_idx, level in enumerate(levels):
                for step in level:
                    if step.step_id == start_after_step:
                        start_level = lvl_idx + 1
                        break

        for level in levels[start_level:]:
            if len(level) == 1:
                stop = False
                async for chunk in self._run_dag_step(level[0], ctx, provider):
                    if chunk.get("__stop__"):
                        yield chunk["__payload__"]
                        stop = True
                        break
                    yield chunk
                if stop:
                    return
            else:
                stop = False
                async for chunk in self._run_parallel_level(level, ctx, provider):
                    if chunk.get("__stop__"):
                        yield chunk["__payload__"]
                        stop = True
                        break
                    yield chunk
                if stop:
                    return

        logger.info(
            "All DAG levels complete, starting final_composition. step_results keys=%s",
            list(ctx.step_results.keys()),
        )
        async for chunk in self._run_final_composition(ctx, provider):
            yield chunk

    async def _run_dag_step(
        self,
        step: PipelineStep,
        ctx: PipelineExecutionContext,
        provider: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if step.type == "validation":
            async for chunk in self._run_validation_step(step, ctx):
                yield chunk
            return

        yield _status(f"Searching knowledge base: {step.name}...")
        try:
            hits = await self._retrieve_for_step_dag(step, ctx, provider)
        except Exception as exc:
            logger.error(
                "Step retrieval error: step=%s err=%s", step.step_id, exc, exc_info=True
            )
            ctx.step_results[step.step_id] = ""
            yield {"type": "step_error", "step_id": step.step_id, "message": str(exc)}
            return

        if not hits:
            if step.step_id not in ctx.step_results:
                ctx.step_results[step.step_id] = ""
            yield {"type": "step_skipped_no_docs", "step_id": step.step_id, "step_name": step.name}
            return

        formatted = format_context_with_role(hits, getattr(step, "role", None))
        ctx.step_results[step.step_id] = formatted
        yield {"type": "step_complete", "step_id": step.step_id, "step_name": step.name}

    async def _run_validation_step(
        self,
        step: PipelineStep,
        ctx: PipelineExecutionContext,
    ) -> AsyncGenerator[dict[str, Any], None]:
        resume_token = secrets.token_urlsafe(32)
        await self._save_pause_state(ctx, step.step_id, step.name, resume_token)
        content = _resolve_prompt(
            step.validation_prompt or step.system_prompt or "",
            ctx,
        )
        yield {
            "__stop__": True,
            "__payload__": {
                "type": "validation_required",
                "step_id": step.step_id,
                "step_name": step.name,
                "content": content,
                "options": step.options or [],
                "resume_token": resume_token,
            },
        }

    async def _run_parallel_level(
        self,
        steps: list[PipelineStep],
        ctx: PipelineExecutionContext,
        provider: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """asyncio.gather() for steps in same level with independent DB sessions."""
        if not self._session_factory:
            logger.warning(
                "PipelineExecutor: no session_factory — parallel steps run sequentially. "
                "Pass session_factory=async_sessionmaker to enable true parallelism."
            )
            for step in steps:
                async for chunk in self._run_dag_step(step, ctx, provider):
                    yield chunk
            return

        async def _step_with_session(step: PipelineStep) -> list[dict]:
            chunks: list[dict] = []
            async with self._session_factory() as session:
                orig_db = self.db
                self.db = session
                try:
                    async for chunk in self._run_dag_step(step, ctx, provider):
                        chunks.append(chunk)
                finally:
                    self.db = orig_db
            return chunks

        results = await asyncio.gather(
            *[_step_with_session(step) for step in steps],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.error("Parallel step error: %s", result, exc_info=True)
                yield {"type": "error", "message": str(result)}
                continue
            for chunk in result:
                yield chunk

    async def _run_final_composition(
        self,
        ctx: PipelineExecutionContext,
        provider: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        prompt = _resolve_prompt(ctx.final_composition.system_prompt, ctx)
        yield _status("Generating response...")
        try:
            async for token in provider.generate_stream([
                {"role": "system", "content": prompt},
                {"role": "user", "content": ctx.query},
            ]):
                yield {"type": "token", "content": token}
        except Exception as exc:
            logger.error("FinalComposition stream error: %s", exc, exc_info=True)
            yield {"type": "error", "message": f"LLM stream error: {exc}"}
            return
        yield {"type": "pipeline_complete"}

    async def _retrieve_for_step_dag(
        self,
        step: PipelineStep,
        ctx: PipelineExecutionContext,
        provider: Any,
    ) -> list[SearchHit]:
        """Retrieval for a DAG step.

        Search query is formed via rewrite_for_retrieval: combines step goal
        (step.system_prompt) and user query into an optimal vector query.
        """
        top_k = step.top_k or int(await settings_service.get("retrieval.top_k"))
        vault_ids: list[str] = ctx.vault_ids or []

        if not vault_ids:
            logger.warning("Step skipped: no vault_ids in context. step=%s", step.step_id)
            return []

        document_ids: list[str] | None = None
        if step.tag_ids:
            domain_id = ctx.domain_id
            if not domain_id:
                logger.warning("Step skipped: tag_ids set but no domain_id. step=%s", step.step_id)
                return []
            document_ids = await get_document_ids_by_tags(step.tag_ids, domain_id, self.db)
            if document_ids == []:
                logger.info("Step skipped: no indexed docs for tag_ids. step=%s", step.step_id)
                return []

        step_prompt = _resolve_prompt(step.system_prompt or "", ctx)
        search_query = await query_rewriter.rewrite_for_retrieval(
            ctx.query,
            step_prompt,
            provider,
        )
        logger.info(
            "RETRIEVE step=%s search_query='%s'",
            step.step_id,
            search_query[:120],
        )

        if len(vault_ids) == 1:
            return await retrieve(search_query, vault_ids[0], document_ids=document_ids, top_k=top_k, db=self.db)
        return await retrieve_multi_vault(search_query, vault_ids, document_ids=document_ids, top_k=top_k, db=self.db)

    async def _save_pause_state(
        self,
        ctx: PipelineExecutionContext,
        step_id: str,
        step_name: str,
        resume_token: str,
    ) -> None:
        """Save pipeline_pause_state in Chat.

        context_snapshot is a full context dump via model_dump(),
        so _restore_context() in pipeline_resume.py can fully restore
        PipelineExecutionContext including steps, final_composition, pipeline_id and vault_ids.
        """
        try:
            chat = await self.db.get(Chat, uuid.UUID(ctx.chat_id))
            if chat is None:
                logger.warning("_save_pause_state: chat %s not found", ctx.chat_id)
                return
            chat.pipeline_pause_state = {
                "pipeline_id": ctx.pipeline_id,
                "step_id": step_id,
                "step_name": step_name,
                "resume_token": resume_token,
                "query": ctx.query,
                "context_snapshot": ctx.model_dump(mode="json"),
                "expires_at": (datetime.now(UTC) + _VALIDATION_TTL).isoformat(),
            }
            await self.db.commit()
        except Exception as exc:
            logger.warning("_save_pause_state failed: %s", exc)
