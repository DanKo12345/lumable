from __future__ import annotations

from PySide6.QtCore import QEvent, QEventLoop, QRectF, Qt, QTime, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton


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
            fill.setColorAt(0.0, QColor(42, 58, 104, 246))
            fill.setColorAt(1.0, QColor(18, 27, 58, 250))
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


class _CloseButton(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("x", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 34)
        self.setFlat(True)
        self.setAttribute(Qt.WA_TranslucentBackground)

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
        painter.drawLine(center.x() - size, center.y() - size, center.x() + size, center.y() + size)
        painter.drawLine(center.x() + size, center.y() - size, center.x() - size, center.y() + size)


class _TimeValueColumn(QFrame):
    def __init__(self, label: str, value: int, minimum: int, maximum: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._value = value
        self.setObjectName("timeValueColumn")
        self.setFixedSize(86, 132)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.up_button = LiquidButton("+", "ghost", self)
        self.up_button.setFixedSize(70, 28)
        self.up_button.clicked.connect(lambda: self.step(1))
        layout.addWidget(self.up_button, 0, Qt.AlignHCenter)

        self.value_label = QLabel(self)
        self.value_label.setObjectName("timePickerValue")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFixedHeight(36)
        layout.addWidget(self.value_label)

        self._label_widget = QLabel(label, self)
        self._label_widget.setObjectName("timePickerLabel")
        self._label_widget.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._label_widget)

        self.down_button = LiquidButton("-", "ghost", self)
        self.down_button.setFixedSize(70, 28)
        self.down_button.clicked.connect(lambda: self.step(-1))
        layout.addWidget(self.down_button, 0, Qt.AlignHCenter)

        self._sync_text()

    def set_label(self, label: str) -> None:
        self._label_widget.setText(label)

    def value(self) -> int:
        return self._value

    def step(self, amount: int) -> None:
        span = self._maximum - self._minimum + 1
        self._value = ((self._value - self._minimum + amount) % span) + self._minimum
        self._sync_text()

    def _sync_text(self) -> None:
        self.value_label.setText(f"{self._value:02d}")


class _TimePickerOverlay(QWidget):
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
        self._accepted = False
        self._loop: QEventLoop | None = None
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)

        panel = _TimePickerPanel(self)
        layout.addWidget(panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(22, 16, 22, 18)
        panel_layout.setSpacing(14)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_spacer = QLabel(panel)
        title_spacer.setFixedSize(32, 28)
        header.addWidget(title_spacer)

        title_label = QLabel(title, panel)
        title_label.setObjectName("timePickerTitle")
        title_label.setAlignment(Qt.AlignCenter)
        header.addWidget(title_label, 1)

        close_button = _CloseButton(panel)
        close_button.clicked.connect(self.reject)
        header.addWidget(close_button)
        panel_layout.addLayout(header)

        picker_row = QHBoxLayout()
        picker_row.setSpacing(12)
        picker_row.addStretch(1)
        self.hour_column = _TimeValueColumn(labels["hours"], value.hour(), 0, 23, panel)
        self.minute_column = _TimeValueColumn(labels["minutes"], value.minute(), 0, 59, panel)
        colon = QLabel(":", panel)
        colon.setObjectName("timePickerColon")
        colon.setAlignment(Qt.AlignCenter)
        picker_row.addWidget(self.hour_column)
        picker_row.addWidget(colon)
        picker_row.addWidget(self.minute_column)
        picker_row.addStretch(1)
        panel_layout.addLayout(picker_row)

        apply_button = LiquidButton(labels["ok"], "accent_soft", panel)
        apply_button.setFixedSize(128, 42)
        apply_button.clicked.connect(self.accept)
        panel_layout.addWidget(apply_button, 0, Qt.AlignHCenter)

    def exec(self) -> bool:
        self._accepted = False
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self._loop = QEventLoop(self)
        self._loop.exec()
        return self._accepted

    def accept(self) -> None:
        self._accepted = True
        self._finish()

    def reject(self) -> None:
        self._accepted = False
        self._finish()

    def _finish(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        self.deleteLater()

    def selected_time(self) -> QTime:
        return QTime(self.hour_column.value(), self.minute_column.value())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

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
        if watched is self.parentWidget() and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(parent.rect())
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
            #timePickerValue {{
                color: {palette["text"]};
                font-size: 26px;
                font-weight: 800;
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


class TimeButton(LiquidButton):
    timeChanged = Signal(QTime)

    def __init__(self, text: str = "00:00", parent: QWidget | None = None) -> None:
        super().__init__(text, role="ghost", parent=parent)
        self._time = QTime.fromString(text, "HH:mm")
        if not self._time.isValid():
            self._time = QTime(0, 0)
        self._dialog_title = ""
        self._labels = {"hours": "Hours", "minutes": "Minutes", "ok": "OK"}
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
        dialog = _TimePickerOverlay(self._dialog_title or self.text(), self._time, self._labels, self.window())
        if dialog.exec():
            self.setTime(dialog.selected_time())
