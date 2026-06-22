from __future__ import annotations
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

# Системный промпт роутера кларификации.
# {fields_block} — описание доступных полей из настроек домена.
_ROUTER_SYSTEM = """\
Ты — роутер запросов RAG-ассистента. Твоя задача: определить, \
каких данных не хватает чтобы дать точный ответ на запрос пользователя.

Доступные поля для уточнения:
{fields_block}

Правила:
- Уточняй ТОЛЬКО если без этой информации поиск по базе знаний вернёт нерелевантные результаты.
- НЕ уточняй если запрос уже достаточно конкретный.
- НЕ уточняй поля которые уже есть в истории диалога.
- Верни JSON строго в формате: {{"missing_fields": ["field_name", ...]}}
- Верни пустой список если уточнения не нужны: {{"missing_fields": []}}
"""


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
        retrieval_strategy = "none"
        retrieval_enabled = bool(await settings_service.get("retrieval.enabled", db))
        if retrieval_enabled:
            if vault_id:
                retrieval_strategy = await self._strategy_for_vault(db, vault_id)
            elif domain_id:
                retrieval_strategy = await self._strategy_for_domain(db, domain_id)

        missing_fields = await self._missing_fields_for_domain(
            query, domain_id or "default", db, history=history or []
        )
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

    async def _missing_fields_for_domain(
        self,
        query: str,
        domain_id: str,
        db: AsyncSession,
        history: list[dict[str, str]],
    ) -> list[str]:
        fields = await domain_service.get_clarification_fields(domain_id, db)
        if not fields:
            return []

        allowed = {f["field_name"] for f in fields}
        provider = settings_service.get_active_provider()
        if provider is None:
            logger.warning("Planner: no active generation provider, skipping LLM clarification routing")
            return []

        # Строим описание полей из настроек домена (label + hint)
        fields_block = "\n".join(
            f'- {f["field_name"]}: {f["label"]}' + (f' — {f["hint"]}' if f.get("hint") else "")
            for f in fields
        )

        system_content = _ROUTER_SYSTEM.format(fields_block=fields_block)

        # Берём последние 6 сообщений истории чтобы роутер видел уже собранный контекст
        recent_history = history[-6:] if history else []

        messages = (
            [{"role": "system", "content": system_content}]
            + recent_history
            + [{"role": "user", "content": query}]
        )

        try:
            result = await provider.generate_json(
                messages,
                fallback={"missing_fields": []},
            )
            raw_fields = result.get("missing_fields", [])
            # Фильтруем: только поля разрешённые для данного домена
            missing = [f for f in raw_fields if isinstance(f, str) and f in allowed]
            logger.info("Planner LLM router: query=%r missing_fields=%s", query[:80], missing)
            return missing
        except Exception as exc:
            logger.warning("Planner LLM router failed, skipping clarification: %s", exc)
            return []
