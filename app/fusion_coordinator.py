"""The one thing that writes a streamed colour to the strip.

::

    Screen sample ─┐
                   ├─ FusionCoordinator ─ ColorStreamEngine ─ BLE
    Music sample ──┘

Both sources are capture threads and neither sends anything. A screen frame
updates the base, an audio block updates the modulation, and on its own tick
this coordinator asks the compositor for one frame and hands it to one engine.

That shape is the point, not an implementation detail. Sending on every event
would work in a demo and then behave differently every run: two sources firing
at unrelated rates would double the command rate, and which of them arrived last
would decide what the strip shows. Here the rate belongs to the engine and
nothing else, whether one source is running or both.

**Brightness travels in the colour.** The strip takes a colour and a brightness
as two separate commands, and music moves brightness on every block — sending
both would double the traffic on a link that manages about ten writes a second.
The composed brightness scales the RGB instead, which is one write and keeps the
hue the screen chose.

**Only the current run is accepted.** Each source stamps its samples with the
token of its capture run, and a sample from any other run is dropped rather than
composed. Without that, a frame emitted just before a stop can arrive after the
next start and put a colour from the previous session on the strip.

**One clock.** The compositor, the samples and the staleness checks all read the
same injected monotonic source, so "how old is this" is a subtraction rather
than a comparison between two ideas of now.

What this does *not* claim to be is the only way anything reaches the strip.
Power, a colour chosen by hand, a scene and a DIY effect all write directly, and
should — they are single commands from a person, not a stream. The contract is
narrower and testable: while Fusion is running, no *streaming* source writes
except through here.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from app.color_stream import ColorStreamEngine
from app.fusion_core import BaseSample, ComposedFrame, FusionCompositor, MusicModulation

RGB = tuple[int, int, int]


class FusionCoordinator(QObject):
    """Collects samples from any thread and composes on its own tick."""

    # The frame that was just composed, for previews and diagnostics. Emitted
    # whether or not it was sent, because "nothing was sent" is the interesting
    # case to be able to see.
    frame_composed = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        tick_ms: int = 33,
        send_interval_ms: int = 70,
    ) -> None:
        super().__init__(parent)
        self._clock = clock
        self._compositor = FusionCompositor(clock=clock)
        self._engine = ColorStreamEngine(self, send_interval_ms=send_interval_ms)
        # Passthrough: the screen's own temporal filter and the compositor's
        # activity weight are the smoothing. A third one here would ease an
        # already-eased colour and put the strip visibly behind the picture.
        self._engine.set_smoothing(1.0)
        self._timer = QTimer(self)
        self._timer.setInterval(max(16, int(tick_ms)))
        self._timer.timeout.connect(self._tick)
        # Samples arrive on capture threads; composing happens on the tick. The
        # lock is held only long enough to swap a reference, never across
        # compose, so a slow frame cannot stall a capture thread.
        self._lock = threading.Lock()
        self._pending_base: BaseSample | None = None
        self._pending_music: MusicModulation | None = None
        self._screen_token = 0
        self._music_token = 0
        self._beat_gain = 1.0
        self._last_frame = ComposedFrame()
        self._dropped_screen = 0
        self._dropped_music = 0

    # ── running ───────────────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, sink: Callable[..., None], *, mode: str, initial: RGB = (0, 0, 0)) -> None:
        """Take the output. ``sink`` is the only route to the strip from here."""
        self._compositor.set_mode(mode)
        self._compositor.set_sources_running(True)
        self._engine.start(sink, initial=initial)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._engine.stop()
        self._compositor.set_sources_running(False)
        with self._lock:
            self._pending_base = None
            self._pending_music = None
        self._screen_token = 0
        self._music_token = 0

    # ── what counts as the current run ────────────────────────────────
    def expect_screen(self, token: int) -> None:
        self._screen_token = int(token)

    def expect_music(self, token: int) -> None:
        self._music_token = int(token)

    def set_beat_gain(self, gain: float) -> None:
        self._beat_gain = max(0.0, min(1.0, float(gain)))

    def set_output_allowed(self, allowed: bool) -> None:
        """Power. Blocks writing, keeps the chosen mode — see fusion_core."""
        self._compositor.set_output_allowed(bool(allowed))

    def output_allowed(self) -> bool:
        return self._compositor.output_allowed

    def mode(self) -> str:
        return self._compositor.mode

    # ── inbound, from capture threads ─────────────────────────────────
    def submit_screen(self, sample) -> None:
        """Take a screen frame as the base. Never sends anything."""
        if not sample.session_token or sample.session_token != self._screen_token:
            self._dropped_screen += 1
            return
        base = BaseSample(
            rgb=tuple(sample.rgb),
            brightness=1.0,
            source="screen",
            at=sample.captured_at,
        )
        with self._lock:
            self._pending_base = base

    def submit_music(self, sample) -> None:
        """Take an audio block as the modulation. Never sends anything."""
        if not sample.session_token or sample.session_token != self._music_token:
            self._dropped_music += 1
            return
        modulation = MusicModulation(
            level=sample.level,
            beat_envelope=sample.beat_envelope,
            at=sample.captured_at,
            block_seconds=sample.block_seconds,
        )
        with self._lock:
            self._pending_music = modulation

    # ── the tick ──────────────────────────────────────────────────────
    def _tick(self) -> None:
        with self._lock:
            base = self._pending_base
            music = self._pending_music
            self._pending_base = None
            self._pending_music = None
        if base is not None:
            self._compositor.submit_base(base)
        if music is not None:
            self._compositor.submit_music(music)

        frame = self._compositor.compose(beat_gain=self._beat_gain)
        self._last_frame = frame
        if frame.should_send:
            red, green, blue = frame.rgb
            scale = frame.brightness
            self._engine.set_target(
                round(red * scale), round(green * scale), round(blue * scale)
            )
        self.frame_composed.emit(frame)

    # ── what happened ─────────────────────────────────────────────────
    def last_frame(self) -> ComposedFrame:
        return self._last_frame

    def dropped_samples(self) -> tuple[int, int]:
        """Screen and music samples refused as belonging to another run."""
        return (self._dropped_screen, self._dropped_music)

    def stream_error_count(self) -> int:
        return self._engine.error_count()

    def last_stream_error(self) -> str:
        return self._engine.last_error()
