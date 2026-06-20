from __future__ import annotations

MIN_SCALE = 0.78
MAX_SCALE = 1.1


def _scale_for_size(width: int, height: int) -> float:
    """Pick a density factor from the available *logical* desktop size.

    Per Qt's High-DPI model the OS already applies the display scale (125/150/…%)
    and the app works in device-independent pixels, so we must NOT scale by
    physical inches — that double-scales. Instead we use the logical room the
    window has (which already reflects the OS scale) as responsive breakpoints,
    the same idea as web/Material layout breakpoints.

    Reference: a ~1080p logical desktop reads as "normal" (1.0). Smaller logical
    areas (e.g. a 13" laptop at 150% ≈ 1280×720) get a more compact UI; larger
    desktops get a slightly roomier one.
    """
    if height < 900 or width < 1400:
        return 0.82
    if height < 1130:
        return 0.88  # typical 1080p laptop (15.6") — noticeably tighter
    if height < 1400:
        return 0.95
    if height < 1650:
        return 1.0
    return 1.05


def resolve_ui_scale(screen) -> float:
    """Density factor derived from the screen's available logical geometry."""
    if screen is None:
        return 1.0
    try:
        geometry = screen.availableGeometry()
        scale = _scale_for_size(geometry.width(), geometry.height())
    except Exception:
        scale = 1.0
    return max(MIN_SCALE, min(MAX_SCALE, scale))
