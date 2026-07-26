"""A tiny thread-safe pub/sub hub for Server-Sent Events.

The app publishes the current strip state (power/colour/brightness/…) on the main
thread; each open ``/events`` connection is a subscriber on its own server
thread that drains its queue and writes SSE frames. Only changes are broadcast,
so idle dashboards stay quiet.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

_QUEUE_MAX = 32

# Pushed into every subscriber queue to unblock a parked ``get()``. It is not a
# state update, so a stream must skip it rather than send it as a frame.
WAKEUP = object()


class SseBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, Any] = {}
        self._subscribers: set[queue.Queue] = set()

    def latest(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest)

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def wake_all(self) -> None:
        """Unblock every parked subscriber.

        A stream sits in ``get(timeout=heartbeat)`` for up to the full heartbeat,
        so on shutdown it would keep its thread alive that long. Pushing a wakeup
        token lets each stream notice the stop immediately. A full queue already
        has something to return, so it needs no token.
        """
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(WAKEUP)
            except queue.Full:
                pass

    def publish(self, state: dict[str, Any]) -> bool:
        """Store and broadcast the state. Returns False (and does nothing) when
        the state is unchanged, so we don't spam identical frames."""
        snapshot = dict(state)
        with self._lock:
            if snapshot == self._latest:
                return False
            self._latest = snapshot
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(snapshot)
            except queue.Full:
                # A slow consumer misses this frame; it gets the next update.
                pass
        return True
