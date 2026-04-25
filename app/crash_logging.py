from __future__ import annotations

import faulthandler
import platform
import sys
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType

from app.constants import (
    CRASH_LOG_MAX_AGE_DAYS,
    CRASH_LOG_MAX_FILES,
    FATAL_LOG_MAX_BYTES,
    FATAL_LOG_TRIM_BYTES,
)
from app.storage import DATA_DIR


CRASH_LOG_DIR = DATA_DIR / "crash_logs"
FATAL_LOG_PATH = CRASH_LOG_DIR / "fatal-crashes.log"

_FAULT_LOG_HANDLE = None
_INSTALLED = False


def _ensure_crash_log_dir() -> None:
    CRASH_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _exception_log_files() -> list[Path]:
    return sorted(
        (
            path
            for path in CRASH_LOG_DIR.glob("*.log")
            if path.name != FATAL_LOG_PATH.name
        ),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def _cleanup_exception_logs() -> None:
    _ensure_crash_log_dir()
    cutoff = datetime.now() - timedelta(days=CRASH_LOG_MAX_AGE_DAYS)
    kept: list[Path] = []
    for path in _exception_log_files():
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if modified < cutoff:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            continue
        kept.append(path)

    for path in kept[CRASH_LOG_MAX_FILES:]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def _trim_fatal_log() -> None:
    _ensure_crash_log_dir()
    if not FATAL_LOG_PATH.exists():
        return
    try:
        size = FATAL_LOG_PATH.stat().st_size
    except OSError:
        return
    if size <= FATAL_LOG_MAX_BYTES:
        return
    try:
        with FATAL_LOG_PATH.open("rb") as handle:
            if size > FATAL_LOG_TRIM_BYTES:
                handle.seek(-FATAL_LOG_TRIM_BYTES, 2)
            payload = handle.read()
    except OSError:
        return

    text = payload.decode("utf-8", errors="ignore").lstrip()
    header = (
        f"Trimmed crash log at {datetime.now().isoformat()} "
        f"to keep the latest {FATAL_LOG_TRIM_BYTES} bytes.\n\n"
    )
    try:
        FATAL_LOG_PATH.write_text(header + text, encoding="utf-8")
    except OSError:
        return


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _exception_log_path(context: str) -> Path:
    safe_context = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in context).strip("-")
    if not safe_context:
        safe_context = "unhandled"
    return CRASH_LOG_DIR / f"{_timestamp()}-{safe_context}.log"


def _build_exception_report(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
    *,
    context: str,
    thread_name: str | None = None,
) -> str:
    lines = [
        f"Timestamp: {datetime.now().isoformat()}",
        f"Context: {context}",
        f"Thread: {thread_name or threading.current_thread().name}",
        f"Python: {sys.version}",
        f"Executable: {sys.executable}",
        f"Platform: {platform.platform()}",
        f"Working directory: {Path.cwd()}",
        "",
        "Traceback:",
        "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)).rstrip(),
        "",
    ]
    return "\n".join(lines)


def write_exception_report(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
    *,
    context: str = "unhandled",
    thread_name: str | None = None,
) -> Path:
    _ensure_crash_log_dir()
    path = _exception_log_path(context)
    report = _build_exception_report(
        exc_type,
        exc_value,
        exc_traceback,
        context=context,
        thread_name=thread_name,
    )
    path.write_text(report, encoding="utf-8")
    _cleanup_exception_logs()
    return path


def write_current_exception(*, context: str = "unhandled", thread_name: str | None = None) -> Path:
    exc_type, exc_value, exc_traceback = sys.exc_info()
    if exc_type is None or exc_value is None:
        raise RuntimeError("write_current_exception() called without an active exception")
    return write_exception_report(
        exc_type,
        exc_value,
        exc_traceback,
        context=context,
        thread_name=thread_name,
    )


def _python_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    write_exception_report(exc_type, exc_value, exc_traceback, context="unhandled")
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if issubclass(args.exc_type, KeyboardInterrupt):
        return
    write_exception_report(
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
        context="thread",
        thread_name=args.thread.name if args.thread else None,
    )


def install_crash_logging() -> None:
    global _FAULT_LOG_HANDLE, _INSTALLED
    if _INSTALLED:
        return

    _ensure_crash_log_dir()
    _cleanup_exception_logs()
    _trim_fatal_log()
    _FAULT_LOG_HANDLE = open(FATAL_LOG_PATH, "a", encoding="utf-8")
    faulthandler.enable(_FAULT_LOG_HANDLE, all_threads=True)
    sys.excepthook = _python_excepthook
    threading.excepthook = _threading_excepthook
    _INSTALLED = True
