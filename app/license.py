from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from app.app_info import APP_VERSION
from app.license_receipt import Verdict, verify

LICENSE_GRACE_DAYS = 7
_LS_BASE = "https://api.lemonsqueezy.com/v1/licenses"
_LS_EXPECTED_VARIANT_ID = 1_776_109
_LS_MAX_RESPONSE_BYTES = 8192
_LS_TIMEOUT_SECONDS = 10.0
_LS_USER_AGENT = f"LumaBLE/{APP_VERSION}"
# What an activated instance is called, and the whole of the binding between a
# licence and one installation. The server that signs a receipt asks Lemon
# Squeezy for the instance and requires this exact string back, rebuilt from
# the installation it was told about — so a receipt cannot be obtained for an
# installation that did not activate.
#
# It carries nothing else. It used to end in the machine's name, which made the
# dashboard readable, and that is given up on purpose: the signing server has
# no way to know a host name and therefore no way to rebuild a string
# containing one, and matching part of a name rather than all of it is exactly
# the looseness this exists to remove.
INSTANCE_NAME_PREFIX = "LumaBLE:"


def normalize_license_key(key: str) -> str:
    return "".join(str(key).strip().upper().split())


def canonical_instance_name(installation_hash: str) -> str:
    """The name this installation activates under, or "" if it has no identity.

    An empty answer means no activation may be attempted. Activating without a
    name the server can rebuild would take an activation slot and produce an
    instance no receipt could ever be issued for — a licence spent on nothing.
    """
    digest = str(installation_hash or "").strip()
    return f"{INSTANCE_NAME_PREFIX}{digest}" if digest else ""


def validate_license_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    license_key = str(data.get("license_key", "")).strip()
    license_id = str(data.get("license_id", "")).strip()
    instance_id = str(data.get("instance_id", "")).strip()
    checked_at = str(data.get("checked_at", "")).strip()
    # The signed receipt, kept as it arrived. Not inspected here: what makes it
    # good is a signature, and a validator that started tidying its fields would
    # be changing the bytes the signature was taken over.
    receipt = data.get("receipt")
    return {
        "activated": False,
        "edition": "free",
        "kind": "",
        "provider": "lemonsqueezy" if license_key or license_id or instance_id else "",
        "license_key": license_key,
        "license_id": license_id,
        "instance_id": instance_id,
        # Kept for the diagnostics report and nothing else. No path to Pro
        # passes through it any more; a receipt is the only thing that grants
        # one, and that is the point of having them.
        "checked_at": checked_at,
        "receipt": receipt if isinstance(receipt, dict) and receipt else None,
        "grace_days": LICENSE_GRACE_DAYS,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_expected_variant(resp: dict[str, Any]) -> bool:
    try:
        return int(resp.get("meta", {}).get("variant_id", 0)) == _LS_EXPECTED_VARIANT_ID
    except (TypeError, ValueError):
        return False


class _NoRedirects(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _read_json_response(response: Any) -> dict[str, Any]:
    raw = response.read(_LS_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _LS_MAX_RESPONSE_BYTES:
        raise URLError("response too large")
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("response is not an object")
    return parsed


def _ls_post(endpoint: str, payload: dict[str, str]) -> dict[str, Any]:
    data = urlencode(payload).encode("utf-8")
    req = urllib_request.Request(
        f"{_LS_BASE}/{endpoint}",
        data=data,
        headers={"Accept": "application/json", "User-Agent": _LS_USER_AGENT},
        method="POST",
    )
    opener = urllib_request.build_opener(_NoRedirects)
    try:
        with opener.open(req, timeout=_LS_TIMEOUT_SECONDS) as resp:
            return _read_json_response(resp)
    except HTTPError as exc:
        try:
            parsed = _read_json_response(exc)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, URLError, OSError):
            raise URLError(str(exc)) from exc
        # Keep transport status separate from Lemon's fields. Callers may use
        # an explicit licence verdict, but never infer one from an error page.
        parsed["_http_status"] = int(getattr(exc, "code", 0) or 0)
        if parsed["_http_status"] >= 500:
            raise URLError(str(exc)) from exc
        return parsed


def _mark_pro(lic: dict[str, Any]) -> None:
    lic["activated"] = True
    lic["edition"] = "pro"
    lic["kind"] = "lemonsqueezy"
    lic["provider"] = "lemonsqueezy"


def clear_licence(settings: dict[str, Any]) -> None:
    """Forget the licence on this machine, receipt included."""
    _clear_license(settings.setdefault("license", {}))


def _clear_license(lic: dict[str, Any]) -> None:
    # The receipt goes with it. Leaving one behind would keep Pro alive for up
    # to a fortnight after the answer that ended the licence.
    lic["receipt"] = None
    lic["license_key"] = ""
    lic["instance_id"] = ""
    lic["license_id"] = ""
    lic["checked_at"] = ""
    lic["kind"] = ""
    lic["provider"] = ""
    lic["activated"] = False
    lic["edition"] = "free"


def stored_receipt(settings: dict[str, Any]) -> dict | None:
    """The signed receipt kept beside the licence, if there is one."""
    licence = settings.get("license", {})
    receipt = licence.get("receipt") if isinstance(licence, dict) else None
    return receipt if isinstance(receipt, dict) and receipt else None


def store_receipt(settings: dict[str, Any], receipt: dict) -> None:
    """Keep a receipt that has already been verified by the caller.

    Verified first, never here: a receipt written before it is checked is one
    that will be refused on every launch afterwards, with the reason nowhere
    near the symptom.
    """
    licence = settings.setdefault("license", {})
    licence["receipt"] = dict(receipt)
    _mark_pro(licence)


def local_verdict(
    settings: dict[str, Any],
    *,
    installation_hash: str,
    public_keys: dict[str, bytes],
    now: datetime,
) -> Verdict:
    """Whether the receipt on this machine is good, right now, offline.

    The whole of the local check. The timestamp this used to trust is not
    consulted and cannot be: it says only that something once wrote a date into
    a file anybody can edit, which is exactly the door the receipts were
    introduced to close.
    """
    receipt = stored_receipt(settings)
    if receipt is None:
        return Verdict(False, "no_receipt")
    return verify(
        receipt, public_keys=public_keys, installation_hash=installation_hash, now=now
    )


def has_licence(settings: dict[str, Any]) -> bool:
    """Whether this installation has anything to lose.

    A receipt on its own counts: it was issued for an installation, so its
    presence is proof that this one was not fresh, whatever else is missing.
    """
    licence = settings.get("license", {}) if isinstance(settings, dict) else {}
    if not isinstance(licence, dict):
        return False
    return bool(
        str(licence.get("license_key", "")).strip()
        or str(licence.get("instance_id", "")).strip()
        or licence.get("receipt")
    )


def activate_license_key(
    key: str, settings: dict[str, Any], *, installation_hash: str
) -> bool:
    """Take an activation slot for this installation, under a name it can prove.

    ``installation_hash`` is required rather than optional: an activation whose
    name the signing server cannot rebuild is a slot spent on an instance that
    can never be issued a receipt, and defaulting it would make that the quiet
    outcome of forgetting to pass it.
    """
    key = normalize_license_key(key)
    instance_name = canonical_instance_name(installation_hash)
    if not key or not instance_name:
        return False

    try:
        resp = _ls_post("activate", {"license_key": key, "instance_name": instance_name})
    except (URLError, OSError, ValueError):
        return False

    if not resp.get("activated") or not _is_expected_variant(resp):
        return False

    lic_data = resp.get("license_key", {})
    instance_data = resp.get("instance", {})
    license_id = str(lic_data.get("id", "")).strip()
    instance_id = str(instance_data.get("id", "")).strip()
    if not license_id or not instance_id:
        return False

    lic = settings.setdefault("license", {})
    lic["license_key"] = key
    lic["license_id"] = license_id
    lic["instance_id"] = instance_id
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

    if check.get("valid") is False:
        _clear_license(lic)
        return True
    return False
