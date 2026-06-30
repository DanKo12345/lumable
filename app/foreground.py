from __future__ import annotations

import sys


def foreground_process_name() -> str:
    """Best-effort executable name of the foreground window's process.

    Windows only (uses Win32 via ctypes); returns "" on other platforms or on
    any failure, so callers can treat it as "unknown / nothing matched".
    """
    if not sys.platform.startswith("win"):
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""

        process_query_limited_information = 0x1000
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(260)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return ""
            return buffer.value.rsplit("\\", 1)[-1]
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
