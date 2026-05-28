from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Chat, Message
from app.providers.generation.base import GenerationProvider
from app.services.domain_service import domain_service
from app.services.pipeline_service import pipeline_service
from app.services.settings_service import settings_service
from shared_contracts.models import PipelineRead


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
    async def decide(
        self,
        query: str,
        chat: Chat,
        db: AsyncSession,
        llm_provider: GenerationProvider | None = None,
    ) -> tuple[PipelineRead | None, str | None, float | None, str | None]:
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
            f'{index}. id="{pipeline.pipeline_id}", name="{pipeline.name}", description="{pipeline.description or ""}"'
            for index, pipeline in enumerate(pipelines, start=1)
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
        available = {pipeline.pipeline_id: pipeline for pipeline in pipelines}
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
        return "\n".join(f"{message.role}: {message.content}" for message in messages)

    async def _log_failure(self, query: str, response: str, available_pipelines: list[str], db: AsyncSession) -> None:
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
