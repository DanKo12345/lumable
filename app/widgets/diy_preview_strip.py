from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.diy_effects import (
    DiyEffect,
    color_at,
    duration_scale,
    timeline_boundaries,
    timeline_stops,
    total_duration_ms,
)
from app.theme import qcolor_from_token, theme_manager


class DiyPreviewStrip(QWidget):
    """A rounded strip that previews a DIY effect. The base shows the colour
    sequence as a looping gradient (smooth) or hard bands (cut); a live glowing
    playhead sweeps across it and pulses with each step's motion, so breathe/
    pulse/strobe are visible before the effect is even started."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors: list[tuple[int, int, int]] = [(40, 40, 44)]
        self._smooth = True
        self._effect: DiyEffect | None = None
        self._wall_ms = 0.0
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        # PreciseTimer avoids Windows' ~15.6 ms coarse tick that makes a 30 fps
        # timer fire unevenly (looks like ~15 fps); 16 ms gives a smooth ~60 fps.
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self.setMinimumHeight(48)

    def set_colors(self, colors: list[tuple[int, int, int]]) -> None:
        self._colors = [tuple(c) for c in colors] or [(40, 40, 44)]
        self.update()

    def set_smooth(self, smooth: bool) -> None:
        self._smooth = bool(smooth)
        self.update()

    def set_effect(self, effect: DiyEffect | None) -> None:
        self._effect = effect
        self._sync_timer()
        self.update()

    # ── live playhead ────────────────────────────────────────────────
    def _sync_timer(self) -> None:
        animatable = (
            self._effect is not None
            and total_duration_ms(self._effect) > 0
            and self.isVisible()
        )
        if animatable and not self._timer.isActive():
            self._wall_ms = 0.0
            self._elapsed.restart()
            self._timer.start()
        elif not animatable and self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _advance(self) -> None:
        self._wall_ms += self._elapsed.restart()
        self.update()

    def _playhead(self) -> tuple[float, tuple[int, int, int]] | None:
        effect = self._effect
        if effect is None:
            return None
        total = total_duration_ms(effect)
        if total <= 0:
            return None
        scale = duration_scale(effect.speed)
        scaled_total = total * scale
        if scaled_total <= 0:
            return None
        pos = self._wall_ms % scaled_total
        phase = pos / scaled_total
        return phase, color_at(effect, pos / scale)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        outer_radius = 11.0
        outer_path = QPainterPath()
        outer_path.addRoundedRect(rect, outer_radius, outer_radius)
        painter.fillPath(outer_path, qcolor_from_token(theme_manager.palette["field_alt"]))
        painter.setPen(QPen(qcolor_from_token(theme_manager.palette["field_border"]), 1.0))
        painter.drawPath(outer_path)

        track = rect.adjusted(9.0, 10.0, -9.0, -10.0)
        radius = track.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(track, radius, radius)

        grad = QLinearGradient(track.left(), 0.0, track.right(), 0.0)
        if self._effect is not None:
            for position, color in timeline_stops(self._effect):
                grad.setColorAt(max(0.0, min(1.0, position)), QColor(*color))
        else:
            colors = self._colors
            if len(colors) == 1:
                grad.setColorAt(0.0, QColor(*colors[0]))
                grad.setColorAt(1.0, QColor(*colors[0]))
            else:
                seq = [*colors, colors[0]]
                span = len(seq) - 1
                for index, color in enumerate(seq):
                    qc = QColor(*color)
                    grad.setColorAt(index / span, qc)
        painter.fillPath(path, grad)

        if self._effect is not None:
            painter.save()
            painter.setClipPath(path)
            painter.setPen(QPen(QColor(255, 255, 255, 85), 1.0))
            for boundary in timeline_boundaries(self._effect):
                x = track.left() + boundary * track.width()
                painter.drawLine(QPointF(x, track.top() + 3.0), QPointF(x, track.bottom() - 3.0))
            painter.restore()

        head = self._playhead()
        if head is not None:
            phase, color = head
            painter.setClipPath(path)  # keep the bead inside the rounded strip
            cx = track.left() + phase * track.width()
            cy = track.center().y()
            qc = QColor(*color)
            level = max(color) / 255.0  # brightness drives size + glow → shows motion
            bead_r = track.height() * (0.34 + 0.10 * level)

            # soft outer halo (tinted with the current colour)
            halo_r = bead_r * 1.9
            halo = QRadialGradient(cx, cy, halo_r)
            halo.setColorAt(0.0, QColor(qc.red(), qc.green(), qc.blue(), int(70 + 120 * level)))
            halo.setColorAt(1.0, QColor(qc.red(), qc.green(), qc.blue(), 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

            # glossy bead: bright specular top, colour body, darker rim
            body = QRadialGradient(cx, cy - bead_r * 0.4, bead_r * 1.4)
            body.setColorAt(0.0, QColor(255, 255, 255, int(160 + 95 * level)))
            body.setColorAt(0.45, qc.lighter(135))
            body.setColorAt(1.0, qc.darker(118))
            painter.setBrush(body)
            painter.drawEllipse(QPointF(cx, cy), bead_r, bead_r)

            # crisp thin ring so the bead reads on any background colour
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 140), 1.4))
            painter.drawEllipse(QPointF(cx, cy), bead_r, bead_r)
