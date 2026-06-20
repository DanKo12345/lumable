from __future__ import annotations

import os
import sys

from app.license import is_license_active
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
        "color_history_full",
        "custom_quick_modes",
        "profile_import",
        "profile_export",
        "schedule",
        "scenes_full",
        "tray_quick_controls",
        "unlimited_profiles",
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


def is_pro() -> bool:
    global _pro_cache
    if _force_pro_env():
        return True
    if _pro_cache is not None:
        return _pro_cache
    result = False
    try:
        # Read-only, local-only: never writes back. Persisting the verified
        # state (and the refreshed ``checked_at``) is the job of
        # ``refresh_pro_status`` so the UI thread stays free of disk writes.
        result = bool(is_license_active(load_settings(), allow_network=False))
    except (OSError, TypeError, ValueError):
        result = False
    _pro_cache = result
    return result


def refresh_pro_status() -> bool:
    """Authoritative Pro check including network revalidation.

    Must be called OFF the UI thread (it may block on an HTTP request). Updates
    the persisted license state and the in-memory cache, then returns the result.
    """
    global _pro_cache
    if _force_pro_env():
        _pro_cache = True
        return True
    result = False
    try:
        settings = load_settings()
        before = dict(settings.get("license", {}))
        result = bool(is_license_active(settings, allow_network=True))
        if settings.get("license", {}) != before:
            save_settings(settings)
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
