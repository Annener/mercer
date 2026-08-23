"""Stage 8.2: typed accessor for retrieval tool PlatformSettings.

The agent loop in `app.services.agent_loop` consumes these settings on every
chat turn. We read them once per turn and cache the values, falling back to
safe defaults if a key is missing or has an unexpected value type.

Public API:
- `RetrievalToolSettings` — dataclass with all five knobs.
- `load_retrieval_tool_settings(db)` — async loader.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import settings_service
from shared_contracts.models import RetrievalPolicy

logger = logging.getLogger(__name__)


# Keys are duplicated as constants so they can be referenced from tests
# and from UI / settings page without stringly-typed coupling.
KEY_TOOL_ENABLED = "retrieval.tool_enabled"
KEY_POLICY = "retrieval.policy"
KEY_MAX_ROUNDS_GROUNDED = "retrieval.max_rounds_chat"
KEY_MAX_ROUNDS_ASSISTIVE = "retrieval.max_rounds_assistive"
KEY_EVIDENCE_TOKEN_BUDGET = "retrieval.evidence_token_budget"


@dataclass(slots=True, frozen=True)
class RetrievalToolSettings:
    """Resolved retrieval-tool settings for one chat turn.

    All fields are safe defaults if the DB row is missing — the host must
    still be able to run a chat turn if a PlatformSetting row was deleted.
    """

    tool_enabled: bool
    policy: RetrievalPolicy
    max_rounds_grounded: int
    max_rounds_assistive: int
    evidence_token_budget: int

    @property
    def max_rounds(self) -> int:
        """Return the round cap for the active policy."""
        if self.policy == RetrievalPolicy.ASSISTIVE:
            return self.max_rounds_assistive
        return self.max_rounds_grounded


def _coerce_policy(raw: object) -> RetrievalPolicy:
    if isinstance(raw, RetrievalPolicy):
        return raw
    if isinstance(raw, str):
        try:
            return RetrievalPolicy(raw)
        except ValueError:
            logger.warning(
                "load_retrieval_tool_settings: unknown policy value %r, defaulting to grounded",
                raw,
            )
            return RetrievalPolicy.GROUNDED
    return RetrievalPolicy.GROUNDED


async def load_retrieval_tool_settings(db: AsyncSession) -> RetrievalToolSettings:
    """Read the five PlatformSetting rows, applying defaults on any failure.

    Never raises — the host must always be able to run a turn, even if the
    DB is temporarily unavailable. Individual fallbacks are logged.
    """
    try:
        tool_enabled = bool(await settings_service.get(KEY_TOOL_ENABLED, db))
    except Exception:  # noqa: BLE001
        logger.warning("load_retrieval_tool_settings: %s missing, defaulting to true", KEY_TOOL_ENABLED, exc_info=True)
        tool_enabled = True

    try:
        policy = _coerce_policy(await settings_service.get(KEY_POLICY, db))
    except Exception:  # noqa: BLE001
        logger.warning("load_retrieval_tool_settings: %s missing, defaulting to grounded", KEY_POLICY, exc_info=True)
        policy = RetrievalPolicy.GROUNDED

    try:
        max_rounds_grounded = int(await settings_service.get(KEY_MAX_ROUNDS_GROUNDED, db))
    except Exception:  # noqa: BLE001
        logger.warning("load_retrieval_tool_settings: %s missing, defaulting to 2", KEY_MAX_ROUNDS_GROUNDED, exc_info=True)
        max_rounds_grounded = 2

    try:
        max_rounds_assistive = int(await settings_service.get(KEY_MAX_ROUNDS_ASSISTIVE, db))
    except Exception:  # noqa: BLE001
        logger.warning("load_retrieval_tool_settings: %s missing, defaulting to 1", KEY_MAX_ROUNDS_ASSISTIVE, exc_info=True)
        max_rounds_assistive = 1

    try:
        evidence_token_budget = int(await settings_service.get(KEY_EVIDENCE_TOKEN_BUDGET, db))
    except Exception:  # noqa: BLE001
        logger.warning("load_retrieval_tool_settings: %s missing, defaulting to 4000", KEY_EVIDENCE_TOKEN_BUDGET, exc_info=True)
        evidence_token_budget = 4000

    return RetrievalToolSettings(
        tool_enabled=tool_enabled,
        policy=policy,
        max_rounds_grounded=max(0, max_rounds_grounded),
        max_rounds_assistive=max(0, max_rounds_assistive),
        evidence_token_budget=max(0, evidence_token_budget),
    )


__all__ = [
    "RetrievalToolSettings",
    "load_retrieval_tool_settings",
    "KEY_TOOL_ENABLED",
    "KEY_POLICY",
    "KEY_MAX_ROUNDS_GROUNDED",
    "KEY_MAX_ROUNDS_ASSISTIVE",
    "KEY_EVIDENCE_TOKEN_BUDGET",
]
