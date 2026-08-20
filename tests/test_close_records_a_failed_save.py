"""A settings write that fails while the window closes must leave a trace.

The file itself is never at risk — the write is atomic, so a failure leaves the
previous settings exactly as they were and only this session's unsaved changes
are lost. What was wrong is that it happened in silence: a close is when a write
is most likely to fail, with the lock still held by something else or the disk
full, and nothing recorded that it had.

Closing still succeeds and nothing is shown. Blocking the close or raising a
dialog on the way out would trade a small, invisible loss for a large, visible
obstruction.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from app import crash_logging


@pytest.fixture()
def window():
    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    app.processEvents()
    try:
        yield win
    finally:
        win._ble.shutdown()
        win.close()


def _close_with_a_broken_save(window, monkeypatch) -> list[str]:
    """Close the window with the settings write refusing, and collect contexts."""
    recorded: list[str] = []

    def refuse() -> None:
        raise OSError("the settings file is locked")

    def note(*, context: str = "unhandled", thread_name: str | None = None):
        recorded.append(context)
        return None

    monkeypatch.setattr(window, "_save_window_settings", refuse)
    monkeypatch.setattr(crash_logging, "write_current_exception", note)
    monkeypatch.setattr(
        window._tray_controller, "should_minimize_on_close", lambda: False, raising=False
    )

    event = QCloseEvent()
    window.closeEvent(event)
    return recorded, event


def test_a_failed_save_is_recorded_under_its_own_context(window, monkeypatch) -> None:
    recorded, _event = _close_with_a_broken_save(window, monkeypatch)

    assert recorded == ["close_save_settings"], (
        f"the failure was not recorded, or not as its own kind of failure: {recorded}"
    )


def test_closing_carries_on_exactly_as_it_would_have(window, monkeypatch) -> None:
    """A save that cannot happen is not a reason to keep someone in the app.

    Acceptance of the event is not the measure here: this window closes in two
    stages and deliberately ignores the first event while the strip is let go.
    What has to hold is that a failed save changes nothing about the sequence —
    the close is requested and the window stops taking input, exactly as it
    does when the save works.
    """
    assert window._close_requested is False

    _recorded, _event = _close_with_a_broken_save(window, monkeypatch)

    assert window._close_requested is True, "the close sequence never started"
    assert window.isEnabled() is False, "the window kept taking input"


def test_a_save_that_works_records_nothing(window, monkeypatch) -> None:
    """The counterpart: an ordinary close must not leave a crash report behind,
    or the log fills with entries for a thing that went fine."""
    recorded: list[str] = []
    monkeypatch.setattr(
        crash_logging,
        "write_current_exception",
        lambda **kwargs: recorded.append(kwargs.get("context", "")),
    )
    monkeypatch.setattr(
        window._tray_controller, "should_minimize_on_close", lambda: False, raising=False
    )

    window.closeEvent(QCloseEvent())

    assert recorded == []
