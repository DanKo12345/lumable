from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.motion_policy import motion_policy
from app.theme import qcolor_from_token, theme_manager


def mix_colors(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, float(t)))
    inv = 1.0 - t
    return QColor(
        round(a.red() * inv + b.red() * t),
        round(a.green() * inv + b.green() * t),
        round(a.blue() * inv + b.blue() * t),
        round(a.alpha() * inv + b.alpha() * t),
    )


class AuroraBackground(QWidget):
    ACTIVE_INTERVAL_MS = 33
    CAPTURE_INTERVAL_MS = 1000
    # When the window is not the active one, paint every Nth tick only
    # (~5 fps at 33 ms) so a backdrop on a second monitor still moves slowly
    # without burning CPU/GPU.
    INACTIVE_FRAME_SKIP = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = True
        self._phase = 0.0
        self._phase_target = 0.0
        self._phase_speed = 0.32
        # ~30 fps is plenty for this slow ambient motion. The old 12 ms (~83 fps)
        # only burned CPU/battery and rendered frames most 60 Hz displays drop.
        self._active_interval_ms = self.ACTIVE_INTERVAL_MS
        self._frame_interval_ms = self._active_interval_ms
        self._inactive_skip = 0
        self._capture_compatibility = False
        # "Lumen": the strip colour becomes the dominant ambient light. We keep
        # the full-strength rgb plus an enabled flag and build a breathing glow
        # in paintEvent so the whole window washes with the colour you control.
        self._accent_enabled = False
        self._accent_rgb = (120, 150, 255)
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._elapsed.start()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        # Reduced motion freezes the phase (the breathing drift); the background
        # still repaints on colour/theme changes (they call update() directly).
        # Connect on self so Qt drops the signal when the widget is destroyed.
        motion_policy.changed.connect(self._on_motion_changed)
        self._sync_motion_timer()

    def _sync_motion_timer(self) -> None:
        # One rule for every path — show/hide and policy flips alike: the phase
        # timer runs only while the widget is on-screen AND motion is not reduced.
        # This closes the lifecycle gap where a hidden widget flipped back to full
        # would otherwise stay frozen after being shown again.
        if self.isVisible() and not motion_policy.reduced:
            if not self._timer.isActive():
                self._elapsed.restart()
                self._timer.start(self._frame_interval_ms)
        else:
            self._timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_motion_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def _on_motion_changed(self, reduced: bool) -> None:
        if reduced:
            self.update()  # settle on a static frame at the current phase
        self._sync_motion_timer()

    def set_dark(self, dark: bool):
        self._dark = dark
        self.update()

    def set_capture_compatibility(self, enabled: bool) -> None:
        self._capture_compatibility = bool(enabled)
        self._frame_interval_ms = self.CAPTURE_INTERVAL_MS if self._capture_compatibility else self._active_interval_ms
        self._timer.setInterval(self._frame_interval_ms)
        self.update()

    def set_target_fps(self, fps: int) -> None:
        """Set the animation frame rate (ignored while in capture-compat mode)."""
        fps = max(15, min(144, int(fps)))
        self._active_interval_ms = max(7, round(1000.0 / fps))
        if not self._capture_compatibility:
            self._frame_interval_ms = self._active_interval_ms
            self._timer.setInterval(self._frame_interval_ms)

    def set_accent_color(self, r: int, g: int, b: int, *, enabled: bool = True) -> None:
        """
        Blend the current LED strip color into the aurora background.

        Call this whenever the strip color changes. Pass enabled=False when the
        strip is powered off to return to the neutral backdrop.
        """
        if not enabled:
            self._accent_enabled = False
        else:
            self._accent_enabled = True
            self._accent_rgb = (
                max(0, min(255, int(r))),
                max(0, min(255, int(g))),
                max(0, min(255, int(b))),
            )
        self.update()

    def _tick(self):
        window = self.window()
        # Nothing to draw when hidden or minimised.
        if not self.isVisible() or window is None or window.isMinimized():
            self._elapsed.restart()
            return
        if self._capture_compatibility:
            return
        # In the background, drop to a low frame rate rather than freezing, so a
        # backdrop on a second monitor keeps drifting while still saving power.
        if not window.isActiveWindow():
            self._inactive_skip = (self._inactive_skip + 1) % self.INACTIVE_FRAME_SKIP
            if self._inactive_skip != 0:
                self._elapsed.restart()
                return
        else:
            self._inactive_skip = 0

        elapsed_ms = self._elapsed.restart()
        if elapsed_ms <= 0:
            elapsed_ms = self._frame_interval_ms
        elapsed_ms = min(elapsed_ms, 48)

        # Advance a target phase in real time, then ease the displayed phase
        # toward it. This smooths out timer jitter that can happen in Qt Widgets.
        self._phase_target += (elapsed_ms / 1000.0) * self._phase_speed
        blend = min(0.34, max(0.12, elapsed_ms / 1000.0 * 12.0))
        self._phase += (self._phase_target - self._phase) * blend
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        palette = theme_manager.palette

        if self._dark:
            # Premium near-black canvas: almost black in the centre so the
            # interface and the LED colour pop, with only a faint dye at the edges.
            base = QLinearGradient(0, 0, 0, h)
            base.setColorAt(0.0, QColor(14, 16, 24))
            base.setColorAt(0.55, QColor(9, 10, 16))
            base.setColorAt(1.0, QColor(6, 7, 11))
            painter.fillRect(self.rect(), base)
        else:
            start_color = qcolor_from_token(palette["window_start"])
            end_color = qcolor_from_token(palette["window_end"])
            swap = (math.sin(self._phase * 0.22) + 1.0) * 0.5
            center = (math.cos(self._phase * 0.28 + 0.65) + 1.0) * 0.5
            left_color = mix_colors(start_color, end_color, swap * 0.18)
            right_color = mix_colors(end_color, start_color, swap * 0.18)
            center_color = mix_colors(left_color, right_color, 0.5 + (center - 0.5) * 0.22)
            base = QLinearGradient(0, 0, w, h)
            base.setColorAt(0.0, left_color)
            base.setColorAt(0.52, center_color)
            base.setColorAt(1.0, right_color)
            painter.fillRect(self.rect(), base)

        if self._dark:
            # Two faint corner glows over the near-black base — slow, subtle,
            # never a full-screen wash of colour.
            drift = (math.cos(self._phase * 0.30) + 1.0) * 0.5
            pulse = (math.sin(self._phase * 0.40) + 1.0) * 0.5
            top_left = QRadialGradient(w * (0.12 + drift * 0.05), 0.0, max(w, h) * 0.72)
            top_left.setColorAt(0.0, QColor(104, 92, 214, int(22 + pulse * 8)))
            top_left.setColorAt(1.0, QColor(104, 92, 214, 0))
            painter.fillRect(self.rect(), top_left)

            bottom_right = QRadialGradient(w * (0.92 - drift * 0.05), float(h), max(w, h) * 0.68)
            bottom_right.setColorAt(0.0, QColor(52, 104, 190, int(18 + pulse * 8)))
            bottom_right.setColorAt(1.0, QColor(52, 104, 190, 0))
            painter.fillRect(self.rect(), bottom_right)
        else:
            pulse = (math.sin(self._phase * 0.46) + 1.0) * 0.5
            drift = (math.cos(self._phase * 0.34 + 0.55) + 1.0) * 0.5
            # Keep the light canvas neutral. A moving white sheen gives it depth
            # without tinting the whole workspace blue or purple; the strip
            # colour is introduced separately by the Lumen glow below.
            veil = QLinearGradient(w * (0.08 + drift * 0.04), 0, w * 0.92, h)
            veil.setColorAt(0.0, QColor(255, 255, 255, int(16 + pulse * 6)))
            veil.setColorAt(0.48, QColor(255, 255, 255, int(7 + drift * 4)))
            veil.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(self.rect(), veil)

        # ── Lumen glow: the strip colour as a large, slowly breathing light ──
        if self._accent_enabled:
            r, g, b = self._accent_rgb
            pulse = (math.sin(self._phase * 1.5) + 1.0) * 0.5
            core_alpha = int((32 + pulse * 18) if self._dark else (9 + pulse * 6))

            top = QRadialGradient(
                w * 0.5,
                h * (0.02 + pulse * 0.06),
                max(w, h) * (0.92 + pulse * 0.06),
            )
            top.setColorAt(0.0, QColor(r, g, b, core_alpha))
            top.setColorAt(0.42, QColor(r, g, b, int(core_alpha * 0.42)))
            top.setColorAt(1.0, QColor(r, g, b, 0))
            painter.fillRect(self.rect(), top)

            drift = (math.cos(self._phase * 0.4 + 0.6) + 1.0) * 0.5
            low = QRadialGradient(
                w * (0.14 + drift * 0.06),
                h * (1.02 - drift * 0.05),
                max(w, h) * 0.62,
            )
            low_alpha = int(core_alpha * (0.55 if self._dark else 0.28))
            low.setColorAt(0.0, QColor(r, g, b, low_alpha))
            low.setColorAt(1.0, QColor(r, g, b, 0))
            painter.fillRect(self.rect(), low)
