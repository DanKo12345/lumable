from __future__ import annotations

import socket
import threading
import time

import pytest

from app.local_api.router import ApiRouter
from app.local_api.server import ApiServer
from app.local_api.sse import SseBroker

TOKEN = "s3cret-token"


class FakeBackend:
    def app_version(self) -> str:
        return "0.3.0"

    def status(self) -> dict:
        return {"power": True}

    def devices(self) -> list[dict]:
        return []

    def set_power(self, on, device_id): ...
    def set_color(self, red, green, blue, device_id): ...
    def set_brightness(self, value, device_id): ...
    def set_effect(self, code, speed, device_id): ...
    def apply_quick_mode(self, key): return False


# ── broker unit ─────────────────────────────────────────────────────────
def test_publish_dedups_identical_states() -> None:
    broker = SseBroker()
    assert broker.publish({"power": True}) is True
    assert broker.publish({"power": True}) is False  # unchanged
    assert broker.publish({"power": False}) is True
    assert broker.latest() == {"power": False}


def test_subscribers_receive_published_state() -> None:
    broker = SseBroker()
    sub = broker.subscribe()
    assert broker.subscriber_count() == 1
    broker.publish({"brightness": 50})
    assert sub.get_nowait() == {"brightness": 50}
    broker.unsubscribe(sub)
    assert broker.subscriber_count() == 0


# ── SSE over a socket ────────────────────────────────────────────────────
@pytest.fixture()
def server():
    broker = SseBroker()
    srv = ApiServer(ApiRouter(FakeBackend(), TOKEN), host="127.0.0.1", port=0, broker=broker)
    srv.start()
    try:
        yield srv, broker
    finally:
        srv.stop()


def _raw_get(srv, path, *, token=None):
    sock = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
    sock.settimeout(3)
    request = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
    if token is not None:
        request += f"Authorization: Bearer {token}\r\n"
    request += "Connection: close\r\n\r\n"
    sock.sendall(request.encode())
    return sock


def test_events_streams_current_state(server) -> None:
    srv, broker = server
    broker.publish({"power": True, "brightness": 80})
    sock = _raw_get(srv, "/events", token=TOKEN)
    chunk = ""
    try:
        # Headers and the first data frame can arrive in separate packets.
        deadline = time.time() + 3
        while "data:" not in chunk and time.time() < deadline:
            received = sock.recv(4096)
            if not received:
                break
            chunk += received.decode("utf-8", "replace")
    finally:
        sock.close()
    assert "200" in chunk.splitlines()[0]
    assert "text/event-stream" in chunk
    assert "data:" in chunk
    assert "power" in chunk


def test_events_requires_token(server) -> None:
    srv, _ = server
    sock = _raw_get(srv, "/events")  # no token
    try:
        chunk = sock.recv(4096).decode("utf-8", "replace")
    finally:
        sock.close()
    assert "401" in chunk.splitlines()[0]


def test_stop_ends_an_open_sse_stream_and_its_thread() -> None:
    """A stream parked on its queue must not outlive the server.

    Handlers are daemon threads, and the stdlib never joins those, so without an
    explicit stop signal an open /events connection kept its thread alive for a
    full heartbeat (15s) past ``stop()`` — long enough to still be running when
    the process ends, which is where the socket-abort tracebacks came from.
    """
    broker = SseBroker()
    srv = ApiServer(ApiRouter(FakeBackend(), TOKEN), host="127.0.0.1", port=0, broker=broker)
    srv.start()
    sock = _raw_get(srv, "/events", token=TOKEN)
    try:
        deadline = time.time() + 3
        while broker.subscriber_count() == 0 and time.time() < deadline:
            time.sleep(0.01)
        assert broker.subscriber_count() == 1

        handlers_before = _handler_threads()
        assert handlers_before, "expected a live handler thread for the open stream"

        started = time.time()
        srv.stop()
        elapsed = time.time() - started

        # Well under the 15s heartbeat: the stream was woken, not waited out.
        assert elapsed < 3, f"stop() took {elapsed:.1f}s — the stream was not woken"
        assert broker.subscriber_count() == 0
        assert not [t for t in handlers_before if t.is_alive()]
    finally:
        sock.close()


def _handler_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "lumable-api-handler" and t.is_alive()]
