import sys
from types import SimpleNamespace

import pytest

from app import music_controller as module
from app.music_controller import MusicController


def test_capture_reopens_after_failure_and_closes_each_reader(monkeypatch):
    controller = MusicController()
    events = []
    states = []
    failures = []
    controller.recovery_changed.connect(lambda token, value: states.append(value))
    controller.failed.connect(failures.append)
    monkeypatch.setattr(module, "CAPTURE_RETRY_DELAYS", (0, 0, 0))

    def open_reader(options):
        number = events.count("open")
        events.append("open")

        def read(size):
            if number == 0:
                raise OSError("device removed")
            return [0] * size

        return read, lambda: events.append("close"), 48000

    monkeypatch.setattr(controller, "_open_loopback_reader", open_reader)
    monkeypatch.setattr(controller, "_process_block", lambda *args: module.BlockResult(
        rgb=(10, 10, 10), level=0.2
    ))
    controller.modulation_sampled.connect(lambda sample: controller._stop.set())
    controller._run()

    assert events == ["open", "close", "open", "close"]
    assert states == [True, False]
    assert failures == []


def test_recovery_has_a_finite_attempt_budget(monkeypatch):
    controller = MusicController()
    attempts = []
    failures = []
    delays = []
    monkeypatch.setattr(controller._stop, "wait", lambda delay: delays.append(delay))

    def unavailable(options):
        attempts.append(options)
        raise OSError("device removed")

    monkeypatch.setattr(controller, "_open_loopback_reader", unavailable)
    controller.failed.connect(failures.append)
    controller._run()
    assert len(attempts) == 4
    assert delays == [1.0, 2.0, 4.0]
    assert len(failures) == 1


def test_stopping_during_retry_wait_prevents_reopening(monkeypatch):
    controller = MusicController()
    attempts = []
    failures = []

    def unavailable(options):
        attempts.append(options)
        raise OSError("device removed")

    def wait(delay):
        controller._stop.set()
        return True

    monkeypatch.setattr(controller, "_open_loopback_reader", unavailable)
    monkeypatch.setattr(controller._stop, "wait", wait)
    controller.failed.connect(failures.append)
    controller._run()
    assert len(attempts) == 1
    assert failures == []


def test_late_block_after_stop_is_not_analyzed_or_emitted(monkeypatch):
    controller = MusicController()
    closed = []
    samples = []

    def read(size):
        controller._stop.set()
        return [0] * size

    monkeypatch.setattr(controller, "_open_loopback_reader", lambda options: (
        read, lambda: closed.append(True), 48000
    ))
    controller.modulation_sampled.connect(samples.append)
    controller._run()
    assert controller._analyzer.stats.blocks == 0
    assert samples == []
    assert closed == [True]


def test_still_alive_capture_blocks_a_second_start(monkeypatch):
    controller = MusicController()
    old_thread = SimpleNamespace(is_alive=lambda: True, join=lambda **kwargs: None)
    controller._thread = old_thread
    controller.stop()
    token = controller.session_token()
    controller.start_listening()
    assert controller._thread is old_thread
    assert controller.session_token() == token
    assert controller._stop.is_set()


def test_recovery_keeps_beat_identity_but_forgets_signal_profile():
    controller = MusicController()
    analyzer = controller._analyzer
    for index in range(30):
        analyzer.feed(bass=0.2, mid=0.2, treble=0.2, rms=0.1, now_ms=index * 20)
    first = analyzer.feed(bass=1.2, mid=0.2, treble=0.2, rms=0.3, now_ms=800)
    assert first.beat
    controller._reset_analysis(preserve_beat_id=True)
    assert analyzer.stats.blocks == 0
    for index in range(30):
        analyzer.feed(bass=0.2, mid=0.2, treble=0.2, rms=0.1, now_ms=1000 + index * 20)
    second = analyzer.feed(bass=1.2, mid=0.2, treble=0.2, rms=0.3, now_ms=1800)
    assert second.beat_id > first.beat_id


@pytest.mark.parametrize("fails_at_start", [True, False])
def test_microphone_resources_close_even_when_driver_raises(monkeypatch, fails_at_start):
    controller = MusicController()
    created = []
    closed = []

    class Stream:
        def __init__(self, **kwargs):
            created.append(self)

        def start(self):
            if fails_at_start:
                raise OSError("start failed")

        def stop(self):
            raise OSError("stop failed")

        def close(self):
            closed.append(self)

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(
        InputStream=Stream,
        query_devices=lambda *args: {"default_samplerate": 48000},
    ))
    if fails_at_start:
        with pytest.raises(RuntimeError, match="mic_open_failed"):
            controller._open_mic_reader(controller.options())
    else:
        _read, close, _rate = controller._open_mic_reader(controller.options())
        close()
    assert created
    assert closed == created
