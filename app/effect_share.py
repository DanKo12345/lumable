from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from app.diy_effects import MAX_STEPS, MOTION_KEYS

# A shareable DIY effect is encoded as ``LUMA1-<base64>`` where the base64 body is
# a compact JSON payload. The short prefix lets us recognise (and version) codes
# pasted from chat/email, and keeps the format portable across machines without
# any server. Import is defensive: anything malformed decodes to ``None`` rather
# than raising, so a bad paste never crashes the app.

SHARE_PREFIX = "LUMA1-"
_KIND = "diy"
_VERSION = 1

_MOTIONS = frozenset(MOTION_KEYS)
_MAX_MS = 10_000


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _clean_steps(raw: Any) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return steps
    for item in raw[:MAX_STEPS]:
        if not isinstance(item, dict):
            continue
        rgb = item.get("rgb", [255, 255, 255])
        if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
            rgb = [255, 255, 255]
        motion = item.get("motion", "none")
        if motion not in _MOTIONS:
            motion = "none"
        steps.append({
            "rgb": [_clamp(rgb[0], 0, 255, 255), _clamp(rgb[1], 0, 255, 255), _clamp(rgb[2], 0, 255, 255)],
            "duration_ms": _clamp(item.get("duration_ms"), 0, _MAX_MS, 1000),
            "motion": motion,
        })
    return steps


def encode_effect(effect: dict[str, Any]) -> str:
    """Encode a DIY effect (name/steps/transition/speed) to a ``LUMA1-`` code."""
    payload = {
        "t": _KIND,
        "v": _VERSION,
        "name": str(effect.get("name", ""))[:40],
        "transition": "cut" if str(effect.get("transition", "smooth")) == "cut" else "smooth",
        "speed": _clamp(effect.get("speed"), 0, 100, 50),
        "steps": [
            {"rgb": s["rgb"], "duration_ms": s["duration_ms"], "motion": s["motion"]}
            for s in _clean_steps(effect.get("steps"))
        ],
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return SHARE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def decode_effect(code: str) -> dict[str, Any] | None:
    """Decode a shared code back to a DIY effect dict, or ``None`` if invalid.

    The returned dict matches the saved-library schema: ``name``, ``steps``
    (each ``rgb``/``duration_ms``/``motion``), ``transition`` and ``speed``.
    """
    if not isinstance(code, str):
        return None
    text = code.strip()
    if not text.startswith(SHARE_PREFIX):
        return None
    body = text[len(SHARE_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(body.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("t") != _KIND or payload.get("v") != _VERSION:
        return None
    steps = _clean_steps(payload.get("steps"))
    if len(steps) < 2:
        return None
    return {
        "name": str(payload.get("name", ""))[:40],
        "steps": steps,
        "transition": "cut" if str(payload.get("transition", "smooth")) == "cut" else "smooth",
        "speed": _clamp(payload.get("speed"), 0, 100, 50),
    }
