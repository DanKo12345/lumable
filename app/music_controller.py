from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from time import monotonic

from PySide6.QtCore import QObject, Signal

from app.color_stream import ColorStreamEngine
from app.music_analysis import MusicAnalyzer, MusicSyncReport
from app.music_color import DEFAULT_BAND_COLORS, bands_to_rgb


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


def list_audio_inputs() -> list[str]:
    """Names of real microphones (recording devices) via sounddevice, or [] if
    unavailable. Enumerated with the same backend that captures them (PortAudio),
    so the names always match what can actually be opened."""
    try:
        import sounddevice as sd

        seen: set[str] = set()
        names: list[str] = []
        for dev in sd.query_devices():
            if int(dev.get("max_input_channels", 0)) <= 0:
                continue
            name = str(dev.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names
    except Exception:
        return []


@dataclass(frozen=True)
class MusicOptions:
    samplerate: int = 48000
    blocksize: int = 1024
    # Where to listen: "system" captures the PC's audio (speaker loopback),
    # "mic" captures a real microphone (sound in the room).
    source: str = "system"
    # The chosen device for the current source: a speaker name in "system" mode,
    # a microphone name in "mic" mode. Empty = that source's system default.
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
    # Noise gate (0..1): loudness at/below this fraction is treated as silence so
    # faint room noise / hiss doesn't make the strip react (useful for the mic).
    noise_gate: float = 0.08


@dataclass(frozen=True)
class MusicModulationSample:
    """One block of sound, described for whoever composes the frame.

    Carries its own time and the run it belongs to, because neither can be
    recovered by the receiver. Qt may deliver a queued signal later than it was
    emitted, and a composer timing staleness from *arrival* would keep calling a
    late block fresh — the one measurement that has to be right for silence to
    look like silence. And a block emitted just before a stop can arrive after
    the next start, so the token says which run it came from and a composer
    holding a different one drops it rather than mixing two sessions.
    """

    session_token: int = 0
    captured_at: float = 0.0
    level: float = 0.0
    beat_envelope: float = 0.0
    block_seconds: float = 0.05


@dataclass(frozen=True)
class BlockResult:
    """What one audio block turned out to be, in both currencies.

    The colour is music reactivity's own answer. The other two are what Fusion
    asks for, and they are deliberately not the same numbers: ``level`` has no
    beat mixed into it and ``beat_envelope`` is the bare onset, because the beat
    slider is applied by whoever composes the frame. Handing over a level that
    already contains a beat would mean the impulse is aimed twice.
    """

    rgb: tuple[int, int, int]
    level: float = 0.0
    beat_envelope: float = 0.0


class MusicController(QObject):
    """Listens to sound. Owning the strip is a separate decision.

    Capture runs on a background thread and every block produces two things: a
    colour, and a description of the sound as loudness and onset. Which of those
    leaves the controller depends on how it was started.

    :meth:`start_output` is music reactivity as it always was — driving the
    strip through its own :class:`ColorStreamEngine`.

    :meth:`start_listening` listens and nothing more: the engine never starts,
    no colour is emitted, and the only output is :attr:`modulation_sampled`.
    That is what "screen colour, music brightness" needs, and it is the thing
    the old design could not do — analysing the sound and owning the strip were
    one act, so the analysis stopped the moment anything else took the line.

    Two named methods rather than one with an optional sink: the difference
    between them is whether this controller drives the strip, and a forgotten
    argument would turn a working music mode into a silent one with nothing
    raising anywhere.

    No colour is emitted while listening only. A colour nobody is meant to send
    is exactly the sort of thing that quietly grows a second path to the strip.
    """

    color_sampled = Signal(int, int, int)
    # One MusicModulationSample. Sent whole rather than as loose numbers so the
    # time and the run cannot be separated from the measurement in transit.
    modulation_sampled = Signal(object)
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
        # One source's idea of silence and of a beat. Reset whenever the source
        # changes or capture restarts — see _reset_analysis.
        self._analyzer = MusicAnalyzer()
        # Bumped by every start, so a block emitted just before a stop can be
        # recognised as belonging to the previous run and dropped.
        self._session_token = 0
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self.color_sampled.connect(self._engine.set_target)

    def options(self) -> MusicOptions:
        return self._options

    def configure(self, **changes) -> None:
        previous = self._options
        self._options = replace(self._options, **changes)
        if self._options.source != previous.source or self._options.device_name != previous.device_name:
            # A microphone's floor describes a room and a loopback's a silent
            # digital line. Carrying one into the other leaves the strip either
            # deaf or twitching, so the history goes with the source.
            self._reset_analysis()
        if "smoothing" in changes:
            self._engine.set_smoothing(self._options.smoothing)

    def _reset_analysis(self) -> None:
        """Forget everything learned about the signal.

        Called on every start and on a capture failure, and by the UI when the
        source changes: a microphone's floor describes a room and a loopback's
        describes a silent digital line, so carrying one into the other leaves
        the strip either deaf or twitching.
        """
        self._band_peak = 1e-6
        self._ema = None
        self._analyzer.reset()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def owns_output(self) -> bool:
        """Whether this controller is the one writing to the strip."""
        return self._engine.is_running()

    def session_token(self) -> int:
        """Which run is current. Every start gets a new one."""
        return self._session_token

    def start_output(self, sink: Callable[[int, int, int], None]) -> None:
        """Listen, and drive the strip with the colour — music reactivity."""
        self._begin(sink)

    def start_listening(self) -> None:
        """Listen only. Nothing is written to the strip by this controller."""
        self._begin(None)

    def _begin(self, sink: Callable[[int, int, int], None] | None) -> None:
        if self.is_running():
            return
        self._reset_analysis()
        self._session_token += 1
        self._started_at = monotonic()
        self._stopped_at = None
        if sink is not None:
            self._engine.set_smoothing(self._options.smoothing)
            self._engine.start(sink, initial=(0, 0, 0))
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="MusicCapture", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        # Noted before the thread is asked to stop, so the reported length is
        # the run rather than however long the join took.
        self._stopped_at = monotonic()
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._engine.stop()

    def music_report(self) -> MusicSyncReport:
        """Numbers for the diagnostics block. No audio, no device names.

        Survives a stop the way the Live Sync report does, so a report exported
        after switching music off still describes the run being asked about.
        """
        stats = self._analyzer.stats
        started = self._started_at
        ended = self._stopped_at if self._stopped_at is not None else monotonic()
        return MusicSyncReport(
            source=self._options.source,
            seconds=round(max(0.0, ended - started), 1) if started is not None else 0.0,
            noise_floor=round(stats.noise_floor, 5),
            beats=stats.beats,
            silent_blocks=stats.silent_blocks,
            blocks=stats.blocks,
            peak_level=round(stats.peak_level, 3),
        )

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

    @classmethod
    def _open_recorder_source(cls, sc, options: MusicOptions):
        """The soundcard loopback device for the chosen speaker (system audio).

        Real microphones are captured via sounddevice instead (see
        :meth:`_open_mic_reader`) — soundcard's WASAPI path asserts on many input
        devices, while it handles speaker loopback reliably."""
        speaker = cls._resolve_speaker(sc, options.device_name)
        return sc.get_microphone(speaker.name, include_loopback=True)

    @staticmethod
    def _open_recorder(source_device, options: MusicOptions):
        """Open a recorder, retrying with simpler args. Some real microphones
        assert inside soundcard when a samplerate/blocksize they don't support is
        forced, so fall back to the device's own defaults instead of failing."""
        # soundcard requires an explicit samplerate; some real microphones also
        # assert unless the channel count is stated. Try a few combos and use the
        # first that opens, so the mic path is robust across devices/drivers.
        attempts = (
            {"samplerate": options.samplerate, "blocksize": options.blocksize},
            {"samplerate": options.samplerate, "channels": 1},
            {"samplerate": options.samplerate, "blocksize": options.blocksize, "channels": 1},
            {"samplerate": options.samplerate},
        )
        errors: list[str] = []
        for kwargs in attempts:
            recorder = None
            try:
                recorder = source_device.recorder(**kwargs)
                recorder.__enter__()
                return recorder
            except Exception as exc:  # probe the next arg combo
                errors.append(f"{tuple(kwargs) or 'defaults'}:{type(exc).__name__}")
                if recorder is not None:
                    try:
                        recorder.__exit__(None, None, None)
                    except Exception:
                        pass
        raise RuntimeError("recorder_open_failed (" + "; ".join(errors) + ")")

    @staticmethod
    def _resolve_sd_input(sd, device_name: str):
        """Index of the chosen sounddevice input device, or None for the default."""
        name = (device_name or "").strip()
        if not name:
            return None
        try:
            for index, dev in enumerate(sd.query_devices()):
                if int(dev.get("max_input_channels", 0)) > 0 and name in str(dev.get("name", "")):
                    return index
        except Exception:
            return None
        return None

    def _open_loopback_reader(self, options: MusicOptions):
        """(read, close, samplerate) for the PC's own audio via speaker loopback."""
        try:
            import soundcard as sc
        except Exception as exc:
            raise RuntimeError(f"audio_capture_unavailable: {exc}") from exc
        source_device = self._open_recorder_source(sc, options)
        recorder = self._open_recorder(source_device, options)

        def read(numframes: int):
            return recorder.record(numframes=numframes)

        def close() -> None:
            try:
                recorder.__exit__(None, None, None)
            except Exception:
                pass

        return read, close, options.samplerate

    def _open_mic_reader(self, options: MusicOptions):
        """(read, close, samplerate) for a real microphone via sounddevice.

        PortAudio opens input devices reliably where soundcard's WASAPI path
        asserts. The samplerate falls back to the device default if the requested
        one isn't supported, so odd mics still work."""
        try:
            import sounddevice as sd
        except ModuleNotFoundError as exc:
            raise RuntimeError(f"mic_backend_missing: {exc}") from exc
        except Exception as exc:
            # Installed but failed to load (e.g. PortAudio DLL missing) — that's a
            # capture failure, not a missing package, so don't tell them to install it.
            raise RuntimeError(f"mic_capture_failed: sounddevice load error: {type(exc).__name__}: {exc}") from exc
        device = self._resolve_sd_input(sd, options.device_name)
        rates = [options.samplerate, 44100]
        try:
            default_sr = int(sd.query_devices(device, "input").get("default_samplerate", 0))
            if default_sr:
                rates.append(default_sr)
        except Exception:
            pass
        stream = None
        rate_used = 0
        errors: list[str] = []
        for rate in dict.fromkeys(r for r in rates if r):
            try:
                candidate = sd.InputStream(
                    device=device, channels=1, samplerate=int(rate),
                    blocksize=options.blocksize, dtype="float32",
                )
                candidate.start()
            except Exception as exc:  # try the next samplerate
                errors.append(f"{rate}:{type(exc).__name__}")
                continue
            stream = candidate
            rate_used = int(rate)
            break
        if stream is None:
            raise RuntimeError("mic_open_failed (" + "; ".join(errors) + ")")

        def read(numframes: int):
            data, _overflow = stream.read(numframes)
            return data

        def close() -> None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        return read, close, rate_used

    def _capture_error_reason(self, exc: Exception) -> str:
        """Tag the failure so the UI can show the right message; keep the class
        name because some WASAPI/soundcard errors carry an empty message."""
        text = str(exc)
        for prefix in ("audio_capture_unavailable", "mic_backend_missing"):
            if text.startswith(prefix):
                return text
        detail = text.strip()
        reason = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
        if self._options.source == "mic":
            return f"mic_capture_failed: {reason}"
        return reason

    def _process_block(self, block, samplerate: int, options: MusicOptions) -> BlockResult:
        bass, mid, treble, rms = analyze_block(block, samplerate)
        # Silence and onsets are judged on the raw block: a transient does not
        # survive smoothing, and a floor learned from smoothed values would
        # chase the music instead of the room.
        reading = self._analyzer.feed(
            bass=bass,
            mid=mid,
            treble=treble,
            rms=rms,
            now_ms=monotonic() * 1000.0,
            manual_gate=self._manual_gate(options),
        )
        # Ease the raw energies toward each reading (EMA) so the colour glides;
        # the factor is the user's "speed": low = calm, high = snappy.
        factor = options.reactivity
        if self._ema is None:
            self._ema = [bass, mid, treble, rms]
        else:
            for i, value in enumerate((bass, mid, treble, rms)):
                self._ema[i] += (value - self._ema[i]) * factor
        bass, mid, treble, smooth_rms = self._ema
        level = self._analyzer.level_for(smooth_rms, self._manual_gate(options))
        # Kept before the beat is folded in: this is the loudness on its own,
        # and it is what a composer wants alongside the bare onset.
        plain_level = level
        if options.beat_strength > 0.0 and level > 0.0:
            level = min(1.0, level + reading.envelope * options.beat_strength)
        # Auto-gain the bands against a slowly decaying running peak so the hue
        # reflects the *balance* of frequencies, not absolute volume.
        current = max(bass, mid, treble, 1e-6)
        self._band_peak = max(current, self._band_peak * options.agc_decay)
        scale = 1.0 / self._band_peak
        rgb = bands_to_rgb(
            bass * scale, mid * scale, treble * scale, level,
            colors=options.band_colors, saturation=options.saturation,
            floor_brightness=options.floor_brightness,
        )
        return BlockResult(rgb=rgb, level=plain_level, beat_envelope=reading.envelope)

    @staticmethod
    def _frame_count(block) -> int:
        """How many frames a block actually holds, whatever container it is in."""
        try:
            shape = block.shape
        except AttributeError:
            try:
                return len(block)
            except TypeError:
                return 0
        return int(shape[0]) if shape else 0

    @staticmethod
    def _manual_gate(options: MusicOptions) -> float:
        """The microphone slider as an RMS rather than a fraction.

        Kept in the units the analyser thinks in, and scaled by the same ceiling
        the loudness curve uses, so a saved 40% still means what it meant.
        """
        return max(0.0, min(0.95, options.noise_gate)) * 0.25

    def _run(self) -> None:
        try:
            options = self._options
            if options.source == "mic":
                read, close, samplerate = self._open_mic_reader(options)
            else:
                read, close, samplerate = self._open_loopback_reader(options)
        except Exception as exc:
            # The device never opened, so whatever was learned came from a
            # different one. Same reasoning as a failure mid-run.
            self._reset_analysis()
            self.failed.emit(self._capture_error_reason(exc))
            return
        try:
            token = self._session_token
            while not self._stop.is_set():
                options = self._options
                block = read(options.blocksize)
                # Stamped here, where the sound actually arrived. A receiver
                # cannot recover this: a queued signal is timed from delivery,
                # and a late block would look like a fresh one.
                captured_at = monotonic()
                result = self._process_block(block, samplerate, options)
                # The block's real length, not the one that was asked for: a
                # device is free to hand back fewer frames, and downstream
                # staleness is measured against this.
                frames = self._frame_count(block) or options.blocksize
                self.modulation_sampled.emit(
                    MusicModulationSample(
                        session_token=token,
                        captured_at=captured_at,
                        level=result.level,
                        beat_envelope=result.beat_envelope,
                        block_seconds=frames / max(1, samplerate),
                    )
                )
                if self._engine.is_running():
                    red, green, blue = result.rgb
                    self.color_sampled.emit(red, green, blue)
        except Exception as exc:  # audio device/driver failure — report and stop cleanly.
            # Whatever was learned came from a device that has just gone wrong;
            # the next attempt starts from nothing rather than from that.
            self._reset_analysis()
            self.failed.emit(self._capture_error_reason(exc))
        finally:
            close()
