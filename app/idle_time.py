"""How long the machine has been left alone.

Windows counts keyboard and mouse input for the whole session, which is what an
"after N minutes of no input" automation means — not "this window lost focus". The
call is cheap enough to make on a timer.

Anywhere else, and on any failure, the answer is 0.0: a rule that waits for idle
time simply never comes round, which is the safe way to be wrong about it. Reporting
a large number would switch the user's light while they were using the machine.
"""

from __future__ import annotations

import ctypes
import os


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input, session-wide."""
    if os.name != "nt":
        return 0.0
    try:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # Both are milliseconds since boot, and GetTickCount wraps every 49 days.
        # The unsigned subtraction below is the documented way to stay correct
        # across that wrap; a negative result would otherwise read as "just used".
        elapsed = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
        return elapsed / 1000.0
    except Exception:
        return 0.0
