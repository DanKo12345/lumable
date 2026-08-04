"""Screen sync feeding the Live Sync metrics.

The point of these tests is the pair ``(token, frame_id)`` surviving the whole
queued path. A controller holding only "the last frame id" would look correct
until a signal emitted just before a stop arrives after the next run has begun.
"""

from __future__ import annotations

import sys
import types

from app.ambient_controller import AmbientController
from app.color_stream import ColorStreamEngine


def _let_the_rate_gate_pass(engine: ColorStreamEngine) -> None:
    """Ticks are capped to one send per interval; move the clock past it."""
    engine._last_send_ms = engine._elapsed.elapsed() - engine._send_interval_ms


def _tick(engine: ColorStreamEngine) -> None:
    _let_the_rate_gate_pass(engine)
    engine._tick()


# ── the engine is where frames are actually displaced ──────────────────
def test_a_frame_replaced_before_any_tick_is_reported_as_coalesced() -> None:
    engine = ColorStreamEngine(send_interval_ms=100)
    dropped: list[tuple[int, int]] = []
    engine.frame_coalesced.connect(lambda token, frame: dropped.append((token, frame)))
    engine.start(lambda r, g, b: None, initial=(0, 0, 0))

    engine.set_target(10, 20, 30, token=7, frame_id=1)
    engine.set_target(40, 50, 60, token=7, frame_id=2)  # frame 1 never had a turn

    assert dropped == [(7, 1)]


def test_a_frame_the_tick_acted_on_is_not_a_drop() -> None:
    engine = ColorStreamEngine(send_interval_ms=100)
    dropped: list[tuple[int, int]] = []
    engine.frame_coalesced.connect(lambda token, frame: dropped.append((token, frame)))
    engine.start(lambda r, g, b: None, initial=(0, 0, 0))

    engine.set_target(10, 20, 30, token=7, frame_id=1)
    _tick(engine)
    engine.set_target(40, 50, 60, token=7, frame_id=2)

    assert dropped == []


def test_a_colour_the_strip_already_shows_is_not_a_lost_frame() -> None:
    """A still screen produces frame after frame of the same colour. Counting
    those as drops would report a working sync as a failing one."""
    engine = ColorStreamEngine(send_interval_ms=100)
    dropped: list[tuple[int, int]] = []
    engine.frame_coalesced.connect(lambda token, frame: dropped.append((token, frame)))
    engine.set_smoothing(1.0)
    engine.start(lambda r, g, b: None, initial=(0, 0, 0))

    engine.set_target(10, 20, 30, token=7, frame_id=1)
    _tick(engine)  # sent
    engine.set_target(10, 20, 30, token=7, frame_id=2)
    _tick(engine)  # nothing to send: the strip is already this colour
    engine.set_target(10, 20, 30, token=7, frame_id=3)

    assert dropped == []


def test_an_unlabelled_target_is_never_reported() -> None:
    """Sliders and DIY drive their own engines without frame ids; they must not
    produce drop reports for anyone to misattribute."""
    engine = ColorStreamEngine(send_interval_ms=100)
    dropped: list[tuple[int, int]] = []
    engine.frame_coalesced.connect(lambda token, frame: dropped.append((token, frame)))
    engine.start(lambda r, g, b: None, initial=(0, 0, 0))

    engine.set_target(10, 20, 30)
    engine.set_target(40, 50, 60)

    assert dropped == []


# ── the capture path ───────────────────────────────────────────────────
class _FakeShot:
    def __init__(self, width: int = 4, height: int = 4) -> None:
        self.width = width
        self.height = height
        self.bgra = bytes([40, 80, 120, 255] * (width * height))


class _FakeSct:
    """Stands in for an mss session, ending the loop after a fixed run."""

    def __init__(self, frames: int, stop_event) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 8, "height": 8},
            {"left": 0, "top": 0, "width": 8, "height": 8},
        ]
        self._left = frames
        self._stop = stop_event
        self.grabs = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def grab(self, region):
        self.grabs += 1
        self._left -= 1
        if self._left <= 0:
            self._stop.set()
        return _FakeShot()


def _install_fake_mss(monkeypatch, factory) -> None:
    module = types.ModuleType("mss")
    module.mss = factory
    monkeypatch.setitem(sys.modules, "mss", module)


def test_the_capture_loop_counts_every_frame_it_produces(monkeypatch) -> None:
    controller = AmbientController()
    sct = _FakeSct(frames=5, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)

    controller._engine.set_smoothing(1.0)
    controller._engine.start(lambda r, g, b: None, initial=(0, 0, 0))
    token = controller._metrics.start(0.0)
    controller._token = token
    controller._run((0, 0, 0), token)

    session = controller.live_sync_report().session
    assert session.captured == 5
    assert session.processed == 5
    assert session.capture_errors == 0
    assert session.worst_frame_ms >= 0.0


def test_a_bug_in_our_colour_code_is_not_blamed_on_the_screen(monkeypatch) -> None:
    """Reported as a capture failure, a bug in the filter sends the user
    chasing drivers and permissions instead of reaching this application."""
    controller = AmbientController()
    sct = _FakeSct(frames=5, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)

    import app.ambient_controller as module

    def broken_shape(*args, **kwargs):
        raise ValueError("gamma table is empty")

    monkeypatch.setattr(module, "shape_color", broken_shape)
    failures: list[str] = []
    controller.failed.connect(failures.append)

    token = controller._metrics.start(0.0)
    controller._run((0, 0, 0), token)

    session = controller.live_sync_report().session
    assert session.processing_errors == 1
    assert session.capture_errors == 0, "our own bug was charged to the screen"
    assert session.captured == 1, "the frame was grabbed before we mishandled it"
    assert failures and "gamma table" in failures[0]


def test_a_capture_failure_is_recorded_and_is_not_a_ble_error(monkeypatch) -> None:
    controller = AmbientController()

    def explode():
        raise OSError("display disconnected")

    _install_fake_mss(monkeypatch, explode)
    failures: list[str] = []
    controller.failed.connect(failures.append)

    token = controller._metrics.start(0.0)
    controller._run((0, 0, 0), token)

    session = controller.live_sync_report().session
    assert session.capture_errors == 1
    assert session.processing_errors == 0
    assert session.command_errors == 0
    assert failures and "display disconnected" in failures[0]


def test_a_grab_that_fails_mid_run_is_a_capture_failure(monkeypatch) -> None:
    controller = AmbientController()

    class _FailingSct(_FakeSct):
        def grab(self, region):
            raise OSError("the monitor went away")

    _install_fake_mss(monkeypatch, lambda: _FailingSct(frames=5, stop_event=controller._stop))

    token = controller._metrics.start(0.0)
    controller._run((0, 0, 0), token)

    session = controller.live_sync_report().session
    assert session.capture_errors == 1
    assert session.processing_errors == 0
    assert session.captured == 0


# ── the pair must survive the queued path ──────────────────────────────
def test_a_stale_colour_never_reaches_the_strip() -> None:
    """The consequence the counters cannot show. A colour emitted just before a
    stop can be delivered after the next run has begun; if it is passed through,
    the strip is set to a colour from a session the user already ended, and the
    fresh frame it displaced is charged as a drop."""
    controller = AmbientController()
    written: list[tuple[int, int, int]] = []
    controller._engine.set_smoothing(1.0)
    controller._engine.start(lambda r, g, b: written.append((r, g, b)), initial=(0, 0, 0))

    stale_token = controller._metrics.start(0.0)
    controller._token = stale_token
    controller._metrics.stop(1.0)

    fresh_token = controller._metrics.start(10.0)
    controller._token = fresh_token
    fresh_frame = controller._metrics.frame_processed(fresh_token, 10.1, frame_ms=4.0)
    controller._accept_sample(9, 9, 9, fresh_token, fresh_frame)

    # The straggler from the ended session arrives now.
    controller._accept_sample(200, 0, 0, stale_token, 1)

    _tick(controller._engine)
    assert written == [(9, 9, 9)], "a colour from an ended session reached the strip"
    assert controller._metrics.report(11.0).session.frames_coalesced == 0, (
        "the stale colour displaced a live frame"
    )


def test_a_sample_arriving_after_the_run_stopped_is_refused() -> None:
    controller = AmbientController()
    written: list[tuple[int, int, int]] = []
    controller._engine.set_smoothing(1.0)
    controller._engine.start(lambda r, g, b: written.append((r, g, b)), initial=(0, 0, 0))

    token = controller._metrics.start(0.0)
    controller._token = token
    controller._token = 0  # what stop() leaves behind

    controller._accept_sample(200, 0, 0, token, 1)

    _tick(controller._engine)
    # The seed colour the engine was started with may be written; the colour
    # from the ended session must not be.
    assert (200, 0, 0) not in written


def test_a_frame_from_the_previous_run_cannot_land_in_the_current_one() -> None:
    """A colour emitted just before a stop can be delivered after the next run
    has started. It carries its own token, so it is refused rather than counted
    against a session it never belonged to."""
    controller = AmbientController()
    engine = controller._engine
    engine.set_smoothing(1.0)
    engine.start(lambda r, g, b: None, initial=(0, 0, 0))

    stale_token = controller._metrics.start(0.0)
    engine.set_target(1, 2, 3, token=stale_token, frame_id=1)
    controller._metrics.stop(1.0)

    fresh_token = controller._metrics.start(10.0)
    controller._metrics.frame_processed(fresh_token, 10.1, frame_ms=4.0)
    # The straggler from the old run arrives now and displaces nothing that
    # belongs to this session.
    engine.set_target(4, 5, 6, token=fresh_token, frame_id=1)

    session = controller._metrics.report(11.0).session
    assert session.frames_coalesced == 0, "a stale frame was counted as a drop"
    assert session.processed == 1


def test_stopping_freezes_the_run_for_the_export_that_follows(monkeypatch) -> None:
    controller = AmbientController()
    sct = _FakeSct(frames=3, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)

    controller.start(lambda r, g, b: None, initial=(0, 0, 0))
    thread = controller._thread
    if thread is not None:
        thread.join(timeout=5)
    controller.stop()

    first = controller.live_sync_report()
    assert first.session.captured == 3
    assert controller.live_sync_report() == first, "the frozen run kept changing"
