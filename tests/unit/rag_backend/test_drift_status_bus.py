"""Tests for DriftStatusBus — pub/sub for drift phases."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock

from shared_contracts.models import DriftPhase, DriftStatus

from app.services.context_engine.status_bus import DriftStatusBus


def _status(phase: DriftPhase, message: str | None = None) -> DriftStatus:
    return DriftStatus(
        chat_id="chat-1",
        phase=phase,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        published_at=datetime.now(timezone.utc),
        message=message,
    )


def _make_redis() -> AsyncMock:
    """Fake aioredis: in-memory store + simple GET/SET semantics."""
    store: dict[str, str] = {}
    ttl: dict[str, int] = {}

    async def set_value(key: str, value: str, ex: int | None = None) -> str:
        store[key] = value
        ttl[key] = ex or 0
        return "OK"

    async def get_value(key: str) -> str | None:
        return store.get(key)

    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=set_value)
    redis.get = AsyncMock(side_effect=get_value)
    redis._store = store  # type: ignore[attr-defined]
    redis._ttl = ttl  # type: ignore[attr-defined]
    return redis


@pytest.mark.asyncio
async def test_publish_writes_to_redis() -> None:
    redis = _make_redis()
    bus = DriftStatusBus(redis)
    status = _status(DriftPhase.DETECTING, "Анализ…")
    await bus.publish("chat-1", status)
    stored = redis._store["drift:status:chat-1"]
    parsed = DriftStatus.model_validate_json(stored)
    assert parsed.phase == DriftPhase.DETECTING
    assert parsed.message == "Анализ…"
    assert redis._ttl["drift:status:chat-1"] == 60


@pytest.mark.asyncio
async def test_get_returns_published_status() -> None:
    redis = _make_redis()
    bus = DriftStatusBus(redis)
    await bus.publish("chat-1", _status(DriftPhase.DRAFT_READY, "Готово"))
    status = await bus.get("chat-1")
    assert status is not None
    assert status.phase == DriftPhase.DRAFT_READY


@pytest.mark.asyncio
async def test_get_returns_none_when_missing() -> None:
    redis = _make_redis()
    bus = DriftStatusBus(redis)
    status = await bus.get("nonexistent")
    assert status is None


@pytest.mark.asyncio
async def test_get_returns_none_on_corrupted_json() -> None:
    redis = _make_redis()
    await redis.set("drift:status:chat-1", "{not json")
    bus = DriftStatusBus(redis)
    status = await bus.get("chat-1")
    assert status is None


@pytest.mark.asyncio
async def test_subscribe_delivers_immediate_status() -> None:
    redis = _make_redis()
    bus = DriftStatusBus(redis)
    await bus.publish("chat-1", _status(DriftPhase.DETECTING))
    async with bus.subscribe("chat-1") as queue:
        first = await asyncio.wait_for(queue.get(), timeout=0.2)
    assert first.phase == DriftPhase.DETECTING


@pytest.mark.asyncio
async def test_subscribe_unregisters_on_exit() -> None:
    redis = _make_redis()
    bus = DriftStatusBus(redis)
    async with bus.subscribe("chat-1"):
        assert bus.subscriber_count("chat-1") == 1
    assert bus.subscriber_count("chat-1") == 0


@pytest.mark.asyncio
async def test_publish_reaches_multiple_subscribers() -> None:
    redis = _make_redis()
    bus = DriftStatusBus(redis)

    async with bus.subscribe("chat-1") as q1, bus.subscribe("chat-1") as q2:
        await bus.publish("chat-1", _status(DriftPhase.DRAFTING))
        s1 = await asyncio.wait_for(q1.get(), timeout=0.2)
        s2 = await asyncio.wait_for(q2.get(), timeout=0.2)
    assert s1.phase == DriftPhase.DRAFTING
    assert s2.phase == DriftPhase.DRAFTING


@pytest.mark.asyncio
async def test_publish_does_not_block_when_no_subscribers() -> None:
    redis = _make_redis()
    bus = DriftStatusBus(redis)
    await bus.publish("chat-1", _status(DriftPhase.IDLE))
    # Side-effect: запись всё равно ушла в Redis.
    assert "drift:status:chat-1" in redis._store


@pytest.mark.asyncio
async def test_redis_failure_does_not_break_publish() -> None:
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=RuntimeError("redis down"))
    bus = DriftStatusBus(redis)
    # Не поднимается.
    await bus.publish("chat-1", _status(DriftPhase.ERROR, "boom"))


@pytest.mark.asyncio
async def test_get_handles_redis_failure() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
    bus = DriftStatusBus(redis)
    assert await bus.get("chat-1") is None
