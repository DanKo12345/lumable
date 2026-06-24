from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.theme import qcolor_from_token, theme_manager


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class DayToggle(QWidget):
    """A weekday selector chip that matches the app's glassy, animated buttons.

    Selected = a light, glossy "lit" pill; unselected = a faint outlined pill.
    The selection cross-fades smoothly and the chip brightens on hover, like the
    LiquidButtons elsewhere. Dims when disabled. Exposes the minimal API the
    schedule controller expects (isChecked / setChecked / clicked / setText).
    """

    clicked = Signal()

    def __init__(self, text: str, theme_provider: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = str(text)
        self._theme_provider = theme_provider
        self._checked = False
        self._progress = 0.0  # 0 = unselected look, 1 = selected look
        self._hover = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

        self._select_anim = QVariantAnimation(self)
        self._select_anim.setDuration(190)
        self._select_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._select_anim.valueChanged.connect(self._on_select_value)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(130)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_value)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        self._animate(self._select_anim, self._progress, 1.0 if value else 0.0)

    def setText(self, text: str) -> None:
        self._text = str(text)
        self.update()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.update()

    def _animate(self, anim: QVariantAnimation, start: float, end: float) -> None:
        anim.stop()
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.start()

    def _on_select_value(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    def _on_hover_value(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        if self.isEnabled():
            self._animate(self._hover_anim, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(self._hover_anim, self._hover, 0.0)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled() and self.rect().contains(event.position().toPoint()):
            self.setChecked(not self._checked)
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = rect.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        tokens = self._theme_provider()
        is_dark = theme_manager.is_dark
        dim = 1.0 if self.isEnabled() else 0.4
        progress = self._progress
        hover = self._hover if self.isEnabled() else 0.0

        def alpha(value: float) -> int:
            return max(0, min(255, int(value * dim)))

        # ── unselected base (always drawn, fades out as the selection grows) ──
        base_fill = (12 if is_dark else 10) + 8 * hover
        painter.fillPath(path, QColor(255, 255, 255, alpha(base_fill * (1.0 - progress))))
        border = qcolor_from_token(tokens.get("surface_border", "rgba(255,255,255,0.16)"))
        border.setAlpha(alpha((70 + 30 * hover) * (1.0 - progress)))
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)

        # ── selected overlay, cross-faded in by the selection progress ──
        if progress > 0.001:
            painter.save()
            painter.setOpacity(progress)
            fill = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if is_dark:
                fill.setColorAt(0.0, QColor(255, 255, 255, alpha(46 + 8 * hover)))
                fill.setColorAt(0.45, QColor(236, 242, 250, alpha(32)))
                fill.setColorAt(1.0, QColor(210, 222, 240, alpha(24)))
                sel_border = QColor(255, 255, 255, alpha(82))
            else:
                accent = qcolor_from_token(tokens["accent_end"])
                fill.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), alpha(235)))
                fill.setColorAt(1.0, accent.darker(112))
                sel_border = QColor(accent.red(), accent.green(), accent.blue(), alpha(255))
            painter.fillPath(path, fill)
            gloss = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.55)
            gloss.setColorAt(0.0, QColor(255, 255, 255, alpha(48 if is_dark else 62)))
            gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, gloss)
            painter.setPen(QPen(sel_border, 1.0))
            painter.drawPath(path)
            painter.restore()

        # ── label: muted -> bright as it becomes selected ──
        muted = qcolor_from_token(tokens["muted"])
        bright = QColor(255, 255, 255)
        text_color = QColor(
            round(_lerp(muted.red(), bright.red(), progress)),
            round(_lerp(muted.green(), bright.green(), progress)),
            round(_lerp(muted.blue(), bright.blue(), progress)),
            alpha(_lerp(muted.alpha(), 245, progress)),
        )
        font = self.font()
        font.setBold(progress > 0.5)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignCenter, self._text)
