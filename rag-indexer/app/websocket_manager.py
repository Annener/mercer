from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, task_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[task_id].add(websocket)

    async def disconnect(self, task_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(task_id)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(task_id, None)

    async def broadcast(self, task_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections.get(task_id, set()))

        stale_connections: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                logger.warning("Failed to send WebSocket event for task_id=%s", task_id, exc_info=True)
                stale_connections.append(websocket)

        for websocket in stale_connections:
            await self.disconnect(task_id, websocket)
