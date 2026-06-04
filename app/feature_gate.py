from __future__ import annotations

from app.license import is_license_active
from app.storage import load_settings

FREE_EFFECT_COUNT = 5
FREE_PROFILE_MAX = 3
PRO_LIMIT_SENTINEL = 999_999

PRO_FEATURES = frozenset(
    {
        "all_effects",
        "color_history_full",
        "color_picker_hsv",
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


def is_pro() -> bool:
    try:
        if is_license_active(load_settings()):
            return True
    except (OSError, TypeError, ValueError):
        pass
    return False


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
