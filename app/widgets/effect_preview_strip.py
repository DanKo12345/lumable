from __future__ import annotations

import math

from PySide6.QtCore import Property, QEasingCurve, QElapsedTimer, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.theme import qcolor_from_token, theme_manager


def effect_semantic_key(effect_key: str, effect_code: int) -> str:
    key = effect_key or "static_color"
    code = int(effect_code)
    if key.startswith("banlanx_effect_"):
        banlanx_effects = {
            0x01: "smooth_rainbow",
            0x02: "jump_rgb",
            0x03: "jump_rgb_cmyw",
            0x04: "fade_spectrum",
            0x05: "flash_spectrum",
            0x06: "fade_red",
            0x07: "fade_green",
            0x08: "fade_blue",
            0x09: "fade_yellow",
            0x0A: "fade_cyan",
            0x0B: "fade_magenta",
            0x0C: "fade_white",
            0x0D: "flash_red",
            0x0E: "flash_green",
            0x0F: "flash_blue",
            0x10: "flash_yellow",
            0x11: "flash_cyan",
            0x12: "flash_magenta",
            0x13: "flash_white",
            0x14: "fade_red_green",
            0x15: "fade_red_blue",
            0x16: "fade_green_blue",
            0x17: "smooth_spectrum",
        }
        return banlanx_effects.get(code, "smooth_spectrum")
    if key.startswith(("triones_", "magic_home_")):
        shared_effects = {
            0x25: "smooth_rainbow",
            0x26: "fade_red",
            0x27: "fade_green",
            0x28: "fade_blue",
            0x29: "fade_yellow",
            0x2A: "fade_cyan",
            0x2B: "fade_magenta",
            0x2C: "fade_white",
            0x2D: "fade_red_green",
            0x2E: "fade_red_blue",
            0x2F: "fade_green_blue",
            0x30: "flash_spectrum",
            0x31: "flash_red",
            0x32: "flash_green",
            0x33: "flash_blue",
            0x34: "flash_yellow",
            0x35: "flash_cyan",
            0x36: "flash_magenta",
            0x37: "flash_white",
            0x38: "jump_rgb_cmyw",
        }
        return shared_effects.get(code, key)
    return key


class EffectPreviewStrip(QWidget):
    """Compact animated preview used by the effects section."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._intensity = 1.0
        self._active_pulse = 0.0
        self._speed = 60
        self._effect_key = "static_color"
        self._effect_code = 0
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._last_tick_ms = 0
        self._prev_pixmap: QPixmap | None = None
        self._switch_value = 0.0
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

        self._active_pulse_anim = QPropertyAnimation(self, b"activePulse", self)
        self._active_pulse_anim.setDuration(2400)
        self._active_pulse_anim.setStartValue(0.0)
        self._active_pulse_anim.setEndValue(1.0)
        self._active_pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._active_pulse_anim.setLoopCount(-1)
        self._active_pulse_anim.start()

        self._switch_anim = QPropertyAnimation(self, b"switchValue", self)
        self._switch_anim.setDuration(300)
        self._switch_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @staticmethod
    def _phase_from_elapsed(elapsed_ms: int, cycle_ms: float) -> float:
        return ((elapsed_ms % max(1.0, cycle_ms)) / max(1.0, cycle_ms)) * (math.pi * 2.0)

    def get_intensity(self) -> float:
        return self._intensity

    def set_intensity(self, value: float) -> None:
        self._intensity = max(0.0, min(1.0, float(value)))
        self.update()

    intensity = Property(float, get_intensity, set_intensity)

    def get_active_pulse(self) -> float:
        return self._active_pulse

    def set_active_pulse(self, value: float) -> None:
        self._active_pulse = max(0.0, min(1.0, float(value)))
        self.update()

    activePulse = Property(float, get_active_pulse, set_active_pulse)

    def get_switch_value(self) -> float:
        return self._switch_value

    def set_switch_value(self, value: float) -> None:
        self._switch_value = max(0.0, min(1.0, float(value)))
        if self._switch_value <= 0.001:
            self._prev_pixmap = None
        self.update()

    switchValue = Property(float, get_switch_value, set_switch_value)

    def _tick(self) -> None:
        elapsed_ms = max(0, self._elapsed.elapsed())
        delta_ms = max(0, elapsed_ms - self._last_tick_ms)
        self._last_tick_ms = elapsed_ms
        semantic_key = effect_semantic_key(self._effect_key, self._effect_code)
        if semantic_key.startswith("jump"):
            palette_size = len(self._effect_palette())
            step_ms = self._jump_step_duration_ms()
            cycle_ms = max(1.0, step_ms * palette_size)
            self._phase = self._phase_from_elapsed(elapsed_ms, cycle_ms)
            self.update()
            return
        if semantic_key.startswith("flash"):
            self._phase = self._phase_from_elapsed(elapsed_ms, self._flash_cycle_duration_ms())
            self.update()
            return
        if "rainbow" in semantic_key or "spectrum" in semantic_key:
            cycle_ms = self._rainbow_cycle_duration_ms()
        else:
            cycle_ms = self._cycle_duration_ms()
        self._phase = (self._phase + (delta_ms / cycle_ms) * (math.pi * 2.0)) % (math.pi * 2.0)
        self.update()

    def _cycle_duration_ms(self) -> float:
        speed_ratio = self._speed / 100.0
        return 6200.0 - speed_ratio * 3900.0

    def _jump_step_duration_ms(self) -> float:
        # BLEDOM jump effects switch in discrete color steps; use absolute
        # elapsed time so skipped UI frames never accumulate visible drift.
        speed_ratio = self._speed / 100.0
        return 1800.0 - speed_ratio * 1100.0

    def _flash_cycle_duration_ms(self) -> float:
        speed_ratio = self._speed / 100.0
        return 3600.0 - speed_ratio * 2300.0

    def _rainbow_cycle_duration_ms(self) -> float:
        speed_ratio = self._speed / 100.0
        return 8600.0 - speed_ratio * 6400.0

    def set_target_fps(self, fps: int) -> None:
        fps = max(15, min(144, int(fps)))
        self._timer.setInterval(max(7, round(1000.0 / fps)))

    def set_speed(self, value: int) -> None:
        self._speed = max(0, min(100, int(value)))
        self.update()

    def set_effect(self, effect_key: str, effect_code: int, *, reset_phase: bool = False) -> None:
        new_key = effect_key or "static_color"
        new_code = int(effect_code)
        changed = new_key != self._effect_key or new_code != self._effect_code
        if changed and self.isVisible() and self.width() > 4 and self.height() > 4:
            # Cross-dissolve from the previous look to the new one.
            self._prev_pixmap = self.grab()
            self._switch_anim.stop()
            self._switch_value = 1.0
            self._switch_anim.setStartValue(1.0)
            self._switch_anim.setEndValue(0.0)
            self._switch_anim.start()
        self._effect_key = new_key
        self._effect_code = new_code
        if reset_phase:
            self.restart()
            self._active_pulse_anim.setCurrentTime(0)
        self.update()

    def restart(self) -> None:
        self._phase = 0.0
        self._elapsed.restart()
        self._last_tick_ms = 0
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
            # Opaque charcoal (slightly lighter than the card) so the pill is
            # always visible and never blends away or reads as a blue bar.
            base.setColorAt(0.0, QColor(42, 43, 48, 255))
            base.setColorAt(0.55, QColor(32, 33, 37, 255))
            base.setColorAt(1.0, QColor(24, 25, 28, 255))
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

        self._paint_active_highlight(painter, rect, radius, is_dark)

        if self._prev_pixmap is not None and self._switch_value > 0.001:
            painter.setOpacity(self._switch_value)
            painter.drawPixmap(0, 0, self._prev_pixmap)
            painter.setOpacity(1.0)

    def _paint_effect_material(self, painter: QPainter, path: QPainterPath, rect: QRectF, is_dark: bool) -> None:
        key = effect_semantic_key(self._effect_key, self._effect_code)
        if key.startswith("flash"):
            self._paint_flash(painter, path, rect, is_dark)
        elif key.startswith("jump"):
            self._paint_jump(painter, path, rect, is_dark)
        elif key.startswith("fade"):
            self._paint_fade(painter, path, rect, is_dark)
        elif "rainbow" in key or "spectrum" in key:
            self._paint_rainbow(painter, path, rect, is_dark)
        else:
            self._paint_static(painter, path, rect, is_dark)

    def _paint_active_highlight(self, painter: QPainter, rect: QRectF, radius: float, is_dark: bool) -> None:
        pulse = 0.5 + 0.5 * math.sin(self._active_pulse * math.pi * 2.0)
        palette = theme_manager.palette
        accent = qcolor_from_token(palette["accent_start"])

        spark_x = rect.left() + rect.width() * self._active_pulse
        spark = QRadialGradient(spark_x, rect.center().y(), rect.width() * 0.22)
        spark.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 30 if is_dark else 38))
        spark.setColorAt(0.48, QColor(255, 255, 255, 12 if is_dark else 18))
        spark.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), radius - 1.0, radius - 1.0)
        painter.fillPath(path, spark)

        glow = QColor(accent)
        glow.setAlpha(int((26 if is_dark else 34) + pulse * (34 if is_dark else 42)))
        painter.setPen(QPen(glow, 2.0))
        painter.drawRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), radius - 1.0, radius - 1.0)

    def _paint_static(self, painter: QPainter, path: QPainterPath, rect: QRectF, is_dark: bool) -> None:
        # Neutral, quiet sheen for the "static colour" preview (no stray blue).
        alpha = 30 if is_dark else 44
        glow = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        glow.setColorAt(0.0, QColor(170, 178, 196, alpha))
        glow.setColorAt(0.55, QColor(150, 158, 178, max(14, alpha - 12)))
        glow.setColorAt(1.0, QColor(170, 178, 196, alpha))
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
        semantic_key = effect_semantic_key(self._effect_key, self._effect_code)
        color = self._cycle_color(self._effect_palette()) if "spectrum" in semantic_key else self._single_effect_color()
        progress = self._phase / (math.pi * 2.0)
        pulse = 1.0 if progress < 0.42 else 0.12
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
        alpha = 138 if is_dark else 118
        rainbow = QLinearGradient(rect.left(), rect.center().y(), rect.right(), rect.center().y())
        stops = 14
        for index in range(stops + 1):
            position = index / stops
            hue = (position + phase_progress) % 1.0
            rainbow.setColorAt(position, QColor.fromHsvF(hue, 0.64, 1.0, alpha / 255.0))
        painter.fillPath(path, rainbow)

        wave_path = QPainterPath()
        y_mid = rect.center().y()
        amp = rect.height() * 0.34
        samples = 72
        cycles = 1.65
        phase = self._phase * 1.18
        for index in range(samples + 1):
            progress = index / samples
            x = rect.left() - 18.0 + (width + 36.0) * progress
            envelope = math.sin(math.pi * progress)
            y = y_mid + math.sin(progress * math.pi * 2.0 * cycles + phase) * amp * envelope
            if index == 0:
                wave_path.moveTo(x, y)
            else:
                wave_path.lineTo(x, y)

        glow = QColor(255, 255, 255, 26 if is_dark else 36)
        painter.setPen(QPen(glow, 12.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(wave_path)
        painter.setPen(QPen(QColor(174, 224, 255, 42 if is_dark else 54), 7.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(wave_path)
        painter.setPen(QPen(QColor(255, 255, 255, 82 if is_dark else 104), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(wave_path)

    def _single_effect_color(self) -> QColor:
        key = effect_semantic_key(self._effect_key, self._effect_code)
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
        key = effect_semantic_key(self._effect_key, self._effect_code)
        if key == "fade_spectrum":
            return self._effect_palette()
        if key == "fade_red_green":
            return [QColor(255, 92, 112), QColor(94, 226, 178)]
        if key == "fade_red_blue":
            return [QColor(255, 92, 112), QColor(118, 174, 255)]
        if key == "fade_green_blue":
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
        key = effect_semantic_key(self._effect_key, self._effect_code)
        if key == "jump_rgb":
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
