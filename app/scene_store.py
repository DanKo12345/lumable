"""Settings-backed store for scenes and light groups — the single source of truth.

Everything here operates on a plain ``settings`` dict (the same one the app
persists), so it stays Qt-free and testable. The controller mutates the dict
through these helpers and then calls ``save_settings`` once. Scenes are stored as
versioned, checksummed envelopes (see :mod:`app.scenes`); groups are stored by a
stable ``group_id`` so renaming a group never breaks a saved scene that points at
it.
"""

from __future__ import annotations

from typing import Any

from app.scenes import new_scene_id, normalize_scene, unwrap_scene, wrap_scene

SCENES_KEY = "scenes"
GROUPS_KEY = "device_groups"
_MAX_GROUP_NAME = 40
MAX_SCENES = 50  # a generous cap so a profile can't grow unbounded


# ── scenes ────────────────────────────────────────────────────────────────
def _stored_list(settings: dict[str, Any], key: str) -> list[Any]:
    value = settings.get(key)
    return list(value) if isinstance(value, list) else []


def _read_scene(entry: Any) -> dict[str, Any] | None:
    # Prefer the envelope; tolerate a bare scene dict saved by an older build.
    scene = unwrap_scene(entry)
    if scene is not None:
        return scene
    if isinstance(entry, dict) and "state" in entry:
        return normalize_scene(entry)
    return None


def list_scenes(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """All saved scenes, corrupt entries silently dropped."""
    scenes = []
    for entry in _stored_list(settings, SCENES_KEY):
        scene = _read_scene(entry)
        if scene is not None:
            scenes.append(scene)
    return scenes


def get_scene(settings: dict[str, Any], scene_id: str) -> dict[str, Any] | None:
    for scene in list_scenes(settings):
        if scene["scene_id"] == scene_id:
            return scene
    return None


def save_scene(settings: dict[str, Any], scene: Any) -> dict[str, Any] | None:
    """Save a scene. Matches an existing one by ``scene_id`` or, failing that, by
    name (case-insensitive) — so re-saving under the same name overwrites it
    instead of piling up duplicates, keeping the original stable id. Returns the
    normalised scene, or ``None`` if it has no name or the store is at capacity."""
    normalized = normalize_scene(scene)
    if normalized is None or not normalized["name"]:
        return None
    entries = _stored_list(settings, SCENES_KEY)
    name_key = normalized["name"].casefold()
    target_index = None
    for index, entry in enumerate(entries):
        existing = _read_scene(entry)
        if not existing:
            continue
        if existing["scene_id"] == normalized["scene_id"] or existing["name"].casefold() == name_key:
            target_index = index
            normalized["scene_id"] = existing["scene_id"]  # preserve the stable id
            break
    if target_index is None and sum(1 for e in entries if _read_scene(e)) >= MAX_SCENES:
        return None  # at capacity — delete one to make room
    envelope = wrap_scene(normalized)
    if target_index is not None:
        entries[target_index] = envelope
    else:
        entries.append(envelope)
    settings[SCENES_KEY] = entries
    return normalized


def delete_scene(settings: dict[str, Any], scene_id: str) -> bool:
    entries = _stored_list(settings, SCENES_KEY)
    kept = [e for e in entries if (_read_scene(e) or {}).get("scene_id") != scene_id]
    settings[SCENES_KEY] = kept
    return len(kept) != len(entries)


# ── groups ──────────────────────────────────────────────────────────────
def normalize_group(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    members = raw.get("members")
    ordered: list[str] = []
    seen: set[str] = set()
    if isinstance(members, list):
        for member in members:
            address = str(member).strip()
            if address and address not in seen:
                seen.add(address)
                ordered.append(address)
    return {
        "group_id": (str(raw.get("group_id") or "").strip() or new_scene_id()),
        "name": str(raw.get("name") or "").strip()[:_MAX_GROUP_NAME],
        "members": ordered,
    }


def list_groups(settings: dict[str, Any]) -> list[dict[str, Any]]:
    groups = []
    for entry in _stored_list(settings, GROUPS_KEY):
        group = normalize_group(entry)
        if group and group["name"]:
            groups.append(group)
    return groups


def save_group(
    settings: dict[str, Any], name: str, members: list[str], *, group_id: str | None = None
) -> dict[str, Any] | None:
    normalized = normalize_group({"group_id": group_id, "name": name, "members": members})
    if normalized is None or not normalized["name"]:
        return None
    entries = _stored_list(settings, GROUPS_KEY)
    for index, entry in enumerate(entries):
        existing = normalize_group(entry)
        if existing and existing["group_id"] == normalized["group_id"]:
            entries[index] = normalized
            break
    else:
        entries.append(normalized)
    settings[GROUPS_KEY] = entries
    return normalized


def delete_group(settings: dict[str, Any], group_id: str) -> bool:
    entries = _stored_list(settings, GROUPS_KEY)
    kept = [g for g in entries if (normalize_group(g) or {}).get("group_id") != group_id]
    settings[GROUPS_KEY] = kept
    return len(kept) != len(entries)


def group_members(settings: dict[str, Any], group_id: str | None) -> list[str]:
    for group in list_groups(settings):
        if group["group_id"] == group_id:
            return group["members"]
    return []


def resolve_target(
    settings: dict[str, Any],
    target: Any,
    *,
    primary: str | None = None,
    all_addresses: list[str] | None = None,
) -> list[str]:
    """Map a scene target to concrete device addresses. ``primary`` and the full
    address list come from the live app; this stays pure by taking them as args."""
    target = target if isinstance(target, dict) else {}
    kind = target.get("kind", "primary")
    if kind == "all":
        return list(all_addresses or [])
    if kind == "group":
        return group_members(settings, target.get("group_id"))
    return [primary] if primary else []
