"""Screen Sync, and Screen Sync with the music moving its brightness.

One mode chooser lives on the screen card: *Экран* or *Экран + музыка*. Both go
through the same coordinator and the same single write to the strip; the second
one additionally borrows the audio analysis. Nothing here is a third way to the
strip — see :mod:`app.fusion_coordinator`.

The two source cards are asked, not reached into. Each of them knows how to run
its own capture without owning the output, and this controller only says when
and collects the tokens. That keeps a card's own gates, options and error
reporting where they already are, and it is why switching the audio source
mid-run restarts audio alone: the music card does what it always did, and the
screen and the strip never learn that anything happened.
"""

from __future__ import annotations

from typing import Any

from app.feature_gate import can_use
from app.fusion_coordinator import FusionCoordinator
from app.storage import save_settings

SCREEN = "screen"
SCREEN_MUSIC = "screen_music"
MODES = (SCREEN, SCREEN_MUSIC)


def normalize_mode(value: object) -> str:
    text = str(value or "").strip()
    return text if text in MODES else SCREEN


class FusionUiController:
    """Runs whichever of the two modes is chosen, through one coordinator."""

    def __init__(self, host: Any) -> None:
        self._host = host
        self._coordinator = FusionCoordinator(host)
        self._mode = SCREEN
        self._sink = None
        self._reason = ""

    def wire(self) -> None:
        """Point both sources at the coordinator, once and for good.

        Connected regardless of the mode: a source that is not running emits
        nothing, and a sample from a run the coordinator is not expecting is
        refused by its token. Connecting and disconnecting per start would add a
        second place for the two to disagree about which run is current.
        """
        host = self._host
        host._ambient_ui.connect_samples(self._coordinator.submit_screen)
        host._music_ui.connect_samples(self._coordinator.submit_music)
        self.load_settings()

    # ── the chosen mode ───────────────────────────────────────────────
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str, *, persist: bool = True) -> None:
        """Choose a mode. Applied live if something is already running."""
        mode = normalize_mode(mode)
        if mode == self._mode:
            return
        self._mode = mode
        if persist:
            self._persist()
        if self.is_running():
            # Restarted rather than adjusted: the difference between the two is
            # which sources are capturing, and asking the coordinator to change
            # that under a live session is the sort of half-state this whole
            # design exists to avoid.
            self.stop_if_running()
            self.activate()

    def load_settings(self) -> None:
        host = self._host
        saved = host._settings.get("fusion", {}) if isinstance(host._settings, dict) else {}
        self._mode = normalize_mode(saved.get("mode", SCREEN))

    def _persist(self) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        host._settings["fusion"] = {"mode": self._mode}
        save_settings(host._settings)

    # ── why the combined mode may not be available ────────────────────
    def unavailable_reason(self, mode: str | None = None) -> str:
        """An empty string, or a translation key saying what is missing.

        Answered rather than acted on: a mode a person chose must not quietly
        fall back to the other one, because then the card shows a choice that is
        not the one being run.
        """
        host = self._host
        mode = normalize_mode(mode or self._mode)
        if not can_use("ambient_sync"):
            return "fusion.needs_pro"
        if mode == SCREEN_MUSIC and not can_use("music_sync"):
            return "fusion.needs_pro"
        if not host._is_connected:
            return "fusion.needs_strip"
        if mode == SCREEN_MUSIC and not host._music_ui.has_audio_source():
            return "fusion.needs_audio"
        return ""

    # ── running ───────────────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._coordinator.is_running()

    def last_reason(self) -> str:
        """Why the last start refused, if it did."""
        return self._reason

    def coordinator(self) -> FusionCoordinator:
        return self._coordinator

    def activate(self) -> bool:
        host = self._host
        self._reason = self.unavailable_reason()
        if self._reason:
            return False
        host.stop_streams(exclude=self)
        if not host.power_button.isChecked():
            host.power_button.setChecked(True)
            host._toggle_power()

        def sink(red: int, green: int, blue: int) -> bool:
            # The only route to the strip from a streaming mode. Colour only:
            # the brightness slider is the strip's own ceiling and the composed
            # factor rides inside these three numbers.
            return host._ble.set_color_stream(red, green, blue)

        self._sink = sink
        seed = host._current_color()
        self._coordinator.attach_sources(start=self._start_sources, stop=self._stop_sources)
        self._coordinator.start(
            sink, mode=self._mode, initial=(seed.red(), seed.green(), seed.blue())
        )
        self._coordinator.set_beat_gain(host._music_ui.beat_strength())
        self._coordinator.set_powered(True)
        return True

    def toggle(self) -> bool:
        if self.is_running():
            self.stop_if_running()
            return False
        return self.activate()

    def stop_if_running(self) -> None:
        if not self.is_running():
            return
        self._coordinator.set_powered(False)
        self._coordinator.stop()
        self._sink = None

    def set_powered(self, on: bool) -> None:
        """Power, while the mode stays chosen. Only meaningful while running."""
        if self.is_running():
            self._coordinator.set_powered(on)

    def shutdown(self) -> None:
        self.stop_if_running()

    # ── the sources, borrowed from their own cards ────────────────────
    def _start_sources(self) -> tuple[int, int]:
        host = self._host
        screen_token = host._ambient_ui.start_listening()
        music_token = 0
        if self._mode == SCREEN_MUSIC:
            music_token = host._music_ui.start_listening()
        return (screen_token, music_token)

    def _stop_sources(self) -> None:
        host = self._host
        host._ambient_ui.stop_listening()
        host._music_ui.stop_listening()

    def restart_audio(self) -> None:
        """Take the audio source again, leaving the screen and the strip alone.

        Changing the microphone must not blink the light: the base keeps
        arriving, the composed colour keeps going out, and only the modulation
        pauses for as long as the device takes to open.
        """
        if not self.is_running() or self._mode != SCREEN_MUSIC:
            return
        host = self._host
        host._music_ui.stop_listening()
        self._coordinator.expect_music(host._music_ui.start_listening())

    def set_beat_gain(self, gain: float) -> None:
        self._coordinator.set_beat_gain(gain)

    def _strip_brightness(self) -> str:
        """The hardware brightness, as the card shows it."""
        slider = getattr(self._host, "brightness_slider", None)
        return f"{int(slider.value())}%" if slider is not None else "-"

    # ── what happened ─────────────────────────────────────────────────
    def stats(self) -> dict:
        frame = self._coordinator.last_frame()
        dropped_screen, dropped_music = self._coordinator.dropped_samples()
        return {
            "running": self.is_running(),
            "mode": self._mode,
            "errors": self._coordinator.stream_error_count(),
            "last_error": self._coordinator.last_stream_error(),
            "frame_reason": frame.reason,
            # Two brightnesses, never one. The strip keeps the hardware level a
            # person set with the slider; Fusion scales the colour underneath
            # it. Reporting their product as "brightness" would make every
            # "too dim" question unanswerable.
            "strip_brightness": self._strip_brightness(),
            "brightness_factor": round(frame.brightness_factor, 3),
            "music_activity": round(frame.activity, 3),
            "music_stale": frame.music_stale,
            "dropped_screen_samples": dropped_screen,
            "dropped_music_samples": dropped_music,
        }
