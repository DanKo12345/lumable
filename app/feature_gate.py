from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

from app.install_identity import advance_high_water, load_identity, save_identity
from app.license import clear_licence, has_licence, local_verdict, store_receipt
from app.license_client import ISSUED, is_refresh_due, request_receipt
from app.license_keys import public_keys
from app.storage import load_settings, save_settings

FREE_EFFECT_COUNT = 12
FREE_COLOR_HISTORY_COUNT = 6
PRO_COLOR_HISTORY_COUNT = 12
FREE_PROFILE_MAX = 3
PRO_LIMIT_SENTINEL = 999_999

PRO_FEATURES = frozenset(
    {
        "all_effects",
        "ambient_sync",
        "music_sync",
        "color_history_full",
        "custom_quick_modes",
        "profile_import",
        "profile_export",
        "schedule",
        "tray_quick_controls",
        "unlimited_profiles",
        "diy_effects",
    }
)


class ProFeatureError(Exception):
    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(f"Pro feature required: {feature}")


class ProfileLimitError(Exception):
    pass


# Pro state is resolved once per session and cached. ``is_pro`` is called on the
# UI thread during rendering, so it must never read the disk repeatedly nor make
# a blocking network request. Authoritative revalidation (which may touch the
# network) happens in ``refresh_pro_status`` off the UI thread.
_pro_cache: bool | None = None


def _force_pro_env() -> bool:
    if getattr(sys, "frozen", False):
        return False
    return os.environ.get("LUMABLE_FORCE_PRO", "").strip().lower() in {"1", "true", "yes", "pro"}


def invalidate_pro_cache() -> None:
    """Drop the cached Pro state so the next check recomputes it."""
    global _pro_cache
    _pro_cache = None


# How far behind the mark a clock may sit and still be believed. Machines
# correct themselves by seconds; a few minutes is generous and still nothing
# like the days it would take to keep a receipt alive.
CLOCK_TOLERANCE = timedelta(minutes=5)


def clock_went_back(identity, now: datetime) -> bool:
    """Whether this machine is claiming a time it has already been past.

    The mark is not used *as* the time. Substituting it would freeze the clock
    at whatever moment it recorded, so a receipt that should have expired never
    would: leave the date in the past and Pro lasts forever, which is the
    opposite of what the mark is for.

    So a clock behind the mark is refused instead. Free until the machine is
    online again, and nothing is cleared — the licence is untouched, because a
    wrong date is not evidence about whether somebody paid.

    Best effort throughout: restoring an older copy of the protected file
    restores an older mark with it. What this stops is the version that needs
    nothing but the date control.
    """
    seen = getattr(identity, "highest_seen", None)
    if seen is None:
        return False
    return now < seen - CLOCK_TOLERANCE


def _local_state() -> tuple[bool, dict, object]:
    """Whether Pro holds right now, without touching the network or the disk.

    Returns the answer along with what it was worked out from, so the
    background path can carry on from here rather than reading everything a
    second time.
    """
    settings = load_settings()
    outcome = load_identity(has_licence=has_licence(settings))
    identity = outcome.identity
    if identity is None:
        return False, settings, None
    now = datetime.now(UTC)
    if clock_went_back(identity, now):
        # Not an accusation and not a punishment: the licence stays exactly
        # where it is, and correcting the clock puts Pro back. Asking the
        # service would not — a fresh receipt is judged against this same
        # wrong clock, and the mark is still ahead of it, so the refusal
        # simply happens again. The date is what has to change.
        return False, settings, identity
    verdict = local_verdict(
        settings,
        installation_hash=identity.installation_hash,
        public_keys=public_keys(),
        now=now,
    )
    return bool(verdict.ok), settings, identity


def is_pro() -> bool:
    global _pro_cache
    if _force_pro_env():
        return True
    if _pro_cache is not None:
        return _pro_cache
    result = False
    try:
        result, _settings, _identity = _local_state()
    except (OSError, TypeError, ValueError):
        result = False
    _pro_cache = result
    return result


def obtain_receipt(settings: dict, identity, *, now: datetime) -> str:
    """Turn a licence into a verified receipt, or say why not. Never on the UI thread.

    The one place that knows how each answer is allowed to change what is
    stored. A receipt only replaces the previous one once it has been checked
    locally; the two answers that end a licence clear it; everything else — a
    service that is down, a rate limit, a reply that will not parse — leaves the
    key, the instance and the old receipt exactly where they are, because a
    service that cannot answer must never be able to cancel a licence.
    """
    licence = settings.get("license", {}) if isinstance(settings, dict) else {}
    key = str(licence.get("license_key", "")).strip()
    instance_id = str(licence.get("instance_id", "")).strip()
    if not key or not instance_id:
        return "no_licence"

    result = request_receipt(
        license_key=key,
        instance_id=instance_id,
        installation_hash=identity.installation_hash,
        public_keys=public_keys(),
        now=now,
    )
    if result.ok:
        store_receipt(settings, result.receipt)
        save_settings(settings)
        return ISSUED
    if result.ends_pro:
        clear_licence(settings)
        save_settings(settings)
    return result.outcome


def refresh_pro_status() -> bool:
    """The authoritative check, off the UI thread.

    Asks for a receipt when there is none or the one held is due, and leaves
    everything alone when it is not. The mark that keeps a clock from being
    wound back is moved here, and only here: it is a write, and writes do not
    belong on the thread drawing the window.
    """
    global _pro_cache
    if _force_pro_env():
        _pro_cache = True
        return True
    result = False
    try:
        result, settings, identity = _local_state()
        if identity is not None:
            now = datetime.now(UTC)
            advanced = advance_high_water(identity, now)
            if advanced is not identity:
                save_identity(advanced)
            receipt = settings.get("license", {}).get("receipt")
            if not result or is_refresh_due(
                receipt, installation_hash=identity.installation_hash, now=now
            ):
                obtain_receipt(settings, identity, now=now)
                result, _settings, _identity = _local_state()
    except (OSError, TypeError, ValueError):
        result = _pro_cache if _pro_cache is not None else False
    _pro_cache = result
    return result


def can_use(feature: str) -> bool:
    if feature not in PRO_FEATURES:
        return True
    return is_pro()


def require_feature(feature: str) -> None:
    if not can_use(feature):
        raise ProFeatureError(feature)


def free_effect_limit() -> int:
    return PRO_LIMIT_SENTINEL if is_pro() else FREE_EFFECT_COUNT


def profile_limit() -> int:
    return PRO_LIMIT_SENTINEL if is_pro() else FREE_PROFILE_MAX


def ensure_profile_capacity(current_count: int) -> None:
    if current_count >= profile_limit():
        raise ProfileLimitError()
