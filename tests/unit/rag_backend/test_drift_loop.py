"""Unit-тесты для DriftLoop → CampaignStateDrafter integration (Phase 3).

Проверяем:

  * при наличии drift hints → ``_run_detect`` вызывает
    ``drafter.plan_draft(chat_id)``;
  * при отсутствии hints (или None) → drafter НЕ вызывается;
  * исключение из drafter-а логируется и НЕ пробрасывается
    (drift-loop не должен падать из-за Phase 3);
  * drafter может быть не задан (default ``None``) — loop продолжает
    работать и просто логирует.

Тесты не поднимают Redis/БД — drift detector и Redis мокаются на
границах ``DriftLoop``.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.context_engine.loop import DriftLoop


CHAT_ID = "11111111-1111-1111-1111-111111111111"


def _make_redis() -> MagicMock:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.sadd = AsyncMock(return_value=1)
    redis.srem = AsyncMock(return_value=1)
    redis.smembers = AsyncMock(return_value=set())
    return redis


def _make_detector(*, hints: list | None) -> MagicMock:
    detector = MagicMock()
    detector.detect = AsyncMock(return_value=hints)
    return detector


def _make_drafter(*, raises: Exception | None = None) -> MagicMock:
    drafter = MagicMock()
    if raises is not None:
        drafter.plan_draft = AsyncMock(side_effect=raises)
    else:
        drafter.plan_draft = AsyncMock(return_value={"chat_id": CHAT_ID})
    return drafter


class TestDriftLoopDrafterIntegration:
    @pytest.mark.asyncio
    async def test_run_detect_calls_drafter_on_hints(self):
        redis = _make_redis()
        detector = _make_detector(
            hints=[{"fact": "x", "confidence": 0.9, "adds_field": "k"}]
        )
        drafter = _make_drafter()

        loop = DriftLoop(detector=detector, redis=redis)
        loop.drafter = drafter

        await loop._run_detect(CHAT_ID)

        detector.detect.assert_awaited_once_with(CHAT_ID)
        drafter.plan_draft.assert_awaited_once_with(CHAT_ID)

    @pytest.mark.asyncio
    async def test_run_detect_skips_drafter_on_no_hints(self):
        redis = _make_redis()
        detector = _make_detector(hints=[])
        drafter = _make_drafter()

        loop = DriftLoop(detector=detector, redis=redis)
        loop.drafter = drafter

        await loop._run_detect(CHAT_ID)

        detector.detect.assert_awaited_once_with(CHAT_ID)
        drafter.plan_draft.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_detect_skips_drafter_on_detector_none(self):
        redis = _make_redis()
        detector = _make_detector(hints=None)
        drafter = _make_drafter()

        loop = DriftLoop(detector=detector, redis=redis)
        loop.drafter = drafter

        await loop._run_detect(CHAT_ID)

        drafter.plan_draft.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_detect_swallows_drafter_exception(self):
        redis = _make_redis()
        detector = _make_detector(
            hints=[{"fact": "x", "confidence": 0.9, "adds_field": "k"}]
        )
        drafter = _make_drafter(raises=RuntimeError("LLM boom"))

        loop = DriftLoop(detector=detector, redis=redis)
        loop.drafter = drafter

        # Не должно бросить наружу.
        await loop._run_detect(CHAT_ID)

        drafter.plan_draft.assert_awaited_once_with(CHAT_ID)

    @pytest.mark.asyncio
    async def test_run_detect_without_drafter_does_not_crash(self):
        redis = _make_redis()
        detector = _make_detector(
            hints=[{"fact": "x", "confidence": 0.9, "adds_field": "k"}]
        )

        loop = DriftLoop(detector=detector, redis=redis)
        # drafter по умолчанию None.
        assert loop.drafter is None

        await loop._run_detect(CHAT_ID)  # no raise

    @pytest.mark.asyncio
    async def test_drafter_attribute_default_is_none(self):
        redis = _make_redis()
        detector = _make_detector(hints=None)
        loop = DriftLoop(detector=detector, redis=redis)
        assert loop.drafter is None

    @pytest.mark.asyncio
    async def test_trigger_for_chat_creates_detect_task(self):
        """Smoke: trigger_for_chat + cooldown → _run_detect."""
        redis = _make_redis()
        redis.set.return_value = True  # acquired
        detector = _make_detector(
            hints=[{"fact": "x", "confidence": 0.9, "adds_field": "k"}]
        )
        drafter = _make_drafter()

        loop = DriftLoop(detector=detector, redis=redis)
        loop.drafter = drafter

        await loop.trigger_for_chat(CHAT_ID)

        # _run_detect — fire-and-forget asyncio.create_task; даём ему
        # шанс выполниться.
        for _ in range(20):
            if drafter.plan_draft.await_count > 0:
                break
            await asyncio.sleep(0.01)

        drafter.plan_draft.assert_awaited_once_with(CHAT_ID)
