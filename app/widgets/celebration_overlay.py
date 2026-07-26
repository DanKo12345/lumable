from __future__ import annotations

import math
import random

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.motion_policy import motion_policy
from app.theme import qcolor_from_token, theme_manager

_CONFETTI_COLORS = (
    QColor(127, 183, 255),
    QColor(111, 158, 255),
    QColor(91, 224, 201),
    QColor(170, 120, 255),
    QColor(255, 196, 92),
    QColor(255, 141, 176),
    QColor(255, 255, 255),
)


class CelebrationOverlay(QWidget):
    """A one-shot success animation: a confetti burst plus a checkmark badge.

    Lives on top of its parent, ignores mouse input, runs for ~1.7 s and then
    emits :attr:`finished` and deletes itself. Drive it with :meth:`start`.
    """

    finished = Signal()

    DURATION_MS = 1700
    _BADGE_POP_MS = 460
    _CHECK_START_MS = 250
    _CHECK_DRAW_MS = 380
    _PARTICLE_COUNT = 96

    def __init__(self, parent: QWidget | None = None, *, message: str = "") -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._message = message
        if parent is not None:
            self.setGeometry(parent.rect())
        self._elapsed = QElapsedTimer()
        self._particles: list[dict] = []
        self._pop_ease = QEasingCurve(QEasingCurve.OutBack)
        self._draw_ease = QEasingCurve(QEasingCurve.OutCubic)
        self._static = False
        # Two timers with distinct jobs: a 60fps frame timer only drives the
        # confetti/animation, and a single-shot finish timer owns the close. Under
        # reduced motion the frame timer never runs, but the finish timer still
        # closes the overlay on schedule.
        self._frame_timer = QTimer(self)
        self._frame_timer.setTimerType(Qt.PreciseTimer)
        self._frame_timer.timeout.connect(self._advance_frame)
        self._finish_timer = QTimer(self)
        self._finish_timer.setSingleShot(True)
        self._finish_timer.timeout.connect(self._finish)
        motion_policy.changed.connect(self._on_motion_changed)

    def start(self) -> None:
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())
        self._static = motion_policy.reduced
        if not self._static:
            self._spawn_particles()
        self.show()
        self.raise_()
        self._elapsed.start()
        # The functional close is independent of motion — never stopped/restarted.
        self._finish_timer.start(self.DURATION_MS)
        if not self._static:
            self._frame_timer.start(16)
        self.update()

    def _advance_frame(self) -> None:
        for particle in self._particles:
            particle["vy"] += 0.45
            particle["vx"] *= 0.992
            particle["x"] += particle["vx"]
            particle["y"] += particle["vy"]
            particle["ang"] += particle["spin"]
        self.update()

    def _finish(self) -> None:
        self._frame_timer.stop()
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def _on_motion_changed(self, reduced: bool) -> None:
        # Freeze an in-flight celebration when motion is reduced, but never
        # un-freeze it — resuming confetti mid-show would jump visually backwards.
        # A one-shot celebration stays static until its close timer fires; the
        # next launch under full motion animates fully again.
        if reduced and not self._static:
            self._static = True
            self._frame_timer.stop()
            self._particles.clear()
            self.update()

    def _center(self) -> QPointF:
        return QPointF(self.width() / 2.0, self.height() / 2.0)

    def _spawn_particles(self) -> None:
        self._particles.clear()
        center = self._center()
        for _ in range(self._PARTICLE_COUNT):
            angle = random.uniform(0.0, 2.0 * math.pi)
            speed = random.uniform(3.5, 11.5)
            self._particles.append(
                {
                    "x": center.x() + random.uniform(-26.0, 26.0),
                    "y": center.y() + random.uniform(-18.0, 18.0),
                    "vx": math.cos(angle) * speed,
                    "vy": math.sin(angle) * speed - random.uniform(2.0, 6.5),
                    "ang": random.uniform(0.0, 360.0),
                    "spin": random.uniform(-15.0, 15.0),
                    "w": random.uniform(6.0, 12.0),
                    "h": random.uniform(8.0, 16.0),
                    "color": random.choice(_CONFETTI_COLORS),
                    "round": random.random() < 0.34,
                }
            )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._static:
            # Reduced motion: the final resting state up front — full badge, drawn
            # check and message, and no confetti.
            final = float(self.DURATION_MS)
            self._paint_badge(painter, final)
            self._paint_message(painter, final)
            return
        elapsed = float(self._elapsed.elapsed()) if self._elapsed.isValid() else 0.0
        self._paint_confetti(painter, elapsed)
        self._paint_badge(painter, elapsed)
        self._paint_message(painter, elapsed)

    def _paint_confetti(self, painter: QPainter, elapsed: float) -> None:
        fade_start = self.DURATION_MS * 0.62
        global_alpha = 1.0
        if elapsed > fade_start:
            global_alpha = max(0.0, 1.0 - (elapsed - fade_start) / (self.DURATION_MS - fade_start))
        painter.setPen(Qt.NoPen)
        for particle in self._particles:
            color = QColor(particle["color"])
            color.setAlpha(int(235 * global_alpha))
            painter.setBrush(color)
            painter.save()
            painter.translate(particle["x"], particle["y"])
            painter.rotate(particle["ang"])
            rect = QRectF(-particle["w"] / 2.0, -particle["h"] / 2.0, particle["w"], particle["h"])
            if particle["round"]:
                painter.drawEllipse(rect)
            else:
                painter.drawRoundedRect(rect, 2.0, 2.0)
            painter.restore()

    def _paint_badge(self, painter: QPainter, elapsed: float) -> None:
        pop = self._pop_ease.valueForProgress(min(1.0, elapsed / self._BADGE_POP_MS))
        if pop <= 0.0:
            return
        center = self._center()
        radius = 46.0 * pop

        glow = QRadialGradient(center, radius * 2.0)
        glow.setColorAt(0.0, QColor(120, 200, 170, int(120 * pop)))
        glow.setColorAt(1.0, QColor(120, 200, 170, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, radius * 2.0, radius * 2.0)

        fill = QRadialGradient(center.x(), center.y() - radius * 0.3, radius * 1.6)
        fill.setColorAt(0.0, QColor(108, 240, 196))
        fill.setColorAt(1.0, QColor(38, 178, 138))
        painter.setBrush(fill)
        painter.drawEllipse(center, radius, radius)

        ring = QColor(255, 255, 255, int(70 * pop))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(ring, 1.6))
        painter.drawEllipse(center, radius, radius)

        draw = self._draw_ease.valueForProgress(
            max(0.0, min(1.0, (elapsed - self._CHECK_START_MS) / self._CHECK_DRAW_MS))
        )
        if draw <= 0.0:
            return
        unit = radius / 46.0
        start = QPointF(center.x() - 20.0 * unit, center.y() + 1.0 * unit)
        elbow = QPointF(center.x() - 5.0 * unit, center.y() + 15.0 * unit)
        tip = QPointF(center.x() + 22.0 * unit, center.y() - 16.0 * unit)

        first_len = 0.42
        path = QPainterPath(start)
        if draw <= first_len:
            t = draw / first_len
            path.lineTo(self._lerp(start, elbow, t))
        else:
            path.lineTo(elbow)
            t = (draw - first_len) / (1.0 - first_len)
            path.lineTo(self._lerp(elbow, tip, t))
        pen = QPen(QColor(255, 255, 255), max(2.0, 5.0 * unit))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

    def _paint_message(self, painter: QPainter, elapsed: float) -> None:
        if not self._message:
            return
        alpha = max(0.0, min(1.0, (elapsed - self._BADGE_POP_MS * 0.6) / 320.0))
        if alpha <= 0.0:
            return
        color = qcolor_from_token(theme_manager.palette["text"])
        color.setAlpha(int(color.alpha() * alpha))
        font = QFont(self.font())
        font.setPointSize(13)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(color)
        center = self._center()
        rect = QRectF(0.0, center.y() + 70.0, float(self.width()), 36.0)
        painter.drawText(rect, Qt.AlignHCenter | Qt.AlignTop, self._message)

    @staticmethod
    def _lerp(a: QPointF, b: QPointF, t: float) -> QPointF:
        return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
