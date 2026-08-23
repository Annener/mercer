"""campaign_state_initial_store.py — Redis-backed proposal store for Initial State.

Хранит неподтверждённый LLM-proposal Initial Campaign State в Redis.

Ключ:    campaign_initial:{campaign_id}
TTL:     3 часа (INITIAL_TTL_SECONDS), обновляется при повторном preview.
Значение: сериализованный в JSON CampaignStateInitialProposalReadV2.

Backward-compat: при чтении принимает и старый V1 payload (suggested_fields
примет дефолт []). Это гарантирует, что proposals, сохранённые до обновления
до Stage 3.v2 (с V1 форматом), продолжают работать — apply правильно обработает
отсутствующий блок suggested_fields.

Без Lua-атомарности: гонка preview ↔ apply маловероятна, а гонка apply ↔ apply
закрыта SELECT FOR UPDATE в CampaignStateValueService.apply_initial.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from shared_contracts.models import (
    CampaignStateInitialProposalRead,
    CampaignStateInitialProposalReadV2,
)

if TYPE_CHECKING:
    import redis.asyncio as aioredis


logger = logging.getLogger(__name__)

# Консистентно с Update Mode (SESSION_TTL_SECONDS = 10800).
INITIAL_TTL_SECONDS: int = 3 * 60 * 60  # 3 hours


def _key(campaign_id: str) -> str:
    return f"campaign_initial:{campaign_id}"


class CampaignStateInitialStore:
    """Тонкая обёртка над Redis для хранения Initial State proposal."""

    async def create(
        self,
        redis: Any,
        payload: CampaignStateInitialProposalReadV2 | CampaignStateInitialProposalRead,
    ) -> None:
        """Сохранить proposal в Redis с TTL.

        Принимает payload V2 (наследует от V1 + добавляет suggested_fields).
        Backward-compat: тест-helpers передают V1 Read напрямую — благодаря
        общему интерфейсу (.model_dump_json, .campaign_id, .proposal_id)
        оба типа обрабатываются одинаково. В Redis всегда попадает актуальный
        JSON (если передан V1 — suggested_fields не сохраняются; фронт их
        тогда и не получит).
        """
        key = _key(payload.campaign_id)
        data = payload.model_dump_json()
        await redis.set(key, data, ex=INITIAL_TTL_SECONDS)
        logger.info(
            "campaign_state_initial_store.create: campaign=%s proposal_id=%s ttl=%ds",
            payload.campaign_id, payload.proposal_id, INITIAL_TTL_SECONDS,
        )

    async def get(
        self,
        redis: Any,
        campaign_id: str,
    ) -> CampaignStateInitialProposalReadV2 | None:
        """Загрузить proposal или None, если ключа нет / TTL истёк.

        Возвращает V2 форму — обратно совместимую: V1 JSON (без suggested_fields)
        десериализуется с пустым suggested_fields=[].
        """
        key = _key(campaign_id)
        raw = await redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return CampaignStateInitialProposalReadV2.model_validate_json(raw)

    async def delete(
        self,
        redis: Any,
        campaign_id: str,
    ) -> None:
        """Удалить proposal (при успешном apply или ручной отмене)."""
        await redis.delete(_key(campaign_id))
        logger.info(
            "campaign_state_initial_store.delete: campaign=%s", campaign_id,
        )


# Module-level singleton — same pattern as campaign_state_value_service.
campaign_state_initial_store = CampaignStateInitialStore()
