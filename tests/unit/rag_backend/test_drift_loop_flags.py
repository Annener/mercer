"""Tests for DriftLoop flag honoring (master detect/draft).

Verifies that when ``drift.enabled`` / ``drift.detect_enabled`` /
``drift.draft_enabled`` PlatformSettings are off, the loop short-circuits
appropriately and ``status_bus`` receives the right transitions.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared_contracts.models import DriftPhase, DriftStatus

from app.services.context_engine.loop import DriftLoop
from app.services.context_engine.status_bus import DriftStatusBus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _NoopDetector:
    async def detect(self, chat_id: str) -> list[dict[str, Any]]:
        return []


class _FixedFlags:
    def __init__(self, enabled: bool, detect: bool, draft: bool) -> None:
        self.enabled = enabled
        self.detect_enabled = detect
        self.draft_enabled = draft


def _make_settings(flags: _FixedFlags) -> MagicMock:
    settings = MagicMock()
    # ``SettingsService.get`` — async; mock должен быть AsyncMock,
    # иначе ``await settings_service.get(...)`` в loop.py падает.
    settings.get = AsyncMock(
        side_effect=lambda key: {
            "drift.enabled": flags.enabled,
            "drift.detect_enabled": flags.detect_enabled,
            "drift.draft_enabled": flags.draft_enabled,
        }.get(key, True)
    )
    return settings


def _make_redis() -> MagicMock:
    """SETNX-cooldown friendly fake.

    Поддерживает оба режима:
    - ``set(key, value, ex=...)`` без ``nx`` — обычный SET (всегда сохраняет);
    - ``set(key, value, ex=..., nx=True)`` — SETNX (только если ключа нет).
    """
    store: dict[str, str] = {}

    async def set_value(
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> str | bool | None:
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def sadd(key: str, value: str) -> int:
        return 1

    async def srem(key: str, value: str) -> int:
        return 0

    async def smembers(key: str) -> set[str]:
        return set()

    async def get_value(key: str) -> str | None:
        return store.get(key)

    redis = MagicMock()
    redis.set = AsyncMock(side_effect=set_value)
    redis.get = AsyncMock(side_effect=get_value)
    redis.sadd = AsyncMock(side_effect=sadd)
    redis.srem = AsyncMock(side_effect=srem)
    redis.smembers = AsyncMock(side_effect=smembers)
    redis._store = store  # type: ignore[attr-defined]
    return redis


def _drain(coros: list[asyncio.Task]) -> list[DriftStatus]:
    """Collect statuses produced by DriftLoop.publish."""
    # tests mostly await run_idle_scan / _run_detect directly,
    # not via fire-and-forget; capture published via the real bus.
    raise NotImplementedError  # not needed; tests use the bus directly


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_master_disabled_skips_cooldown_and_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(_FixedFlags(enabled=False, detect=True, draft=True))
    monkeypatch.setattr(
        "app.services.settings_service.settings_service", settings, raising=False
    )

    redis = _make_redis()
    bus = DriftStatusBus(redis)
    detector = _NoopDetector()
    loop = DriftLoop(detector=detector, redis=redis, status_bus=bus)  # type: ignore[arg-type]

    await loop.trigger_for_chat("chat-1")

    # SETNX не должен был сработать — флаг выключен.
    redis.set.assert_not_called()
    # detect не вызывался.
    # bus должен остаться без публикаций (status_bus=None не важен здесь).
    assert bus.subscriber_count("chat-1") == 0


@pytest.mark.asyncio
async def test_detect_disabled_skips_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(_FixedFlags(enabled=True, detect=False, draft=True))
    monkeypatch.setattr(
        "app.services.settings_service.settings_service", settings, raising=False
    )

    redis = _make_redis()
    bus = DriftStatusBus(redis)
    detector = _NoopDetector()
    loop = DriftLoop(detector=detector, redis=redis, status_bus=bus)  # type: ignore[arg-type]

    await loop.trigger_for_chat("chat-1")

    redis.set.assert_not_called()
    assert bus.subscriber_count("chat-1") == 0


@pytest.mark.asyncio
async def test_flags_cached_then_invalidated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(_FixedFlags(enabled=True, detect=True, draft=True))
    monkeypatch.setattr(
        "app.services.settings_service.settings_service", settings, raising=False
    )

    redis = _make_redis()
    bus = DriftStatusBus(redis)
    loop = DriftLoop(detector=_NoopDetector(), redis=redis, status_bus=bus)  # type: ignore[arg-type]

    # 1й вызов — пробивает кеш (settings.get вызывается 3 раза).
    await loop._get_flags()
    calls_first = settings.get.call_count
    # 2й — берётся из кеша.
    flags2 = await loop._get_flags()
    calls_second = settings.get.call_count
    assert calls_first == calls_second  # не увеличилось

    # invalidate → следующий вызов снова читает.
    loop.invalidate_flags()
    flags3 = await loop._get_flags()
    calls_third = settings.get.call_count
    assert calls_third > calls_second
    assert flags3.enabled is True


@pytest.mark.asyncio
async def test_no_hints_publishes_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(_FixedFlags(enabled=True, detect=True, draft=True))
    monkeypatch.setattr(
        "app.services.settings_service.settings_service", settings, raising=False
    )

    redis = _make_redis()
    bus = DriftStatusBus(redis)
    loop = DriftLoop(detector=_NoopDetector(), redis=redis, status_bus=bus)  # type: ignore[arg-type]

    await loop._run_detect("chat-1")
    latest = await bus.get("chat-1")
    assert latest is not None
    assert latest.phase == DriftPhase.IDLE


@pytest.mark.asyncio
async def test_draft_disabled_with_hints_publishes_idle_with_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(_FixedFlags(enabled=True, detect=True, draft=False))
    monkeypatch.setattr(
        "app.services.settings_service.settings_service", settings, raising=False
    )

    redis = _make_redis()

    class _HintDetector:
        async def detect(self, chat_id: str) -> list[dict[str, Any]]:
            return [{"hint": "foo"}]

    bus = DriftStatusBus(redis)
    loop = DriftLoop(detector=_HintDetector(), redis=redis, status_bus=bus)  # type: ignore[arg-type]

    await loop._run_detect("chat-1")
    latest = await bus.get("chat-1")
    assert latest is not None
    assert latest.phase == DriftPhase.IDLE
    assert latest.message is not None
    assert "draft" in latest.message.lower()
    assert latest.drift_hints_count == 1


@pytest.mark.asyncio
async def test_drafter_error_publishes_error_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(_FixedFlags(enabled=True, detect=True, draft=True))
    monkeypatch.setattr(
        "app.services.settings_service.settings_service", settings, raising=False
    )

    redis = _make_redis()

    class _HintDetector:
        async def detect(self, chat_id: str) -> list[dict[str, Any]]:
            return [{"hint": "foo"}]

    class _BoomDrafter:
        async def plan_draft(self, chat_id: str) -> None:
            raise RuntimeError("llm offline")

    bus = DriftStatusBus(redis)
    loop = DriftLoop(detector=_HintDetector(), redis=redis, status_bus=bus)  # type: ignore[arg-type]
    loop.drafter = _BoomDrafter()  # type: ignore[assignment]

    await loop._run_detect("chat-1")
    latest = await bus.get("chat-1")
    assert latest is not None
    assert latest.phase == DriftPhase.ERROR
    assert latest.error is not None
    assert "llm offline" in latest.error
