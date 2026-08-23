"""effective_context.py — Stage 6: общий runtime helper для prompt assembly.

Содержит функции, которые используются и в chat runtime, и в debug-эндпойнте:
  - `_compose_full_system_prompt_text` — собрать system_prompt + Campaign State
    в единую строку (без RAG-context);
  - `build_effective_context` — собрать полный effective-context для UI.

Не зависит от FastAPI. Используется из `app.api.chat`, `app.api.pipeline_resume`,
`app.services.pipeline_executor`, `app.api.settings.campaigns`.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.campaign_state_compiler import (
    compile_campaign_state,
    default_token_counter,
    get_campaign_state_token_budget,
)
from app.services.campaign_state_value_service import campaign_state_value_service
from app.services.domain_service import domain_service
from shared_contracts.models import (
    CampaignStateCompiledBlock,
    EffectiveContextBlock,
    EffectiveContextRead,
)

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
            "effective_context._resolve_campaign_state_block_safe: get_active_state failed: %s",
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
            "effective_context._resolve_campaign_state_block_safe: compile failed: %s",
            exc,
        )
        return "", None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compose_full_system_prompt(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
) -> str:
    """Собрать `system_prompt + Campaign State block` через filter(None).

    Не подставляет RAG-context — это делает вызывающий код после retrieval.
    """
    system_prompt = await _resolve_system_prompt_text(campaign_id, domain_id, db)
    state_text, _ = await _resolve_campaign_state_block_safe(campaign_id, db)
    parts = [p for p in (system_prompt, state_text) if p]
    return "\n\n".join(parts)


async def compose_full_system_prompt_with_state(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
) -> tuple[str, CampaignStateCompiledBlock | None]:
    """Вернуть (system_prompt_text, state_block).

    Возвращает уже склеенный `system_prompt + state` и сам block для debug.
    """
    system_prompt = await _resolve_system_prompt_text(campaign_id, domain_id, db)
    state_text, block = await _resolve_campaign_state_block_safe(campaign_id, db)
    parts = [p for p in (system_prompt, state_text) if p]
    return "\n\n".join(parts), block


async def compose_state_block_only(
    campaign_id: str | None,
    db: AsyncSession,
) -> str:
    """Вернуть только текст Campaign State block (без system_prompt и rag_context).

    Используется в `_run_final_composition` для добавления блока после
    pipeline-resolved prompt без вмешательства в шаблоны с {query}/{STEP_ID.*}.
    """
    state_text, _ = await _resolve_campaign_state_block_safe(campaign_id, db)
    return state_text


# ---------------------------------------------------------------------------
# Effective context (debug endpoint)
# ---------------------------------------------------------------------------


async def build_effective_context(
    campaign_id: str | None,
    chat_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    *,
    include_rag: bool = False,
    rag_hits: list[Any] | None = None,
    user_message: str = "",
) -> EffectiveContextRead:
    """Собрать effective-context для дебага prompt assembly.

    Не выполняет retrieval. Если `include_rag=True` — берёт уже посчитанные
    `rag_hits` (иначе пропускает блок).
    """
    system_prompt = await _resolve_system_prompt_text(campaign_id, domain_id, db)
    _, state_block = await _resolve_campaign_state_block_safe(campaign_id, db)
    budget = await get_campaign_state_token_budget(db)

    blocks: list[EffectiveContextBlock] = []
    total_tokens = 0

    if system_prompt:
        sp_tokens = default_token_counter(system_prompt)
        blocks.append(EffectiveContextBlock(
            name="system_prompt",
            text=system_prompt,
            estimated_tokens=sp_tokens,
        ))
        total_tokens += sp_tokens

    if state_block is not None and state_block.text:
        blocks.append(EffectiveContextBlock(
            name="campaign_state",
            text=state_block.text,
            estimated_tokens=state_block.used_tokens,
        ))
        total_tokens += state_block.used_tokens

    if include_rag and rag_hits:
        from app.services.retrieval import format_context
        rag_text = format_context(rag_hits)
        rag_tokens = default_token_counter(rag_text) if rag_text else 0
        if rag_text:
            blocks.append(EffectiveContextBlock(
                name="rag_context",
                text=rag_text,
                estimated_tokens=rag_tokens,
            ))
            total_tokens += rag_tokens

    if user_message:
        um_tokens = default_token_counter(user_message)
        blocks.append(EffectiveContextBlock(
            name="user_message",
            text=user_message,
            estimated_tokens=um_tokens,
        ))
        total_tokens += um_tokens

    return EffectiveContextRead(
        campaign_id=campaign_id,
        chat_id=chat_id,
        domain_id=domain_id,
        blocks=blocks,
        total_tokens=total_tokens,
        budget=budget,
        truncated_fields=list(state_block.truncated_fields) if state_block else [],
        state_version=state_block.state_version if state_block else None,
    )


__all__ = [
    "build_effective_context",
    "compose_full_system_prompt",
    "compose_full_system_prompt_with_state",
    "compose_state_block_only",
]
