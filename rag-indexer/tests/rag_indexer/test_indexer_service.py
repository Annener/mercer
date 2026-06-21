"""Unit-тесты для IndexerService после рефакторинга на RedisStateManager (этап 7)."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock

import fakeredis.aioredis as fakeredis

from app.indexer_service import IndexerService
from parser.state.redis_state_manager import RedisStateManager


@pytest.fixture
def state_manager():
    return RedisStateManager(fakeredis.FakeRedis(decode_responses=True))


@pytest.fixture
def service(state_manager):
    db_client = AsyncMock()
    return IndexerService(db_client=db_client, state_manager=state_manager)


def test_service_has_no_broadcaster(service):
    """After refactor the service must not have a broadcaster field."""
    assert not hasattr(service, "_broadcaster"), "_broadcaster должен быть удалён"
    assert not hasattr(service, "broadcaster"), "broadcaster должен быть удалён"


def test_service_has_no_cancel_flags(service):
    """_cancel_flags (дикт) заменён на Redis — не должен быть в сервисе."""
    assert not hasattr(service, "_cancel_flags"), "_cancel_flags должен быть удалён"


def test_service_has_no_get_broadcaster(service):
    """get_broadcaster удалён вместе с WebSocket manager."""
    assert not hasattr(service, "get_broadcaster"), "get_broadcaster должен быть удалён"


@pytest.mark.asyncio
async def test_cancel_task_returns_false_for_unknown(service):
    """cancel_task возвращает False для незапущенной задачи."""
    result = await service.cancel_task("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_task_sets_redis_flag(service, state_manager):
    """cancel_task записывает флаг отмены в Redis."""
    async def dummy():
        await asyncio.sleep(100)

    task = asyncio.create_task(dummy())
    service._tasks["t1"] = task

    result = await service.cancel_task("t1")
    assert result is True
    assert await state_manager.is_cancelled("t1") is True

    # Чистим за собой
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_on_task_done_removes_from_tasks(service):
    """_on_task_done чистит _tasks после завершения."""
    async def dummy():
        pass

    task = asyncio.create_task(dummy())
    service._tasks["t2"] = task
    await task
    service._on_task_done("t2", task)
    assert "t2" not in service._tasks


@pytest.mark.asyncio
async def test_cancel_task_does_not_hard_cancel_asyncio_task(service, state_manager):
    """cancel_task не вызывает task.cancel() — worker завершается чисто через Redis-флаг."""
    completed = False

    async def graceful_worker():
        nonlocal completed
        # Проверяем флаг через state_manager (imitation worker behaviour)
        for _ in range(5):
            await asyncio.sleep(0)
            if await state_manager.is_cancelled("t3"):
                return  # чистое завершение
        completed = True

    task = asyncio.create_task(graceful_worker())
    service._tasks["t3"] = task

    await service.cancel_task("t3")
    await task  # не должен бросить CancelledError

    assert not task.cancelled(), "asyncio.Task не должен быть жёстко отменён"
    assert not completed, "Worker должен выйти через проверку Redis-флага, а не дойти до completed=True"
