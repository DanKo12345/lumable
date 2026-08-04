"""Live sync metrics: the numbers that replace "it feels slower".

The load-bearing test is the last one — a run that degrades near the end must be
visible, which is exactly what session averages cannot show.
"""

from __future__ import annotations

import threading

from app.live_sync_metrics import LiveSyncMetrics


def _session(start: float = 100.0, window: float = 30.0):
    metrics = LiveSyncMetrics(window_seconds=window)
    return metrics, metrics.start(start)


def test_a_steady_run_reports_the_same_rate_both_ways() -> None:
    metrics, token = _session()
    for index in range(1, 61):
        metrics.frame_processed(token, 100.0 + index / 30.0, frame_ms=4.0)
        if index % 2 == 0:
            metrics.command_submitted(token, 100.0 + index / 30.0, queue_depth=1)

    report = metrics.report(102.0)

    assert report.session.captured == 60
    assert report.session.processed == 60
    assert report.recent.capture_fps == 30.0
    assert report.recent.command_rate == 15.0
    assert report.recent.frame_ms_avg == 4.0


def test_a_run_that_degrades_late_shows_it_in_the_recent_window() -> None:
    """The whole reason for two layers. Session totals average the healthy first
    half over the bad ending; the recent window does not."""
    metrics, token = _session()

    for index in range(1, 1501):  # 50 seconds at 30 fps
        metrics.frame_processed(token, 100.0 + index / 30.0, frame_ms=4.0)
    # Then the strip falls behind: 5 fps for the next 40 seconds, which is
    # longer than the window, so the recent layer sees only the bad stretch.
    for index in range(1, 201):
        metrics.frame_processed(token, 150.0 + index / 5.0, frame_ms=90.0)

    report = metrics.report(190.0)

    assert report.session.captured == 1700
    assert report.session.seconds == 90.0
    assert report.recent.capture_fps < 10.0, "the recent window hid the slowdown"
    assert report.recent.frame_ms_avg > 50.0


def test_a_coalesced_frame_is_not_an_error() -> None:
    """It means the sync keeps up with the screen but not with the strip, which
    is a different problem from a failed write."""
    metrics, token = _session()

    for index in range(8):
        metrics.frame_processed(token, 100.0 + index * 0.1, frame_ms=3.0)
    for index in range(2):
        metrics.frame_coalesced(token, 101.0 + index * 0.1)

    report = metrics.report(102.0)
    assert (report.session.captured, report.session.processed) == (10, 8)
    assert report.session.frames_coalesced == 2
    assert report.session.command_errors == 0
    assert report.recent.drop_ratio == 0.2


def test_a_failed_write_is_never_counted_as_a_command() -> None:
    metrics, token = _session()

    metrics.command_submitted(token, 100.5, queue_depth=1)
    metrics.command_failed(token, 100.6)
    metrics.command_failed(token, 100.7)

    report = metrics.report(101.0)
    assert report.session.commands_submitted == 1
    assert report.session.command_errors == 2


def test_the_worst_frame_says_when_it_happened() -> None:
    """Without the timestamp, a single stall from minute two reads as a problem
    happening now."""
    metrics, token = _session()

    metrics.frame_processed(token, 102.0, frame_ms=250.0)
    for index in range(200):
        metrics.frame_processed(token, 150.0 + index * 0.03, frame_ms=3.0)

    report = metrics.report(160.0)
    assert report.session.worst_frame_ms == 250.0
    assert report.session.worst_frame_at == 2.0
    assert report.recent.frame_ms_p95 < 10.0, "an old stall must not colour the present"


def test_the_p95_catches_what_the_average_smooths_over() -> None:
    metrics, token = _session()

    # 10% slow frames: with exactly 5% the 95th value sits on the boundary and
    # the assertion would be about rounding rather than about the metric.
    for index in range(90):
        metrics.frame_processed(token, 100.0 + index * 0.01, frame_ms=5.0)
    for index in range(10):
        metrics.frame_processed(token, 101.0 + index * 0.01, frame_ms=120.0)

    recent = metrics.report(102.0).recent
    # The claim is the gap, not either number: an average of ~17ms looks fine
    # while one frame in ten takes 120ms, which is the stutter people report.
    assert recent.frame_ms_p95 >= 100.0
    assert recent.frame_ms_p95 > recent.frame_ms_avg * 5


def test_the_deepest_queue_of_the_session_is_kept_and_the_current_one_reported() -> None:
    metrics, token = _session()

    for depth in (1, 9, 2):
        metrics.command_submitted(token, 100.5, queue_depth=depth)

    report = metrics.report(101.0)
    assert report.session.queue_max == 9
    assert report.recent.queue_depth == 2


def test_taking_a_snapshot_changes_nothing() -> None:
    """Diagnostics can be exported repeatedly; that must not move the numbers."""
    metrics, token = _session()
    metrics.frame_processed(token, 100.5, frame_ms=7.0)
    metrics.command_submitted(token, 100.6, queue_depth=3)

    first = metrics.report(101.0)
    for _ in range(5):
        metrics.report(101.0)
    again = metrics.report(101.0)

    assert first == again


def test_restarting_forgets_the_previous_session() -> None:
    metrics, token = _session()
    metrics.frame_processed(token, 100.5, frame_ms=40.0)
    metrics.frame_coalesced(token, 100.6)
    metrics.command_submitted(token, 100.7, queue_depth=7)
    metrics.reconnected(token)

    token = metrics.start(200.0)
    report = metrics.report(200.0)

    assert report.session.captured == 0
    assert report.session.worst_frame_ms == 0.0
    assert report.session.queue_max == 0
    assert report.recent.capture_fps == 0.0


def test_an_empty_session_reports_zeroes_rather_than_dividing_by_them() -> None:
    metrics, _token = _session()
    report = metrics.report(100.0)

    assert report.session.captured == 0
    assert report.recent.capture_fps == 0.0
    assert report.recent.drop_ratio == 0.0
    assert report.recent.frame_ms_p95 == 0.0


def test_recording_from_several_threads_loses_nothing() -> None:
    """Frames come from the capture thread while the UI reads the report."""
    metrics, token = _session()
    barrier = threading.Barrier(4)

    def record() -> None:
        barrier.wait(timeout=5)
        for index in range(250):
            metrics.frame_processed(token, 100.0 + index * 0.001, frame_ms=2.0)

    readers: list = []

    def read() -> None:
        barrier.wait(timeout=5)
        for _ in range(100):
            readers.append(metrics.report(101.0))

    threads = [threading.Thread(target=record) for _ in range(3)]
    threads.append(threading.Thread(target=read))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert metrics.report(101.0).session.captured == 750
    assert len(readers) == 100


def test_another_mode_writing_to_the_same_path_is_not_counted() -> None:
    """Colour sliders, DIY and music share the streaming path with Screen Sync.
    Counting where they meet would put someone dragging a slider into the Live
    Sync report."""
    metrics, token = _session()
    metrics.frame_processed(token, 100.1, frame_ms=4.0)

    slider_token = token + 1000  # not a session we started
    metrics.command_submitted(slider_token, 100.2, queue_depth=3)
    metrics.frame_processed(slider_token, 100.3, frame_ms=99.0)

    report = metrics.report(101.0)
    assert report.session.captured == 1
    assert report.session.commands_submitted == 0
    assert report.session.worst_frame_ms == 4.0


def test_a_late_result_from_the_previous_session_is_dropped() -> None:
    metrics, first = _session()
    metrics.frame_processed(first, 100.1, frame_ms=4.0)
    metrics.stop(101.0)

    second = metrics.start(200.0)
    metrics.command_succeeded(first, 200.5)  # the old session's callback arrives
    metrics.frame_processed(second, 200.6, frame_ms=3.0)

    report = metrics.report(201.0)
    assert report.session.commands_succeeded == 0
    assert report.session.captured == 1


def test_nothing_is_recorded_while_no_session_runs() -> None:
    metrics = LiveSyncMetrics()

    metrics.frame_processed(0, 100.0, frame_ms=5.0)
    metrics.command_submitted(1, 100.1)

    assert metrics.report(101.0).session.captured == 0


def test_stopping_keeps_the_numbers_for_the_export_that_follows() -> None:
    """Diagnostics is usually exported after stopping; losing the run at that
    moment would leave nothing to report."""
    metrics, token = _session()
    for index in range(10):
        metrics.frame_processed(token, 100.0 + index * 0.1, frame_ms=6.0)

    metrics.stop(101.0)
    later = metrics.report(400.0)

    assert later.session.captured == 10
    assert later.session.seconds == 0.9
    assert later.recent.capture_fps > 0, "the frozen window must not decay to zero"


def test_a_capture_failure_is_not_a_ble_failure() -> None:
    """Which end is at fault is the first question when sync stops working."""
    metrics, token = _session()

    metrics.capture_failed(token, 100.2)
    metrics.command_failed(token, 100.3)

    report = metrics.report(101.0)
    assert report.session.capture_errors == 1
    assert report.session.command_errors == 1


def test_submitted_is_not_the_sum_of_succeeded_and_failed() -> None:
    """Some writes are still in flight when the snapshot is taken; making the
    totals add up would mean lying about timing."""
    metrics, token = _session()

    for _ in range(5):
        metrics.command_submitted(token, 100.1, queue_depth=1)
    metrics.command_succeeded(token, 100.2)
    metrics.command_failed(token, 100.3)

    report = metrics.report(101.0)
    assert report.session.commands_submitted == 5
    assert report.session.commands_succeeded + report.session.command_errors == 2
