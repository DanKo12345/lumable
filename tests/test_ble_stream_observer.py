"""Reporting the outcome of one streaming write.

Live Sync counts what the link actually did. That needs two things the stream
path did not previously say: whether a write was accepted at all, and how it
ended. No hardware is involved — with nothing connected the write fails, which
is exactly the branch worth pinning.
"""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("PySide6")

from app.ble import BleController


@pytest.fixture()
def controller():
    ble = BleController()
    try:
        yield ble
    finally:
        ble.shutdown()


def test_an_accepted_write_reports_its_outcome_exactly_once(controller) -> None:
    outcomes: list[bool] = []
    done = threading.Event()

    def observer(ok: bool) -> None:
        outcomes.append(ok)
        done.set()

    accepted = controller.set_color_stream(10, 20, 30, observer=observer)

    assert accepted is True
    assert done.wait(timeout=3.0), "the write never reported back"
    # Nothing is connected, so the write fails — the point is that it said so.
    assert outcomes == [False]


def test_a_frame_dropped_for_back_pressure_is_refused_not_failed(controller) -> None:
    """A write already in flight makes the link drop the next frame. That is not
    a failure and must not be reported as one — nor counted as sent."""
    outcomes: list[bool] = []
    controller._stream_busy = True

    accepted = controller.set_color_stream(10, 20, 30, observer=outcomes.append)

    assert accepted is False
    assert outcomes == [], "a frame that was never sent reported an outcome"


def test_a_write_after_shutdown_is_refused(controller) -> None:
    outcomes: list[bool] = []
    controller.shutdown()

    accepted = controller.set_color_stream(10, 20, 30, observer=outcomes.append)

    assert accepted is False
    assert outcomes == []


def test_the_other_modes_call_it_exactly_as_before(controller) -> None:
    """Sliders, DIY, music and the timers pass three arguments and ignore the
    result. Adding the observer must not have changed that path."""
    assert controller.set_color_stream(1, 2, 3) is True
