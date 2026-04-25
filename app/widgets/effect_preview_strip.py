from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPropertyAnimation, QRectF, Qt, QTimer, Property
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.theme import qcolor_from_token, theme_manager


class EffectPreviewStrip(QWidget):
    """Compact animated preview used by the effects section."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._intensity = 1.0
        self._speed = 60
        self._effect_key = "static_color"
        self._effect_code = 0
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._pulse_anim = QPropertyAnimation(self, b"intensity", self)
        self._pulse_anim.setDuration(1800)
        self._pulse_anim.setStartValue(0.78)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.start()

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def get_intensity(self) -> float:
        return self._intensity

    def set_intensity(self, value: float) -> None:
        self._intensity = max(0.0, min(1.0, float(value)))
        self.update()

    intensity = Property(float, get_intensity, set_intensity)

    def _tick(self) -> None:
        elapsed_ms = max(0, self._elapsed.elapsed())
        if self._effect_key.startswith("jump"):
            palette_size = len(self._effect_palette())
            step_ms = self._jump_step_duration_ms()
            cycle_ms = max(1.0, step_ms * palette_size)
        else:
            cycle_ms = self._cycle_duration_ms()
        self._phase = ((elapsed_ms % cycle_ms) / cycle_ms) * (math.pi * 2.0)
        self.update()

    def _cycle_duration_ms(self) -> float:
        speed_ratio = self._speed / 100.0
        return 6200.0 - speed_ratio * 3900.0

    def _jump_step_duration_ms(self) -> float:
        # BLEDOM jump effects switch in discrete color steps; use absolute
        # elapsed time so skipped UI frames never accumulate visible drift.
        speed_ratio = self._speed / 100.0
        return 3200.0 - speed_ratio * 2000.0

    def set_speed(self, value: int) -> None:
        self._speed = max(0, min(100, int(value)))
        self._timer.setInterval(max(18, min(60, 72 - self._speed // 2)))
        self.update()

    def set_effect(self, effect_key: str, effect_code: int, *, reset_phase: bool = False) -> None:
        self._effect_key = effect_key or "static_color"
        self._effect_code = int(effect_code)
        if reset_phase:
            self.restart()
        self.update()

    def restart(self) -> None:
        self._phase = 0.0
        self._elapsed.restart()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1.0, 5.0, -1.0, -5.0)
        radius = min(16.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        is_dark = theme_manager.is_dark
        palette = theme_manager.palette
        surface = qcolor_from_token(palette["surface_strong" if is_dark else "surface_soft"])
        border = qcolor_from_token(palette["surface_border"])

        base = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        if is_dark:
            base.setColorAt(0.0, QColor(20, 33, 72, 190))
            base.setColorAt(0.55, QColor(14, 24, 54, 184))
            base.setColorAt(1.0, QColor(10, 17, 42, 198))
        else:
            base.setColorAt(0.0, QColor(255, 255, 255, 198))
            base.setColorAt(0.55, QColor(236, 244, 255, 172))
            base.setColorAt(1.0, QColor(214, 229, 252, 158))
        painter.fillPath(path, base)

        painter.save()
        painter.setClipPath(path)

        self._paint_effect_material(painter, path, rect, is_dark)

        top_light = QLinearGradient(0, rect.top(), 0, rect.bottom())
        top_light.setColorAt(0.0, QColor(255, 255, 255, 36 if is_dark else 70))
        top_light.setColorAt(0.28, QColor(255, 255, 255, 10 if is_dark else 22))
        top_light.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, top_light)

        painter.restore()

        edge = QColor(border)
        edge.setAlpha(82 if is_dark else 105)
        painter.setPen(QPen(edge, 1.0))
        painter.drawRoundedRect(rect, radius, radius)

        inner = QColor(surface)
        inner.setAlpha(28 if is_dark else 42)
        painter.setPen(QPen(inner, 1.0))
        painter.drawRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), radius - 1.0, radius - 1.0)

    def _paint_effect_material(self, painter: QPainter, path: QPainterPath, rect: QRectF, is_dark: bool) -> None:
        key = self._effect_key
        if key.startswith("flash"):
            self._paint_flash(painter, path, rect, is_dark)
        elif key.startswith("jump"):
            self._paint_jump(painter, path, rect, is_dark)
        elif "rainbow" in key or "spectrum" in key:
            self._paint_rainbow(painter, path, rect, is_dark)
        elif key.startswith("fade"):
            self._paint_fade(painter, path, rect, is_dark)
        else:
            self._paint_static(painter, path, rect, is_dark)

    def _paint_static(self, painter: QPainter, path: QPainterPath, rect: QRectF, is_dark: bool) -> None:
        accent = QColor(118, 174, 255, 82 if is_dark else 68)
        glow = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        glow.setColorAt(0.0, QColor(96, 180, 255, accent.alpha()))
        glow.setColorAt(0.55, QColor(158, 132, 255, max(36, accent.alpha() - 18)))
        glow.setColorAt(1.0, QColor(118, 174, 255, accent.alpha()))
        painter.fillPath(path, glow)

    def _paint_jump(self, painter: QPainter, path: QPainterPath, rect: QRectF, is_dark: bool) -> None:
        palette = self._effect_palette()
        step = int((self._phase / (math.pi * 2.0)) * len(palette)) % len(palette)
        color = QColor(palette[step])
        color.setAlpha(124 if is_dark else 98)
        fill = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        fill.setColorAt(0.0, color.lighter(132))
        fill.setColorAt(0.45, color)
        fill.setColorAt(1.0, color.darker(128))
        painter.fillPath(path, fill)

        edge_flash = QColor(255, 255, 255, 26 if is_dark else 38)
        edge = QLinearGradient(rect.left(), 0, rect.right(), 0)
        edge.setColorAt(0.0, edge_flash)
        edge.setColorAt(0.08, QColor(255, 255, 255, 0))
        edge.setColorAt(0.92, QColor(255, 255, 255, 0))
        edge.setColorAt(1.0, edge_flash)
        painter.fillPath(path, edge)

    def _paint_fade(self, painter: QPainter, path: QPainterPath, rect: QRectF, is_dark: bool) -> None:
        colors = self._gradient_effect_colors()
        if len(colors) > 1:
            color = self._cycle_color(colors)
            pulse = 0.84
        else:
            color = colors[0]
            pulse = 0.28 + 0.56 * (0.5 + 0.5 * math.sin(self._phase))
        color.setAlpha(int((118 if is_dark else 92) * pulse * self._intensity))
        fill = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        fill.setColorAt(0.0, color.lighter(138))
        fill.setColorAt(0.52, color)
        fill.setColorAt(1.0, color.darker(132))
        painter.fillPath(path, fill)

        width = max(1.0, rect.width())
        glow_x = rect.left() + width * (0.5 + 0.18 * math.sin(self._phase * 0.72))
        breathing = QRadialGradient(glow_x, rect.center().y(), width * (0.34 + pulse * 0.18))
        breathing.setColorAt(0.0, QColor(255, 255, 255, 28 if is_dark else 42))
        breathing.setColorAt(0.42, QColor(color.red(), color.green(), color.blue(), 28 if is_dark else 34))
        breathing.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, breathing)

    def _paint_flash(self, painter: QPainter, path: QPainterPath, rect: QRectF, is_dark: bool) -> None:
        color = self._cycle_color(self._effect_palette()) if "spectrum" in self._effect_key else self._single_effect_color()
        raw = (math.sin(self._phase * 3.2) + 1.0) * 0.5
        pulse = 1.0 if raw > 0.78 else 0.16
        color.setAlpha(int((138 if is_dark else 112) * pulse))
        painter.fillPath(path, color)

        if pulse > 0.5:
            width = max(1.0, rect.width())
            flash = QRadialGradient(rect.center(), width * 0.36)
            flash.setColorAt(0.0, QColor(255, 255, 255, 92 if is_dark else 112))
            flash.setColorAt(0.28, QColor(color.red(), color.green(), color.blue(), 48 if is_dark else 56))
            flash.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, flash)

    def _paint_rainbow(self, painter: QPainter, path: QPainterPath, rect: QRectF, is_dark: bool) -> None:
        width = max(1.0, rect.width())
        phase_progress = self._phase / (math.pi * 2.0)
        offset = (phase_progress * 0.46 + math.sin(self._phase) * 0.06) * width
        wave = QLinearGradient(rect.left() - width * 0.38 + offset, rect.center().y(), rect.right() + offset, rect.center().y())
        alpha = int(92 * self._intensity) if is_dark else int(76 * self._intensity)
        wave.setColorAt(0.00, QColor(95, 230, 218, alpha))
        wave.setColorAt(0.20, QColor(88, 170, 255, alpha + 8))
        wave.setColorAt(0.42, QColor(183, 130, 255, alpha))
        wave.setColorAt(0.66, QColor(255, 141, 150, max(42, alpha - 12)))
        wave.setColorAt(0.84, QColor(255, 216, 102, max(38, alpha - 18)))
        wave.setColorAt(1.00, QColor(114, 234, 201, alpha))
        painter.fillPath(path, wave)

        crest_y = rect.center().y() + math.sin(self._phase * 1.35) * rect.height() * 0.16
        crest = QRadialGradient(rect.left() + width * (0.46 + math.sin(self._phase * 0.85) * 0.18), crest_y, width * 0.52)
        crest.setColorAt(0.0, QColor(255, 255, 255, 30 if is_dark else 42))
        crest.setColorAt(0.45, QColor(145, 225, 255, 18 if is_dark else 26))
        crest.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, crest)

        ribbon = QPainterPath()
        y_mid = rect.center().y()
        amp = rect.height() * 0.18
        ribbon.moveTo(rect.left() - 8.0, y_mid + math.sin(self._phase) * amp)
        ribbon.cubicTo(
            rect.left() + width * 0.28,
            y_mid - amp * 1.4,
            rect.left() + width * 0.58,
            y_mid + amp * 1.5,
            rect.right() + 8.0,
            y_mid + math.sin(self._phase + 1.2) * amp,
        )
        painter.setPen(QPen(QColor(255, 255, 255, 42 if is_dark else 58), 2.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(ribbon)

    def _single_effect_color(self) -> QColor:
        key = self._effect_key
        colors = {
            "red": QColor(255, 92, 112),
            "green": QColor(94, 226, 178),
            "blue": QColor(118, 174, 255),
            "yellow": QColor(255, 216, 100),
            "cyan": QColor(88, 226, 232),
            "magenta": QColor(197, 118, 255),
            "white": QColor(245, 248, 255),
        }
        for token, color in colors.items():
            if token in key:
                return QColor(color)
        return QColor(118, 174, 255)

    def _gradient_effect_colors(self) -> list[QColor]:
        if self._effect_key == "fade_red_green":
            return [QColor(255, 92, 112), QColor(94, 226, 178)]
        if self._effect_key == "fade_red_blue":
            return [QColor(255, 92, 112), QColor(118, 174, 255)]
        if self._effect_key == "fade_green_blue":
            return [QColor(94, 226, 178), QColor(118, 174, 255)]
        return [self._single_effect_color()]

    def _cycle_color(self, colors: list[QColor]) -> QColor:
        if not colors:
            return QColor(118, 174, 255)
        if len(colors) == 1:
            return QColor(colors[0])
        progress = (self._phase / (math.pi * 2.0)) * len(colors)
        index = int(progress) % len(colors)
        next_index = (index + 1) % len(colors)
        mix = progress - math.floor(progress)
        start = colors[index]
        end = colors[next_index]
        return QColor(
            round(start.red() + (end.red() - start.red()) * mix),
            round(start.green() + (end.green() - start.green()) * mix),
            round(start.blue() + (end.blue() - start.blue()) * mix),
        )

    def _effect_palette(self) -> list[QColor]:
        if self._effect_key == "jump_rgb":
            return [QColor(255, 92, 112), QColor(94, 226, 178), QColor(118, 174, 255)]
        return [
            QColor(255, 92, 112),
            QColor(94, 226, 178),
            QColor(118, 174, 255),
            QColor(88, 226, 232),
            QColor(197, 118, 255),
            QColor(255, 216, 100),
            QColor(245, 248, 255),
        ]
