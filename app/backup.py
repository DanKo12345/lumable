"""A portable backup of what the user made, not a copy of their settings file.

The difference matters in both directions. A settings file carries a licence
key, a Local API token and the address of a particular Bluetooth controller;
handing that to someone else, or to a support thread, gives away more than was
meant. And a settings file carries this machine's window size and update
bookkeeping, which are worthless anywhere else.

So the contents are chosen by name, not by exclusion. Anything added to settings
later is absent from a backup until someone decides it belongs — which is the
safe direction to be wrong in.

**Groups keep their names and lose their members.** A group's members are BLE
addresses, and addresses are exactly what must not travel. Promising to carry
groups across while dropping the addresses inside them would be a lie that only
shows up when a scene aimed at a group lights nothing, so the members are
cleared deliberately and the restore says so.

Qt-free and file-free: this builds and checks dictionaries. Writing them, and
the atomic replacement that follows, belong to the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Bumped when the shape changes in a way an older build could not read. A file
# from the future is refused rather than half-understood: the fields it gained
# are exactly the ones this build would silently drop.
BACKUP_VERSION = 1
BACKUP_KIND = "lumable-backup"

# A settings file is tens of kilobytes; a megabyte is already something else.
# Checked before parsing, because the cheapest way to survive a hostile or
# corrupt file is not to hand it to the JSON parser at all.
MAX_BACKUP_BYTES = 4 * 1024 * 1024

# What travels. Named one by one, so a key added to settings next year is not
# quietly exported by a rule nobody re-read.
PORTABLE_KEYS: tuple[str, ...] = (
    "scenes",
    "device_groups",
    "automations",
    "app_triggers",
    "diy",
    "diy_saved",
    "custom_quick_modes",
    "quick_mode",
    "hotkeys",
    "ambient",
    "fusion",
    "music",
    "software_fx",
    "timers",
    "schedule",
    "color_temperature",
    "color_history",
    "fade",
    "theme",
    "theme_mode",
    "motion_mode",
    "language",
    "ui_fps",
)

# Named only to say why they are missing — the export never reads them. Kept as
# a list so the reason survives the next person to wonder.
WITHHELD_KEYS: dict[str, str] = {
    "license": "licence key and activation",
    "api": "Local API token and address",
    "last_device_address": "the Bluetooth controller in use",
    "last_device_name": "the Bluetooth controller in use",
    "extra_device_addresses": "addresses of the other strips",
    "device_names": "names given to particular strips",
    "capture_compatibility": "what was probed on this machine",
    "last_state": "the light's state right now",
    "onboarding_seen": "local to this installation",
    "window_width": "this machine's window",
    "window_height": "this machine's window",
}

# Without these a file is not a backup of anything.
REQUIRED_SECTIONS: tuple[str, ...] = ("scenes", "automations")


@dataclass(frozen=True)
class BackupCheck:
    """The verdict on a file, before anything has been touched."""

    ok: bool = False
    error: str = ""
    version: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RestoreReport:
    """What a restore would put back, and what it could not."""

    counts: dict[str, int] = field(default_factory=dict)
    groups_need_strips: int = 0


def _strip_group_members(groups: Any) -> list[dict[str, Any]]:
    """Group names without their members.

    Members are BLE addresses. Carrying them would put the identifiers of
    someone's hardware into a file meant to be shared, and carrying the groups
    without saying the members are gone would leave a scene pointing at an empty
    group — which lights nothing and explains nothing.
    """
    kept: list[dict[str, Any]] = []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        kept.append(
            {
                "group_id": str(group.get("group_id") or ""),
                "name": str(group.get("name") or ""),
                "members": [],
            }
        )
    return kept


def build_backup(settings: dict[str, Any], *, app_version: str = "") -> dict[str, Any]:
    """The exportable part of ``settings``, as a versioned document."""
    data: dict[str, Any] = {}
    for key in PORTABLE_KEYS:
        if key not in settings:
            continue
        value = settings[key]
        data[key] = _strip_group_members(value) if key == "device_groups" else value
    return {
        "kind": BACKUP_KIND,
        "version": BACKUP_VERSION,
        "app_version": str(app_version or ""),
        "data": data,
    }


def summarise(data: dict[str, Any]) -> dict[str, int]:
    """How much of each thing a document holds, for the report shown to the user."""
    counts: dict[str, int] = {}
    for key in ("scenes", "device_groups", "diy_saved", "custom_quick_modes"):
        value = data.get(key)
        if isinstance(value, list):
            counts[key] = len(value)
    rules = (data.get("automations") or {}).get("rules") if isinstance(data.get("automations"), dict) else None
    if isinstance(rules, list):
        counts["automations"] = len(rules)
    triggers = data.get("app_triggers")
    if isinstance(triggers, list):
        counts["app_triggers"] = len(triggers)
    return counts


def inspect_backup(raw: bytes | str) -> BackupCheck:
    """Read a file and decide whether it may be restored — touching nothing.

    Every refusal names its own reason. "Invalid file" tells the user to try
    the same file again; "made by a newer version" tells them what to do.
    """
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    if not raw:
        return BackupCheck(error="empty")
    if len(raw) > MAX_BACKUP_BYTES:
        return BackupCheck(error="too_large")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return BackupCheck(error="unreadable")
    if not isinstance(document, dict):
        return BackupCheck(error="unreadable")
    if str(document.get("kind") or "") != BACKUP_KIND:
        return BackupCheck(error="not_a_backup")

    try:
        version = int(document.get("version", 0))
    except (TypeError, ValueError):
        return BackupCheck(error="unreadable")
    if version <= 0:
        return BackupCheck(error="unreadable")
    if version > BACKUP_VERSION:
        # Refused rather than read as far as it goes: the parts this build does
        # not know about are exactly the parts it would drop, and it would drop
        # them while reporting success.
        return BackupCheck(error="too_new", version=version)

    data = document.get("data")
    if not isinstance(data, dict):
        return BackupCheck(error="unreadable", version=version)
    missing = [name for name in REQUIRED_SECTIONS if name not in data]
    if missing:
        return BackupCheck(error="incomplete", version=version)

    return BackupCheck(ok=True, version=version, payload=data, counts=summarise(data))


def restore_into(settings: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, Any], RestoreReport]:
    """A new settings dict with the backup applied — the original untouched.

    Built as a copy so a failure part-way through leaves nothing half-restored:
    the caller writes the result or does not, and there is no third outcome.
    Only portable keys are taken, even if the file carries more, so a document
    edited by hand cannot put a licence or an address back in.
    """
    restored = dict(settings)
    for key in PORTABLE_KEYS:
        if key not in data:
            continue
        value = data[key]
        restored[key] = _strip_group_members(value) if key == "device_groups" else value

    groups = restored.get("device_groups")
    needing = sum(
        1 for group in groups if isinstance(group, dict) and not group.get("members")
    ) if isinstance(groups, list) else 0
    return restored, RestoreReport(counts=summarise(data), groups_need_strips=needing)
