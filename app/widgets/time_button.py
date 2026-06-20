from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTime,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.theme import qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton

# Rolling digit display


class _DigitDisplay(QWidget):
    """Single animated digit (HH or MM) with slide+fade roll effect."""

    _DURATION = 180

    def __init__(self, value: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = f"{value:02d}"
        self._next = self._current
        self._offset = 0.0
        self._direction = 1
        self.setFixedHeight(36)

        self._anim = QPropertyAnimation(self, b"rollOffset", self)
        self._anim.setDuration(self._DURATION)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_finished)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, val: float) -> None:
        self._offset = val
        self.update()

    rollOffset = Property(float, _get_offset, _set_offset)

    def set_instant(self, text: str) -> None:
        self._anim.stop()
        self._current = text
        self._next = text
        self._offset = 0.0
        self.update()

    def roll_to(self, text: str, direction: int) -> None:
        self._anim.stop()
        self._next = text
        self._direction = direction
        self._offset = 0.0
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_finished(self) -> None:
        self._current = self._next
        self._offset = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        w = float(self.width())
        h = float(self.height())
        if w <= 0 or h <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.rect())

        font = QFont()
        font.setPixelSize(26)
        font.setWeight(QFont.Weight.ExtraBold)
        painter.setFont(font)

        base = qcolor_from_token(theme_manager.palette["text"])
        t = self._offset
        d = float(self._direction)

        # Current slides out — fades faster so it's gone by midpoint
        curr_y = -d * t * h
        curr_alpha = int(255 * max(0.0, 1.0 - t * 2.0))
        if curr_alpha > 0:
            c = QColor(base)
            c.setAlpha(curr_alpha)
            painter.setPen(c)
            painter.drawText(QRectF(0.0, curr_y, w, h), Qt.AlignCenter, self._current)

        # Next slides in — fades in from midpoint
        next_y = d * (1.0 - t) * h
        next_alpha = int(255 * min(1.0, t * 2.0))
        if next_alpha > 0:
            c = QColor(base)
            c.setAlpha(next_alpha)
            painter.setPen(c)
            painter.drawText(QRectF(0.0, next_y, w, h), Qt.AlignCenter, self._next)


# Time value column (hours or minutes)


class _TimeValueColumn(QFrame):
    _AUTO_REPEAT_DELAY = 450
    _AUTO_REPEAT_INTERVAL = 70

    def __init__(
        self,
        label: str,
        value: int,
        minimum: int,
        maximum: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._value = value
        self.setObjectName("timeValueColumn")
        self.setFixedSize(86, 132)
        self.setFocusPolicy(Qt.WheelFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.up_button = LiquidButton("+", "ghost", self)
        self.up_button.setFixedSize(70, 28)
        self.up_button.setAutoRepeat(True)
        self.up_button.setAutoRepeatDelay(self._AUTO_REPEAT_DELAY)
        self.up_button.setAutoRepeatInterval(self._AUTO_REPEAT_INTERVAL)
        self.up_button.clicked.connect(lambda: self.step(1))
        layout.addWidget(self.up_button, 0, Qt.AlignHCenter)

        self._digit = _DigitDisplay(value, self)
        layout.addWidget(self._digit)

        self._label_widget = QLabel(label, self)
        self._label_widget.setObjectName("timePickerLabel")
        self._label_widget.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._label_widget)

        self.down_button = LiquidButton("-", "ghost", self)
        self.down_button.setFixedSize(70, 28)
        self.down_button.setAutoRepeat(True)
        self.down_button.setAutoRepeatDelay(self._AUTO_REPEAT_DELAY)
        self.down_button.setAutoRepeatInterval(self._AUTO_REPEAT_INTERVAL)
        self.down_button.clicked.connect(lambda: self.step(-1))
        layout.addWidget(self.down_button, 0, Qt.AlignHCenter)

    def set_label(self, label: str) -> None:
        self._label_widget.setText(label)

    def value(self) -> int:
        return self._value

    def step(self, amount: int) -> None:
        span = self._maximum - self._minimum + 1
        new_val = ((self._value - self._minimum + amount) % span) + self._minimum
        self._value = new_val
        self._digit.roll_to(f"{new_val:02d}", 1 if amount > 0 else -1)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta > 0:
            self.step(1)
        elif delta < 0:
            self.step(-1)
        event.accept()


# Panel background


class _TimePickerPanel(QFrame):
    RADIUS = 22.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timePickerPanel")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(328, 272)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        if theme_manager.is_dark:
            fill.setColorAt(0.0, QColor(34, 38, 50, 250))
            fill.setColorAt(1.0, QColor(18, 20, 28, 252))
        else:
            fill.setColorAt(0.0, QColor(248, 251, 255, 250))
            fill.setColorAt(1.0, QColor(219, 232, 255, 250))
        painter.fillPath(path, fill)

        shine = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        shine.setColorAt(0.0, QColor(255, 255, 255, 24 if theme_manager.is_dark else 52))
        shine.setColorAt(0.42, QColor(255, 255, 255, 5 if theme_manager.is_dark else 16))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(86 if theme_manager.is_dark else 140)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


# Close button


class _CloseButton(LiquidButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("x", "ghost", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 34)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(3.0, 3.0, -3.0, -3.0)
        radius = rect.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        fill = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        if theme_manager.is_dark:
            if self.underMouse():
                top = QColor(180, 60, 80, 188)
                bottom = QColor(105, 28, 48, 162)
            else:
                top = QColor(138, 42, 63, 132)
                bottom = QColor(78, 20, 38, 112)
            border = QColor(255, 190, 202, 120)
            cross = QColor(255, 238, 241)
        else:
            if self.underMouse():
                top = QColor(140, 60, 75, 88)
                bottom = QColor(140, 60, 75, 54)
            else:
                top = QColor(140, 60, 75, 48)
                bottom = QColor(140, 60, 75, 30)
            border = QColor(140, 60, 75, 82)
            cross = QColor(96, 42, 58)
        fill.setColorAt(0.0, top)
        fill.setColorAt(1.0, bottom)
        painter.fillPath(path, fill)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)

        painter.setPen(QPen(cross, 1.8, Qt.SolidLine, Qt.RoundCap))
        center = rect.center()
        size = 4.8
        painter.drawLine(
            center.x() - size, center.y() - size,
            center.x() + size, center.y() + size,
        )
        painter.drawLine(
            center.x() + size, center.y() - size,
            center.x() - size, center.y() + size,
        )


# Full-window overlay


class _TimePickerOverlay(QWidget):
    time_selected = Signal(QTime)  # emitted only on accept
    closed = Signal()

    def __init__(
        self,
        title: str,
        value: QTime,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("timePickerOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()
        self._panel_scale = 1.0
        self._base_panel_size = QSize(328, 272)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._fade_anim: QPropertyAnimation | None = None
        self._scale_anim: QPropertyAnimation | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)

        self._panel_widget = _TimePickerPanel(self)
        layout.addWidget(self._panel_widget, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel_widget)
        panel_layout.setContentsMargins(22, 16, 22, 18)
        panel_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_spacer = QLabel(self._panel_widget)
        title_spacer.setFixedSize(32, 28)
        header.addWidget(title_spacer)

        title_label = QLabel(title, self._panel_widget)
        title_label.setObjectName("timePickerTitle")
        title_label.setAlignment(Qt.AlignCenter)
        header.addWidget(title_label, 1)

        close_button = _CloseButton(self._panel_widget)
        close_button.clicked.connect(self.reject)
        header.addWidget(close_button)
        panel_layout.addLayout(header)

        picker_row = QHBoxLayout()
        picker_row.setSpacing(12)
        picker_row.addStretch(1)
        self.hour_column = _TimeValueColumn(
            labels["hours"], value.hour(), 0, 23, self._panel_widget
        )
        self.minute_column = _TimeValueColumn(
            labels["minutes"], value.minute(), 0, 59, self._panel_widget
        )
        colon = QLabel(":", self._panel_widget)
        colon.setObjectName("timePickerColon")
        colon.setAlignment(Qt.AlignCenter)
        picker_row.addWidget(self.hour_column)
        picker_row.addWidget(colon)
        picker_row.addWidget(self.minute_column)
        picker_row.addStretch(1)
        panel_layout.addLayout(picker_row)

        apply_button = LiquidButton(labels["ok"], "accent_soft", self._panel_widget)
        apply_button.setFixedSize(128, 42)
        apply_button.clicked.connect(self.accept)
        panel_layout.addWidget(apply_button, 0, Qt.AlignHCenter)

    def _get_panel_scale(self) -> float:
        return self._panel_scale

    def _set_panel_scale(self, value: float) -> None:
        self._panel_scale = max(0.9, min(1.0, float(value)))
        self._panel_widget.setFixedSize(
            max(1, round(self._base_panel_size.width() * self._panel_scale)),
            max(1, round(self._base_panel_size.height() * self._panel_scale)),
        )

    panelScale = Property(float, _get_panel_scale, _set_panel_scale)

    def open(self) -> None:
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())
            p.installEventFilter(self)
        self._set_panel_scale(0.92)
        self._opacity_effect.setOpacity(0.0)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()

        self._scale_anim = QPropertyAnimation(self, b"panelScale", self)
        self._scale_anim.setDuration(200)
        self._scale_anim.setStartValue(0.92)
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scale_anim.start()

    def accept(self) -> None:
        t = QTime(self.hour_column.value(), self.minute_column.value())
        self._close()
        self.time_selected.emit(t)

    def reject(self) -> None:
        self._close()

    def _close(self) -> None:
        p = self.parentWidget()
        if p is not None:
            p.removeEventFilter(self)
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def mousePressEvent(self, event) -> None:
        if not self._panel_widget.geometry().contains(event.pos()):
            self.reject()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42 if theme_manager.is_dark else 28))
        painter.drawRect(self.rect())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        p = self.parentWidget()
        if p is not None and watched is p:
            t = event.type()
            if t == event.Type.Resize or t == event.Type.Move:
                self.setGeometry(p.rect())
        return super().eventFilter(watched, event)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        if theme_manager.is_dark:
            column_bg = "rgba(255,255,255,0.065)"
            column_border = "rgba(255,255,255,0.18)"
        else:
            column_bg = "rgba(190,214,255,0.34)"
            column_border = "rgba(100,130,200,0.30)"
        self.setStyleSheet(
            f"""
            #timePickerOverlay {{
                background: transparent;
            }}
            #timePickerPanel {{
                background: transparent;
                border: none;
            }}
            #timePickerTitle {{
                color: {palette["text"]};
                font-size: 18px;
                font-weight: 700;
            }}
            #timeValueColumn {{
                background: {column_bg};
                border: 1px solid {column_border};
                border-radius: 18px;
            }}
            #timePickerColon {{
                color: {palette["text_soft"]};
                font-size: 24px;
                font-weight: 800;
            }}
            #timePickerLabel {{
                color: {palette["muted"]};
                font-size: 10px;
                font-weight: 700;
            }}
            """
        )


# Public widget


class TimeButton(LiquidButton):
    timeChanged = Signal(QTime)

    def __init__(self, text: str = "00:00", parent: QWidget | None = None) -> None:
        super().__init__(text, role="ghost", parent=parent)
        self._time = QTime.fromString(text, "HH:mm")
        if not self._time.isValid():
            self._time = QTime(0, 0)
        self._dialog_title = ""
        self._labels = {"hours": "Hours", "minutes": "Minutes", "ok": "OK"}
        self._picker: _TimePickerOverlay | None = None
        self.setFixedSize(96, 42)
        self.clicked.connect(self._open_picker)

    def set_picker_title(self, title: str) -> None:
        self._dialog_title = title

    def set_picker_labels(self, *, hours: str, minutes: str, ok: str) -> None:
        self._labels = {"hours": hours, "minutes": minutes, "ok": ok}

    def setTime(self, value: QTime) -> None:
        if not value.isValid():
            return
        if value == self._time:
            self.setText(value.toString("HH:mm"))
            return
        self._time = value
        self.setText(value.toString("HH:mm"))
        self.timeChanged.emit(value)

    def time(self) -> QTime:
        return QTime(self._time)

    def _open_picker(self) -> None:
        if self._picker is not None:
            return  # already open
        picker = _TimePickerOverlay(
            self._dialog_title or self.text(),
            self._time,
            self._labels,
            self.window(),
        )
        self._picker = picker
        picker.time_selected.connect(self.setTime)
        picker.closed.connect(self._on_picker_destroyed)
        picker.destroyed.connect(self._on_picker_destroyed)
        picker.open()

    def _on_picker_destroyed(self) -> None:
        self._picker = None
