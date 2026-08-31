"""context_engine.assembly — единая точка сборки chat context.

Содержит функции, которые компонуют `system_prompt + Campaign State + Scene State`
в единый текст для отправки в LLM. Не подставляет RAG-context — это делает
вызывающий код после retrieval.

Не зависит от FastAPI. Используется из `app.api.chat`,
`app.api.pipeline_resume`, `app.services.pipeline_executor`.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.campaign_state_compiler import (
    compile_campaign_state,
    get_campaign_state_token_budget,
)
from app.services.campaign_state_value_service import campaign_state_value_service
from app.services.domain_service import domain_service
from shared_contracts.models import CampaignStateCompiledBlock

from .scene_memory import compose_scene_block

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_system_prompt_text(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
) -> str:
    if campaign_id:
        from app.db.models import Campaign
        try:
            campaign = await db.get(Campaign, uuid.UUID(campaign_id))
        except (ValueError, TypeError):
            campaign = None
        if campaign is not None and campaign.system_prompt:
            return campaign.system_prompt
    return await domain_service.get_prompt(domain_id or "default", "system", db)


async def _resolve_campaign_state_block_safe(
    campaign_id: str | None,
    db: AsyncSession,
) -> tuple[str, CampaignStateCompiledBlock | None]:
    """Скомпилировать active Campaign State.

    Возвращает `(text, block_or_none)`. Никогда не падает: ошибки логируются и
    возвращается пустой блок — runtime чата не должен зависеть от Campaign State.
    """
    if not campaign_id:
        return "", None
    try:
        version = await campaign_state_value_service.get_active_state(
            db, uuid.UUID(campaign_id)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "assembly._resolve_campaign_state_block_safe: get_active_state failed: %s",
            exc,
        )
        version = None

    if version is None:
        return "", CampaignStateCompiledBlock(
            budget_tokens=await get_campaign_state_token_budget(db),
            used_tokens=0,
        )

    try:
        budget = await get_campaign_state_token_budget(db)
        fields = await campaign_state_value_service.list_enabled_fields_ordered(
            db, uuid.UUID(campaign_id)
        )
        block = compile_campaign_state(version, fields, budget_tokens=budget)
        return block.text, block
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "assembly._resolve_campaign_state_block_safe: compile failed: %s",
            exc,
        )
        return "", None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_chat_context(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    scene_state: dict[str, Any] | None = None,
) -> str:
    """Собрать `system_prompt + Campaign State block + Scene State block` через filter(None).

    `scene_state` (если задан) рендерится отдельным блоком между campaign_state
    и финальным system_prompt — модель видит активный контекст сцены
    (location, active_npcs, current_act и т.п.) и помнит его между turn-ами.

    Не подставляет RAG-context — это делает вызывающий код после retrieval.
    """
    system_prompt = await _resolve_system_prompt_text(campaign_id, domain_id, db)
    state_text, _ = await _resolve_campaign_state_block_safe(campaign_id, db)
    scene_text = compose_scene_block(scene_state)
    parts = [p for p in (system_prompt, state_text, scene_text) if p]
    return "\n\n".join(parts)


async def build_chat_context_with_state(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    scene_state: dict[str, Any] | None = None,
) -> tuple[str, CampaignStateCompiledBlock | None]:
    """Вернуть (system_prompt_text, state_block).

    Возвращает уже склеенный `system_prompt + state + scene_state` и сам
    state_block для debug. `scene_state` рендерится после campaign_state.
    """
    system_prompt = await _resolve_system_prompt_text(campaign_id, domain_id, db)
    state_text, block = await _resolve_campaign_state_block_safe(campaign_id, db)
    scene_text = compose_scene_block(scene_state)
    parts = [p for p in (system_prompt, state_text, scene_text) if p]
    return "\n\n".join(parts), block


async def build_state_block_only(
    campaign_id: str | None,
    db: AsyncSession,
) -> str:
    """Вернуть только текст Campaign State block (без system_prompt и rag_context).

    Используется в `_run_final_composition` для добавления блока после
    pipeline-resolved prompt без вмешательства в шаблоны с {query}/{STEP_ID.*}.
    """
    state_text, _ = await _resolve_campaign_state_block_safe(campaign_id, db)
    return state_text