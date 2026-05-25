from __future__ import annotations
import json
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import AppConfig
from app.db.models import VaultBinding
from app.pipelines.registry import PipelineRegistry
from app.providers.generation import get_generation_provider, GenerationProviderUnavailableError
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
    def __init__(self, config: AppConfig, pipeline_registry: PipelineRegistry | None = None) -> None:
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
        if self.config.retrieval.enabled:
            if vault_id:
                retrieval_strategy = await self._strategy_for_vault(db, vault_id)
            elif domain_id:
                # Чат привязан к домену (без конкретного vault) — используем semantic retrieval
                # если в домене есть хотя бы один vault с проиндексированными чанками
                retrieval_strategy = await self._strategy_for_domain(db, domain_id)

        missing_fields = self._missing_fields(query)
        pipeline_invocations = await self._pipeline_invocations(domain_id)
        decision = PlannerDecision(
            retrieval_strategy=retrieval_strategy,
            clarification_needed=bool(missing_fields) and self.config.chat.max_clarification_turns > 0,
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
        result = await db.execute(select(VaultBinding).where(VaultBinding.vault_id == vault_id))
        binding = result.scalar_one_or_none()
        if binding is not None and binding.chunk_count <= 0:
            return "none"
        return "semantic"

    async def _strategy_for_domain(self, db: AsyncSession, domain_id: str) -> str:
        """Возвращает 'semantic' если в домене есть хотя бы один vault с данными."""
        domain_vault_ids = [
            v.vault_id
            for v in self.config.vaults.values()
            if v.domain_id == domain_id and v.enabled
        ]
        if not domain_vault_ids:
            return "none"
        result = await db.execute(
            select(VaultBinding).where(VaultBinding.vault_id.in_(domain_vault_ids))
        )
        bindings = result.scalars().all()
        # Хотя бы один vault проиндексирован (chunk_count > 0)
        for binding in bindings:
            if binding.chunk_count > 0:
                return "semantic"
        # Нет ни одного binding или все пустые — всё равно пробуем semantic,
        # т.к. binding может быть не создан, но данные могут быть в LanceDB
        if not bindings:
            return "semantic"
        return "none"

    async def _pipeline_invocations(self, domain_id: str | None) -> list[PipelineInvocation]:
        if self.pipeline_registry is None or not self.config.pipelines.enabled:
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


class LLMRAGPlanner:
    """
    LLM-driven декомпозитор запросов. Разбивает сложный промпт на список оптимизированных подзапросов
    для параллельного retrieval. Возвращает fallback на исходный запрос при ошибке LLM.
    """
    PROMPT_TEMPLATE = """Ты агент-координатор поиска в RAG-системе для D&D.
Твоя задача: проанализировать запрос пользователя и разбить его на 1-3 конкретных подзапроса для семантического поиска по базе знаний.
Возвращай ТОЛЬКО валидный JSON в формате: {"queries": ["запрос1", "запрос2"]}
Правила:
1. Если запрос требует сюжета/боя/лора, выдели отдельные аспекты (локация, монстры, правила, предыстория).
2. Не меняй смысл запроса, только оптимизируй для векторного поиска.
3. Если запрос уже конкретен, верни его один раз.
Пример: {"queries": ["Лес ветров описание локации Альварон", "Монстры D&D 5e для леса", "Расчет сложности encounter уровень 5"]}"""

    def __init__(self, config: AppConfig):
        self.config = config

    async def decompose(self, query: str, domain_id: str, history: list[str] | None = None) -> list[str]:
        try:
            provider = get_generation_provider(self.config)
            context_hint = f"Последние сообщения чата: {history[-2:]}" if history else ""
            full_prompt = f"{self.PROMPT_TEMPLATE}\n\nКонтекст чата:\n{context_hint}\n\nЗапрос пользователя:\n{query}"
            
            result = await provider.generate_json(
                messages=[{"role": "system", "content": self.PROMPT_TEMPLATE}, {"role": "user", "content": full_prompt}],
                fallback={"queries": [query]}
            )
            queries = result.get("queries", [])
            if isinstance(queries, list) and queries:
                logger.info(f"LLM decomposed query into {len(queries)} sub-queries")
                return [q.strip() for q in queries if q.strip()]
        except (GenerationProviderUnavailableError, Exception) as e:
            logger.warning(f"LLRAGPlanner decomposition failed: {e}")
        return [query]
