from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Chat, Message
from app.providers.generation.base import GenerationProvider
from app.services.domain_service import domain_service
from app.services.pipeline_service import pipeline_service
from app.services.settings_service import settings_service
from shared_contracts.models import PipelineExecutionContext, PipelineRead


logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """Ты — маршрутизатор запросов для домена "{domain_id}".

Доступные pipelines:
{pipelines_list}

Query пользователя: "{query}"
История чата (последние 3 сообщения):
{chat_history}

Проанализируй запрос и выбери наиболее подходящий pipeline.
Верни ТОЛЬКО валидный JSON в формате:
{{"pipeline_id": "...", "confidence": 0.0-1.0, "reasoning": "..."}}

Правила:
- confidence >= 0.7 — высокая уверенность
- confidence 0.5-0.7 — средняя уверенность
- confidence < 0.5 — низкая уверенность (система отклонит выбор)
- Если ни один pipeline не подходит — верни {{"pipeline_id": null, "confidence": 0.0, "reasoning": "..."}}
"""


class PipelineRouter:
    """Маршрутизатор пайплайнов.

    Публичный API (используется в chat.py):
        select(context, locked_pipeline_id) -> PipelineRead | None

    Внутренний API (legacy, используется в тестах):
        decide(query, chat, db) -> tuple[...]
    """

    # ------------------------------------------------------------------
    # Основной метод — принимает PipelineExecutionContext (iter2+)
    # ------------------------------------------------------------------

    async def select(
        self,
        context: PipelineExecutionContext,
        locked_pipeline_id: str | None = None,
        db: AsyncSession | None = None,
        llm_provider: GenerationProvider | None = None,
    ) -> PipelineRead | None:
        """Выбрать пайплайн по контексту.

        1. Если locked_pipeline_id — вернуть его без LLM-вызова (проверяем режим).
        2. Получить активные пайплайны домена, отфильтровать по campaign_id.
        3. LLM-роутинг по query + history.
        4. Вернуть PipelineRead или None (→ chat.py переходит на plain RAG).
        """
        if db is None:
            raise ValueError("db session is required for PipelineRouter.select()")

        domain_id: str = context.domain_id or "default"
        campaign_id: str | None = context.campaign_id
        query: str = context.query
        mode: str = "campaign" if campaign_id else "general"

        # --- locked pipeline ---
        if locked_pipeline_id:
            pipeline = await pipeline_service.get_pipeline(locked_pipeline_id, db)
            if pipeline is not None:
                # Validate mode compatibility: campaign pipeline must not leak into general mode and vice versa.
                pipeline_is_campaign = pipeline.campaign_id is not None
                if pipeline_is_campaign and mode == "general":
                    logger.warning(
                        "Locked pipeline is campaign-specific but chat is in general mode; ignoring lock. "
                        "pipeline_id=%s campaign_id=%s",
                        locked_pipeline_id, pipeline.campaign_id,
                    )
                elif not pipeline_is_campaign and mode == "campaign":
                    # General pipeline allowed in campaign mode (fallback).
                    pass
                context.pipeline_id = pipeline.pipeline_id
                context.pipeline_version = pipeline.version
                context.steps = pipeline.steps
                context.final_composition = pipeline.final_composition
                context.confidence = 1.0
                context.reasoning = "locked by user"
                context.mode = mode
                return pipeline
            logger.warning(
                "Locked pipeline not found: pipeline_id=%s", locked_pipeline_id
            )

        # --- get active pipelines for domain, filtered by campaign ---
        all_pipelines = await pipeline_service.get_active_pipelines(domain_id, db)
        if not all_pipelines:
            logger.info("No active pipelines for domain_id=%s", domain_id)
            return None

        # Filter:
        # - campaign mode  → campaign-specific pipelines for this campaign_id
        #                    + general pipelines (campaign_id IS NULL) as fallback candidates
        # - general mode   → only general pipelines (campaign_id IS NULL)
        if campaign_id:
            campaign_uuid = str(uuid.UUID(campaign_id)) if campaign_id else None
            candidates = [
                p for p in all_pipelines
                if p.campaign_id is None or str(p.campaign_id) == campaign_uuid
            ]
        else:
            candidates = [p for p in all_pipelines if p.campaign_id is None]

        if not candidates:
            logger.info(
                "No pipeline candidates after mode filter: domain_id=%s campaign_id=%s mode=%s",
                domain_id, campaign_id, mode,
            )
            return None

        # --- LLM routing ---
        history_text = "\n".join(
            f"{m.role}: {m.content}"
            for m in (context.history or [])[-3:]
        )
        prompt_override = await domain_service.get_prompt(domain_id, "pipeline_router", db)
        template = prompt_override if prompt_override and prompt_override.strip() else PROMPT_TEMPLATE
        pipelines_list = "\n".join(
            f'{i}. id="{p.pipeline_id}", name="{p.name}", description="{p.description or ""}"'
            for i, p in enumerate(candidates, start=1)
        )
        full_prompt = template.format(
            domain_id=domain_id,
            pipelines_list=pipelines_list,
            query=query,
            chat_history=history_text,
        )

        provider = llm_provider or settings_service.get_active_provider()
        if provider is None:
            logger.warning("No active generation model; pipeline router cannot function.")
            return None

        raw_output = await provider.generate([
            {"role": "system", "content": full_prompt},
            {"role": "user", "content": query},
        ])
        available = {p.pipeline_id: p for p in candidates}
        try:
            payload = json.loads(raw_output)
            pipeline_id = payload.get("pipeline_id")
            confidence = float(payload.get("confidence") or 0.0)
            reasoning = str(payload.get("reasoning") or "")
        except Exception:
            await self._log_failure(query, raw_output, list(available), db)
            return None

        if not pipeline_id or pipeline_id not in available or confidence < 0.5:
            if pipeline_id and pipeline_id not in available:
                await self._log_failure(query, raw_output, list(available), db)
            return None

        selected = available[pipeline_id]
        context.pipeline_id = selected.pipeline_id
        context.pipeline_version = selected.version
        context.steps = selected.steps
        context.final_composition = selected.final_composition
        context.confidence = confidence
        context.reasoning = reasoning
        context.mode = mode
        logger.info(
            "Pipeline selected: pipeline_id=%s confidence=%.2f mode=%s domain_id=%s campaign_id=%s",
            pipeline_id, confidence, mode, domain_id, campaign_id,
        )
        return selected

    # ------------------------------------------------------------------
    # Legacy method — kept for backwards compat / tests
    # ------------------------------------------------------------------

    async def decide(
        self,
        query: str,
        chat: Chat,
        db: AsyncSession,
        llm_provider: GenerationProvider | None = None,
    ) -> tuple[PipelineRead | None, str | None, float | None, str | None]:
        """Legacy: принимает Chat ORM-объект. Используй select() для новых вызовов."""
        if chat.locked_pipeline_id:
            pipeline = await pipeline_service.get_pipeline(chat.locked_pipeline_id, db)
            if pipeline is not None:
                return pipeline, "lock", 1.0, "locked by user"
            logger.warning("Locked pipeline not found: chat_id=%s pipeline_id=%s", chat.id, chat.locked_pipeline_id)

        domain_id = chat.domain_id or "default"
        pipelines = await pipeline_service.get_active_pipelines(domain_id, db)
        if not pipelines:
            return None, None, None, None

        prompt = await domain_service.get_prompt(domain_id, "pipeline_router", db)
        template = prompt if prompt and prompt.strip() else PROMPT_TEMPLATE
        pipelines_list = "\n".join(
            f'{index}. id="{p.pipeline_id}", name="{p.name}", description="{p.description or ""}"'
            for index, p in enumerate(pipelines, start=1)
        )
        history = await self._chat_history(chat, db)
        full_prompt = template.format(
            domain_id=domain_id,
            pipelines_list=pipelines_list,
            query=query,
            chat_history=history,
        )
        provider = llm_provider or settings_service.get_active_provider()
        if provider is None:
            logger.warning("No active generation model configured; pipeline router cannot function.")
            return None, None, None, None
        raw_output = await provider.generate([{"role": "system", "content": full_prompt}, {"role": "user", "content": query}])
        available = {p.pipeline_id: p for p in pipelines}
        try:
            payload = json.loads(raw_output)
            pipeline_id = payload.get("pipeline_id")
            confidence = float(payload.get("confidence") or 0.0)
            reasoning = str(payload.get("reasoning") or "")
        except Exception:
            await self._log_failure(query, raw_output, list(available), db)
            return None, None, None, None

        if not pipeline_id or pipeline_id not in available or confidence < 0.5:
            if pipeline_id and pipeline_id not in available:
                await self._log_failure(query, raw_output, list(available), db)
            return None, None, None, None
        return available[pipeline_id], "auto", confidence, reasoning

    async def _chat_history(self, chat: Chat, db: AsyncSession) -> str:
        result = await db.execute(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at.desc()).limit(3)
        )
        messages = list(reversed(result.scalars().all()))
        return "\n".join(f"{m.role}: {m.content}" for m in messages)

    async def _log_failure(
        self,
        query: str,
        response: str,
        available_pipelines: list[str],
        db: AsyncSession,
    ) -> None:
        db.add(
            AuditLog(
                action="pipeline_router_failure",
                entity_type="pipeline",
                entity_id=None,
                details={"query": query, "response": response, "available_pipelines": available_pipelines},
            )
        )
        await db.commit()


pipeline_router = PipelineRouter()
