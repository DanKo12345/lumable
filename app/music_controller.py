from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache

from PySide6.QtCore import QObject, Signal

from app.color_stream import ColorStreamEngine
from app.music_color import DEFAULT_BAND_COLORS, bands_to_rgb, normalize_level, update_beat


@lru_cache(maxsize=8)
def _analysis_kernels(n: int, samplerate: int):
    """Hann window + per-band frequency masks for a given block size/rate.

    Cached because they only depend on ``(n, samplerate)`` — which are fixed for
    a capture session — so we build them once instead of every audio block. This
    is the bulk of the per-block CPU saving.
    """
    import numpy as np

    window = np.hanning(n).astype(np.float32)
    freqs = np.fft.rfftfreq(n, d=1.0 / samplerate)
    bass_mask = (freqs >= 20.0) & (freqs < 250.0)
    mid_mask = (freqs >= 250.0) & (freqs < 2000.0)
    treble_mask = (freqs >= 2000.0) & (freqs < 16000.0)
    return window, bass_mask, mid_mask, treble_mask


def analyze_block(samples, samplerate: int) -> tuple[float, float, float, float]:
    """Return ``(bass, mid, treble, rms)`` for one audio block.

    ``samples`` is a 1-D mono or 2-D (frames, channels) array of floats in
    roughly ``[-1, 1]``; stereo is downmixed. A Hann window + real FFT split the
    magnitude spectrum into bass (20-250 Hz), mid (250-2000 Hz) and treble
    (2-16 kHz) sums, alongside the block RMS. Computation is float32 and reuses
    cached window/masks to keep CPU low. numpy is imported lazily so the module
    loads even where numpy isn't installed (matching the ambient/mss pattern);
    the function is pure given numpy, so it's unit-testable.
    """
    import numpy as np

    arr = np.asarray(samples, dtype=np.float32)
    mono = arr.mean(axis=1) if arr.ndim == 2 else arr.reshape(-1)
    n = mono.size
    if n == 0:
        return (0.0, 0.0, 0.0, 0.0)
    rms = float(np.sqrt(np.mean(mono * mono)))
    window, bass_mask, mid_mask, treble_mask = _analysis_kernels(n, samplerate)
    spectrum = np.abs(np.fft.rfft(mono * window))
    return (
        float(spectrum[bass_mask].sum()),
        float(spectrum[mid_mask].sum()),
        float(spectrum[treble_mask].sum()),
        rms,
    )


def list_audio_outputs() -> list[str]:
    """Names of the system's audio output devices (speakers), or [] if audio
    capture isn't available. Used to let the user pick which output's loopback
    the music reactivity listens to."""
    try:
        import soundcard as sc

        return [speaker.name for speaker in sc.all_speakers()]
    except Exception:
        return []


@dataclass(frozen=True)
class MusicOptions:
    samplerate: int = 48000
    blocksize: int = 1024
    # Output device to capture (loopback). Empty = the system default speaker.
    device_name: str = ""
    saturation: float = 1.4
    smoothing: float = 0.5
    floor_brightness: float = 0.06
    # Per-band colours (bass, mid, treble); defaults to red/green/blue.
    band_colors: tuple = DEFAULT_BAND_COLORS
    # Auto-gain: the band ceiling decays each block so the colour adapts to the
    # current track loudness instead of needing a manual sensitivity slider.
    agc_decay: float = 0.92
    # Reaction speed: how fast the band/level energies follow the audio (EMA
    # factor, 0..1). Low = slow, calm glide; high = snappy/instant.
    reactivity: float = 0.35
    # Beat detection: a bass-energy onset briefly pops the brightness so the
    # strip punches on the beat instead of only tracking volume. ``beat_strength``
    # 0 disables it; sensitivity is how far above the running average counts as a
    # beat; decay is how fast the pop fades.
    beat_strength: float = 0.4
    beat_sensitivity: float = 1.3
    beat_decay: float = 0.82


class MusicController(QObject):
    """Drives music reactivity: captures system audio (WASAPI loopback) on a
    background thread, turns each block into a colour and streams it to a sink
    (BLE write) through :class:`ColorStreamEngine`.

    Mirrors :class:`AmbientController`: capture runs off-thread and emits
    :attr:`color_sampled` (connected to the engine on the main thread); capture
    failures surface via :attr:`failed`.
    """

    color_sampled = Signal(int, int, int)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Music wants a snappier feel than ambient, but the BLE link still caps
        # out ~15-20 writes/sec, so the engine coalesces to a safe rate.
        self._engine = ColorStreamEngine(self, send_interval_ms=60)
        self._options = MusicOptions()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._band_peak = 1e-6
        self._ema: list[float] | None = None
        # Beat detector state (running bass average + decaying pulse envelope).
        self._bass_avg = 0.0
        self._beat_env = 0.0
        self.color_sampled.connect(self._engine.set_target)

    def options(self) -> MusicOptions:
        return self._options

    def configure(self, **changes) -> None:
        self._options = replace(self._options, **changes)
        if "smoothing" in changes:
            self._engine.set_smoothing(self._options.smoothing)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, sink: Callable[[int, int, int], None]) -> None:
        if self.is_running():
            return
        self._band_peak = 1e-6
        self._ema = None
        self._bass_avg = 0.0
        self._beat_env = 0.0
        self._engine.set_smoothing(self._options.smoothing)
        self._engine.start(sink, initial=(0, 0, 0))
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="MusicCapture", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._engine.stop()

    def stream_error_count(self) -> int:
        return self._engine.error_count()

    def last_stream_error(self) -> str:
        return self._engine.last_error()

    @staticmethod
    def _resolve_speaker(sc, device_name: str):
        """Pick the chosen output device, falling back to the system default."""
        name = (device_name or "").strip()
        if name:
            try:
                return sc.get_speaker(name)
            except Exception:
                for speaker in sc.all_speakers():
                    if name in (getattr(speaker, "id", ""), speaker.name):
                        return speaker
        return sc.default_speaker()

    def _run(self) -> None:
        try:
            import soundcard as sc
        except Exception as exc:
            self.failed.emit(f"audio_capture_unavailable: {exc}")
            return
        try:
            speaker = self._resolve_speaker(sc, self._options.device_name)
            loopback = sc.get_microphone(speaker.name, include_loopback=True)
            options = self._options
            with loopback.recorder(samplerate=options.samplerate, blocksize=options.blocksize) as recorder:
                while not self._stop.is_set():
                    options = self._options
                    block = recorder.record(numframes=options.blocksize)
                    bass, mid, treble, rms = analyze_block(block, options.samplerate)
                    # Detect beats from the *raw* bass (before smoothing, so the
                    # transient survives) — the envelope pulses brightness below.
                    self._bass_avg, self._beat_env, _is_beat = update_beat(
                        bass,
                        self._bass_avg,
                        self._beat_env,
                        sensitivity=options.beat_sensitivity,
                        decay=options.beat_decay,
                    )
                    # Ease the raw energies toward each new reading (EMA) so the
                    # colour glides instead of jumping on every block. The factor
                    # is the user's "speed": low = calm/slow, high = snappy.
                    factor = options.reactivity
                    if self._ema is None:
                        self._ema = [bass, mid, treble, rms]
                    else:
                        for i, value in enumerate((bass, mid, treble, rms)):
                            self._ema[i] += (value - self._ema[i]) * factor
                    bass, mid, treble, rms = self._ema
                    level = normalize_level(rms)
                    # Punch the brightness up on a beat, then let it decay.
                    if options.beat_strength > 0.0:
                        level = min(1.0, level + self._beat_env * options.beat_strength)
                    # Auto-gain the bands against a slowly decaying running peak so
                    # the hue reflects the *balance* of frequencies, not absolute volume.
                    current = max(bass, mid, treble, 1e-6)
                    self._band_peak = max(current, self._band_peak * options.agc_decay)
                    scale = 1.0 / self._band_peak
                    red, green, blue = bands_to_rgb(
                        bass * scale,
                        mid * scale,
                        treble * scale,
                        level,
                        colors=options.band_colors,
                        saturation=options.saturation,
                        floor_brightness=options.floor_brightness,
                    )
                    self.color_sampled.emit(red, green, blue)
        except Exception as exc:  # audio device/driver failure — report and stop cleanly.
            self.failed.emit(str(exc))
