from __future__ import annotations

from typing import Any

LICENSE_GRACE_DAYS = 7


def normalize_license_key(key: str) -> str:
    return "".join(str(key).strip().upper().split())


def validate_license_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    license_key = str(data.get("license_key", "")).strip()
    license_id = str(data.get("license_id", "")).strip()
    instance_id = str(data.get("instance_id", "")).strip()
    checked_at = str(data.get("checked_at", "")).strip()
    return {
        "activated": False,
        "edition": "free",
        "kind": "",
        "provider": "lemonsqueezy" if license_key or license_id or instance_id else "",
        "license_key": license_key,
        "license_id": license_id,
        "instance_id": instance_id,
        "checked_at": checked_at,
        "grace_days": LICENSE_GRACE_DAYS,
    }


def is_license_active(settings: dict[str, Any]) -> bool:
    return False


def activate_license_key(key: str, settings: dict[str, Any]) -> bool:
    _ = normalize_license_key(key)
    return False
