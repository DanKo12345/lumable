"""Integration test: the router served over a real loopback socket."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from app.local_api.router import ApiRouter
from app.local_api.server import ApiServer

TOKEN = "s3cret-token"


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def app_version(self) -> str:
        return "0.3.0"

    def status(self) -> dict:
        return {"power": True, "brightness": 80}

    def devices(self) -> list[dict]:
        return [{"address": "AA:BB", "name": "Desk"}]

    def set_power(self, on, device_id):
        self.calls.append(("power", on, device_id))

    def set_color(self, red, green, blue, device_id):
        self.calls.append(("color", red, green, blue, device_id))

    def set_brightness(self, value, device_id):
        self.calls.append(("brightness", value, device_id))

    def set_effect(self, code, speed, device_id):
        self.calls.append(("effect", code, speed, device_id))

    def apply_quick_mode(self, key):
        return False


def _request(url, *, method="GET", token=None, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture()
def server():
    backend = FakeBackend()
    srv = ApiServer(ApiRouter(backend, TOKEN), host="127.0.0.1", port=0)
    srv.start()
    try:
        yield srv, backend
    finally:
        srv.stop()


def _base(srv) -> str:
    return f"http://127.0.0.1:{srv.port}"


def test_health_reachable_without_token(server) -> None:
    srv, _ = server
    status, body = _request(f"{_base(srv)}/health")
    assert status == 200
    assert body["name"] == "LumaBLE"


def test_status_requires_token(server) -> None:
    srv, _ = server
    assert _request(f"{_base(srv)}/status")[0] == 401
    status, body = _request(f"{_base(srv)}/status", token=TOKEN)
    assert status == 200
    assert body["brightness"] == 80


def test_power_command_reaches_backend(server) -> None:
    srv, backend = server
    status, _ = _request(f"{_base(srv)}/power", method="POST", token=TOKEN, body={"on": True})
    assert status == 200
    assert ("power", True, None) in backend.calls


def test_server_binds_loopback_only(server) -> None:
    srv, _ = server
    assert srv.host == "127.0.0.1"


def test_command_denied_without_token_never_reaches_backend(server) -> None:
    srv, backend = server
    status, _ = _request(f"{_base(srv)}/power", method="POST", body={"on": True})  # no token
    assert status == 401
    assert backend.calls == []  # default-deny: nothing happened
