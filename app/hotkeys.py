from __future__ import annotations

from dataclasses import dataclass

# Pure, OS-agnostic hotkey model: parse "Ctrl+Alt+L" specs into a normalized
# Hotkey, and translate them into the modifier bitmask / virtual-key code that
# the Windows RegisterHotKey layer needs. No Qt or win32 here, so it's fully
# unit-testable; the actual registration lives in hotkey_controller.py.

# Actions a global hotkey can trigger.
ACTIONS: tuple[str, ...] = (
    "toggle_power",
    "brightness_up",
    "brightness_down",
    "next_scene",
    "prev_scene",
)

# Sensible defaults — short two-key combos (one modifier) for convenience.
# Avoid Ctrl+Alt+Arrows (rotates the screen on Intel graphics) and OS shortcuts.
DEFAULT_HOTKEYS: dict[str, str] = {
    "toggle_power": "Alt+L",
    "brightness_up": "Alt+PageUp",
    "brightness_down": "Alt+PageDown",
    "next_scene": "Alt+N",
    "prev_scene": "Alt+B",
}

# Windows RegisterHotKey modifier flags.
_WIN_MOD = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}

# Canonical modifier display order.
_MOD_ORDER = ("ctrl", "alt", "shift", "win")
_MOD_LABEL = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}

_MOD_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt",
    "shift": "shift",
    "win": "win", "meta": "win", "super": "win", "cmd": "win", "command": "win",
}

_NAMED_VK = {
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "SPACE": 0x20, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "INSERT": 0x2D, "DELETE": 0x2E,
}


@dataclass(frozen=True)
class Hotkey:
    mods: frozenset[str]
    key: str  # normalized: "A".."Z", "0".."9", "F1".."F12", or a named key


def _normalize_key(token: str) -> str | None:
    token = token.strip().upper()
    if not token:
        return None
    if len(token) == 1 and (token.isalpha() or token.isdigit()):
        return token
    if token in _NAMED_VK:
        return token
    if token.startswith("F") and token[1:].isdigit():
        if 1 <= int(token[1:]) <= 12:
            return token
    return None


def parse_hotkey(spec: str) -> Hotkey | None:
    """Parse a spec like "Ctrl+Alt+L" into a Hotkey, or None if it's invalid."""
    if not isinstance(spec, str) or not spec.strip():
        return None
    parts = [p for p in (piece.strip() for piece in spec.split("+")) if p]
    if not parts:
        return None
    mods: set[str] = set()
    key: str | None = None
    for part in parts:
        alias = _MOD_ALIASES.get(part.lower())
        if alias is not None:
            mods.add(alias)
            continue
        normalized = _normalize_key(part)
        if normalized is None:
            return None
        if key is not None:
            return None  # more than one non-modifier key
        key = normalized
    if key is None:
        return None
    return Hotkey(mods=frozenset(mods), key=key)


def key_to_vk(key: str) -> int | None:
    """Virtual-key code for a normalized key, or None if unmapped."""
    key = key.upper()
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return ord(key)  # VK_A..VK_Z / VK_0..VK_9 match ASCII upper
    if key in _NAMED_VK:
        return _NAMED_VK[key]
    if key.startswith("F") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 12:
            return 0x70 + (n - 1)  # VK_F1 = 0x70
    return None


def to_win_modifiers(mods: frozenset[str]) -> int:
    flags = 0
    for mod in mods:
        flags |= _WIN_MOD.get(mod, 0)
    return flags


def format_hotkey(hotkey: Hotkey) -> str:
    """Canonical display string, e.g. "Ctrl+Alt+L"."""
    ordered = [_MOD_LABEL[m] for m in _MOD_ORDER if m in hotkey.mods]
    ordered.append(hotkey.key if len(hotkey.key) == 1 or hotkey.key.startswith("F") else hotkey.key.title())
    return "+".join(ordered)
