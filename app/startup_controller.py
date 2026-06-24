from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.app_info import APP_NAME
from app.storage import APP_DIR

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SCHEDULE_TASK_ON = f"{APP_NAME} Schedule On"
SCHEDULE_TASK_OFF = f"{APP_NAME} Schedule Off"


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    launcher = APP_DIR / "run_app.bat"
    if launcher.exists():
        return f'"{launcher}"'
    main_path = Path(APP_DIR) / "main.py"
    return f'"{sys.executable}" "{main_path}"'


def _quote(value: str | Path) -> str:
    return f'"{value!s}"'


def _scheduled_action_command(action: str) -> str:
    if getattr(sys, "frozen", False):
        return f'{_quote(sys.executable)} --scheduled-action {action}'
    main_path = Path(APP_DIR) / "main.py"
    return f'{_quote(sys.executable)} {_quote(main_path)} --scheduled-action {action}'


def is_supported() -> bool:
    return os.name == "nt"


def _schtasks_disabled() -> bool:
    return os.environ.get("LUMABLE_DISABLE_SCHTASKS", "").strip().lower() in {"1", "true", "yes"}


def _run_schtasks(args: list[str], *, allow_missing: bool = False) -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        check=False,
    )
    if completed.returncode == 0:
        return True
    message = (completed.stderr or completed.stdout or "").strip()
    if allow_missing and ("cannot find" in message.lower() or "не удается найти" in message.lower()):
        return False
    raise OSError(message or f"schtasks failed with exit code {completed.returncode}")


_DAY_CODES = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}


def _create_schedule_task(name: str, action: str, time_text: str, days: list[int]) -> None:
    # All seven days -> a simple daily task; a subset -> a weekly task limited to
    # those weekdays (schtasks /D MON,WED,...).
    if len(set(days)) >= 7:
        schedule_args = ["/SC", "DAILY"]
    else:
        codes = ",".join(_DAY_CODES[d] for d in sorted(set(days)) if d in _DAY_CODES)
        schedule_args = ["/SC", "WEEKLY", "/D", codes]
    _run_schtasks(
        [
            "/Create",
            "/F",
            "/TN",
            name,
            *schedule_args,
            "/ST",
            time_text,
            "/TR",
            _scheduled_action_command(action),
        ]
    )


def _delete_task(name: str) -> None:
    _run_schtasks(["/Delete", "/F", "/TN", name], allow_missing=True)


def are_schedule_tasks_enabled() -> bool:
    if not is_supported() or _schtasks_disabled():
        return False
    try:
        return bool(
            _run_schtasks(["/Query", "/TN", SCHEDULE_TASK_ON], allow_missing=True)
            and _run_schtasks(["/Query", "/TN", SCHEDULE_TASK_OFF], allow_missing=True)
        )
    except OSError:
        return False


def set_schedule_tasks_enabled(
    enabled: bool, *, on_time: str, off_time: str, days: list[int] | None = None
) -> None:
    if days is None:
        days = [0, 1, 2, 3, 4, 5, 6]
    if not is_supported():
        if not enabled:
            return
        raise OSError("Windows Task Scheduler is not supported on this platform.")
    if _schtasks_disabled():
        if not enabled:
            return
        raise OSError("Windows Task Scheduler is disabled for this process.")
    # With no day selected the schedule can never fire, so there's nothing to run.
    if enabled and days:
        _create_schedule_task(SCHEDULE_TASK_ON, "on", on_time, days)
        _create_schedule_task(SCHEDULE_TASK_OFF, "off", off_time, days)
        return
    _delete_task(SCHEDULE_TASK_ON)
    _delete_task(SCHEDULE_TASK_OFF)


def is_startup_enabled() -> bool:
    if not is_supported():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, APP_NAME)
        return str(value).strip() == _startup_command()
    except (FileNotFoundError, OSError):
        return False


def set_startup_enabled(enabled: bool) -> None:
    if not is_supported():
        raise OSError("Windows startup is not supported on this platform.")
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
