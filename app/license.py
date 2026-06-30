from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

LICENSE_GRACE_DAYS = 7
_LS_BASE = "https://api.lemonsqueezy.com/v1/licenses"
_REVALIDATE_HOURS = 24
_LS_EXPECTED_VARIANT_ID = 1_776_109
_INSTANCE_NAME = "LumaBLE"


def normalize_license_key(key: str) -> str:
    return "".join(str(key).strip().upper().split())


def _instance_name() -> str:
    """Make each activated machine recognisable in the Lemon Squeezy dashboard."""
    host = ""
    try:
        host = platform.node().strip()
    except OSError:
        host = ""
    return f"{_INSTANCE_NAME} - {host}" if host else _INSTANCE_NAME


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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _age_hours(checked_at: str) -> float | None:
    if not checked_at:
        return None
    try:
        dt = datetime.fromisoformat(checked_at)
    except (ValueError, TypeError):
        return None
    return (datetime.now(UTC) - dt).total_seconds() / 3600


def _needs_revalidation(checked_at: str) -> bool:
    age_hours = _age_hours(checked_at)
    # Missing, in the future (a forged timestamp), or simply old -> re-check.
    return age_hours is None or age_hours < 0 or age_hours >= _REVALIDATE_HOURS


def _is_within_grace(checked_at: str) -> bool:
    age_hours = _age_hours(checked_at)
    # A future timestamp (negative age) is forged, so it never earns grace.
    return age_hours is not None and 0 <= age_hours <= LICENSE_GRACE_DAYS * 24


def _is_expected_variant(resp: dict[str, Any]) -> bool:
    try:
        return int(resp.get("meta", {}).get("variant_id", 0)) == _LS_EXPECTED_VARIANT_ID
    except (TypeError, ValueError):
        return False


def _ls_post(endpoint: str, payload: dict[str, str]) -> dict[str, Any]:
    data = urlencode(payload).encode("utf-8")
    req = urllib_request.Request(
        f"{_LS_BASE}/{endpoint}",
        data=data,
        headers={"Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise URLError(str(exc)) from exc


def _mark_pro(lic: dict[str, Any]) -> None:
    lic["activated"] = True
    lic["edition"] = "pro"
    lic["kind"] = "lemonsqueezy"
    lic["provider"] = "lemonsqueezy"


def _clear_license(lic: dict[str, Any]) -> None:
    lic["license_key"] = ""
    lic["instance_id"] = ""
    lic["license_id"] = ""
    lic["checked_at"] = ""
    lic["kind"] = ""
    lic["provider"] = ""
    lic["activated"] = False
    lic["edition"] = "free"


def is_license_active(settings: dict[str, Any], *, allow_network: bool = True) -> bool:
    """Return whether a Pro license is currently valid.

    When ``allow_network`` is False the check stays fully local (no blocking
    HTTP request): a recently verified key is trusted, and a stale key is kept
    alive optimistically while inside the grace window. Pass ``allow_network``
    True only off the UI thread (see ``feature_gate.refresh_pro_status``).
    """
    lic = settings.get("license", {})
    key = str(lic.get("license_key", "")).strip()
    instance_id = str(lic.get("instance_id", "")).strip()

    if not key or not instance_id:
        return False

    checked_at = str(lic.get("checked_at", ""))
    if not allow_network:
        # UI thread / offline: trust a recent server-verified check, or stay
        # alive within the offline grace window. Never blocks on the network.
        if not _needs_revalidation(checked_at) or _is_within_grace(checked_at):
            _mark_pro(lic)
            return True
        return False

    # Authoritative path (off the UI thread): always re-check with the server, so
    # a forged local state — a fake key, or a hand-edited recent/future
    # "checked_at" — can't grant Pro. Grace applies only when the server is
    # genuinely unreachable.
    try:
        resp = _ls_post("validate", {"license_key": key, "instance_id": instance_id})
    except (URLError, OSError, ValueError):
        if _is_within_grace(checked_at):
            _mark_pro(lic)
            return True
        return False

    if resp.get("valid") and _is_expected_variant(resp):
        lic["checked_at"] = _now_iso()
        _mark_pro(lic)
        return True

    _clear_license(lic)
    return False


def activate_license_key(key: str, settings: dict[str, Any]) -> bool:
    key = normalize_license_key(key)
    if not key:
        return False

    try:
        resp = _ls_post("activate", {"license_key": key, "instance_name": _instance_name()})
    except (URLError, OSError, ValueError):
        return False

    if not resp.get("activated") or not _is_expected_variant(resp):
        return False

    lic_data = resp.get("license_key", {})
    instance_data = resp.get("instance", {})

    lic = settings.setdefault("license", {})
    lic["license_key"] = key
    lic["license_id"] = str(lic_data.get("id", ""))
    lic["instance_id"] = str(instance_data.get("id", ""))
    lic["checked_at"] = _now_iso()
    lic["grace_days"] = LICENSE_GRACE_DAYS
    _mark_pro(lic)
    return True


def deactivate_license(settings: dict[str, Any]) -> bool:
    lic = settings.get("license", {})
    key = str(lic.get("license_key", "")).strip()
    instance_id = str(lic.get("instance_id", "")).strip()
    if not key or not instance_id:
        _clear_license(settings.setdefault("license", {}))
        return True

    try:
        resp = _ls_post("deactivate", {"license_key": key, "instance_id": instance_id})
        if resp.get("deactivated"):
            _clear_license(lic)
            return True
    except (URLError, OSError, ValueError):
        pass

    # The server may have freed the slot even though we didn't get a clean
    # confirmation (lost response, timeout, or the instance was already
    # deactivated). Re-check with validate: if the instance is no longer valid,
    # the slot is gone, so treat the deactivation as done locally too.
    try:
        check = _ls_post("validate", {"license_key": key, "instance_id": instance_id})
    except (URLError, OSError, ValueError):
        return False

    if not check.get("valid"):
        _clear_license(lic)
        return True
    return False
