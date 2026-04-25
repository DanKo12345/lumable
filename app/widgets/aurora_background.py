from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

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
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = True
        self._phase = 0.0
        self._phase_target = 0.0
        self._phase_speed = 0.32
        self._frame_interval_ms = 12
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self._frame_interval_ms)
        self._elapsed.start()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def set_dark(self, dark: bool):
        self._dark = dark
        self.update()

    def _tick(self):
        if not self.isVisible() or (self.window() and self.window().isMinimized()):
            self._elapsed.restart()
            return

        elapsed_ms = self._elapsed.restart()
        if elapsed_ms <= 0:
            elapsed_ms = self._frame_interval_ms
        elapsed_ms = min(elapsed_ms, 24)

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

        start_color = qcolor_from_token(palette["window_start"])
        end_color = qcolor_from_token(palette["window_end"])

        base = QLinearGradient(0, 0, w, h)
        if self._dark:
            swap = (math.sin(self._phase * 0.26) + 1.0) * 0.5
            center = (math.cos(self._phase * 0.33 + 0.8) + 1.0) * 0.5
            left_color = mix_colors(start_color, end_color, swap * 0.38)
            right_color = mix_colors(end_color, start_color, swap * 0.38)
            center_color = mix_colors(left_color, right_color, 0.5 + (center - 0.5) * 0.4)
            base.setColorAt(0.0, left_color)
            base.setColorAt(0.52, center_color)
            base.setColorAt(1.0, right_color)
        else:
            swap = (math.sin(self._phase * 0.22) + 1.0) * 0.5
            center = (math.cos(self._phase * 0.28 + 0.65) + 1.0) * 0.5
            left_color = mix_colors(start_color, end_color, swap * 0.18)
            right_color = mix_colors(end_color, start_color, swap * 0.18)
            center_color = mix_colors(left_color, right_color, 0.5 + (center - 0.5) * 0.22)
            base.setColorAt(0.0, left_color)
            base.setColorAt(0.52, center_color)
            base.setColorAt(1.0, right_color)
        painter.fillRect(self.rect(), base)

        # Let the dark backdrop "breathe" with the same palette instead of
        # introducing new hues. Keep it visible enough to read as motion,
        # but still premium and slow.
        if self._dark:
            pulse = (math.sin(self._phase * 0.58) + 1.0) * 0.5
            drift = (math.cos(self._phase * 0.44 + 0.7) + 1.0) * 0.5
            sweep = (math.sin(self._phase * 0.34 + 1.1) + 1.0) * 0.5

            wave = QLinearGradient(
                w * (0.04 + sweep * 0.08),
                h * (0.10 + drift * 0.08),
                w * (0.96 - sweep * 0.06),
                h * (0.92 - drift * 0.06),
            )
            wave_top = qcolor_from_token(palette["window_start"])
            wave_bottom = qcolor_from_token(palette["window_end"])
            wave_top.setAlpha(int(40 + pulse * 22))
            wave_bottom.setAlpha(int(52 + drift * 22))
            wave.setColorAt(0.0, wave_top)
            wave.setColorAt(0.42, QColor(wave_top.red(), wave_top.green(), wave_top.blue(), int(18 + pulse * 10)))
            wave.setColorAt(1.0, wave_bottom)
            painter.fillRect(self.rect(), wave)

            veil = QLinearGradient(w * (0.02 + drift * 0.08), 0, w * (0.98 - drift * 0.05), h)
            veil_left = QColor(255, 255, 255, int(10 + pulse * 10))
            veil_mid = QColor(160, 190, 255, int(18 + drift * 14))
            veil_right = QColor(255, 255, 255, 0)
            veil.setColorAt(0.0, veil_left)
            veil.setColorAt(0.52, veil_mid)
            veil.setColorAt(1.0, veil_right)
            painter.fillRect(self.rect(), veil)

            bloom = QRadialGradient(
                w * (0.30 + sweep * 0.24),
                h * (0.34 + pulse * 0.10),
                max(w, h) * 0.72,
            )
            bloom_core = QColor(110, 150, 255, int(18 + pulse * 12))
            bloom_mid = QColor(86, 118, 210, int(10 + drift * 10))
            bloom_edge = QColor(86, 118, 210, 0)
            bloom.setColorAt(0.0, bloom_core)
            bloom.setColorAt(0.48, bloom_mid)
            bloom.setColorAt(1.0, bloom_edge)
            painter.fillRect(self.rect(), bloom)
        else:
            pulse = (math.sin(self._phase * 0.46) + 1.0) * 0.5
            drift = (math.cos(self._phase * 0.34 + 0.55) + 1.0) * 0.5
            sweep = (math.sin(self._phase * 0.26 + 0.9) + 1.0) * 0.5

            wave = QLinearGradient(
                w * (0.06 + sweep * 0.06),
                h * (0.08 + drift * 0.06),
                w * (0.94 - sweep * 0.05),
                h * (0.94 - drift * 0.05),
            )
            wave_top = qcolor_from_token(palette["window_start"])
            wave_bottom = qcolor_from_token(palette["window_end"])
            wave_top.setAlpha(int(16 + pulse * 10))
            wave_bottom.setAlpha(int(20 + drift * 10))
            wave.setColorAt(0.0, wave_top)
            wave.setColorAt(
                0.50,
                QColor(wave_top.red(), wave_top.green(), wave_top.blue(), int(8 + pulse * 6)),
            )
            wave.setColorAt(1.0, wave_bottom)
            painter.fillRect(self.rect(), wave)

            veil = QLinearGradient(w * (0.04 + drift * 0.06), 0, w * (0.96 - drift * 0.04), h)
            veil_left = QColor(255, 255, 255, int(12 + pulse * 8))
            veil_mid = QColor(165, 196, 255, int(12 + drift * 10))
            veil_right = QColor(255, 255, 255, 0)
            veil.setColorAt(0.0, veil_left)
            veil.setColorAt(0.50, veil_mid)
            veil.setColorAt(1.0, veil_right)
            painter.fillRect(self.rect(), veil)

            bloom = QRadialGradient(
                w * (0.34 + sweep * 0.18),
                h * (0.40 + pulse * 0.08),
                max(w, h) * 0.66,
            )
            bloom_core = QColor(150, 195, 255, int(12 + pulse * 8))
            bloom_mid = QColor(176, 196, 255, int(8 + drift * 6))
            bloom_edge = QColor(176, 196, 255, 0)
            bloom.setColorAt(0.0, bloom_core)
            bloom.setColorAt(0.46, bloom_mid)
            bloom.setColorAt(1.0, bloom_edge)
            painter.fillRect(self.rect(), bloom)

        if self._dark:
            orbs = [
                (0.16, 0.14, 0.42, QColor(72, 132, 255, 58)),
                (0.78, 0.18, 0.28, QColor(124, 90, 255, 46)),
                (0.52, 0.78, 0.38, QColor(75, 215, 210, 30)),
            ]
        else:
            orbs = [
                (0.16, 0.14, 0.42, QColor(100, 160, 255, 55)),
                (0.78, 0.18, 0.28, QColor(150, 100, 255, 42)),
                (0.52, 0.78, 0.38, QColor(80, 200, 220, 32)),
            ]
        for ox, oy, size, color in orbs:
            cx = (ox + math.sin(self._phase + ox) * 0.03) * w
            cy = (oy + math.cos(self._phase + oy) * 0.03) * h
            radius = size * max(w, h)
            grad = QRadialGradient(cx, cy, radius)
            grad.setColorAt(0.0, color)
            edge = QColor(color)
            edge.setAlpha(0)
            grad.setColorAt(1.0, edge)
            painter.fillRect(self.rect(), grad)
