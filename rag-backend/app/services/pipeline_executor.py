from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import settings_service
from app.services.retrieval import (
    get_allowed_tag_ids,
    get_document_ids_by_tags,
    retrieve,
    retrieve_multi_vault,
)
from shared_contracts.models import PipelineExecutionContext, PipelineStep

logger = logging.getLogger(__name__)


class PipelineExecutor:
    """
    Executes a resolved pipeline (steps already populated by PipelineRouter).

    Each step has an optional `tag_ids` list that scopes retrieval.

    Tag scoping rules:
    - Step WITH tag_ids  → isolated: use step.tag_ids directly, no campaign
                           scope filter. The pipeline author is responsible for
                           specifying which tags to query on each step.
    - Step WITHOUT tag_ids, campaign present → inherit campaign scope:
                           own campaign tags + explicitly linked global tags.
    - Step WITHOUT tag_ids, no campaign → query whole domain (no doc filter).

    The same get_allowed_tag_ids logic is reused in the fallback RAG path
    (chat without pipeline), ensuring consistent access control outside pipelines.
    """

    async def run(
        self,
        context: PipelineExecutionContext,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Execute pipeline synchronously, return assembled result."""
        results: dict[str, Any] = {}
        chat_context = context.chat_context or {}

        for index, step in enumerate(context.steps or []):
            step_result = await self._run_step(index, step, context.query, chat_context, db)
            results[step.name] = step_result

        return {
            "results": results,
            "final_composition": context.final_composition,
            "pipeline_id": str(context.pipeline_id) if context.pipeline_id else None,
        }

    async def run_stream(
        self,
        context: PipelineExecutionContext,
        db: AsyncSession,
    ):
        """Execute pipeline with SSE streaming."""
        chat_context = context.chat_context or {}
        results: dict[str, Any] = {}

        yield {
            "type": "pipeline_selected",
            "pipeline_id": str(context.pipeline_id) if context.pipeline_id else None,
            "pipeline_name": context.pipeline_name or "",
            "steps": [s.name for s in (context.steps or [])],
        }

        try:
            for index, step in enumerate(context.steps or []):
                yield {
                    "type": "progress",
                    "step_index": index,
                    "step_name": step.name,
                    "total_steps": len(context.steps or []),
                }

                step_result = await self._run_step(
                    index, step, context.query, chat_context, db
                )

                if step_result is None or (isinstance(step_result, list) and not step_result):
                    yield {
                        "type": "step_skipped_no_docs",
                        "step_index": index,
                        "step_name": step.name,
                    }
                    results[step.name] = []
                    continue

                results[step.name] = step_result
                yield {
                    "type": "step_done",
                    "step_index": index,
                    "step_name": step.name,
                    "doc_count": len(step_result) if isinstance(step_result, list) else 1,
                }

            # Final composition / generation
            async for chunk in self._generate_stream(context, results, db):
                yield chunk

        except Exception as exc:
            logger.error(
                "Pipeline execution error: pipeline=%s",
                getattr(context, "pipeline_id", None),
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

        # vault_ids sourced exclusively from domain enabled-Vaults (no legacy fallback).
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
    ) -> list:
        """Run a single pipeline step: retrieve docs, optionally run sub-LLM call."""
        docs = await self._retrieve_for_step(query, step, chat_context, db)
        return docs

    # ------------------------------------------------------------------
    # Generation helpers
    # ------------------------------------------------------------------

    async def _generate_stream(
        self,
        context: PipelineExecutionContext,
        results: dict[str, Any],
        db: AsyncSession,
    ):
        """
        Final generation step: assemble context from step results and stream tokens.
        Uses context.final_composition template if provided.
        """
        from app.services.llm import stream_llm_response  # local import to avoid circular

        all_docs: list = []
        for step_docs in results.values():
            if isinstance(step_docs, list):
                all_docs.extend(step_docs)

        if not all_docs:
            yield {"type": "token", "content": "Не найдено релевантных материалов по запросу."}
            yield {"type": "sources", "sources": []}
            yield {"type": "done"}
            return

        # Build context string
        ctx_parts = []
        for doc in all_docs:
            text = doc.get("text") or doc.get("content") or ""
            source = doc.get("source") or doc.get("document_id") or ""
            if text:
                ctx_parts.append(f"[{source}]\n{text}")
        context_str = "\n\n---\n\n".join(ctx_parts)

        composition = context.final_composition or (
            "На основе следующих материалов ответь на вопрос пользователя.\n\n"
            "Материалы:\n{context}\n\nВопрос: {query}"
        )
        prompt = composition.format(
            context=context_str,
            query=context.query or "",
        )

        chat_context = context.chat_context or {}
        history = chat_context.get("history") or []
        config = chat_context.get("config")

        sources = []
        seen_ids: set[str] = set()
        for doc in all_docs:
            doc_id = doc.get("document_id") or doc.get("id") or ""
            if doc_id and doc_id not in seen_ids:
                seen_ids.add(doc_id)
                sources.append({
                    "document_id": doc_id,
                    "source": doc.get("source") or "",
                    "title": doc.get("title") or doc.get("source") or "",
                })

        try:
            async for token in stream_llm_response(
                system_prompt=prompt,
                history=history,
                user_message=context.query or "",
                config=config,
                db=db,
            ):
                yield {"type": "token", "content": token}
        except Exception as e:
            logger.error("LLM generation error in pipeline: %s", e, exc_info=True)
            yield {"type": "error", "message": f"Ошибка генерации: {e}"}
            return

        yield {"type": "sources", "sources": sources}
        yield {"type": "done"}
