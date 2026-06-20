from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
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

    Публичный API:
        select(context, locked_pipeline_id) -> PipelineRead | None
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Основной метод
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
        db = db or self.db
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
                pipeline_is_campaign = pipeline.campaign_id is not None
                if pipeline_is_campaign and mode == "general":
                    logger.warning(
                        "Locked pipeline is campaign-specific but chat is in general mode; ignoring lock. "
                        "pipeline_id=%s campaign_id=%s",
                        locked_pipeline_id, pipeline.campaign_id,
                    )
                elif not pipeline_is_campaign and mode == "campaign":
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
