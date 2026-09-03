"""context_engine.status_bus — DriftStatusBus.

Лёгкая шина для real-time уведомлений о фазах drift loop.

Хранилище — двухуровневое:
- in-memory: ``_subs[chat_id] -> set[Queue]`` для SSE-подписчиков.
- Redis: ``drift:status:{chat_id}`` с TTL 60 сек — для poll-endpoint
  и для catch-up при переподключении SSE-клиента.

Все ошибки Redis/JSON логируются и тихо глотаются — DriftStatusBus
не должен влиять на основной chat-loop.

Использование::

    bus = DriftStatusBus(redis_client)

    # Из DriftLoop._run_detect:
    await bus.publish(chat_id, DriftStatus(...))

    # Из SSE-endpoint:
    async with bus.subscribe(chat_id) as queue:
        while True:
            status = await queue.get()
            yield status
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from shared_contracts.models import DriftStatus

logger = logging.getLogger(__name__)


_STATUS_TTL_SECONDS = 60
_STATUS_KEY_TEMPLATE = "drift:status:{chat_id}"


def _status_key(chat_id: str) -> str:
    return _STATUS_KEY_TEMPLATE.format(chat_id=chat_id)


class DriftStatusBus:
    """Публикация/подписка для drift-статусов одного чата."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self.redis = redis
        self._subs: dict[str, set[asyncio.Queue[DriftStatus]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, chat_id: str, status: DriftStatus) -> None:
        """Записать статус в Redis (TTL) и разослать всем подписчикам.

        Подписчики получают копию статуса вне зависимости от состояния
        Redis — это позволяет UI видеть точно то событие, что произошло.
        Если подписчиков нет — запись всё равно уходит в Redis (для poll).
        """
        try:
            await self.redis.set(
                _status_key(chat_id),
                status.model_dump_json(),
                ex=_STATUS_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "status_bus.publish: redis SET failed chat_id=%s: %s",
                chat_id,
                exc,
            )

        async with self._lock:
            queues = list(self._subs.get(chat_id, ()))
        for q in queues:
            try:
                q.put_nowait(status)
            except asyncio.QueueFull:
                # Подписчик медленно потребляет — пропускаем ивент,
                # он уже зафиксирован в Redis для catch-up.
                logger.debug(
                    "status_bus.publish: queue full chat_id=%s, drop event",
                    chat_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "status_bus.publish: queue put failed chat_id=%s: %s",
                    chat_id,
                    exc,
                )

    async def get(self, chat_id: str) -> DriftStatus | None:
        """Прочитать последний зафиксированный статус из Redis.

        Возвращает ``None`` если ключа нет или значение повреждено.
        """
        try:
            raw: Any = await self.redis.get(_status_key(chat_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "status_bus.get: redis GET failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "status_bus.get: invalid JSON chat_id=%s: %s",
                chat_id,
                exc,
            )
            return None
        try:
            return DriftStatus.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "status_bus.get: DriftStatus validation failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            return None

    @asynccontextmanager
    async def subscribe(
        self, chat_id: str, *, maxsize: int = 32
    ) -> AsyncIterator[asyncio.Queue[DriftStatus]]:
        """Подписаться на поток drift-статусов для чата.

        При выходе из ``async with`` подписчик автоматически удаляется.
        Если в Redis есть последний зафиксированный статус — он
        доставляется в очередь синхронно как catch-up событие.
        """
        queue: asyncio.Queue[DriftStatus] = asyncio.Queue(maxsize=maxsize)
        async with self._lock:
            self._subs.setdefault(chat_id, set()).add(queue)
        try:
            latest = await self.get(chat_id)
            if latest is not None:
                # Catch-up: доставляем последний известный статус.
                try:
                    queue.put_nowait(latest)
                except asyncio.QueueFull:  # pragma: no cover
                    pass
            yield queue
        finally:
            async with self._lock:
                subs = self._subs.get(chat_id)
                if subs is not None:
                    subs.discard(queue)
                    if not subs:
                        self._subs.pop(chat_id, None)

    def subscriber_count(self, chat_id: str) -> int:
        """Тест-хелпер: количество активных подписчиков."""
        return len(self._subs.get(chat_id, ()))
