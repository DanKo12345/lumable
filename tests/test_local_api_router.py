from __future__ import annotations

import json

from app.local_api import API_VERSION, MAX_BODY_BYTES, ApiRouter

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self._quick_modes = {"gaming", "chill"}

    def app_version(self) -> str:
        return "0.3.0"

    def status(self) -> dict:
        return {"power": True, "color": {"r": 10, "g": 20, "b": 30}, "brightness": 80, "connected": True}

    def devices(self) -> list[dict]:
        return [{"address": "AA:BB", "name": "Desk", "connected": True}]

    def set_power(self, on, device_id):
        self.calls.append(("power", on, device_id))

    def set_color(self, red, green, blue, device_id):
        self.calls.append(("color", red, green, blue, device_id))

    def set_brightness(self, value, device_id):
        self.calls.append(("brightness", value, device_id))

    def set_effect(self, code, speed, device_id):
        self.calls.append(("effect", code, speed, device_id))

    def apply_quick_mode(self, key):
        self.calls.append(("quick", key))
        return key in self._quick_modes


def _router():
    return ApiRouter(FakeBackend(), TOKEN)


def _body(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ── health & auth ──────────────────────────────────────────────────────
def test_health_is_unauthenticated_and_reports_version() -> None:
    resp = _router().handle("GET", "/health")
    assert resp.status == 200
    assert resp.body["api_version"] == API_VERSION
    assert resp.body["app_version"] == "0.3.0"
    assert resp.body["name"] == "LumaBLE"


def test_index_is_unauthenticated_and_lists_endpoints() -> None:
    resp = _router().handle("GET", "/")
    assert resp.status == 200
    assert "endpoints" in resp.body
    assert "GET /status" in resp.body["endpoints"]
    assert "auth" in resp.body


def test_missing_token_is_unauthorized() -> None:
    assert _router().handle("GET", "/status").status == 401


def test_wrong_token_is_unauthorized() -> None:
    resp = _router().handle("GET", "/status", {"Authorization": "Bearer nope"})
    assert resp.status == 401


def test_empty_configured_token_rejects_everything() -> None:
    router = ApiRouter(FakeBackend(), "")
    assert router.handle("GET", "/status", {"Authorization": "Bearer "}).status == 401


def test_unknown_path_is_404() -> None:
    assert _router().handle("GET", "/nope", AUTH).status == 404


def test_wrong_method_is_405() -> None:
    assert _router().handle("GET", "/power", AUTH).status == 405


# ── reads ───────────────────────────────────────────────────────────────
def test_status_returns_backend_state() -> None:
    resp = _router().handle("GET", "/status", AUTH)
    assert resp.status == 200
    assert resp.body["brightness"] == 80


def test_devices_wraps_list() -> None:
    resp = _router().handle("GET", "/devices", AUTH)
    assert resp.status == 200
    assert resp.body["devices"][0]["name"] == "Desk"


# ── power ────────────────────────────────────────────────────────────────
def test_power_on_is_idempotent_command() -> None:
    backend = FakeBackend()
    router = ApiRouter(backend, TOKEN)
    resp = router.handle("POST", "/power", AUTH, _body({"on": True}))
    assert resp.status == 200
    assert ("power", True, None) in backend.calls


def test_power_requires_boolean() -> None:
    assert _router().handle("POST", "/power", AUTH, _body({"on": "yes"})).status == 400
    assert _router().handle("POST", "/power", AUTH, _body({})).status == 400


def test_power_passes_device_id() -> None:
    backend = FakeBackend()
    ApiRouter(backend, TOKEN).handle("POST", "/power", AUTH, _body({"on": False, "device_id": "AA:BB"}))
    assert ("power", False, "AA:BB") in backend.calls


# ── color / brightness / effect ─────────────────────────────────────────
def test_color_clamps_out_of_range_channels() -> None:
    backend = FakeBackend()
    ApiRouter(backend, TOKEN).handle("POST", "/color", AUTH, _body({"r": 999, "g": -5, "b": 128}))
    assert ("color", 255, 0, 128, None) in backend.calls


def test_color_rejects_non_numeric() -> None:
    assert _router().handle("POST", "/color", AUTH, _body({"r": "x", "g": 1, "b": 2})).status == 400


def test_brightness_clamps_and_requires_value() -> None:
    backend = FakeBackend()
    ApiRouter(backend, TOKEN).handle("POST", "/brightness", AUTH, _body({"value": 150}))
    assert ("brightness", 100, None) in backend.calls
    assert _router().handle("POST", "/brightness", AUTH, _body({})).status == 400


def test_effect_optional_speed() -> None:
    backend = FakeBackend()
    ApiRouter(backend, TOKEN).handle("POST", "/effect", AUTH, _body({"code": 5}))
    ApiRouter(backend, TOKEN).handle("POST", "/effect", AUTH, _body({"code": 5, "speed": 70}))
    assert ("effect", 5, None, None) in backend.calls
    assert ("effect", 5, 70, None) in backend.calls


# ── quick mode ───────────────────────────────────────────────────────────
def test_quick_mode_applies_known_and_404s_unknown() -> None:
    assert _router().handle("POST", "/quick-mode", AUTH, _body({"key": "gaming"})).status == 200
    assert _router().handle("POST", "/quick-mode", AUTH, _body({"key": "nope"})).status == 404
    assert _router().handle("POST", "/quick-mode", AUTH, _body({})).status == 400


# ── body handling ────────────────────────────────────────────────────────
def test_invalid_json_is_400() -> None:
    assert _router().handle("POST", "/power", AUTH, b"{not json").status == 400


def test_oversized_body_is_413() -> None:
    big = b"x" * (MAX_BODY_BYTES + 1)
    assert _router().handle("POST", "/power", AUTH, big).status == 413


def test_path_normalization_ignores_query_and_trailing_slash() -> None:
    assert _router().handle("GET", "/status/?foo=1", AUTH).status == 200
