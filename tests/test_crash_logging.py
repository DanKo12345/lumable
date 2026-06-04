from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import app.crash_logging as crash_logging
from app.constants import CRASH_LOG_MAX_FILES, FATAL_LOG_MAX_BYTES
from app.crash_logging import (
    _cleanup_exception_logs,
    _display_path,
    _exception_log_path,
    _trim_fatal_log,
    write_exception_report,
)

# ── _display_path ─────────────────────────────────────────────────────

def test_display_path_replaces_home_prefix(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    target = str(tmp_path / "Documents" / "file.txt")

    result = _display_path(target)

    assert result.startswith("~")
    assert "Documents" in result


def test_display_path_returns_path_unchanged_when_not_under_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "user"))
    other = "/some/other/path/file.txt"

    assert _display_path(other) == other


def test_display_path_returns_tilde_for_home_itself(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    assert _display_path(str(tmp_path)) == "~"


# ── _exception_log_path ───────────────────────────────────────────────

def test_exception_log_path_uses_context_in_filename(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)

    path = _exception_log_path("my-context")

    assert "my-context" in path.name
    assert path.suffix == ".log"


def test_exception_log_path_sanitises_special_chars(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)

    path = _exception_log_path("bad/context?name")

    assert "/" not in path.name
    assert "?" not in path.name


def test_exception_log_path_fallback_for_empty_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)

    path = _exception_log_path("---")

    assert "unhandled" in path.name


# ── write_exception_report ────────────────────────────────────────────

def test_write_exception_report_creates_log_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)
    monkeypatch.setattr(crash_logging, "FATAL_LOG_PATH", tmp_path / "fatal-crashes.log")

    try:
        raise ValueError("test crash")
    except ValueError:
        import sys
        exc_type, exc_value, exc_tb = sys.exc_info()

    write_exception_report(exc_type, exc_value, exc_tb, context="test")

    log_files = [f for f in tmp_path.glob("*.log") if f.name != "fatal-crashes.log"]
    assert log_files
    content = log_files[0].read_text(encoding="utf-8")
    assert "ValueError" in content
    assert "test crash" in content


def test_write_exception_report_includes_app_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)
    monkeypatch.setattr(crash_logging, "FATAL_LOG_PATH", tmp_path / "fatal-crashes.log")

    try:
        raise RuntimeError("metadata test")
    except RuntimeError:
        import sys
        exc_type, exc_value, exc_tb = sys.exc_info()

    write_exception_report(exc_type, exc_value, exc_tb, context="test")

    log_files = [f for f in tmp_path.glob("*.log") if f.name != "fatal-crashes.log"]
    content = log_files[0].read_text(encoding="utf-8")
    assert "LumaBLE" in content
    assert "Python" in content


# ── _cleanup_exception_logs ───────────────────────────────────────────

def test_cleanup_removes_old_log_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)
    monkeypatch.setattr(crash_logging, "FATAL_LOG_PATH", tmp_path / "fatal-crashes.log")

    old_file = tmp_path / "20200101-120000-old.log"
    old_file.write_text("old crash", encoding="utf-8")
    old_time = (datetime.now() - timedelta(days=400)).timestamp()
    import os
    os.utime(old_file, (old_time, old_time))

    _cleanup_exception_logs()

    assert not old_file.exists()


def test_cleanup_keeps_recent_log_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)
    monkeypatch.setattr(crash_logging, "FATAL_LOG_PATH", tmp_path / "fatal-crashes.log")

    recent = tmp_path / "20260101-120000-recent.log"
    recent.write_text("recent crash", encoding="utf-8")

    _cleanup_exception_logs()

    assert recent.exists()


def test_cleanup_removes_excess_files_beyond_max(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)
    monkeypatch.setattr(crash_logging, "FATAL_LOG_PATH", tmp_path / "fatal-crashes.log")

    for i in range(CRASH_LOG_MAX_FILES + 3):
        f = tmp_path / f"2026010{i % 9 + 1}-{i:06d}-ctx.log"
        f.write_text(f"crash {i}", encoding="utf-8")
        t = (datetime.now() - timedelta(seconds=i)).timestamp()
        import os
        os.utime(f, (t, t))

    _cleanup_exception_logs()

    remaining = [f for f in tmp_path.glob("*.log") if f.name != "fatal-crashes.log"]
    assert len(remaining) <= CRASH_LOG_MAX_FILES


# ── _trim_fatal_log ───────────────────────────────────────────────────

def test_trim_fatal_log_does_nothing_when_file_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)
    monkeypatch.setattr(crash_logging, "FATAL_LOG_PATH", tmp_path / "fatal-crashes.log")

    _trim_fatal_log()  # should not raise


def test_trim_fatal_log_does_nothing_when_file_small(tmp_path, monkeypatch) -> None:
    fatal = tmp_path / "fatal-crashes.log"
    fatal.write_text("small content", encoding="utf-8")
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)
    monkeypatch.setattr(crash_logging, "FATAL_LOG_PATH", fatal)

    _trim_fatal_log()

    assert fatal.read_text(encoding="utf-8") == "small content"


def test_trim_fatal_log_truncates_oversized_file(tmp_path, monkeypatch) -> None:
    fatal = tmp_path / "fatal-crashes.log"
    content = "x" * (FATAL_LOG_MAX_BYTES + 1000)
    fatal.write_text(content, encoding="utf-8")
    monkeypatch.setattr(crash_logging, "CRASH_LOG_DIR", tmp_path)
    monkeypatch.setattr(crash_logging, "FATAL_LOG_PATH", fatal)

    _trim_fatal_log()

    assert fatal.stat().st_size < len(content)
    assert "Trimmed" in fatal.read_text(encoding="utf-8")
