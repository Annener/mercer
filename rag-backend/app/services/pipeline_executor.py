from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any
import logging

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
from shared_contracts.models import PipelineRead, PipelineStep, SearchHit

logger = logging.getLogger(__name__)

# Sentinel returned from _run_step when the step is skipped due to no documents.
_SKIPPED = object()


class PipelineExecutor:
    async def run(self, pipeline, query, chat_context, db, request=None):
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

            steps = sorted(pipeline.steps, key=lambda step: step.order)
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
                    # Step was skipped: no documents found for its tags.
                    yield {
                        "type": "step_skipped_no_docs",
                        "step": index,
                        "step_name": step.name,
                    }
                    partial_results.append("")  # empty contribution to final composition
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
            logger.error("Pipeline execution error: pipeline=%s", getattr(pipeline, "pipeline_id", None), exc_info=True)
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
        config = chat_context.get("config")

        # vault_ids sourced exclusively from domain enabled-Vaults (no legacy fallback).
        vault_ids: list[str] = chat_context.get("vault_ids") or []

        document_ids: list[str] | None = None  # None = no filter

        if step.tag_ids:
            if not domain_id:
                logger.warning(
                    "Pipeline step skipped: tag_ids set but no domain_id in context. step=%s",
                    step.name,
                )
                return []

            allowed = await get_allowed_tag_ids(domain_id, campaign_id, db)
            effective_tag_ids = [t for t in step.tag_ids if t in allowed]

            if not effective_tag_ids:
                logger.warning(
                    "Pipeline step skipped: all tag_ids filtered out by campaign scope. "
                    "step=%s, domain_id=%s, campaign_id=%s",
                    step.name, domain_id, campaign_id,
                )
                return []

            document_ids = await get_document_ids_by_tags(effective_tag_ids, domain_id, db)

            if document_ids == []:
                logger.info(
                    "Pipeline step skipped: no indexed documents for tags. step=%s domain_id=%s",
                    step.name, domain_id,
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
        provider,
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

    @staticmethod
    async def _check_cancelled(request: Request | None) -> None:
        if request is not None and await request.is_disconnected():
            raise asyncio.CancelledError

    async def _mark_started(self, pipeline: PipelineRead, chat_context: dict[str, Any], db: AsyncSession) -> None:
        chat = await db.get(Chat, chat_context["chat_id"])
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
        chat = await db.get(Chat, chat_context["chat_id"])
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


pipeline_executor = PipelineExecutor()
