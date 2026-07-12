# bus.py — In-memory publish/subscribe event bus for the UI backend.
#
# Decoupled from watchfiles and websockets so it is trivially testable: a test
# can publish a message directly and assert a subscriber receives it. Messages
# are plain dicts carrying a ``type`` and (usually) a ``project_id``; a None
# project_id marks a global message (e.g. project_list_changed).
from __future__ import annotations

import asyncio


class Subscription:
    """One subscriber's handle: an asyncio queue plus lifecycle helpers."""

    def __init__(self, bus: "EventBus", queue: "asyncio.Queue[dict]") -> None:
        self._bus = bus
        self._queue = queue

    async def get(self) -> dict:
        """Await the next published message for this subscriber."""
        return await self._queue.get()

    def close(self) -> None:
        """Detach this subscription from the bus (no more deliveries)."""
        self._bus._unsubscribe(self._queue)

    def __enter__(self) -> "Subscription":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class EventBus:
    """Fan-out of dict messages to every live subscriber.

    ``publish`` is safe to call from any thread (the exec output pumps and the
    file watcher run off the event loop): when a running loop is bound it hops
    onto it via ``call_soon_threadsafe``; otherwise it delivers inline (unit
    tests without a loop). Delivery is best-effort — a full subscriber queue
    drops the message for that subscriber instead of blocking the publisher.
    """

    def __init__(self, max_queue: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._max_queue = max_queue
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the event loop threads should publish onto (called at startup)."""
        self._loop = loop

    def subscribe(self) -> Subscription:
        """Register a new subscriber and return its Subscription handle."""
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return Subscription(self, queue)

    def _unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    def publish(self, message: dict) -> None:
        """Deliver ``message`` to every subscriber (thread-safe, non-blocking)."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._deliver, message)
        else:
            self._deliver(message)

    def _deliver(self, message: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # slow consumer — drop rather than block the publisher
