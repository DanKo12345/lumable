"""Pure, Qt-free core for LumaBLE scenes.

A *scene* is one saved light state that every surface — the PC UI, the phone
remote, hotkeys and the Local API — can trigger through a single model, instead
of each re-implementing "set this look". The design notes (0.3.2 Scenes
Foundation, extended with targets in 0.3.3):

- **Optional state fields.** A field that is ``None`` means "leave it as it is",
  distinct from a field set to a value ("apply this"). So a "dim everything"
  scene can carry only ``brightness`` and touch nothing else.
- **Tagged effect.** ``effect`` is a small union ``{kind, ref, speed}`` where
  ``kind`` is ``firmware`` (ref = int code), ``software`` (ref = key) or ``diy``
  (ref = effect id). One int can't stand in for three incompatible subsystems.
- **Stable targets.** A scene points at ``primary`` / ``all`` / a ``group_id``
  (a stable id, never a display name), so renames don't break saved scenes.
- **Capability-aware apply.** :func:`plan_apply` turns a scene's state + a target
  capability map into an ordered, best-effort action list plus a report of the
  fields it had to skip (e.g. no CCT hardware). It never raises and never does
  "all or nothing".
- **Versioned + validated.** Scenes round-trip through a versioned envelope with
  a checksum and are normalised defensively on read, because they live for years
  in profiles and shared codes.

This module is intentionally free of Qt and any I/O so it stays trivially
testable; the store and the (main-thread) apply service build on top of it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from typing import Any

from app.screen_profiles import PROFILE_IDS

SCENE_TYPE = "scene"
# v2: scenes default to targeting *all* connected strips. In v1 the target field
# existed but was never honoured (every scene applied to everything), so a stored
# v1 target was not a real user choice — see _migrate.
# v3: pc_mode serialises as an object {kind, preset} instead of a bare string.
# The bump matters for forward-compat: an older build that only knows up to v2
# must *reject* a v3 envelope, not accept it and choke on the dict pc_mode.
# v4: "screen_music" joins the pc_mode kinds. Bumped for the same reason: an
# older build does not know the mode and would apply the scene as though it had
# no PC mode at all, quietly lighting the strip in a way nobody saved.
SCENE_VERSION = 4
SHARE_PREFIX = "LUMASCENE1-"

EFFECT_KINDS = frozenset({"firmware", "software", "diy"})
TARGET_KINDS = frozenset({"primary", "all", "group"})
PC_MODES = frozenset({"screen", "screen_music", "music", "effect", "diy"})

_MAX_NAME = 40
_MAX_ICON = 32
_CCT_MIN, _CCT_MAX = 1000, 10000

# Canonical application order. Streams are stopped first (by the apply service),
# then the light state is set, and a PC mode — if any — is started last so it
# takes ownership of the strip after the base look is in place.
STATE_FIELDS = ("power", "rgb", "cct", "brightness", "effect", "pc_mode")


def new_scene_id() -> str:
    return uuid.uuid4().hex[:12]


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _norm_hex(raw: Any) -> str:
    text = str(raw or "").strip()
    if len(text) == 7 and text[0] == "#":
        try:
            int(text[1:], 16)
            return text.upper()
        except ValueError:
            return ""
    return ""


def _norm_rgb(raw: Any) -> list[int] | None:
    if isinstance(raw, dict) and all(k in raw for k in ("r", "g", "b")):
        raw = [raw["r"], raw["g"], raw["b"]]
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    return [_clamp(raw[0], 0, 255, 0), _clamp(raw[1], 0, 255, 0), _clamp(raw[2], 0, 255, 0)]


def _norm_effect(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind not in EFFECT_KINDS:
        return None
    ref = raw.get("ref")
    if kind == "firmware":
        try:
            ref = max(0, min(255, int(ref)))
        except (TypeError, ValueError):
            return None
    else:
        ref = str(ref or "").strip()
        if not ref:
            return None
    speed = raw.get("speed")
    if speed is not None:
        speed = _clamp(speed, 0, 100, 50)
    return {"kind": kind, "ref": ref, "speed": speed}


def _norm_target(raw: Any) -> dict[str, Any]:
    # "all" is the default: a scene the user saved without picking a target should
    # keep doing what it always did — drive every connected strip.
    if not isinstance(raw, dict):
        return {"kind": "all", "group_id": None}
    kind = raw.get("kind")
    if kind not in TARGET_KINDS:
        kind = "all"
    group_id = raw.get("group_id")
    group_id = str(group_id).strip() if group_id else None
    if kind == "group" and not group_id:
        kind = "all"  # a group target with no id is meaningless
    return {"kind": kind, "group_id": group_id if kind == "group" else None}


def _norm_state(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    power = raw.get("power")
    cct = _clamp(raw["cct"], _CCT_MIN, _CCT_MAX, _CCT_MIN) if raw.get("cct") is not None else None
    brightness = _clamp(raw["brightness"], 0, 100, 100) if raw.get("brightness") is not None else None
    return {
        "power": bool(power) if isinstance(power, bool) else None,
        "rgb": _norm_rgb(raw["rgb"]) if raw.get("rgb") is not None else None,
        "cct": cct,
        "brightness": brightness,
        "effect": _norm_effect(raw["effect"]) if raw.get("effect") is not None else None,
        "pc_mode": _norm_pc_mode(raw.get("pc_mode")),
    }


def _norm_pc_mode(raw: Any) -> dict[str, Any] | None:
    """Canonical PC-mode: ``None`` or ``{"kind": <mode>, "preset": <id|None>}``.

    Accepts the legacy bare-string form (``"screen"``) from scenes saved before
    0.3.4 — it becomes ``{"kind": "screen", "preset": None}``. ``preset`` is a
    stable id (e.g. a screen-sync profile) so a saved scene restores not just the
    mode but the exact look. ``target`` is deliberately dropped: the streaming
    backend is global, so a per-strip target would be a lie.
    """
    if isinstance(raw, str):
        raw = {"kind": raw}
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in PC_MODES:
        return None
    preset = raw.get("preset")
    preset = str(preset).strip() if isinstance(preset, str) and preset.strip() else None
    # Only the screen modes have presets, and only the known profiles are valid.
    # An unknown preset degrades to None (use the current profile) rather than
    # silently resolving to Desktop later — honest degradation, not a lie.
    if kind in ("screen", "screen_music"):
        if preset not in PROFILE_IDS:
            preset = None
    else:
        preset = None
    return {"kind": kind, "preset": preset}


def normalize_scene(raw: Any) -> dict[str, Any] | None:
    """Coerce any dict into a valid, canonical scene (safe defaults, clamped
    ranges, a generated id if missing). Returns ``None`` only for non-dict input,
    so a corrupt-but-shaped JSON blob degrades gracefully instead of crashing."""
    if not isinstance(raw, dict):
        return None
    return {
        "scene_id": (str(raw.get("scene_id") or "").strip() or new_scene_id()),
        "name": str(raw.get("name") or "").strip()[:_MAX_NAME],
        "icon": str(raw.get("icon") or "").strip()[:_MAX_ICON],
        "color": _norm_hex(raw.get("color")),
        "target": _norm_target(raw.get("target")),
        "state": _norm_state(raw.get("state")),
    }


def make_scene(
    name: str,
    state: dict[str, Any],
    *,
    target: dict[str, Any] | None = None,
    icon: str = "",
    color: str = "",
    scene_id: str | None = None,
) -> dict[str, Any]:
    """Build a normalised scene from parts (generates an id when not given)."""
    scene = normalize_scene(
        {
            "scene_id": scene_id,
            "name": name,
            "icon": icon,
            "color": color,
            "target": target,
            "state": state,
        }
    )
    assert scene is not None  # input is always a dict here
    return scene


# ── storage envelope (versioned + checksummed) ────────────────────────────
def _checksum(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _migrate(payload: Any, version: int) -> Any:
    """Bring an older stored scene up to the current schema.

    v1 -> v2: the target field existed but was ignored (every scene drove all
    strips), so its stored value was never a deliberate choice. Rewrite any
    legacy target to ``all`` so updating LumaBLE doesn't silently narrow existing
    scenes to one strip. Only scenes saved after the target selector exists carry
    a real ``primary``/``group`` choice.

    v2 -> v3: ``pc_mode`` changed from a bare string to a ``{kind, preset}``
    object so a screen-sync scene can restore its exact profile.

    v3 -> v4: ``screen_music`` became a mode of its own. Nothing stored needs
    changing — a scene saved as ``screen`` still means the screen alone — so the
    bump exists only so an older build refuses a scene it cannot honour.
    """
    if not isinstance(payload, dict):
        return payload
    if version < 2:
        payload = {**payload, "target": {"kind": "all", "group_id": None}}
    if version < 3:
        # pc_mode was a bare string; carry it into the {kind, preset} object.
        # (normalize_scene also accepts the string, but migrating explicitly
        # keeps the stored shape honest.)
        state = payload.get("state")
        if isinstance(state, dict) and isinstance(state.get("pc_mode"), str):
            kind = state["pc_mode"].strip().lower()
            payload = {
                **payload,
                "state": {**state, "pc_mode": ({"kind": kind, "preset": None} if kind else None)},
            }
    return payload


def wrap_scene(scene: dict[str, Any]) -> dict[str, Any]:
    """Wrap a scene for on-disk storage: type + version + payload + checksum."""
    normalized = normalize_scene(scene) or {}
    return {
        "type": SCENE_TYPE,
        "version": SCENE_VERSION,
        "payload": normalized,
        "checksum": _checksum(normalized),
    }


def is_future_scene_envelope(data: Any) -> bool:
    """Whether this is an intact scene written by a newer application.

    It cannot be displayed or applied safely, but it must survive a settings
    round-trip unchanged. Otherwise merely opening an older build turns
    "unknown for now" into permanent data loss.
    """
    if not isinstance(data, dict) or data.get("type") != SCENE_TYPE:
        return False
    version = data.get("version")
    stored = data.get("payload")
    checksum = data.get("checksum")
    return bool(
        isinstance(version, int)
        and version > SCENE_VERSION
        and isinstance(stored, dict)
        and isinstance(checksum, str)
        and checksum
        and _checksum(stored) == checksum
    )


def unwrap_scene(data: Any) -> dict[str, Any] | None:
    """Read a stored envelope back to a scene, or ``None`` if it is the wrong
    type, a newer version, or fails its checksum. The checksum is **mandatory**
    for this format: a missing or non-matching one is treated as corruption."""
    if not isinstance(data, dict) or data.get("type") != SCENE_TYPE:
        return None
    version = data.get("version")
    if not isinstance(version, int) or version < 1 or version > SCENE_VERSION:
        return None
    stored = data.get("payload")
    checksum = data.get("checksum")
    if not isinstance(checksum, str) or not checksum or not isinstance(stored, dict):
        return None
    # Verify integrity against what was actually written, *then* migrate — a
    # migrated payload would never match the stored checksum.
    if _checksum(stored) != checksum:
        return None
    return normalize_scene(_migrate(stored, version))


# ── portable share code (distinct sentinel, not a DIY effect) ─────────────
def encode_scene(scene: dict[str, Any]) -> str:
    """Encode a scene to a portable ``LUMASCENE1-<base64>`` code."""
    payload = {"t": SCENE_TYPE, "v": SCENE_VERSION, "scene": normalize_scene(scene) or {}}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return SHARE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def decode_scene(code: str) -> dict[str, Any] | None:
    """Decode a shared scene code back to a scene, or ``None`` if invalid."""
    if not isinstance(code, str) or not code.strip().startswith(SHARE_PREFIX):
        return None
    body = code.strip()[len(SHARE_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(body.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("t") != SCENE_TYPE:
        return None
    version = payload.get("v")
    if not isinstance(version, int) or version < 1 or version > SCENE_VERSION:
        return None
    return normalize_scene(_migrate(payload.get("scene"), version))


# ── capability-aware apply planning ───────────────────────────────────────
def _supports(capabilities: dict[str, Any] | None, name: str, default: bool) -> bool:
    value = (capabilities or {}).get(name)
    return default if value is None else bool(value)


def plan_apply(state: dict[str, Any], capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn a scene's ``state`` + a target's capabilities into an ordered,
    best-effort plan.

    Returns ``{"actions": [...], "skipped": [...]}``. Only fields present in the
    scene are considered; a present field the target can't do (e.g. ``cct`` on a
    plain RGB strip) is reported in ``skipped`` with a reason, never silently
    dropped and never a hard failure. Actions come out in canonical order so a
    PC ``pc_mode`` starts after the base light state is set.
    """
    state = state if isinstance(state, dict) else {}
    actions: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    if isinstance(state.get("power"), bool):
        actions.append({"op": "power", "on": state["power"]})

    rgb = state.get("rgb")
    if rgb is not None:
        if _supports(capabilities, "rgb", True):
            actions.append({"op": "color", "rgb": list(rgb)})
        else:
            skipped.append({"field": "rgb", "reason": "unsupported"})

    cct = state.get("cct")
    if cct is not None:
        if _supports(capabilities, "cct", False):  # most cheap strips have no white channel
            actions.append({"op": "cct", "value": cct})
        else:
            skipped.append({"field": "cct", "reason": "unsupported"})

    brightness = state.get("brightness")
    if brightness is not None:
        actions.append({"op": "brightness", "value": brightness})

    effect = state.get("effect")
    if effect is not None:
        kind = effect.get("kind")
        if kind == "firmware" and not _supports(capabilities, "firmware_effects", True):
            skipped.append({"field": "effect", "reason": "unsupported"})
        elif kind == "firmware" and effect.get("speed") is not None and not _supports(capabilities, "effect_speed", True):
            # The effect itself is supported but its speed control isn't (e.g. a
            # BanlanX variant without speed): run the effect, drop the speed.
            actions.append({"op": "effect", "effect": {**effect, "speed": None}})
            skipped.append({"field": "effect_speed", "reason": "unsupported"})
        else:
            actions.append({"op": "effect", "effect": effect})

    pc_mode = state.get("pc_mode")
    if isinstance(pc_mode, dict) and pc_mode.get("kind"):
        actions.append({"op": "pc_mode", "mode": pc_mode["kind"], "preset": pc_mode.get("preset")})
    elif isinstance(pc_mode, str) and pc_mode:  # tolerate a raw plan input
        actions.append({"op": "pc_mode", "mode": pc_mode, "preset": None})

    return {"actions": actions, "skipped": skipped}
