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

from app.db.models import Chat, World
from app.services.prompt_pack import format_prompt
from app.services.retrieval import format_context_with_role, retrieve
from app.services.settings_service import settings_service
from shared_contracts.models import PipelineRead, PipelineStep, SearchHit

logger = logging.getLogger(__name__)


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
                partial_results.append(partial)
                yield {"type": "step_done", "step": index, "step_name": step.name, "partial_length": len(partial)}

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
            yield {"type": "error", "message": str(exc)}

    async def _retrieve_for_step(self, query, step, chat_context, db):
        top_k = step.top_k or int(await settings_service.get("retrieval.top_k", db))
        vault_id = chat_context.get("vault_id")
        config = chat_context.get("config")
    
        logger.info(
            "Pipeline retrieval start: step=%s type=%s vault_id=%s document_ids=%s world_id=%s top_k=%s",
            step.name, step.type, vault_id, step.document_ids, step.world_id, top_k,
        )
    
        if step.type == "book":
            hits = await retrieve(query, vault_id, document_ids=step.document_ids, top_k=top_k, config=config)
        elif step.type == "world":
            world = await db.execute(select(World).where(World.world_id == step.world_id))
            world = world.scalar_one_or_none()
            world_path_prefix = world.path_prefix if world else None
            logger.info("World lookup: world_id=%s found=%s path_prefix=%s", 
                step.world_id, world is not None, world_path_prefix)
            hits = await retrieve(query, vault_id, world_id=step.world_id, world_path_prefix=world_path_prefix, categories=step.categories, top_k=top_k, config=config)
        elif step.type == "campaign":
            hits = await retrieve(query, vault_id, campaign_id=step.campaign_id, top_k=top_k, config=config)
        else:
            hits = []
    
        logger.info(
            "Pipeline retrieval done: step=%s hits=%d vault_id=%s",
            step.name, len(hits), vault_id,
        )
        return hits

    async def _run_step(
        self,
        index: int,
        step: PipelineStep,
        query: str,
        chat_context: dict[str, Any],
        db: AsyncSession,
        provider,
    ) -> tuple[int, PipelineStep, list[SearchHit], str]:
        hits = await self._retrieve_for_step(query, step, chat_context, db)

        # Пропускаем LLM-вызов если retrieval вернул пустой результат
        if not hits:
            logger.info(
                "Step skipped (no hits): step=%s type=%s",
                step.name, step.type,
            )
            return index, step, hits, ""

        context_block = format_context_with_role(hits, step.role)
        prompt = format_prompt(step.system_prompt, {"context": context_block, "query": query})

        # Логируем запрос в модель
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

        # Логируем ответ модели
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