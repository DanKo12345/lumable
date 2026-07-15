"""Local API settings: validation, token generation, and — most importantly —
the safe default of binding to loopback only.

Home Assistant and other tools often run on a *different* machine, so users will
be tempted to expose the API on the LAN. That's an explicit, opt-in, clearly
dangerous choice: it requires both a flag AND a specific local IP. Anything less
falls back to 127.0.0.1 so the API is never reachable off-box by accident.
"""

from __future__ import annotations

import secrets
import socket
from typing import Any

from app.local_api.server import DEFAULT_PORT, LOOPBACK

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def validate_api_settings(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    try:
        port = int(data.get("port", DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    if not 1 <= port <= 65535:
        port = DEFAULT_PORT
    return {
        "enabled": bool(data.get("enabled", False)),
        "port": port,
        "token": str(data.get("token", "") or "").strip(),
        "allow_lan": bool(data.get("allow_lan", False)),
        "lan_host": str(data.get("lan_host", "") or "").strip(),
    }


def resolve_bind_host(config: dict[str, Any]) -> str:
    """The address the server should bind to.

    Loopback unless LAN access is explicitly enabled AND a concrete, non-loopback
    host is provided. An empty (or loopback/0.0.0.0) LAN host stays on 127.0.0.1
    — we never bind all interfaces implicitly.
    """
    if config.get("allow_lan"):
        host = str(config.get("lan_host") or "").strip()
        if host and host not in _LOOPBACK_HOSTS:
            return host
    return LOOPBACK


def is_loopback(host: str) -> bool:
    return str(host or "").strip() in {"127.0.0.1", "localhost", "::1"}


def detect_lan_ip() -> str:
    """Best-effort primary LAN IPv4 of this machine, or "" if offline.

    Sends nothing on the wire — a UDP ``connect`` just makes the OS choose the
    outbound interface, whose local address is this PC's LAN IP. Lets the app
    fill the LAN field automatically so the user never has to run ipconfig.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = str(sock.getsockname()[0])
    except OSError:
        return ""
    finally:
        sock.close()
    return "" if is_loopback(ip) else ip
