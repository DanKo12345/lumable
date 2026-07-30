from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.accent_color import subdued_led_accent
from app.widgets.animation_helpers import play_or_complete


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class DayToggle(QAbstractButton):
    """A weekday selector chip that matches the app's glassy, animated buttons.

    Selected = a light, glossy "lit" pill; unselected = a faint outlined pill.
    The selection cross-fades smoothly and the chip brightens on hover, like the
    LiquidButtons elsewhere. Dims when disabled.

    Only the painting is custom. Deriving from QAbstractButton (rather than a
    bare QWidget with hand-rolled click handling) is what makes the chip a real
    control: keyboard activation, click semantics and — the part a custom widget
    cannot fake — the accessible role and checkable/checked state that screen
    readers read out. It also means Space does not re-toggle on auto-repeat.
    """

    def __init__(self, text: str, theme_provider: Callable[[], dict[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(str(text))
        self.setCheckable(True)
        self._theme_provider = theme_provider
        self._progress = 0.0  # 0 = unselected look, 1 = selected look
        self._hover = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._select_anim = QVariantAnimation(self)
        self._select_anim.setDuration(190)
        self._select_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._select_anim.valueChanged.connect(self._on_select_value)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(130)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_value)

        # Drives the cross-fade from the real checked state, so the look follows
        # whether it was changed by mouse, keyboard or setChecked().
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self._animate(self._select_anim, self._progress, 1.0 if checked else 0.0)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.update()

    def _animate(self, anim: QVariantAnimation, start: float, end: float) -> None:
        anim.stop()
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        play_or_complete(anim)

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

    def hideEvent(self, event) -> None:
        self._select_anim.stop()
        self._hover_anim.stop()
        super().hideEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()  # the ring is painted by paintEvent, so ask for a repaint

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()

    def keyPressEvent(self, event) -> None:
        # QAbstractButton already handles Space; Enter is added so the chip
        # matches the push buttons around it. Auto-repeat is ignored: holding
        # the key down would otherwise flip the day on and off continuously.
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not event.isAutoRepeat()
            and self.isEnabled()
        ):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

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
            accent = subdued_led_accent()
            fill.setColorAt(
                0.0,
                QColor(accent.red(), accent.green(), accent.blue(), alpha(244 + 6 * hover)),
            )
            fill.setColorAt(1.0, accent.darker(116))
            sel_border = accent.lighter(118)
            sel_border.setAlpha(alpha(255))
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
        accent = subdued_led_accent()
        bright = QColor(28, 31, 38) if accent.lightness() > 170 else QColor(255, 255, 255)
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
        painter.drawText(rect, Qt.AlignCenter, self.text())

        # ── keyboard focus ring ──
        # Drawn outside the pill and only for keyboard focus: a ring that also
        # appeared on click would read as a stuck selection.
        if self.hasFocus() and self.isEnabled():
            # Kept inside the pill so a 2px pen is never clipped by the layout.
            focus_rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
            focus_radius = focus_rect.height() / 2.0
            ring = qcolor_from_token(tokens.get("accent_end", "#7fb7ff"))
            ring.setAlpha(210)
            painter.setPen(QPen(ring, 2.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(focus_rect, focus_radius, focus_radius)
