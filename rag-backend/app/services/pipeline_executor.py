from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat
from app.services.prompt_pack import format_prompt
from app.services.retrieval import (
    format_context_with_role,
    get_allowed_tag_ids,
    get_document_ids_by_tags,
    retrieve,
    retrieve_multi_vault,
)
from app.services.settings_service import settings_service
from shared_contracts.models import (
    PipelineExecutionContext,
    PipelineRead,
    PipelineStep,
    SearchHit,
)

logger = logging.getLogger(__name__)

_SKIPPED = object()


# =============================================================================
# DAG helpers (Этап 6)
# =============================================================================

def _build_levels(steps: list[PipelineStep]) -> list[list[PipelineStep]]:
    """Топологическая сортировка шагов по уровням на основе after_step_ids.

    Уровень 0 — шаги без зависимостей (стартовые).
    Уровень N — шаги, все зависимости которых находятся в уровнях 0..N-1.
    """
    level_map: dict[str, int] = {}

    queue: list[str] = [s.step_id for s in steps if not s.after_step_ids]
    for sid in queue:
        level_map[sid] = 0

    visited_as_parent: set[str] = set()
    while queue:
        nxt: list[str] = []
        for sid in queue:
            if sid in visited_as_parent:
                continue
            visited_as_parent.add(sid)
            cur_level = level_map[sid]
            for s in steps:
                if sid in s.after_step_ids:
                    candidate = max(level_map.get(s.step_id, 0), cur_level + 1)
                    level_map[s.step_id] = candidate
                    if all(dep in level_map for dep in s.after_step_ids):
                        if s.step_id not in nxt:
                            nxt.append(s.step_id)
        queue = nxt

    for s in steps:
        if s.step_id not in level_map:
            level_map[s.step_id] = 0

    buckets: dict[int, list[PipelineStep]] = defaultdict(list)
    for s in steps:
        buckets[level_map[s.step_id]].append(s)

    return [buckets[i] for i in sorted(buckets)]


def _resolve_prompt(template: str, ctx: PipelineExecutionContext) -> str:
    """Подставить {query}, {STEP_ID.result}, {STEP_ID.key} в шаблон промта."""
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

class _ExecutionResult:
    """Result of a non-streaming pipeline execution."""
    __slots__ = ("final_answer", "sources")

    def __init__(self, final_answer: str, sources: list[dict[str, Any]]) -> None:
        self.final_answer = final_answer
        self.sources = sources


class PipelineExecutor:
    """Executes a pipeline against a PipelineExecutionContext.

    New API (Этап 6, DAG):
        run_stream(ctx)                  -> AsyncIterator[dict]
        resume_from_validation(ctx, sid) -> AsyncIterator[dict]

    Legacy API (сохранён до Этапа 8):
        run(ctx)                         -> _ExecutionResult
    """

    def __init__(
        self,
        db: AsyncSession,
        session_factory=None,
    ) -> None:
        self.db = db
        self._session_factory = session_factory

    # -------------------------------------------------------------------------
    # NEW API: DAG execution (Этап 6)
    # -------------------------------------------------------------------------

    async def run_stream(
        self,
        ctx: PipelineExecutionContext,
    ) -> AsyncIterator[dict[str, Any]]:
        """Запустить пайплайн с 0-го уровня DAG."""
        async for chunk in self._dag_execute(ctx, start_after_step=None):
            yield chunk

    async def resume_from_validation(
        self,
        ctx: PipelineExecutionContext,
        validated_step_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Продолжить пайплайн после пользовательского ответа на validation-шаг."""
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

        levels = _build_levels(ctx.steps)

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

        hits = await self._retrieve_for_step_dag(step, ctx)
        if not hits:
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
        await self._save_pause_state(ctx, step.step_id, resume_token)
        yield {
            "__stop__": True,
            "__payload__": {
                "type": "validation_required",
                "step_id": step.step_id,
                "step_name": step.name,
                "content": getattr(step, "validation_prompt", None) or step.system_prompt,
                "options": getattr(step, "options", None) or [],
                "resume_token": resume_token,
            },
        }

    async def _run_parallel_level(
        self,
        steps: list[PipelineStep],
        ctx: PipelineExecutionContext,
        provider: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """asyncio.gather() для шагов одного уровня с независимыми DB-сессиями."""
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
    ) -> list[SearchHit]:
        """Retrieval для DAG-шага через ctx.vault_ids + step.tag_ids."""
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

        if len(vault_ids) == 1:
            return await retrieve(ctx.query, vault_ids[0], document_ids=document_ids, top_k=top_k, db=self.db)
        return await retrieve_multi_vault(ctx.query, vault_ids, document_ids=document_ids, top_k=top_k, db=self.db)

    async def _save_pause_state(
        self,
        ctx: PipelineExecutionContext,
        step_id: str,
        resume_token: str,
    ) -> None:
        """Сохранить pipeline_pause_state в Chat."""
        try:
            chat = await self.db.get(Chat, uuid.UUID(ctx.chat_id))
            if chat is None:
                return
            chat.pipeline_pause_state = {
                "step_id": step_id,
                "resume_token": resume_token,
                "context_snapshot": {
                    "step_results": dict(ctx.step_results),
                    "query": ctx.query,
                },
                "expires_at": datetime.now(UTC).isoformat(),
            }
            await self.db.commit()
        except Exception as exc:
            logger.warning("_save_pause_state failed: %s", exc)

    # -------------------------------------------------------------------------
    # LEGACY API (сохранён до Этапа 8, не трогаем)
    # -------------------------------------------------------------------------

    async def run(self, context: PipelineExecutionContext) -> _ExecutionResult:
        """[LEGACY] Линейный запуск для /send — сохранён до Этапа 8."""
        db: AsyncSession = self.db
        pipeline = _pipeline_from_context(context)
        final_answer = ""
        sources: list[dict[str, Any]] = []
        async for chunk in self._execute(pipeline, context.query, _ctx_dict(context), db, request=None):
            if chunk.get("type") == "token":
                final_answer += chunk.get("content", "")
            elif chunk.get("type") == "sources":
                for group in chunk.get("step_groups", []):
                    sources.extend(group.get("sources", []))
            elif chunk.get("type") == "error":
                logger.error("Pipeline run() got error chunk: %s", chunk.get("message"))
                raise RuntimeError(chunk.get("message", "Pipeline execution error"))
        return _ExecutionResult(final_answer=final_answer, sources=sources)

    async def _execute(
        self,
        pipeline: PipelineRead,
        query: str,
        chat_context: dict[str, Any],
        db: AsyncSession,
        request: Request | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """[LEGACY] Линейный executor. Будет удалён в Этапе 8."""
        try:
            await self._check_cancelled(request)
            await self._mark_started(pipeline, chat_context, db)
            yield {
                "type": "pipeline_selected",
                "pipeline_id": pipeline.pipeline_id,
                "pipeline_name": pipeline.name,
                "reasoning": chat_context.get("reasoning", "executing pipeline"),
                "mode": chat_context.get("mode", "auto"),
            }

            steps = sorted(pipeline.steps, key=lambda s: s.order)
            provider = settings_service.get_active_provider()
            if provider is None:
                raise RuntimeError("No active generation model configured")
            total = len(steps)

            for index, step in enumerate(steps, start=1):
                yield {"type": "progress", "step": index, "total": total, "step_name": step.name}

            logger.info("Pipeline sequential start: steps=%d pipeline=%s", total, pipeline.pipeline_id)
            step_results = []
            for index, step in enumerate(steps, start=1):
                result = await self._run_step(index, step, query, chat_context, db, provider)
                step_results.append(result)
            logger.info("Pipeline sequential done: pipeline=%s", pipeline.pipeline_id)

            step_hits: list[list[SearchHit]] = []
            partial_results: list[str] = []
            for index, step, hits, partial in step_results:
                step_hits.append(hits)
                if partial is _SKIPPED:
                    yield {"type": "step_skipped_no_docs", "step": index, "step_name": step.name}
                    partial_results.append("")
                else:
                    partial_results.append(partial)
                    yield {"type": "step_done", "step": index, "step_name": step.name, "partial_length": len(partial)}

            await self._check_cancelled(request)
            _deprecated_context_vars(
                combined_context="\n\n---\n\n".join(filter(None, partial_results)),
                chat_context=chat_context,
            )
            combined_context = "\n\n---\n\n".join(filter(None, partial_results))
            final_prompt = format_prompt(
                pipeline.final_composition.system_prompt,
                {
                    "context": combined_context,
                    "collected_fields": json.dumps(
                        chat_context.get("collected_fields") or {}, ensure_ascii=False
                    ),
                },
            )
            async for token in provider.generate_stream([
                {"role": "system", "content": final_prompt},
                {"role": "user", "content": query},
            ]):
                await self._check_cancelled(request)
                yield {"type": "token", "content": token}

            yield {
                "type": "sources",
                "grouped_by_step": True,
                "step_groups": [
                    {
                        "step": index,
                        "step_name": step.name,
                        "sources": self._gather_sources_for_step(step_hits[index - 1]),
                    }
                    for index, step in enumerate(steps, start=1)
                ],
            }
            await self._mark_completed(chat_context, db)

        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error(
                "Pipeline execution error: pipeline=%s",
                getattr(pipeline, "pipeline_id", None),
                exc_info=True,
            )
            yield {"type": "error", "message": str(exc)}

    async def _retrieve_for_step(
        self,
        query: str,
        step: PipelineStep,
        chat_context: dict,
        db: AsyncSession,
    ) -> list:
        top_k = step.top_k or int(await settings_service.get("retrieval.top_k", db))
        domain_id: str | None = chat_context.get("domain_id")
        campaign_id: str | None = chat_context.get("campaign_id")
        vault_ids: list[str] = chat_context.get("vault_ids") or []
        document_ids: list[str] | None = None

        if step.tag_ids:
            if not domain_id:
                logger.warning("Pipeline step skipped: tag_ids set but no domain_id. step=%s", step.name)
                return []
            document_ids = await get_document_ids_by_tags(step.tag_ids, domain_id, db)
            if document_ids == []:
                logger.info("Pipeline step skipped: no indexed documents for step tag_ids. step=%s", step.name)
                return []
        elif campaign_id and domain_id:
            allowed = await get_allowed_tag_ids(domain_id, campaign_id, db)
            if not allowed:
                logger.info("Pipeline step skipped: campaign has no tags. step=%s", step.name)
                return []
            document_ids = await get_document_ids_by_tags(list(allowed), domain_id, db)
            if document_ids == []:
                logger.info("Pipeline step skipped: no indexed documents for campaign tags. step=%s", step.name)
                return []

        if not vault_ids:
            logger.warning("Pipeline step skipped: no vault_ids in context. step=%s", step.name)
            return []

        if len(vault_ids) == 1:
            return await retrieve(query, vault_ids[0], document_ids=document_ids, top_k=top_k, db=db)
        return await retrieve_multi_vault(query, vault_ids, document_ids=document_ids, top_k=top_k, db=db)

    async def _run_step(
        self,
        index: int,
        step: PipelineStep,
        query: str,
        chat_context: dict[str, Any],
        db: AsyncSession,
        provider: Any,
    ) -> tuple[int, PipelineStep, list[SearchHit], Any]:
        hits = await self._retrieve_for_step(query, step, chat_context, db)
        if not hits:
            logger.info("Step skipped (no hits): step=%s", step.name)
            return index, step, hits, _SKIPPED
        context_block = format_context_with_role(hits, step.role)
        prompt = format_prompt(step.system_prompt, {"context": context_block, "query": query})
        partial = await provider.generate([
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ])
        return index, step, hits, partial

    @staticmethod
    async def _check_cancelled(request: Request | None) -> None:
        if request is not None and await request.is_disconnected():
            raise asyncio.CancelledError

    async def _mark_started(self, pipeline: PipelineRead, chat_context: dict[str, Any], db: AsyncSession) -> None:
        chat_id = chat_context.get("chat_id")
        if not chat_id:
            return
        chat = await db.get(Chat, uuid.UUID(str(chat_id)))
        if chat is None:
            return
        versions = dict(chat.pipeline_versions or {})
        versions["last_used"] = {
            "pipeline_id": pipeline.pipeline_id,
            "version": pipeline.version,
            "started_at": datetime.utcnow().isoformat(),
        }
        chat.pipeline_versions = versions
        await db.commit()

    async def _mark_completed(self, chat_context: dict[str, Any], db: AsyncSession) -> None:
        chat_id = chat_context.get("chat_id")
        if not chat_id:
            return
        chat = await db.get(Chat, uuid.UUID(str(chat_id)))
        if chat is None:
            return
        versions = dict(chat.pipeline_versions or {})
        last_used = dict(versions.get("last_used") or {})
        last_used["completed_at"] = datetime.utcnow().isoformat()
        versions["last_used"] = last_used
        chat.pipeline_versions = versions
        await db.commit()

    @staticmethod
    def _gather_sources_for_step(hits: list[SearchHit]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, int | None, str]] = set()
        for hit in hits:
            metadata = hit.metadata or {}
            path = metadata.get("source_path") or hit.document_id
            page = metadata.get("page_number")
            vault_id = metadata.get("vault_id") or ""
            key = (path, page, vault_id)
            if key in seen:
                continue
            seen.add(key)
            sources.append({"path": path, "page": page, "vault_id": vault_id})
        return sources


# =============================================================================
# Module-level helpers (legacy)
# =============================================================================

def _pipeline_from_context(context: PipelineExecutionContext) -> PipelineRead:
    return PipelineRead(
        id="",
        pipeline_id=context.pipeline_id,
        domain_id=context.domain_id or "default",
        version=context.pipeline_version or "0",
        name=context.pipeline_id or "unknown",
        steps=context.steps or [],
        final_composition=context.final_composition,
        campaign_id=context.campaign_id,
    )


def _ctx_dict(context: PipelineExecutionContext) -> dict[str, Any]:
    return {
        "chat_id": context.chat_id,
        "domain_id": context.domain_id,
        "campaign_id": context.campaign_id,
        "vault_ids": getattr(context, "vault_ids", []) or [],
        "vault_id": getattr(context, "vault_id", None),
        "history": context.history or [],
        "collected_fields": {},
        "mode": getattr(context, "mode", "general"),
        "confidence": getattr(context, "confidence", None),
        "reasoning": getattr(context, "reasoning", ""),
    }


def _deprecated_context_vars(combined_context: str, chat_context: dict[str, Any]) -> None:
    """[DEPRECATED] Удалить в Этапе 8 после применения миграции."""
    logger.debug(
        "_deprecated_context_vars called: combined_context_len=%d — "
        "migrate to {STEP_ID.result} variables",
        len(combined_context),
    )


# Module-level singleton (legacy usage)
pipeline_executor = PipelineExecutor.__new__(PipelineExecutor)
