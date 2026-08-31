"""context_engine.loop — DriftLoop с cooldown + idle scan.

Запускается в FastAPI lifespan. На каждый chat turn (через
``trigger_for_chat``) проверяет Redis SETNX cooldown-ключ; если не
выставлен — ставит на 30 сек и запускает ``DriftDetector.detect`` в
fire-and-forget asyncio task.

Параллельно крутится ``run_idle_scan`` (каждые 60 сек) — fallback для
чатов, помеченных в Redis set ``drift:dirty``, у которых direct trigger
провалился (Redis SETNX упал с ошибкой).

Все ошибки (Redis, detector, провайдер) логируются и тихо глотаются —
фазовый сбой drift не должен влиять на основной chat-loop.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis

from .drift import DriftDetector

if TYPE_CHECKING:
    from .draft import CampaignStateDrafter

logger = logging.getLogger(__name__)


# Cooldown per-chat — не чаще 1 раза в N секунд.
_COOLDOWN_SECONDS = 30
_COOLDOWN_KEY = "drift:cooldown:{chat_id}"

# Dirty set — для idle scan fallback.
_DIRTY_SET_KEY = "drift:dirty"

# Idle scan период.
_IDLE_SCAN_PERIOD_SECONDS = 60


class DriftLoop:
    """Background loop с cooldown для drift-detection."""

    def __init__(
        self,
        *,
        detector: DriftDetector,
        redis: aioredis.Redis,
        cooldown_seconds: int = _COOLDOWN_SECONDS,
        idle_scan_period_seconds: int = _IDLE_SCAN_PERIOD_SECONDS,
    ) -> None:
        self.detector = detector
        self.redis = redis
        self.cooldown_seconds = cooldown_seconds
        self.idle_scan_period_seconds = idle_scan_period_seconds
        # Phase 3: drafter планирует draft на основе drift hints.
        # Устанавливается через ``drift_loop.drafter = ...`` в lifespan
        # (или напрямую в тестах). Если None — detect работает, но draft
        # не создаётся (логируется INFO).
        self.drafter: "CampaignStateDrafter | None" = None
        self._idle_task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def trigger_for_chat(self, chat_id: str) -> None:
        """Fire-and-forget запуск drift для одного чата. Cooldown через Redis SETNX."""
        if not chat_id:
            return

        cooldown_key = _COOLDOWN_KEY.format(chat_id=chat_id)
        try:
            acquired = await self.redis.set(
                cooldown_key,
                "1",
                ex=self.cooldown_seconds,
                nx=True,
            )
        except Exception as exc:  # noqa: BLE001
            # Redis упал — не блокируем drift-detection, но помечаем чат
            # в dirty set, чтобы idle scan попробовал позже.
            logger.warning(
                "drift_loop.trigger_for_chat: redis SETNX failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            acquired = True

        if not acquired:
            logger.debug(
                "drift_loop.trigger_for_chat: cooldown active chat_id=%s, skip",
                chat_id,
            )
            return

        # Mark dirty для fallback.
        try:
            await self.redis.sadd(_DIRTY_SET_KEY, chat_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "drift_loop.trigger_for_chat: redis SADD failed chat_id=%s: %s",
                chat_id,
                exc,
            )

        # Fire-and-forget task — exceptions логируются внутри _run_detect.
        try:
            asyncio.create_task(self._run_detect(chat_id))
        except RuntimeError:
            # event loop закрыт (shutdown) — игнорируем.
            logger.debug(
                "drift_loop.trigger_for_chat: no running loop chat_id=%s",
                chat_id,
            )

    def shutdown(self) -> None:
        """Остановить idle scan. Direct fire-and-forget tasks не трогаем —
        они завершатся сами (после detector.detect)."""
        self._shutdown.set()
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_detect(self, chat_id: str) -> None:
        try:
            hints = await self.detector.detect(chat_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "drift_loop._run_detect: detector failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            return

        if not hints:
            # Нет hints (или пропуск) — очищаем чат из dirty set.
            try:
                await self.redis.srem(_DIRTY_SET_KEY, chat_id)
            except Exception:  # noqa: BLE001
                pass
            return

        # Phase 3: запустить CampaignStateDrafter (если задан).
        # Ошибка drafter-а не должна ломать loop — drift hints уже
        # записаны в scene_state.drift и видны в UI; просто логируем.
        if self.drafter is not None:
            try:
                await self.drafter.plan_draft(chat_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "drift_loop._run_detect: drafter failed chat_id=%s: %s",
                    chat_id,
                    exc,
                )
        else:
            logger.info(
                "drift_loop._run_detect: chat_id=%s produced %d hints "
                "(drafter not configured, skip)",
                chat_id,
                len(hints),
            )

        # Убираем чат из dirty set — direct trigger его уже обработал.
        try:
            await self.redis.srem(_DIRTY_SET_KEY, chat_id)
        except Exception:  # noqa: BLE001
            pass

    async def run_idle_scan(self) -> None:
        """Каждые idle_scan_period_seconds сканирует drift:dirty и запускает detect."""
        while not self._shutdown.is_set():
            try:
                dirty_ids = await self.redis.smembers(_DIRTY_SET_KEY)
            except Exception as exc:  # noqa: BLE001
                logger.warning("drift_loop.run_idle_scan: SMEMBERS failed: %s", exc)
                dirty_ids = set()

            for chat_id in list(dirty_ids):
                if self._shutdown.is_set():
                    break
                try:
                    await self.trigger_for_chat(chat_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "drift_loop.run_idle_scan: trigger failed chat_id=%s: %s",
                        chat_id,
                        exc,
                    )

            # Прерываемый sleep.
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self.idle_scan_period_seconds,
                )
            except asyncio.TimeoutError:
                pass
