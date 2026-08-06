"""Screen sync feeding the Live Sync metrics.

The point of these tests is the pair ``(token, frame_id)`` surviving the whole
queued path. A controller holding only "the last frame id" would look correct
until a signal emitted just before a stop arrives after the next run has begun.
"""

from __future__ import annotations

import sys
import threading
import types

import pytest

from app.ambient_controller import AmbientController
from app.color_stream import ColorStreamEngine


@pytest.fixture(autouse=True)
def _stop_every_engine_started_here():
    """Starting the stream engine starts a QTimer, and a test that leaves one
    running leaves a live timer pointing at an object the test dropped. It fires
    inside whatever processes events next — another test's ``processEvents``, in
    a different file — and takes the interpreter down there, where nothing looks
    related. Stopping is tracked at ``start`` so no call site can forget."""
    started: list[ColorStreamEngine] = []
    original = ColorStreamEngine.start

    def tracked(self, *args, **kwargs):
        started.append(self)
        return original(self, *args, **kwargs)

    ColorStreamEngine.start = tracked
    try:
        yield
    finally:
        ColorStreamEngine.start = original
        for engine in started:
            try:
                engine.stop()
            except RuntimeError:
                # Its owner was collected first and took the C++ timer with it.
                # That one cannot fire again either, which is all we needed.
                pass


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


def test_the_wait_is_what_is_left_of_the_period_not_a_fresh_one(monkeypatch) -> None:
    """Pausing a full interval after the work makes the real rate
    ``work + interval``. With 25 ms of colour work under a 50 ms period that is
    13 fps rather than 20 — and the report then reads as slow sampling when the
    sampling had 25 ms of room to spare."""
    controller = AmbientController()
    controller.configure(interval_s=0.05)
    sct = _FakeSct(frames=4, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)

    clock = [1000.0]
    waits: list[float] = []

    def fake_monotonic() -> float:
        return clock[0]

    def fake_wait(delay: float = 0.0) -> bool:
        waits.append(delay)
        clock[0] += delay
        return controller._stop.is_set()

    import app.ambient_controller as module

    monkeypatch.setattr(module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(controller._stop, "wait", fake_wait)

    # Every grab costs 25 ms of the 50 ms period.
    original_grab = sct.grab

    def slow_grab(region):
        clock[0] += 0.025
        return original_grab(region)

    sct.grab = slow_grab

    token = controller._metrics.start(clock[0])
    controller._token = token
    controller._run((0, 0, 0), token)

    assert waits, "the loop never waited"
    assert all(abs(delay - 0.025) < 1e-6 for delay in waits), (
        f"the loop waited a full period on top of the work: {waits}"
    )


def test_a_frame_that_overruns_its_slot_does_not_burst_afterwards(monkeypatch) -> None:
    """Catching up on missed frames would fire several back to back at the
    strip and then stall again. The schedule restarts instead."""
    controller = AmbientController()
    controller.configure(interval_s=0.05)
    sct = _FakeSct(frames=3, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)

    clock = [1000.0]
    waits: list[float] = []

    def fake_wait(delay: float = 0.0) -> bool:
        waits.append(delay)
        clock[0] += delay
        return controller._stop.is_set()

    import app.ambient_controller as module

    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(controller._stop, "wait", fake_wait)

    original_grab = sct.grab

    def slow_grab(region):
        clock[0] += 0.4  # eight periods in one frame
        return original_grab(region)

    sct.grab = slow_grab

    token = controller._metrics.start(clock[0])
    controller._token = token
    controller._run((0, 0, 0), token)

    assert waits and all(delay > 0.0 for delay in waits), (
        "a frame that overran left no pause at all"
    )
    assert all(delay < 0.05 for delay in waits)


def test_the_reported_settings_are_the_ones_that_made_the_colour(monkeypatch) -> None:
    """Read from the live options instead, the report pairs the colour of a
    finished run with a profile chosen afterwards — and describes something
    that never happened."""
    controller = AmbientController()
    controller.configure(profile_id="desktop", region="full")
    sct = _FakeSct(frames=3, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)

    token = controller._metrics.start(0.0)
    controller._token = token
    controller._run((0, 0, 0), token)
    after_run = controller.live_sync_settings()

    # The user pokes at the card after stopping, then exports.
    controller.configure(profile_id="movie", region="center", intensity=90)

    settings = controller.live_sync_settings()
    assert settings["profile"] == "desktop"
    assert settings["region"] == "full"
    assert settings["intensity"] != 90
    assert settings == after_run


def test_a_run_that_dies_before_its_first_frame_shows_no_colour(monkeypatch) -> None:
    """Otherwise the failed run wears the colour of the last one that worked,
    which is the most convincing wrong answer the report could give."""
    controller = AmbientController()

    def run_once() -> None:
        """Through the real start/stop, so the clearing under test is exercised
        rather than reproduced by hand."""
        controller.start(lambda *args: True, initial=(0, 0, 0))
        thread = controller._thread
        if thread is not None:
            thread.join(timeout=5)
        controller.stop()

    sct = _FakeSct(frames=2, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)
    run_once()
    assert controller.live_sync_settings()["sampled"] is True

    class _DeadSct(_FakeSct):
        def grab(self, region):
            raise OSError("the monitor went away")

    _install_fake_mss(monkeypatch, lambda: _DeadSct(frames=1, stop_event=controller._stop))
    run_once()

    assert controller.live_sync_settings() == {"sampled": False}


def test_changing_the_profile_mid_run_moves_settings_and_colour_together(monkeypatch) -> None:
    controller = AmbientController()
    controller.configure(profile_id="desktop")
    sct = _FakeSct(frames=4, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)

    original_grab = sct.grab

    def switching_grab(region):
        if sct.grabs == 1:  # after the first frame, as the card's toggle would
            controller.configure(profile_id="movie")
        return original_grab(region)

    sct.grab = switching_grab

    token = controller._metrics.start(0.0)
    controller._token = token
    controller._run((0, 0, 0), token)

    settings = controller.live_sync_settings()
    assert settings["profile"] == "movie", "the report kept the profile the run began with"
    assert settings["raw_rgb"] is not None and settings["final_rgb"] is not None


def test_a_switch_during_the_last_frame_does_not_relabel_it(monkeypatch) -> None:
    """A frame is made with the options read at the top of its iteration. If the
    user switches profile while that frame is being processed, re-reading the
    options at the end would label the colour with a profile that had no part in
    producing it — the same lie as reading them at export time, just narrower."""
    controller = AmbientController()
    controller.configure(profile_id="desktop")
    sct = _FakeSct(frames=2, stop_event=controller._stop)
    _install_fake_mss(monkeypatch, lambda: sct)

    original_grab = sct.grab

    def switching_grab(region):
        shot = original_grab(region)
        if sct.grabs == 2:  # during the final frame, after its options were read
            controller.configure(profile_id="movie")
        return shot

    sct.grab = switching_grab

    token = controller._metrics.start(0.0)
    controller._token = token
    controller._run((0, 0, 0), token)

    assert controller._options.profile_id == "movie", "the switch did not happen"
    assert controller.live_sync_settings()["profile"] == "desktop", (
        "the colour was labelled with a profile that never touched it"
    )


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
# ── what the BLE layer did, not what the capture loop hoped ───────────
def _running_controller(sink) -> AmbientController:
    """A controller wired to ``sink`` with a session open, without a capture
    thread — the tests below are about the send path, not the screen."""
    controller = AmbientController()
    controller._sink = sink
    controller._engine.set_smoothing(1.0)
    controller._engine.start(controller._deliver, initial=(0, 0, 0), labelled_sink=True)
    controller._token = controller._metrics.start(0.0)
    return controller


def test_a_write_the_link_refused_to_take_is_not_a_submitted_command() -> None:
    """The BLE layer refuses a frame while an earlier write is still going.
    Counting those would report a send rate the strip never saw."""
    accepted: list[bool] = [True, False, True]
    calls: list[tuple[int, int]] = []

    def sink(r, g, b, token, frame_id):
        calls.append((token, frame_id))
        return accepted.pop(0)

    controller = _running_controller(sink)
    token = controller._token
    for colour in (10, 20, 30):
        controller._accept_sample(colour, 0, 0, token, controller._metrics.frame_processed(token, 0.1))
        _tick(controller._engine)

    session = controller.live_sync_report().session
    assert len(calls) == 3, "every frame reached the link"
    assert session.commands_submitted == 2, "a refused write was counted as sent"
    assert session.link_rejections == 1
    assert session.command_errors == 0, "back-pressure was reported as a failure"


def test_a_refused_colour_is_offered_again_and_is_not_lost() -> None:
    """The worst outcome of getting this wrong is silent and permanent: on a
    still screen no later frame differs from the refused one, so if the engine
    believes it was sent, the strip keeps the previous colour for the rest of
    the session."""
    outcomes: list[bool] = [False, True]
    written: list[tuple[int, int, int]] = []
    frames: list[int] = []

    def sink(r, g, b, token, frame_id):
        written.append((r, g, b))
        frames.append(frame_id)
        return outcomes.pop(0)

    controller = _running_controller(sink)
    token = controller._token
    frame = controller._metrics.frame_processed(token, 0.1)
    controller._accept_sample(90, 10, 5, token, frame)

    _tick(controller._engine)  # refused
    _tick(controller._engine)  # no newer frame: the same colour must be retried

    assert written == [(90, 10, 5), (90, 10, 5)], "a refused colour was never retried"
    # The retry is the same frame trying again, so it must keep its identity —
    # a retry that forgot it would submit a colour no frame claims, and the
    # session token on it would be 0.
    assert frames == [frame, frame]
    session = controller.live_sync_report().session
    assert session.commands_submitted == 1
    assert session.link_rejections == 1


def test_a_result_that_arrives_inline_is_counted_after_its_command() -> None:
    """An already-finished future runs its callback inside add_done_callback,
    on this thread, before the submit call returns. A snapshot taken in between
    would show a success for a command that had not been submitted yet."""
    seen: list[tuple[int, int]] = []
    controller = None

    def sink(r, g, b, token, frame_id):
        # The link answers immediately, from inside the submit call.
        controller.command_finished(token, frame_id, ok=True)
        session = controller.live_sync_report().session
        seen.append((session.commands_submitted, session.commands_succeeded))
        return True

    controller = _running_controller(sink)
    token = controller._token
    frame = controller._metrics.frame_processed(token, 0.1)
    controller._accept_sample(1, 2, 3, token, frame)
    _tick(controller._engine)

    assert seen == [(0, 0)], "a result was recorded before its command"
    session = controller.live_sync_report().session
    assert (session.commands_submitted, session.commands_succeeded) == (1, 1)


def test_the_frame_that_produced_a_write_is_the_one_the_result_belongs_to() -> None:
    results: list[tuple[int, int]] = []

    def sink(r, g, b, token, frame_id):
        results.append((token, frame_id))
        return True

    controller = _running_controller(sink)
    token = controller._token
    frame = controller._metrics.frame_processed(token, 0.1, frame_ms=4.0)
    controller._accept_sample(1, 2, 3, token, frame)
    _tick(controller._engine)

    assert results == [(token, frame)]

    controller.command_finished(token, frame, ok=True)
    session = controller.live_sync_report().session
    assert session.commands_succeeded == 1
    assert session.command_errors == 0


def test_a_failed_write_is_counted_once_and_never_as_a_success() -> None:
    controller = _running_controller(lambda *args: True)
    token = controller._token
    frame = controller._metrics.frame_processed(token, 0.1)
    controller._accept_sample(1, 2, 3, token, frame)
    _tick(controller._engine)

    controller.command_finished(token, frame, ok=False)

    session = controller.live_sync_report().session
    assert session.command_errors == 1
    assert session.commands_succeeded == 0
    assert session.capture_errors == 0, "a link failure was blamed on the screen"


def test_a_previous_command_finishing_during_a_refused_attempt_is_not_lost() -> None:
    """Buffering by "a submit is in progress" rather than by which command is
    being submitted swallows this: the earlier write's result lands in the
    buffer, the refused attempt returns without applying it, and a confirmed
    write disappears from the report."""
    controller = None
    frames: list[int] = []
    outcomes = [True, False]

    def sink(r, g, b, token, frame_id):
        accepted = outcomes.pop(0)
        if not accepted:
            # The earlier write reports back exactly while this one is refused.
            controller.command_finished(token, frames[0], ok=True)
        return accepted

    controller = _running_controller(sink)
    token = controller._token
    for colour in (10, 20):
        frames.append(controller._metrics.frame_processed(token, 0.1))
        controller._accept_sample(colour, 0, 0, token, frames[-1])
        _tick(controller._engine)

    session = controller.live_sync_report().session
    assert session.commands_submitted == 1
    assert session.link_rejections == 1
    assert session.commands_succeeded == 1, "a confirmed write vanished"


def test_a_snapshot_never_shows_a_success_for_a_command_not_yet_submitted() -> None:
    """The result of the write being handed over arrives from the BLE thread.
    It must wait for the command to exist, and the ordering has to hold whether
    the thread lands before the sink returns or while the count is being made."""
    applied: list[tuple[int, int]] = []

    class _Watching(AmbientController):
        def _record_result(self, token: int, ok: bool, now: float) -> None:
            session = self._metrics.report(now).session
            applied.append((session.commands_submitted, session.commands_succeeded))
            super()._record_result(token, ok, now)

    controller = _Watching()

    def sink(r, g, b, token, frame_id):
        # A real BLE completion, on its own thread, during the hand-over.
        worker = threading.Thread(
            target=controller.command_finished, args=(token, frame_id, True)
        )
        worker.start()
        worker.join(timeout=5)
        return True

    controller._sink = sink
    controller._engine.set_smoothing(1.0)
    controller._engine.start(controller._deliver, initial=(0, 0, 0), labelled_sink=True)
    controller._token = controller._metrics.start(0.0)
    token = controller._token

    frame = controller._metrics.frame_processed(token, 0.1)
    controller._accept_sample(5, 6, 7, token, frame)
    _tick(controller._engine)

    assert applied == [(1, 0)], "the result was applied before its command existed"
    session = controller.live_sync_report().session
    assert (session.commands_submitted, session.commands_succeeded) == (1, 1)


def test_the_invariant_holds_under_real_concurrency() -> None:
    """Many hand-overs with results arriving from other threads. No observer
    should ever see more successes than submitted commands."""
    controller = None
    workers: list[threading.Thread] = []

    def sink(r, g, b, token, frame_id):
        worker = threading.Thread(
            target=controller.command_finished, args=(token, frame_id, True)
        )
        workers.append(worker)
        worker.start()
        return True

    controller = _running_controller(sink)
    token = controller._token
    violations: list[tuple[int, int]] = []
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            session = controller.live_sync_report().session
            if session.commands_succeeded > session.commands_submitted:
                violations.append(
                    (session.commands_submitted, session.commands_succeeded)
                )

    reader = threading.Thread(target=watch)
    reader.start()
    try:
        for index in range(200):
            frame = controller._metrics.frame_processed(token, 0.1)
            controller._accept_sample(index % 200, 0, 0, token, frame)
            _tick(controller._engine)
    finally:
        stop.set()
        reader.join(timeout=5)
        for worker in workers:
            worker.join(timeout=5)

    assert violations == [], f"a success outran its command: {violations[:3]}"


def test_a_result_from_an_ended_session_lands_nowhere() -> None:
    """A write submitted just before a stop finishes afterwards. It belongs to
    the run that made it, and that run's numbers are already frozen."""
    controller = _running_controller(lambda *args: True)
    stale_token = controller._token
    stale_frame = controller._metrics.frame_processed(stale_token, 0.1)
    controller._metrics.stop(1.0)

    fresh_token = controller._metrics.start(10.0)
    controller._token = fresh_token
    controller.command_finished(stale_token, stale_frame, ok=True)

    session = controller.live_sync_report().session
    assert session.commands_succeeded == 0, "an old run's result was charged to this one"


def test_a_colour_the_strip_already_shows_invents_no_command() -> None:
    calls: list = []

    def sink(r, g, b, token, frame_id):
        calls.append((r, g, b))
        return True

    controller = _running_controller(sink)
    token = controller._token
    for _ in range(3):
        frame = controller._metrics.frame_processed(token, 0.1)
        controller._accept_sample(7, 7, 7, token, frame)
        _tick(controller._engine)

    assert calls == [(7, 7, 7)], "the same colour was written again"
    assert controller.live_sync_report().session.commands_submitted == 1


def test_a_frame_displaced_before_the_tick_is_never_submitted() -> None:
    calls: list = []

    def sink(r, g, b, token, frame_id):
        calls.append(frame_id)
        return True

    controller = _running_controller(sink)
    token = controller._token
    first = controller._metrics.frame_processed(token, 0.1)
    second = controller._metrics.frame_processed(token, 0.2)
    controller._accept_sample(1, 0, 0, token, first)
    controller._accept_sample(2, 0, 0, token, second)  # first never had a turn
    _tick(controller._engine)

    session = controller.live_sync_report().session
    assert calls == [second]
    assert session.commands_submitted == 1
    assert session.frames_coalesced == 1


def test_a_reconnect_while_another_mode_owns_the_strip_is_not_counted() -> None:
    """The BLE layer's reconnect signal belongs to the whole app. Music or DIY
    losing the strip and getting it back is not a Screen Sync event.

    The order matters: a reconnect *before* any session, checked against a live
    report. Stopping first would freeze the numbers and hide a missing guard
    rather than test it.
    """
    controller = AmbientController()

    controller.note_reconnect()  # nothing of ours is running

    assert controller.live_sync_report().session.reconnects == 0

    token = controller._metrics.start(0.0)
    controller._token = token
    controller.note_reconnect()
    assert controller.live_sync_report().session.reconnects == 1


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
