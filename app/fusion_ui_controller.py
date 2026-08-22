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

# Where a run's colours are going. Decided once, when it starts, and never
# again: a preview started with no strip must not begin lighting one that is
# plugged in later. Somebody who wanted that would have pressed the button
# again, and the button says which of the two it would start.
LIVE = "live"
PREVIEW = "preview_only"


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
        self._target = LIVE
        # Whether this run's writes may reach the strip *right now*. Separate
        # from the target: a live run whose strip has gone keeps everything else
        # exactly as it was and only stops writing.
        self._ble_allowed = False
        # Set while a reconnected run waits for a frame captured after the
        # break. Until one arrives there is nothing honest to send.
        self._awaiting_fresh_base = False

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
        self._coordinator.frame_composed.connect(self._on_frame_composed)
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

    # ── where a start would send its colours ──────────────────────────
    def intended_target(self, mode: str | None = None) -> str:
        """Which of the two a press of the button would start, right now.

        A strip and the licence for the mode are what make the difference. Both
        are read at the moment of the press and then held for the whole run —
        this is the *only* place the question is asked.
        """
        host = self._host
        mode = normalize_mode(mode or self._mode)
        if not host._is_connected:
            return PREVIEW
        if not can_use("ambient_sync"):
            return PREVIEW
        if mode == SCREEN_MUSIC and not can_use("music_sync"):
            return PREVIEW
        return LIVE

    def target(self) -> str:
        """What the current run was started as."""
        return self._target

    def previewing(self) -> bool:
        """Whether what is running is showing rather than lighting."""
        return self.is_running() and self._target == PREVIEW

    # ── why a mode may not be available at all ────────────────────────
    def unavailable_reason(self, mode: str | None = None) -> str:
        """An empty string, or a translation key saying what is missing.

        Only what stops the mode from *running*. A missing strip and a Free
        licence no longer belong here: neither prevents the screen being read
        and composed, they only decide where the result goes, and that is what
        the target answers.

        A missing audio device is a different matter and stays. Screen + music
        with nothing listening is not a dimmer version of the mode, it is the
        other mode wearing its name — and that is as untrue in a preview as it
        is on a strip.
        """
        host = self._host
        mode = normalize_mode(mode or self._mode)
        if mode == SCREEN_MUSIC and not host._music_ui.has_audio_source():
            return "fusion.needs_audio"
        return ""

    def live_unavailable_reason(self, mode: str | None = None) -> str:
        """Why a start would preview rather than light, or an empty string."""
        host = self._host
        mode = normalize_mode(mode or self._mode)
        if not can_use("ambient_sync") or (mode == SCREEN_MUSIC and not can_use("music_sync")):
            return "fusion.needs_pro"
        if not host._is_connected:
            return "fusion.needs_strip"
        return ""

    # ── what the card says ────────────────────────────────────────────
    def status_key(self) -> str:
        """The one line under the row title, decided in one place.

        Ordered by what a person needs to know first: something is stopping the
        mode, then where its colours are going, then which mode it is. Where the
        colours go outranks which mode it is, because "Screen and music" beside
        a strip that is not lighting is the one sentence this mode must never
        say.
        """
        host = self._host
        mode = self._mode
        reason = self.unavailable_reason(mode)
        if reason:
            return reason
        if self.is_running():
            if self.audio_lost():
                return "fusion.audio_lost"
            if self._target == PREVIEW:
                return (
                    "fusion.preview.strip_unused"
                    if host._is_connected
                    else "fusion.preview.no_strip"
                )
            if not host._is_connected:
                return "fusion.preview.link_lost"
            if self._awaiting_fresh_base:
                return "fusion.preview.waiting_frame"
            return f"fusion.status.{mode}"
        # Stopped. What the line says is what a press would do, not what is
        # missing: neither of these prevents anything any more, and "Connect a
        # strip first" in front of a button that works is an instruction to do
        # something unnecessary before doing the thing that would have worked.
        if not host._is_connected:
            return "fusion.idle.no_strip"
        if self.intended_target() == PREVIEW:
            return "fusion.idle.free"
        return "ambient.status_off"

    def preview_hint_key(self) -> str:
        """The caption over the two capsules: what the right-hand one is.

        "Screen -> Strip" is a claim about where the colour went, and in a
        preview it is simply false — there is no strip in it. The arrow still
        points at the same thing it always did, the colour that was delivered;
        only the name of the destination changes.
        """
        if self.previewing():
            return "ambient.preview_hint_preview"
        return "ambient.preview_hint"

    def toggle_label_key(self) -> str:
        """What the button offers. While running it is simply on."""
        if self.is_running():
            return "ambient.toggle_on"
        if self.intended_target() == PREVIEW:
            return "ambient.toggle_preview"
        return "ambient.toggle_off"

    # ── running ───────────────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._coordinator.is_running()

    def last_reason(self) -> str:
        """Why the last start refused, if it did."""
        return self._reason

    def coordinator(self) -> FusionCoordinator:
        return self._coordinator

    def activate(self, *, target: str | None = None) -> bool:
        host = self._host
        self._reason = self.unavailable_reason()
        if self._reason:
            return False
        target = target if target in (LIVE, PREVIEW) else self.intended_target()
        host.stop_streams(exclude=self)
        self._run_token += 1
        self._audio_lost = False
        self._submitted = 0
        self._succeeded = 0
        self._failed = 0
        self._link_rejections = 0
        self._next_command = 0
        self._target = target
        self._ble_allowed = target == LIVE
        self._awaiting_fresh_base = False
        if target == LIVE and not host.power_button.isChecked():
            # Only on the way to a strip. Power is a command to hardware, and a
            # preview has no hardware to command — pressing it on someone's
            # behalf would be this mode reaching a device it promised not to
            # touch, and on a Free licence with a strip attached it would light
            # a strip nobody agreed to light.
            host.power_button.setChecked(True)
            host._toggle_power()

        run = self._run_token

        def sink(red: int, green: int, blue: int) -> bool:
            if not self._ble_allowed:
                # A delivery with nothing at the end of it. Accepted, because
                # the pacing and the beat's turn are the same either way — what
                # is missing is only the radio. Nothing is counted: these are
                # not commands, and a report listing them beside real ones would
                # be describing a link that was never used.
                self._show_delivered(red, green, blue)
                return True
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
            if accepted:
                # Shown only when it was actually taken. A refused write put
                # nothing on the wall, and a preview that moved anyway would be
                # smoother than the strip it stands for.
                self._show_delivered(red, green, blue)
            return accepted

        seed = host._current_color()
        self._coordinator.attach_sources(start=self._start_sources, stop=self._stop_sources)
        self._coordinator.start(
            sink,
            mode=self._mode,
            initial=(seed.red(), seed.green(), seed.blue()),
            measures_a_link=target == LIVE,
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
        """Power, while the mode stays chosen. Only meaningful while running.

        A preview is left alone. The power button switches a strip on and off,
        and a run that is not writing to one has nothing in that switch to obey
        — stopping its capture would make the button mean two different things
        depending on what happens to be plugged in. Somebody with a strip
        attached may well press it while previewing, and their preview should
        carry on exactly as before.
        """
        if self.is_running() and self._target == LIVE:
            self._coordinator.set_powered(on)

    # ── the strip coming and going under a live run ───────────────────
    def note_link_lost(self) -> None:
        """The strip has gone. Keep showing, stop writing, remember the intent.

        The alternative — tearing the run down — throws away the mode, the
        capture and everything the compositor has learned about the music,
        because a radio dropped for a second. What the person asked for has not
        changed, and neither has anything this side of the aerial.
        """
        if not self.is_running() or self._target != LIVE:
            return
        self._ble_allowed = False
        self._awaiting_fresh_base = False
        self._coordinator.set_measures_a_link(False)

    def note_link_back(self) -> None:
        """The strip is back. Take the capture again and wait for a new frame.

        Permission is not restored here. Everything held describes a screen from
        before the break, and handing that to a strip the moment it answers is
        exactly the stale frame this whole design refuses elsewhere. The capture
        is restarted with new tokens, and writing resumes on the first frame
        composed after this point — see :meth:`_on_frame_composed`.
        """
        if not self.is_running() or self._target != LIVE:
            return
        self._ble_allowed = False
        self._awaiting_fresh_base = True
        self._coordinator.restart_sources()

    def _on_frame_composed(self, frame) -> None:
        """Every composed frame, sent or not. Two jobs and no more.

        Nothing here writes: a frame with no colour clears what is shown, and a
        reconnected run is let through on the first frame that has one.
        """
        if frame.output_rgb is None:
            self._clear_delivered()
        if self._awaiting_fresh_base and frame.should_send and frame.output_rgb is not None:
            self._awaiting_fresh_base = False
            self._ble_allowed = True
            self._coordinator.set_measures_a_link(True)
            host = self._host
            refresh = getattr(getattr(host, "_ambient_ui", None), "refresh_status", None)
            if callable(refresh):
                refresh()

    # ── what is shown beside the card ─────────────────────────────────
    def _show_delivered(self, red: int, green: int, blue: int) -> None:
        """The colour a delivery carried, whether or not a radio took it."""
        preview = getattr(self._host, "ambient_preview", None)
        if preview is not None:
            preview.set_final((int(red), int(green), int(blue)))

    def _clear_delivered(self) -> None:
        preview = getattr(self._host, "ambient_preview", None)
        if preview is not None:
            preview.clear_final()

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
            "target": self._target,
            # Reported from the run rather than from the connection: a report is
            # usually exported after the fact, and by then a strip may well be
            # plugged in that this run never wrote to.
            "previewing": self._target == PREVIEW,
            "writing_to_strip": self._ble_allowed,
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
            "beat_delay": self._coordinator.beat_delays_ms(),
            "music_activity": round(frame.activity, 3),
            "music_stale": frame.music_stale,
            "audio_lost": self.audio_lost(),
            "dropped_screen_samples": dropped_screen,
            "dropped_music_samples": dropped_music,
        }
