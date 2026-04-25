"""WebSocket broadcaster with topic-based pub/sub."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class Broadcaster:
    def __init__(self) -> None:
        self._topics: dict[str, set[asyncio.Queue[dict]]] = {}

    async def subscribe(self, topic: str) -> AsyncIterator[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue()
        self._topics.setdefault(topic, set()).add(q)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            self._topics.get(topic, set()).discard(q)
            if not self._topics.get(topic):
                self._topics.pop(topic, None)

    async def publish(self, topic: str, message: dict) -> None:
        for q in list(self._topics.get(topic, ())):
            await q.put(message)

    def subscriber_count(self, topic: str) -> int:
        return len(self._topics.get(topic, ()))
