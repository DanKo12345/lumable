"""The Live Sync block of the diagnostics report.

These tests are about wording as much as arithmetic. The report is read by
someone who was not here when it was written, and every number in it has a
plausible wrong reading — a caption that invites one is a defect.
"""

from __future__ import annotations

from app.live_sync_metrics import LiveSyncMetrics, LiveSyncReport
from app.live_sync_text import format_live_sync


def _text(report: LiveSyncReport, **kwargs) -> str:
    return "\n".join(format_live_sync(report, **kwargs))


def test_a_session_that_never_ran_adds_nothing() -> None:
    """A block of zeros would read as "measured, all quiet" when the truth is
    "never measured"."""
    assert format_live_sync(LiveSyncReport()) == []


def test_a_broken_invariant_is_shown_rather_than_hidden() -> None:
    """A result without a submission cannot happen today. If it ever does, the
    report has to say so — deciding it is impossible and printing nothing would
    hide exactly the contradiction worth seeing."""
    from app.live_sync_metrics import SessionTotals

    impossible = LiveSyncReport(session=SessionTotals(commands_succeeded=3))

    text = _text(impossible, running=False)
    assert "commands: 0 submitted, 3 succeeded, 0 failed" in text


def test_a_running_session_reports_both_layers() -> None:
    metrics = LiveSyncMetrics()
    token = metrics.start(100.0)
    for index in range(1, 61):
        at = 100.0 + index / 30.0
        metrics.frame_captured(token, at)
        frame = metrics.frame_processed(token, at, frame_ms=4.0)
        if index % 3 == 0:
            metrics.command_submitted(token, at)
            metrics.command_succeeded(token, at)
        if index % 10 == 0:
            metrics.frame_coalesced(token, frame)

    text = _text(metrics.report(102.0), running=True)

    assert "Live Sync — session" in text
    assert "mode: screen (running)" in text
    assert "duration: 2.0s" in text
    assert "frames: 60 captured, 60 processed, 6 coalesced" in text
    assert "commands: 20 submitted, 20 succeeded, 0 failed" in text
    assert "Live Sync — last 30 seconds" in text
    assert "capture: 30.0 fps" in text
    assert "processing time: 4.0 ms avg, 4.0 ms p95" in text


def test_the_three_error_kinds_stay_apart() -> None:
    """Which end is at fault is the first question a report has to answer: the
    screen, this application, or the strip."""
    metrics = LiveSyncMetrics()
    token = metrics.start(100.0)
    metrics.capture_failed(token, 100.1)
    metrics.capture_failed(token, 100.2)
    metrics.processing_failed(token, 100.3)
    metrics.command_submitted(token, 100.4)
    metrics.command_failed(token, 100.5)
    metrics.link_rejected(token, 100.6)

    text = _text(metrics.report(101.0), running=True)

    assert "frame errors: 2 capture, 1 processing" in text
    assert "commands: 1 submitted, 0 succeeded, 1 failed" in text
    assert "link rejections: 1" in text


def test_link_rejections_are_not_presented_as_write_errors() -> None:
    """They are back-pressure: the link was busy and the same colour is offered
    again. Read as BLE errors they send someone hunting a strip fault."""
    metrics = LiveSyncMetrics()
    token = metrics.start(100.0)
    for _ in range(4):
        metrics.link_rejected(token, 100.1)
    metrics.command_submitted(token, 100.2)

    text = _text(metrics.report(101.0), running=True)

    assert "link rejections: 4 (link busy, not a write error)" in text
    assert "link rejection rate: 0.8 (share of attempts refused)" in text


def test_the_drop_ratio_says_what_it_counts() -> None:
    """Displaced frames, not failed writes."""
    metrics = LiveSyncMetrics()
    token = metrics.start(100.0)
    frames = [metrics.frame_processed(token, 100.0 + i * 0.1, frame_ms=3.0) for i in range(4)]
    metrics.frame_coalesced(token, frames[0])

    text = _text(metrics.report(101.0), running=True)

    assert "drop ratio: 0.25 (frames displaced before sending)" in text


def test_writes_still_in_flight_are_named_rather_than_left_to_subtraction() -> None:
    """Submitted is not the sum of the other two. Unexplained, the reader
    concludes the counters are broken."""
    metrics = LiveSyncMetrics()
    token = metrics.start(100.0)
    for _ in range(5):
        metrics.command_submitted(token, 100.1)
    metrics.command_succeeded(token, 100.2)
    metrics.command_failed(token, 100.3)

    text = _text(metrics.report(101.0), running=True)

    assert "commands: 5 submitted, 1 succeeded, 1 failed, 3 still in flight" in text


def test_a_stopped_session_shows_its_own_last_seconds_not_zeros() -> None:
    """Diagnostics is usually exported after switching sync off. A window
    measured from the moment of export would be empty every time, and the run
    the user is asking about would have no numbers at all."""
    metrics = LiveSyncMetrics()
    token = metrics.start(100.0)
    for index in range(1, 61):
        at = 100.0 + index / 30.0
        metrics.frame_captured(token, at)
        metrics.frame_processed(token, at, frame_ms=5.0)
    metrics.stop(102.0)

    text = _text(metrics.report(900.0), running=False)

    assert "mode: screen (stopped)" in text
    assert "Live Sync — last 30 seconds of the run" in text
    assert "capture: 30.0 fps" in text, "the finished run reported as zeros"
    assert "duration: 2.0s" in text


def test_the_worst_frame_is_placed_in_the_run() -> None:
    metrics = LiveSyncMetrics()
    token = metrics.start(100.0)
    metrics.frame_processed(token, 102.0, frame_ms=250.0)
    metrics.frame_processed(token, 103.0, frame_ms=4.0)

    text = _text(metrics.report(140.0), running=True)

    assert "worst frame: 250.0 ms at 2.0s into the run" in text
