"""Pure, socket-free request router for the LumaBLE local API.

Everything HTTP-specific (sockets, threads) lives elsewhere; this module just
turns a (method, path, headers, body) request into a (status, json) response.
That keeps the whole surface — auth, size limits, validation, routing — testable
without opening a port.

Design notes (v1):
- 127.0.0.1 by default; the server layer enforces the bind address.
- Bearer-token auth on everything except ``GET /health`` (a version probe).
- Commands are idempotent — ``POST /power {"on": true}``, never a toggle — so
  automations are safe to retry.
- ``device_id`` is optional: omit it to address the whole group, include it to
  target one strip (the backend decides how to apply it).
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

API_VERSION = 1
MAX_BODY_BYTES = 64 * 1024  # generous for JSON commands, small enough to be safe

_KNOWN_ROUTES: dict[str, set[str]] = {
    "/health": {"GET"},
    "/status": {"GET"},
    "/devices": {"GET"},
    "/power": {"POST"},
    "/color": {"POST"},
    "/brightness": {"POST"},
    "/effect": {"POST"},
    "/quick-mode": {"POST"},
    "/pc-mode": {"POST"},
    "/scenes": {"GET"},
    "/scenes/save": {"POST"},
    "/scenes/apply": {"POST"},
    "/scenes/delete": {"POST"},
}

# PC "hub" modes the phone can trigger (plus "off" to stop and return to manual).
_PC_MODES = {"screen", "screen_music", "music", "effect", "diy", "off"}


@dataclass
class ApiResponse:
    status: int
    body: dict[str, Any]


@runtime_checkable
class ApiBackend(Protocol):
    """What the router needs from the app. The real adapter marshals these onto
    the Qt main thread; tests use a plain fake."""

    def app_version(self) -> str: ...
    def status(self) -> dict[str, Any]: ...
    def devices(self) -> list[dict[str, Any]]: ...
    def set_power(self, on: bool, device_id: str | None) -> None: ...
    def set_color(self, red: int, green: int, blue: int, device_id: str | None) -> None: ...
    def set_brightness(self, value: int, device_id: str | None) -> None: ...
    def set_effect(self, code: int, speed: int | None, device_id: str | None) -> None: ...
    def apply_quick_mode(self, key: str) -> bool: ...
    def set_pc_mode(self, mode: str) -> bool: ...
    def list_scenes(self) -> list[dict[str, Any]]: ...
    def save_scene(self, name: str) -> dict[str, Any] | None: ...
    def apply_scene(self, scene_id: str) -> dict[str, Any] | None: ...
    def delete_scene(self, scene_id: str) -> bool: ...


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


class ApiRouter:
    def __init__(
        self,
        backend: ApiBackend,
        token: str,
        *,
        session_authorizer: Callable[[str], bool] | None = None,
        pair_handler: Callable[[str], str | None] | None = None,
    ) -> None:
        self._backend = backend
        self._token = str(token or "")
        self._session_authorizer = session_authorizer
        self._pair_handler = pair_handler

    # ── entry point ───────────────────────────────────────────────────
    def handle(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> ApiResponse:
        method = (method or "").upper()
        path = self._normalize_path(path)
        headers = self._lower_headers(headers)

        # "/" and "/health" are unauthenticated so clients can discover us; the
        # index also lists the endpoints as a tiny built-in reference.
        if method == "GET" and path in ("/", "/health"):
            body = {
                "name": "LumaBLE",
                "api_version": API_VERSION,
                "app_version": self._backend.app_version(),
            }
            if path == "/":
                body["endpoints"] = {
                    "GET /health": "version probe (no auth)",
                    "GET /status": "current strip state",
                    "GET /devices": "connected controllers",
                    "GET /events": "live status stream (SSE)",
                    "POST /power": "{on: true|false}",
                    "POST /color": "{r, g, b}",
                    "POST /brightness": "{value: 0-100}",
                    "POST /effect": "{code, speed?}",
                    "POST /quick-mode": "{key}",
                    "POST /pc-mode": "{mode: screen|music|effect|diy|off}",
                    "GET /scenes": "saved scenes",
                    "POST /scenes/save": "{name} — snapshot current state",
                    "POST /scenes/apply": "{scene_id}",
                    "POST /scenes/delete": "{scene_id}",
                }
                body["auth"] = "Send 'Authorization: Bearer <token>' on every request except /health and /."
            return ApiResponse(200, body)

        # Pairing is how a phone earns a session token, so it can't require one.
        if path == "/pair" and method == "POST":
            return self._handle_pair(body)

        allowed = _KNOWN_ROUTES.get(path)
        if allowed is None:
            return ApiResponse(404, {"error": "not found"})

        if not self._authorized(headers):
            return ApiResponse(401, {"error": "unauthorized"})

        if method not in allowed:
            return ApiResponse(405, {"error": "method not allowed"})

        if body is not None and len(body) > MAX_BODY_BYTES:
            return ApiResponse(413, {"error": "request too large"})

        if method == "GET":
            return self._handle_get(path)
        return self._handle_post(path, body)

    # ── GET ───────────────────────────────────────────────────────────
    def _handle_get(self, path: str) -> ApiResponse:
        if path == "/status":
            return ApiResponse(200, dict(self._backend.status()))
        if path == "/devices":
            return ApiResponse(200, {"devices": list(self._backend.devices())})
        if path == "/scenes":
            return ApiResponse(200, {"scenes": list(self._backend.list_scenes())})
        return ApiResponse(404, {"error": "not found"})

    # ── POST ──────────────────────────────────────────────────────────
    def _handle_post(self, path: str, body: bytes | None) -> ApiResponse:
        data, error = self._parse_json(body)
        if error is not None:
            return ApiResponse(400, {"error": error})
        device_id = self._device_id(data)

        if path == "/power":
            if not isinstance(data.get("on"), bool):
                return ApiResponse(400, {"error": "'on' must be true or false"})
            self._backend.set_power(bool(data["on"]), device_id)
            return ApiResponse(200, {"ok": True})

        if path == "/color":
            rgb, error = self._read_rgb(data)
            if error is not None:
                return ApiResponse(400, {"error": error})
            self._backend.set_color(rgb[0], rgb[1], rgb[2], device_id)
            return ApiResponse(200, {"ok": True})

        if path == "/brightness":
            value, error = self._read_int(data, "value", 0, 100)
            if error is not None:
                return ApiResponse(400, {"error": error})
            self._backend.set_brightness(value, device_id)
            return ApiResponse(200, {"ok": True})

        if path == "/effect":
            code, error = self._read_int(data, "code", 0, 255)
            if error is not None:
                return ApiResponse(400, {"error": error})
            speed: int | None = None
            if data.get("speed") is not None:
                speed, error = self._read_int(data, "speed", 0, 100)
                if error is not None:
                    return ApiResponse(400, {"error": error})
            self._backend.set_effect(code, speed, device_id)
            return ApiResponse(200, {"ok": True})

        if path == "/quick-mode":
            key = data.get("key")
            if not isinstance(key, str) or not key.strip():
                return ApiResponse(400, {"error": "'key' is required"})
            if not self._backend.apply_quick_mode(key.strip()):
                return ApiResponse(404, {"error": "unknown quick mode"})
            return ApiResponse(200, {"ok": True})

        if path == "/pc-mode":
            mode = data.get("mode")
            if not isinstance(mode, str) or mode.strip().lower() not in _PC_MODES:
                return ApiResponse(400, {"error": "'mode' must be one of screen, music, effect, diy, off"})
            normalized = mode.strip().lower()
            if not self._backend.set_pc_mode(normalized):
                # The mode is valid but didn't start — e.g. needs Pro, or no strip
                # is connected. Report a conflict, not a success.
                return ApiResponse(409, {"error": "mode could not start (needs Pro or a connected strip)"})
            return ApiResponse(200, {"ok": True, "mode": normalized})

        scene_response = self._handle_scene_post(path, data)
        if scene_response is not None:
            return scene_response

        return ApiResponse(404, {"error": "not found"})

    def _handle_scene_post(self, path: str, data: dict[str, Any]) -> ApiResponse | None:
        if path == "/scenes/save":
            name = data.get("name")
            if not isinstance(name, str) or not name.strip():
                return ApiResponse(400, {"error": "'name' is required"})
            scene = self._backend.save_scene(name.strip())
            if scene is None:
                return ApiResponse(400, {"error": "scene could not be saved"})
            return ApiResponse(200, {"scene": scene})

        if path == "/scenes/apply":
            scene_id = data.get("scene_id")
            if not isinstance(scene_id, str) or not scene_id.strip():
                return ApiResponse(400, {"error": "'scene_id' is required"})
            report = self._backend.apply_scene(scene_id.strip())
            if report is None:
                return ApiResponse(404, {"error": "scene not found"})
            return ApiResponse(200, {"ok": True, "report": report})

        if path == "/scenes/delete":
            scene_id = data.get("scene_id")
            if not isinstance(scene_id, str) or not scene_id.strip():
                return ApiResponse(400, {"error": "'scene_id' is required"})
            if not self._backend.delete_scene(scene_id.strip()):
                return ApiResponse(404, {"error": "scene not found"})
            return ApiResponse(200, {"ok": True})

        return None

    def authorize(self, headers: dict[str, str] | None) -> bool:
        """Public auth check for raw request headers (used by the SSE stream,
        which bypasses the normal request/response path)."""
        return self._authorized(self._lower_headers(headers))

    # ── helpers ───────────────────────────────────────────────────────
    def _authorized(self, headers: dict[str, str]) -> bool:
        header = headers.get("authorization", "")
        prefix = "bearer "
        if not header.lower().startswith(prefix):
            return False
        presented = header[len(prefix):].strip()
        if not presented:
            return False
        # The full app token, or a valid short-lived phone session token.
        if self._token and hmac.compare_digest(presented, self._token):
            return True
        return bool(self._session_authorizer is not None and self._session_authorizer(presented))

    def _handle_pair(self, body: bytes | None) -> ApiResponse:
        if self._pair_handler is None:
            return ApiResponse(404, {"error": "pairing not available"})
        if body is not None and len(body) > MAX_BODY_BYTES:
            return ApiResponse(413, {"error": "request too large"})
        data, error = self._parse_json(body)
        if error is not None:
            return ApiResponse(400, {"error": error})
        token = self._pair_handler(str(data.get("code", "")))
        if not token:
            return ApiResponse(401, {"error": "invalid or expired code"})
        return ApiResponse(200, {"session": token})

    @staticmethod
    def _normalize_path(path: str) -> str:
        path = (path or "").split("?", 1)[0].split("#", 1)[0]
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        return path or "/"

    @staticmethod
    def _lower_headers(headers: dict[str, str] | None) -> dict[str, str]:
        if not headers:
            return {}
        return {str(k).lower(): str(v) for k, v in headers.items()}

    @staticmethod
    def _parse_json(body: bytes | None) -> tuple[dict[str, Any], str | None]:
        if not body:
            return {}, None  # empty body is an empty command object
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}, "invalid JSON body"
        if not isinstance(data, dict):
            return {}, "JSON body must be an object"
        return data, None

    @staticmethod
    def _device_id(data: dict[str, Any]) -> str | None:
        value = data.get("device_id")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _read_int(self, data: dict[str, Any], key: str, low: int, high: int) -> tuple[int, str | None]:
        if key not in data:
            return 0, f"'{key}' is required"
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0, f"'{key}' must be a number"
        return _clamp(int(value), low, high), None

    def _read_rgb(self, data: dict[str, Any]) -> tuple[tuple[int, int, int], str | None]:
        channels: list[int] = []
        for key in ("r", "g", "b"):
            value, error = self._read_int(data, key, 0, 255)
            if error is not None:
                return (0, 0, 0), error
            channels.append(value)
        return (channels[0], channels[1], channels[2]), None
