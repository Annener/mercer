from __future__ import annotations
import json
import logging
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import AppConfig
from app.db.models import Vault
from app.pipelines.registry import PipelineRegistry
from app.services.domain_service import domain_service
from app.services.settings_service import settings_service
from shared_contracts.models import PipelineInvocation, PlannerDecision

logger = logging.getLogger(__name__)

AMBIGUOUS_SUBJECTS = {
    "класс": "subject",
    "class": "subject",
    "раса": "subject",
    "race": "subject",
    "заклинание": "subject",
    "spell": "subject",
}

class Planner:
    def __init__(self, config: AppConfig | None = None, pipeline_registry: PipelineRegistry | None = None) -> None:
        self.config = config
        self.pipeline_registry = pipeline_registry

    async def decide(
        self,
        db: AsyncSession,
        query: str,
        vault_id: str | None,
        domain_id: str | None,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[PlannerDecision, list[str]]:
        _ = history
        retrieval_strategy = "none"
        retrieval_enabled = bool(await settings_service.get("retrieval.enabled", db))
        if retrieval_enabled:
            if vault_id:
                retrieval_strategy = await self._strategy_for_vault(db, vault_id)
            elif domain_id:
                retrieval_strategy = await self._strategy_for_domain(db, domain_id)

        missing_fields = await self._missing_fields_for_domain(query, domain_id or "default", db)
        pipeline_invocations = await self._pipeline_invocations(domain_id)
        max_clarification_turns = int(await settings_service.get("chat.max_clarification_turns", db))
        decision = PlannerDecision(
            retrieval_strategy=retrieval_strategy,
            clarification_needed=bool(missing_fields) and max_clarification_turns > 0,
            pipeline_invocations=pipeline_invocations,
            reasoning=(
                f"strategy={retrieval_strategy}; "
                f"missing_fields={','.join(missing_fields) if missing_fields else 'none'}"
            ),
        )
        logger.info(
            "Planner decision: vault_id=%s domain_id=%s strategy=%s clarification_needed=%s missing_fields=%s",
            vault_id,
            domain_id,
            decision.retrieval_strategy,
            decision.clarification_needed,
            missing_fields,
        )
        return decision, missing_fields

    async def _strategy_for_vault(self, db: AsyncSession, vault_id: str) -> str:
        result = await db.execute(
            select(Vault).where(Vault.vault_id == vault_id, Vault.enabled == True)
        )
        vault = result.scalar_one_or_none()
        if not vault or vault.chunk_count <= 0:
            return "none"
        return "semantic"

    async def _strategy_for_domain(self, db: AsyncSession, domain_id: str) -> str:
        result = await db.execute(
            select(func.count()).select_from(Vault).where(
                Vault.domain_id == domain_id,
                Vault.enabled == True,
                Vault.chunk_count > 0,
            )
        )
        count = result.scalar()
        return "semantic" if count and count > 0 else "none"

    async def _pipeline_invocations(self, domain_id: str | None) -> list[PipelineInvocation]:
        if self.pipeline_registry is None or self.config is None or not self.config.pipelines.enabled:
            return []
        runners = await self.pipeline_registry.list_by_domain(domain_id)
        return [
            PipelineInvocation(pipeline_id=runner.metadata.pipeline_id, domain=runner.metadata.domain, priority=index)
            for index, runner in enumerate(runners)
        ]

    @staticmethod
    def _missing_fields(query: str) -> list[str]:
        words = query.lower().split()
        if len(words) < 3:
            return ["topic"]
        missing: list[str] = []
        for trigger, field in AMBIGUOUS_SUBJECTS.items():
            if trigger in query.lower() and field not in missing:
                missing.append(field)
        return missing

    async def _missing_fields_for_domain(self, query: str, domain_id: str, db: AsyncSession) -> list[str]:
        fields = await domain_service.get_clarification_fields(domain_id, db)
        allowed = {field["field_name"] for field in fields}
        if not allowed:
            return []
        return [field for field in self._missing_fields(query) if field in allowed]
