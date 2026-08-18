from __future__ import annotations

import json

from app.local_api import API_VERSION, MAX_BODY_BYTES, ApiRouter

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self._quick_modes = {"gaming", "chill"}
        self.pc_mode_starts = True
        self._scenes: list[dict] = []

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

    def set_pc_mode(self, mode):
        self.calls.append(("pc_mode", mode))
        if not self.pc_mode_starts:
            return False
        return mode in {"screen", "music", "effect", "diy", "off"}

    def list_scenes(self):
        return list(self._scenes)

    def save_scene(self, name):
        scene = {"scene_id": "s1", "name": name, "state": {}}
        self._scenes.append(scene)
        return scene

    def apply_scene(self, scene_id):
        self.calls.append(("apply_scene", scene_id))
        if any(s["scene_id"] == scene_id for s in self._scenes):
            return {"applied": ["power"], "skipped": []}
        return None

    def delete_scene(self, scene_id):
        before = len(self._scenes)
        self._scenes = [s for s in self._scenes if s["scene_id"] != scene_id]
        return len(self._scenes) != before


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


# ── session auth + pairing ───────────────────────────────────────────────
def _session_router():
    return ApiRouter(
        FakeBackend(),
        TOKEN,
        session_authorizer=lambda t: t == "good-session",
        pair_handler=lambda code: "good-session" if code == "123456" else None,
    )


def test_valid_session_token_is_accepted() -> None:
    resp = _session_router().handle("GET", "/status", {"Authorization": "Bearer good-session"})
    assert resp.status == 200


def test_invalid_session_token_is_rejected() -> None:
    resp = _session_router().handle("GET", "/status", {"Authorization": "Bearer bad-session"})
    assert resp.status == 401


def test_pair_exchanges_code_for_session() -> None:
    resp = _session_router().handle("POST", "/pair", body=_body({"code": "123456"}))
    assert resp.status == 200
    assert resp.body["session"] == "good-session"


def test_pair_rejects_bad_code() -> None:
    assert _session_router().handle("POST", "/pair", body=_body({"code": "000000"})).status == 401


def test_pair_is_unauthenticated() -> None:
    # No Authorization header at all, still reaches the pair handler.
    assert _session_router().handle("POST", "/pair", body=_body({"code": "123456"})).status == 200


def test_pair_unavailable_without_handler() -> None:
    assert _router().handle("POST", "/pair", AUTH, _body({"code": "123456"})).status == 404


def test_revoked_sessions_lose_api_access() -> None:
    # End-to-end with a real PairingManager: pairing grants access; "Disconnect
    # all phones" (revoke_all) takes it away again.
    from app.local_api.pairing import PairingManager

    pairing = PairingManager()
    router = ApiRouter(
        FakeBackend(),
        TOKEN,
        session_authorizer=pairing.is_valid_session,
        pair_handler=pairing.pair,
    )
    session = router.handle("POST", "/pair", body=_body({"code": pairing.new_code()})).body["session"]
    auth = {"Authorization": f"Bearer {session}"}
    assert router.handle("GET", "/status", auth).status == 200
    assert pairing.session_count() == 1

    pairing.revoke_all()
    assert router.handle("GET", "/status", auth).status == 401
    assert pairing.session_count() == 0


# ── PC hub modes ─────────────────────────────────────────────────────────
def test_pc_mode_triggers_backend() -> None:
    backend = FakeBackend()
    resp = ApiRouter(backend, TOKEN).handle("POST", "/pc-mode", AUTH, _body({"mode": "music"}))
    assert resp.status == 200
    assert resp.body["mode"] == "music"
    assert ("pc_mode", "music") in backend.calls


def test_pc_mode_off_stops() -> None:
    backend = FakeBackend()
    resp = ApiRouter(backend, TOKEN).handle("POST", "/pc-mode", AUTH, _body({"mode": "off"}))
    assert resp.status == 200
    assert ("pc_mode", "off") in backend.calls


def test_pc_mode_rejects_unknown() -> None:
    assert _router().handle("POST", "/pc-mode", AUTH, _body({"mode": "laser"})).status == 400
    assert _router().handle("POST", "/pc-mode", AUTH, _body({})).status == 400


def test_pc_mode_returns_409_when_it_cannot_start() -> None:
    # Valid mode, but the desktop refused to start it (Free licence / no strip).
    backend = FakeBackend()
    backend.pc_mode_starts = False
    resp = ApiRouter(backend, TOKEN).handle("POST", "/pc-mode", AUTH, _body({"mode": "music"}))
    assert resp.status == 409
    assert "error" in resp.body


# ── scenes ───────────────────────────────────────────────────────────────
def test_scenes_save_list_apply_delete_flow() -> None:
    backend = FakeBackend()
    router = ApiRouter(backend, TOKEN)

    saved = router.handle("POST", "/scenes/save", AUTH, _body({"name": "Movie"}))
    assert saved.status == 200
    scene_id = saved.body["scene"]["scene_id"]

    listed = router.handle("GET", "/scenes", AUTH)
    assert listed.status == 200
    assert [s["name"] for s in listed.body["scenes"]] == ["Movie"]

    applied = router.handle("POST", "/scenes/apply", AUTH, _body({"scene_id": scene_id}))
    assert applied.status == 200
    assert applied.body["report"]["applied"] == ["power"]

    deleted = router.handle("POST", "/scenes/delete", AUTH, _body({"scene_id": scene_id}))
    assert deleted.status == 200
    assert router.handle("GET", "/scenes", AUTH).body["scenes"] == []


def test_scene_save_requires_a_name() -> None:
    assert _router().handle("POST", "/scenes/save", AUTH, _body({})).status == 400


def test_apply_unknown_scene_is_404() -> None:
    assert _router().handle("POST", "/scenes/apply", AUTH, _body({"scene_id": "nope"})).status == 404


def test_delete_unknown_scene_is_404() -> None:
    assert _router().handle("POST", "/scenes/delete", AUTH, _body({"scene_id": "nope"})).status == 404


def test_scenes_require_auth() -> None:
    assert _router().handle("GET", "/scenes").status == 401


def test_the_combined_screen_mode_is_accepted_by_the_phone() -> None:
    """The router is the gate: a mode it does not know is refused before it ever
    reaches the desktop, so the phone silently cannot ask for it."""
    from app.local_api.router import _PC_MODES

    assert "screen_music" in _PC_MODES
    assert "screen" in _PC_MODES


def test_the_phone_offers_the_combined_mode_with_a_label() -> None:
    """A mode the API accepts and the page has no button for is a mode nobody
    can reach from a phone."""
    from app.local_api.mobile_page import build_mobile_page

    page = build_mobile_page()

    assert '"screen_music"' in page, "the phone has no button for the combined mode"
    assert "Screen + music" in page, "the button has no label"
