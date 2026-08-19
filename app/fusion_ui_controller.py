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

import threading
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
        self._submitted = 0
        self._succeeded = 0
        self._failed = 0
        self._link_rejections = 0
        self._run_token = 0
        # A result can land while its own command is still being submitted, and
        # on another thread. Held under the same lock that counts the command,
        # so a snapshot can never show a success for a write that does not exist.
        self._result_lock = threading.Lock()
        self._registering: tuple[int, int] | None = None
        self._held: bool | None = None
        self._next_command = 0
        self._audio_lost = False

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
        self._run_token += 1
        self._audio_lost = False
        self._submitted = 0
        self._succeeded = 0
        self._failed = 0
        self._link_rejections = 0
        self._next_command = 0
        if not host.power_button.isChecked():
            host.power_button.setChecked(True)
            host._toggle_power()

        run = self._run_token

        def sink(red: int, green: int, blue: int) -> bool:
            # The only route to the strip from a streaming mode. Colour only:
            # the brightness slider is the strip's own ceiling and the composed
            # factor rides inside these three numbers.
            #
            # Counted here rather than by the screen's own metrics: a composed
            # write is not a screen frame — several frames can coalesce into one
            # — so attributing an outcome back to a frame id would be inventing a
            # correspondence that does not exist.
            #
            # The result is held rather than counted as it arrives, because it
            # can arrive *inside* this call — a write that fails immediately
            # calls the observer before the call returns. Counted then, a
            # snapshot taken from within the observer shows a success for a
            # command that does not exist yet.
            #
            # Held against this command, not merely this run. An earlier write
            # can settle while a later one is being submitted, and holding it as
            # though it belonged to the later one loses it entirely when that
            # later one is refused.
            with self._result_lock:
                self._next_command += 1
                command = self._next_command
                self._registering = (run, command)
                self._held = None
            try:
                accepted = host._ble.set_color_stream(
                    red, green, blue, observer=lambda ok: self._note_result(run, command, ok)
                )
            except BaseException:
                with self._result_lock:
                    self._registering = None
                    self._held = None
                raise

            with self._result_lock:
                held = self._held
                self._held = None
                self._registering = None
                if accepted:
                    self._submitted += 1
                else:
                    # A refused frame is the link being busy, not a failed write.
                    # Counting it as submitted would report a command that was
                    # never sent and can never settle, so the totals would never
                    # add up. Any result held for it is discarded with it.
                    self._link_rejections += 1
                    held = None
                if held is True:
                    self._succeeded += 1
                elif held is False:
                    self._failed += 1
            return accepted

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
        # Cleared by a start that worked, whichever start it was. Power brings
        # the sources back through here too, and a flag left set would leave the
        # card apologising for a device that is listening again.
        self._audio_lost = not bool(music_token) if self._mode == SCREEN_MUSIC else False
        return (screen_token, music_token)

    def _stop_sources(self) -> None:
        host = self._host
        host._ambient_ui.stop_listening()
        host._music_ui.stop_listening()

    def note_audio_lost(self) -> None:
        """The audio device has gone. Keep the screen, drop the claim to music.

        The mode the user chose is not changed — they still want screen and
        music, and plugging the device back in should resume it. What must stop
        is the interface saying "Экран + музыка" while nothing is listening, and
        the coordinator waiting for a token no source will ever send.
        """
        if not self.is_running():
            return
        self._audio_lost = True
        self._coordinator.expect_music(0)

    def audio_lost(self) -> bool:
        """Whether the combined mode is running with its audio half missing."""
        return self._audio_lost and self.is_running() and self._mode == SCREEN_MUSIC

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
        token = host._music_ui.start_listening()
        self._audio_lost = not bool(token)
        self._coordinator.expect_music(token)

    def set_beat_gain(self, gain: float) -> None:
        self._coordinator.set_beat_gain(gain)

    def _note_result(self, run: int, command: int, ok: bool) -> None:
        """An outcome, credited to the run and the command that asked for it.

        Results arrive on the BLE thread and can land after a stop. Without the
        run, a write from the previous session would settle into the counters of
        the new one, which have just been zeroed.

        Only the command currently being submitted is held; anything else is
        counted straight away. An earlier write settling during a later
        submission is a real outcome of a command that already exists — holding
        it as though it belonged to the later one throws it away whenever that
        later one is refused.
        """
        with self._result_lock:
            if run != self._run_token:
                return
            if self._registering == (run, command):
                self._held = bool(ok)
                return
            if ok:
                self._succeeded += 1
            else:
                self._failed += 1

    def _strip_brightness(self) -> str:
        """The hardware brightness, as the card shows it."""
        slider = getattr(self._host, "brightness_slider", None)
        return f"{int(slider.value())}%" if slider is not None else "-"

    # ── what happened ─────────────────────────────────────────────────
    def has_run(self) -> bool:
        """Whether there is a run to describe — this one or the last one.

        A report is usually exported *after* stopping, so a block that only
        exists while running is a block nobody ever sees when they need it.
        """
        return self._run_token > 0

    def stats(self) -> dict:
        frame = self._coordinator.last_frame()
        dropped_screen, dropped_music = self._coordinator.dropped_samples()
        return {
            "running": self.is_running(),
            "has_run": self.has_run(),
            "mode": self._mode,
            "errors": self._coordinator.stream_error_count(),
            "commands_submitted": self._submitted,
            "commands_succeeded": self._succeeded,
            "commands_failed": self._failed,
            "link_rejections": self._link_rejections,
            "last_error": self._coordinator.last_stream_error(),
            "frame_reason": frame.reason,
            # Two brightnesses, never one. The strip keeps the hardware level a
            # person set with the slider; Fusion scales the colour underneath
            # it. Reporting their product as "brightness" would make every
            # "too dim" question unanswerable.
            "strip_brightness": self._strip_brightness(),
            "brightness_factor": round(frame.brightness_factor, 3),
            "beat_boost": round(frame.beat_boost, 3),
            "music_activity": round(frame.activity, 3),
            "music_stale": frame.music_stale,
            "audio_lost": self.audio_lost(),
            "dropped_screen_samples": dropped_screen,
            "dropped_music_samples": dropped_music,
        }
