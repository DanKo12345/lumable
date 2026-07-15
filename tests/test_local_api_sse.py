from __future__ import annotations

import socket
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
