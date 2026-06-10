from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import datetime
from typing import Any
import logging
import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import Chat
from app.services.prompt_pack import format_prompt
from app.services.retrieval import (
    format_context_with_role,
    retrieve,
    retrieve_multi_vault,
    get_allowed_tag_ids,
    get_document_ids_by_tags,
)
from app.services.settings_service import settings_service
from shared_contracts.models import PipelineExecutionContext, PipelineRead, PipelineStep, SearchHit

logger = logging.getLogger(__name__)

# Sentinel returned from _run_step when the step is skipped due to no documents.
_SKIPPED = object()


class _ExecutionResult:
    """Result of a non-streaming pipeline execution."""
    __slots__ = ("final_answer", "sources")

    def __init__(self, final_answer: str, sources: list[dict[str, Any]]) -> None:
        self.final_answer = final_answer
        self.sources = sources


class PipelineExecutor:
    """Executes a pipeline against a PipelineExecutionContext.

    Public API:
        run(context)         -> _ExecutionResult          # non-streaming, used by /send
        run_stream(context)  -> AsyncIterator[dict]       # SSE chunks, used by /send_stream

    Tag scoping rules for _retrieve_for_step:
        - Step WITH tag_ids  -> isolated from campaign scope: step.tag_ids used directly.
          Pipeline author is responsible for specifying which tags to query.
          Global domain tags NOT linked to the campaign are accessible intentionally.
        - Step WITHOUT tag_ids + campaign present -> inherit campaign scope:
          own campaign tags + explicitly linked global tags (via campaign_tags table).
        - Step WITHOUT tag_ids + no campaign -> query whole domain (no doc filter).
    """

    def __init__(self, db: AsyncSession) -> None:
        # BUG-2 fix: храним db в self — context не несёт db по контракту shared_contracts
        self.db = db

    # ------------------------------------------------------------------
    # Non-streaming entry point  (used by chat.py /send)
    # ------------------------------------------------------------------

    async def run(self, context: PipelineExecutionContext) -> _ExecutionResult:
        """Execute pipeline and return the final answer as a string.

        Collects all SSE chunks internally; does NOT stream to client.
        """
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

    # ------------------------------------------------------------------
    # Streaming entry point  (used by chat.py /send_stream)
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        context: PipelineExecutionContext,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE-ready dicts for streaming response."""
        db: AsyncSession = self.db
        pipeline = _pipeline_from_context(context)
        async for chunk in self._execute(pipeline, context.query, _ctx_dict(context), db, request=None):
            yield chunk

    # ------------------------------------------------------------------
    # Core async generator (shared between run() and run_stream())
    # ------------------------------------------------------------------

    async def _execute(
        self,
        pipeline: PipelineRead,
        query: str,
        chat_context: dict[str, Any],
        db: AsyncSession,
        request: Request | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
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

            logger.info("Pipeline parallel start: steps=%d pipeline=%s", total, pipeline.pipeline_id)
            tasks = [
                self._run_step(index, step, query, chat_context, db, provider)
                for index, step in enumerate(steps, start=1)
            ]
            step_results = await asyncio.gather(*tasks)
            logger.info("Pipeline parallel done: pipeline=%s", pipeline.pipeline_id)

            step_hits: list[list[SearchHit]] = []
            partial_results: list[str] = []
            for index, step, hits, partial in step_results:
                step_hits.append(hits)
                if partial is _SKIPPED:
                    yield {
                        "type": "step_skipped_no_docs",
                        "step": index,
                        "step_name": step.name,
                    }
                    partial_results.append("")
                else:
                    partial_results.append(partial)
                    yield {
                        "type": "step_done",
                        "step": index,
                        "step_name": step.name,
                        "partial_length": len(partial),
                    }

            await self._check_cancelled(request)

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

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------

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
        config = chat_context.get("config")

        vault_ids: list[str] = chat_context.get("vault_ids") or []

        document_ids: list[str] | None = None  # None = no filter

        if step.tag_ids:
            # Шаг пайплайна изолирован от ограничений кампании:
            # tag_ids шага — прямая инструкция автора пайплайна.
            # Глобальные теги, не добавленные в кампанию, здесь доступны намеренно —
            # пайплайн сам описывает, из каких источников брать данные на каждом шаге.
            if not domain_id:
                logger.warning(
                    "Pipeline step skipped: tag_ids set but no domain_id in context. step=%s",
                    step.name,
                )
                return []

            document_ids = await get_document_ids_by_tags(step.tag_ids, domain_id, db)

            if document_ids == []:
                logger.info(
                    "Pipeline step skipped: no indexed documents for step tag_ids. "
                    "step=%s domain_id=%s tag_ids=%s",
                    step.name, domain_id, step.tag_ids,
                )
                return []

        elif campaign_id and domain_id:
            # Шаг без tag_ids, но чат привязан к кампании —
            # ограничиваем документами тегов кампании (собственные + явно подключённые глобальные)
            allowed = await get_allowed_tag_ids(domain_id, campaign_id, db)
            if not allowed:
                logger.info(
                    "Pipeline step skipped: campaign has no tags at all. step=%s campaign_id=%s",
                    step.name, campaign_id,
                )
                return []
            document_ids = await get_document_ids_by_tags(list(allowed), domain_id, db)
            if document_ids == []:
                logger.info(
                    "Pipeline step skipped: no indexed documents for campaign tags. "
                    "step=%s campaign_id=%s",
                    step.name, campaign_id,
                )
                return []

        logger.info(
            "Pipeline retrieval start: step=%s domain_id=%s vault_ids=%s document_ids=%s top_k=%s",
            step.name, domain_id, vault_ids, document_ids, top_k,
        )

        if not vault_ids:
            logger.warning("Pipeline step skipped: no vault_ids in context. step=%s", step.name)
            return []

        if len(vault_ids) == 1:
            return await retrieve(
                query, vault_ids[0],
                document_ids=document_ids,
                top_k=top_k,
                config=config,
            )
        return await retrieve_multi_vault(
            query, vault_ids,
            document_ids=document_ids,
            top_k=top_k,
            config=config,
        )

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

        logger.info(
            "Step LLM request: step=%s role=%s prompt_chars=%d messages=[system(%d chars), user(%d chars)]",
            step.name, step.role, len(prompt), len(prompt), len(query),
        )
        logger.info(
            "Step LLM prompt full: step=%s\n--- SYSTEM ---\n%s\n--- USER ---\n%s",
            step.name, prompt, query,
        )

        partial = await provider.generate([
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ])

        logger.info(
            "Step LLM response: step=%s chars=%d preview='%s'",
            step.name,
            len(partial),
            partial[:120].replace("\n", " "),
        )

        return index, step, hits, partial

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _check_cancelled(request: Request | None) -> None:
        if request is not None and await request.is_disconnected():
            raise asyncio.CancelledError

    async def _mark_started(
        self, pipeline: PipelineRead, chat_context: dict[str, Any], db: AsyncSession
    ) -> None:
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

    async def _mark_completed(
        self, chat_context: dict[str, Any], db: AsyncSession
    ) -> None:
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


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _pipeline_from_context(context: PipelineExecutionContext) -> PipelineRead:
    """Re-create a PipelineRead stub from the context fields set by PipelineRouter.select()."""
    # BUG-3 fix: domain_id обязательно для PipelineRead (ORMModel)
    return PipelineRead(
        id="",  # stub — нет UUID на этапе выполнения
        pipeline_id=context.pipeline_id,
        domain_id=context.domain_id or "default",
        version=context.pipeline_version or "0",
        name=context.pipeline_id or "unknown",
        steps=context.steps or [],
        final_composition=context.final_composition,
        campaign_id=context.campaign_id,
    )


def _ctx_dict(context: PipelineExecutionContext) -> dict[str, Any]:
    """Convert PipelineExecutionContext to the dict format expected by _execute()."""
    return {
        "chat_id": context.chat_id,
        "domain_id": context.domain_id,
        "campaign_id": context.campaign_id,
        "vault_ids": getattr(context, "vault_ids", []) or [],
        "vault_id": getattr(context, "vault_id", None),
        "history": context.history or [],
        "collected_fields": getattr(context, "collected_fields", {}) or {},
        "mode": getattr(context, "mode", "general"),
        "confidence": getattr(context, "confidence", None),
        "reasoning": getattr(context, "reasoning", ""),
        "config": getattr(context, "config", None),
    }


pipeline_executor = PipelineExecutor.__new__(PipelineExecutor)
