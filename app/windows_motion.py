from __future__ import annotations

import ctypes

# SPI_GETCLIENTAREAANIMATION: reads the Windows accessibility setting "Show
# animations in Windows" (Settings → Accessibility → Visual effects). When it is
# OFF the user has asked for reduced motion.
_SPI_GETCLIENTAREAANIMATION = 0x1042


def _client_area_animation_enabled() -> bool:
    """Query Windows for whether client-area animations are enabled. Raises on
    failure or on a non-Windows platform (ctypes.windll is Windows-only) —
    seam kept small so tests can patch it without touching the real API."""
    enabled = ctypes.c_int(1)
    ok = ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
        _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
    )
    if not ok:
        raise OSError("SystemParametersInfo(SPI_GETCLIENTAREAANIMATION) failed")
    return bool(enabled.value)


def windows_motion_reduced() -> bool:
    """True when Windows requests reduced motion (animations turned off).

    Install as MotionPolicy's provider; MotionPolicy calls it only on refresh()
    and treats any exception as 'not reduced' (animations stay on).
    """
    return not _client_area_animation_enabled()
