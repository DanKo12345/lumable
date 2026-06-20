from __future__ import annotations

import ctypes

UI_FPS_MODES = ("auto", "30", "60", "120")


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def on_ac_power() -> bool:
    """True if running on mains power (or status unknown / non-Windows).

    Unknown defaults to True so the smoother 60 fps is used unless we are sure
    the machine is on battery.
    """
    try:
        status = _SystemPowerStatus()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            # ACLineStatus: 0 = on battery, 1 = on mains, 255 = unknown.
            return status.ACLineStatus != 0
    except Exception:
        return True
    return True


def resolve_ui_fps(mode: str) -> int:
    """Resolve a UI-fps setting to a concrete frame rate.

    ``auto`` picks 60 fps on mains power and 30 fps on battery; explicit modes
    return their value.
    """
    normalized = str(mode).strip().lower()
    if normalized in {"30", "60", "120"}:
        return int(normalized)
    return 60 if on_ac_power() else 30
