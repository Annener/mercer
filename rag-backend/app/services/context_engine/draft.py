"""context_engine.draft — CampaignStateDrafter.

Phase 3: после того как ``DriftDetector`` записал hints в
``chat.metadata.scene_state.drift``, ``CampaignStateDrafter`` планирует
*минимальный* ``state_patch`` (через активную большую generation-модель)
и сохраняет его как draft в Redis.

Ключевые инварианты:

* Draft содержит ТОЛЬКО ``state_patch`` операции — schema changes
  (``create_field`` / ``update_field``) и ``file_changes`` запрещены
  (см. system prompt ниже).
* ``draft:campaign:{campaign_id}:chat:{chat_id}`` живёт 3 часа
  (``_DRAFT_TTL_SECONDS``). По истечении TTL draft исчезает.
* Если новый drift hash совпадает с уже сохранённым draft — LLM не
  вызывается, возвращается existing draft (без пересоздания).
* Все ошибки (LLM недоступен, невалидный JSON, пустой patch, пропавший
  chat) логируются и тихо возвращают ``None`` — drafter не должен
  ронять drift-loop.

Применение draft (Accept / Reject / Check-files) делается в Фазе 4
через ``/api/chats/{chat_id}/context-draft/*``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.campaign_state_compiler import compile_campaign_state
from app.services.campaign_state_value_service import campaign_state_value_service

from .scene_memory import read_scene_state

logger = logging.getLogger(__name__)


# Redis key + TTL для draft. Хардкод (см. plan-context-engine.md §"Открытые
# вопросы" — настройка через platform_settings отложена).
_DRAFT_REDIS_KEY = "draft:campaign:{campaign_id}:chat:{chat_id}"
_DRAFT_TTL_SECONDS = 3 * 60 * 60  # 3 часа

# Бюджет токенов на компиляцию Campaign State для промпта drafter-а.
# Меньше, чем в основном chat-промпте — drafter видит только essentials.
_DRAFT_STATE_BUDGET_TOKENS = 2000

# Сколько последних сообщений чата подкидываем в промпт drafter-а.
_DRAFT_MESSAGES_LOOKBACK = 10

# Разрешённые типы state_patch операций. Всё остальное фильтруется.
_ALLOWED_OP_TYPES: frozenset[str] = frozenset(
    {
        "replace_single",
        "clear_single",
        "add_list_item",
        "update_list_item",
        "resolve_list_item",
        "remove_list_item",
    }
)


_SYSTEM_PROMPT = (
    "You are a Campaign State drafter. Given recent chat messages, current "
    "campaign state, and detected drift hints, propose MINIMAL state_patch "
    "operations to update the campaign state.\n\n"
    "Allowed operations (state_patch only, NO schema changes, NO file changes):\n"
    "- replace_single {field_key, text, reason, source_refs}\n"
    "- clear_single {field_key, reason}\n"
    "- add_list_item {field_key, text, reason, source_refs}\n"
    "- update_list_item {field_key, item_key, text, reason}\n"
    "- resolve_list_item {field_key, item_key, reason}\n"
    "- remove_list_item {field_key, item_key, reason}\n\n"
    "Output JSON: "
    '{"state_patch": [{"type": "...", "field_key": "...", ...}], '
    '"summary": "short user-facing description"}\n\n'
    "Rules:\n"
    "- Be conservative — only propose what is clearly supported by drift hints.\n"
    "- NEVER propose schema changes (create_field/update_field) — too risky "
    "without user review.\n"
    "- NEVER propose file_changes — handled separately.\n"
    "- Every operation MUST have a non-empty 'reason'.\n"
    "- If no clear updates are needed, return "
    '{"state_patch": [], "summary": "No changes needed"}.\n'
)


# Тип для generation_provider_factory. Совместимо с
# settings_service.get_active_provider() → GenerationProvider | None.
GenerationProviderFactory = Callable[[], Any]


class CampaignStateDrafter:
    """Планирует draft campaign state на основе drift + messages."""

    def __init__(
        self,
        *,
        db_factory: async_sessionmaker[AsyncSession],
        redis_client: aioredis.Redis,
        generation_provider_factory: GenerationProviderFactory,
    ) -> None:
        self.db_factory = db_factory
        self.redis = redis_client
        self.generation_provider_factory = generation_provider_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def plan_draft(self, chat_id: str) -> dict[str, Any] | None:
        """Спланировать draft для чата.

        Возвращает ``dict`` с draft (включая ``state_patch``, ``summary``,
        ``drift_hash``, ``drift_hints``, ``created_at``, ``expires_at``)
        или ``None`` если draft планировать нечего / не получилось:

          * нет drift hints;
          * активная модель недоступна;
          * LLM вернул пустой / невалидный patch;
          * ошибки БД или Redis.

        TTL draft — ``_DRAFT_TTL_SECONDS`` (3 часа).
        """
        try:
            async with self.db_factory() as db:
                return await self._plan_draft_inner(chat_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "draft.plan_draft: outer failure chat_id=%s: %s", chat_id, exc
            )
            return None

    # ------------------------------------------------------------------
    # Inner logic
    # ------------------------------------------------------------------

    async def _plan_draft_inner(
        self, chat_id: str, db: AsyncSession
    ) -> dict[str, Any] | None:
        # 1. Chat + campaign_id
        from app.db.models import Chat

        try:
            chat_uuid = _uuid.UUID(chat_id)
        except (ValueError, TypeError):
            return None

        try:
            chat = await db.get(Chat, chat_uuid)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "draft.plan_draft: chat load failed chat_id=%s: %s", chat_id, exc
            )
            return None
        if chat is None or not chat.campaign_id:
            logger.debug(
                "draft.plan_draft: chat missing or no campaign, skip chat_id=%s",
                chat_id,
            )
            return None

        campaign_id = str(chat.campaign_id)

        # 2. Drift hints
        scene_state = await read_scene_state(chat_id, db)
        drift_block = scene_state.get("drift") if isinstance(scene_state, dict) else None
        hints_raw = drift_block.get("_hints") if isinstance(drift_block, dict) else None
        hints: list[dict[str, Any]] = [
            h for h in (hints_raw or []) if isinstance(h, dict)
        ]
        if not hints:
            logger.debug(
                "draft.plan_draft: no drift hints, skip chat_id=%s", chat_id
            )
            return None

        # 3. Hash compare с existing draft
        new_drift_hash = self._hash_hints(hints)
        redis_key = _DRAFT_REDIS_KEY.format(
            campaign_id=campaign_id, chat_id=chat_id
        )
        existing = await self._read_existing(redis_key)
        if existing and existing.get("drift_hash") == new_drift_hash:
            logger.debug(
                "draft.plan_draft: drift unchanged, skip chat_id=%s", chat_id
            )
            return existing

        # 4. Messages + state text
        messages = await self._read_last_messages(chat_id, db)
        state_text = await self._compile_state_text(chat.campaign_id, db)

        # 5. Generation provider
        provider = self.generation_provider_factory()
        if provider is None:
            logger.warning(
                "draft.plan_draft: no active generation provider, skip chat_id=%s",
                chat_id,
            )
            return None

        # 6. LLM call
        user_prompt = (
            f"## Campaign State:\n{state_text}\n\n"
            f"## Drift Hints:\n{json.dumps(hints, ensure_ascii=False, indent=2)}\n\n"
            f"## Recent Messages:\n"
            + "\n".join(f"[{m['role']}] {m['content']}" for m in messages)
        )

        try:
            parsed = await provider.generate_json(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "draft.plan_draft: generation failed chat_id=%s: %s", chat_id, exc
            )
            return None

        # 7. Парсинг и фильтрация
        if not isinstance(parsed, dict):
            logger.warning(
                "draft.plan_draft: provider returned non-dict chat_id=%s type=%s",
                chat_id,
                type(parsed).__name__,
            )
            return None

        state_patch_raw = parsed.get("state_patch")
        if not isinstance(state_patch_raw, list):
            logger.warning(
                "draft.plan_draft: state_patch is not a list chat_id=%s", chat_id
            )
            return None

        state_patch = self._filter_allowed_ops(state_patch_raw)
        if not state_patch:
            logger.info(
                "draft.plan_draft: empty/filtered patch chat_id=%s", chat_id
            )
            return None

        summary_raw = parsed.get("summary", "")
        summary = summary_raw if isinstance(summary_raw, str) else ""

        # 8. Сборка draft
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=_DRAFT_TTL_SECONDS)
        draft: dict[str, Any] = {
            "chat_id": chat_id,
            "campaign_id": campaign_id,
            "state_patch": state_patch,
            "summary": summary,
            "drift_hash": new_drift_hash,
            "drift_hints": hints,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        # 9. Сохранение в Redis
        try:
            await self.redis.setex(
                redis_key,
                _DRAFT_TTL_SECONDS,
                json.dumps(draft, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "draft.plan_draft: redis setex failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            return None

        logger.info(
            "draft.plan_draft: saved %d ops for chat_id=%s campaign_id=%s",
            len(state_patch),
            chat_id,
            campaign_id,
        )
        return draft

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_hints(hints: list[dict[str, Any]]) -> str:
        canonical = json.dumps(hints, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    async def _read_existing(self, redis_key: str) -> dict[str, Any] | None:
        try:
            raw = await self.redis.get(redis_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("draft._read_existing: redis GET failed: %s", exc)
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "draft._read_existing: json decode failed for key=%s: %s",
                redis_key,
                exc,
            )
            return None
        if not isinstance(data, dict):
            return None
        return data

    @staticmethod
    async def _read_last_messages(
        chat_id: str, db: AsyncSession
    ) -> list[dict[str, str]]:
        from sqlalchemy import select

        from app.db.models import Message

        try:
            chat_uuid = _uuid.UUID(chat_id)
        except (ValueError, TypeError):
            return []
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_uuid)
            .order_by(Message.created_at.desc())
            .limit(_DRAFT_MESSAGES_LOOKBACK)
        )
        try:
            result = await db.execute(stmt)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "draft._read_last_messages: query failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            return []
        msgs = list(result.scalars().all())
        return [
            {"role": m.role, "content": m.content} for m in reversed(msgs)
        ]

    @staticmethod
    async def _compile_state_text(
        campaign_id: Any, db: AsyncSession
    ) -> str:
        try:
            version = await campaign_state_value_service.get_active_state(
                db, campaign_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "draft._compile_state_text: get_active_state failed: %s", exc
            )
            return "(failed to load campaign state)"

        if version is None:
            return "(empty campaign state)"

        try:
            fields = await campaign_state_value_service.list_enabled_fields_ordered(
                db, campaign_id
            )
            block = compile_campaign_state(
                version, fields, budget_tokens=_DRAFT_STATE_BUDGET_TOKENS
            )
            return block.text or "(empty campaign state)"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "draft._compile_state_text: compile_campaign_state failed: %s",
                exc,
            )
            return "(failed to compile campaign state)"

    @staticmethod
    def _filter_allowed_ops(
        raw_ops: list[Any],
    ) -> list[dict[str, Any]]:
        """Оставить только ops с разрешённым ``type``.

        Логирование отброшенных — чтобы видеть, если LLM генерирует
        мусор. Возвращает список dict-ов (мусор отфильтрован).
        """
        cleaned: list[dict[str, Any]] = []
        rejected = 0
        for op in raw_ops:
            if not isinstance(op, dict):
                rejected += 1
                continue
            op_type = op.get("type")
            if op_type not in _ALLOWED_OP_TYPES:
                rejected += 1
                continue
            cleaned.append(op)
        if rejected:
            logger.warning(
                "draft._filter_allowed_ops: rejected %d ops (unknown type or shape)",
                rejected,
            )
        return cleaned


__all__ = [
    "CampaignStateDrafter",
    "GenerationProviderFactory",
]
