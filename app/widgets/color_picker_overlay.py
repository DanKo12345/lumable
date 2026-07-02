from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.color_swatch import ColorSwatch
from app.widgets.liquid_button import LiquidButton
from app.widgets.liquid_slider import LiquidSlider
from app.widgets.themed_line_edit import ThemedLineEdit

PANEL_WIDTH = 500
PANEL_HEIGHT_WITH_HISTORY = 560
PANEL_HEIGHT_COMPACT = 520
PANEL_MARGIN_X = 30
PANEL_MARGIN_TOP = 22
PANEL_MARGIN_BOTTOM = 24
ROW_SIDE_MARGIN = 14
ROW_SPACING = 10
LABEL_WIDTH = 84
VALUE_WIDTH = 54
VALUE_HEIGHT = 36
PICKER_WIDTH = PANEL_WIDTH - (PANEL_MARGIN_X * 2) - (ROW_SIDE_MARGIN * 2)
HUE_BAR_WIDTH = 30
PICKER_SPACING = 12
COLOR_PLANE_WIDTH = PICKER_WIDTH - HUE_BAR_WIDTH - PICKER_SPACING
COLOR_PLANE_HEIGHT = 145


class _ColorPreview(QFrame):
    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(36, 36)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 10.0, 10.0)

        fill = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        fill.setColorAt(0.0, self._color.lighter(128))
        fill.setColorAt(0.42, self._color)
        fill.setColorAt(1.0, self._color.darker(128))
        painter.fillPath(path, fill)

        shine = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.45)
        shine.setColorAt(0.0, QColor(255, 255, 255, 58))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(112 if theme_manager.is_dark else 150)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class _ColorPlane(QFrame):
    colorChanged = Signal(QColor)

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hue = max(0, color.hue())
        self._sat = max(0, color.saturation())
        self._val = max(0, color.value())
        self.setFixedSize(COLOR_PLANE_WIDTH, COLOR_PLANE_HEIGHT)
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_color(self, color: QColor) -> None:
        if color.hue() >= 0:
            self._hue = color.hue()
        self._sat = max(0, color.saturation())
        self._val = max(0, color.value())
        self.update()

    def set_hue(self, hue: int) -> None:
        self._hue = max(0, min(359, hue))
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 18.0, 18.0)
        painter.setClipPath(path)

        painter.fillPath(path, QColor.fromHsv(self._hue, 255, 255))

        white = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        white.setColorAt(0.0, QColor(255, 255, 255, 255))
        white.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(rect, white)

        black = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        black.setColorAt(0.0, QColor(0, 0, 0, 0))
        black.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.fillRect(rect, black)
        painter.setClipping(False)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(120)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)

        x = rect.left() + rect.width() * (self._sat / 255.0)
        y = rect.top() + rect.height() * (1.0 - self._val / 255.0)
        cursor_rect = QRectF(x - 6.0, y - 6.0, 12.0, 12.0)
        painter.setPen(QPen(QColor(0, 0, 0, 100), 3.0))
        painter.drawEllipse(cursor_rect.adjusted(-1.0, -1.0, 1.0, 1.0))
        painter.setPen(QPen(QColor(255, 255, 255), 2.0))
        painter.drawEllipse(cursor_rect)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._pick_at(event.position().x(), event.position().y())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self._pick_at(event.position().x(), event.position().y())
        super().mouseMoveEvent(event)

    def _pick_at(self, x: float, y: float) -> None:
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        self._sat = round(max(0.0, min(1.0, (x - rect.left()) / max(1.0, rect.width()))) * 255)
        self._val = round((1.0 - max(0.0, min(1.0, (y - rect.top()) / max(1.0, rect.height())))) * 255)
        color = QColor.fromHsv(self._hue, self._sat, self._val)
        self.update()
        self.colorChanged.emit(color)


class _HueBar(QFrame):
    hueChanged = Signal(int)

    def __init__(self, hue: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hue = max(0, min(359, hue))
        self.setFixedSize(HUE_BAR_WIDTH, COLOR_PLANE_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_hue(self, hue: int) -> None:
        self._hue = max(0, min(359, hue))
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(4.0, 1.0, -4.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.width() / 2.0, rect.width() / 2.0)
        hue_gradient = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        for position, hue in (
            (0.0, 0),
            (1.0 / 6.0, 60),
            (2.0 / 6.0, 120),
            (3.0 / 6.0, 180),
            (4.0 / 6.0, 240),
            (5.0 / 6.0, 300),
            (1.0, 359),
        ):
            hue_gradient.setColorAt(position, QColor.fromHsv(hue, 255, 255))
        painter.fillPath(path, hue_gradient)
        hue_border = qcolor_from_token(theme_manager.palette["surface_border"])
        hue_border.setAlpha(128 if theme_manager.is_dark else 150)
        painter.setPen(QPen(hue_border, 1.0))
        painter.drawPath(path)

        y = rect.top() + rect.height() * (self._hue / 359.0)
        painter.setPen(QPen(QColor(0, 0, 0, 130), 3.0))
        painter.drawLine(rect.left() - 3.0, y, rect.right() + 3.0, y)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1.8))
        painter.drawLine(rect.left() - 3.0, y, rect.right() + 3.0, y)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._pick_at(event.position().y())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self._pick_at(event.position().y())
        super().mouseMoveEvent(event)

    def _pick_at(self, y: float) -> None:
        rect = QRectF(self.rect()).adjusted(4.0, 1.0, -4.0, -1.0)
        self._hue = round(max(0.0, min(1.0, (y - rect.top()) / max(1.0, rect.height()))) * 359)
        self.update()
        self.hueChanged.emit(self._hue)


class _ColorPickerPanel(QFrame):
    RADIUS = 24.0

    def __init__(self, *, has_history: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT_WITH_HISTORY if has_history else PANEL_HEIGHT_COMPACT)
        self.setAttribute(Qt.WA_TranslucentBackground)

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
        border.setAlpha(88 if theme_manager.is_dark else 96)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class ColorPickerOverlay(QWidget):
    colorSelected = Signal(QColor)
    closed = Signal()

    def __init__(
        self,
        title: str,
        color: QColor,
        labels: dict[str, str],
        history: list[dict[str, int]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("colorPickerOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._color = QColor(color)
        self._syncing = False
        self._hex_syncing = False
        history_items = self._validated_history(history or [])
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        panel = _ColorPickerPanel(has_history=bool(history_items), parent=self)
        layout.addWidget(panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(PANEL_MARGIN_X, PANEL_MARGIN_TOP, PANEL_MARGIN_X, PANEL_MARGIN_BOTTOM)
        panel_layout.setSpacing(10)

        title_label = QLabel(title, panel)
        title_label.setObjectName("colorPickerTitle")
        title_label.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(title_label)

        picker_row = QHBoxLayout()
        picker_row.setContentsMargins(ROW_SIDE_MARGIN, 0, ROW_SIDE_MARGIN, 0)
        picker_row.setSpacing(PICKER_SPACING)
        hue = max(0, self._color.hue())
        self.color_plane = _ColorPlane(self._color, panel)
        self.hue_bar = _HueBar(hue, panel)
        self.color_plane.colorChanged.connect(self._set_color_from_picker)
        self.hue_bar.hueChanged.connect(self._set_hue_from_picker)
        picker_row.addWidget(self.color_plane, 1)
        picker_row.addWidget(self.hue_bar)
        panel_layout.addLayout(picker_row)

        hex_row = self._control_row(labels["hex"])
        self.hex_input = ThemedLineEdit(panel)
        self.hex_input.setObjectName("colorPickerHexInput")
        self.hex_input.setMaxLength(7)
        self.hex_input.setText(self._hex_text(self._color))
        self.hex_input.editingFinished.connect(self._apply_hex_input)
        hex_row.addWidget(self.hex_input, 1)
        self.hex_swatch = _ColorPreview(self._color, panel)
        hex_row.addWidget(self.hex_swatch)
        panel_layout.addLayout(hex_row)

        self.red_slider, self.red_value = self._add_slider(panel_layout, labels["red"], "red", self._color.red())
        self.green_slider, self.green_value = self._add_slider(panel_layout, labels["green"], "green", self._color.green())
        self.blue_slider, self.blue_value = self._add_slider(panel_layout, labels["blue"], "blue", self._color.blue())

        if history_items:
            history_row = self._control_row(labels["recent"])
            swatches = QHBoxLayout()
            swatches.setSpacing(8)
            for item in history_items[:8]:
                color_item = QColor(item["r"], item["g"], item["b"])
                swatch = ColorSwatch(lambda: theme_manager.palette, panel)
                swatch.setFixedSize(32, 32)
                swatch.set_color(color_item)
                swatch.clicked.connect(lambda picked=color_item: self._set_color(picked, sync_hue=True))
                swatches.addWidget(swatch)
            swatches.addStretch(1)
            history_row.addLayout(swatches, 1)
            history_spacer = QWidget(panel)
            history_spacer.setFixedSize(VALUE_WIDTH, VALUE_HEIGHT)
            history_row.addWidget(history_spacer)
            panel_layout.addLayout(history_row)

        actions = QHBoxLayout()
        actions.setContentsMargins(ROW_SIDE_MARGIN, 2, ROW_SIDE_MARGIN, 0)
        actions.setSpacing(12)
        cancel_button = LiquidButton(labels["cancel"], "ghost", panel)
        ok_button = LiquidButton(labels["ok"], "accent_soft", panel)
        cancel_button.setFixedHeight(42)
        ok_button.setFixedHeight(42)
        cancel_button.setFixedWidth(180)
        ok_button.setFixedWidth(180)
        cancel_button.clicked.connect(self.reject)
        ok_button.clicked.connect(self.accept)
        actions.addWidget(cancel_button)
        actions.addWidget(ok_button)
        panel_layout.addLayout(actions)

    def _control_row(self, label: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(ROW_SIDE_MARGIN, 0, ROW_SIDE_MARGIN, 0)
        row.setSpacing(ROW_SPACING)
        label_widget = QLabel(label, self)
        label_widget.setObjectName("colorPickerLabel")
        label_widget.setFixedWidth(LABEL_WIDTH)
        label_widget.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addWidget(label_widget)
        return row

    def _add_slider(self, parent_layout: QVBoxLayout, label: str, accent: str, value: int) -> tuple[LiquidSlider, QLabel]:
        row = self._control_row(label)
        slider = LiquidSlider(accent, self)
        slider.setRange(0, 255)
        slider.setValue(value)
        slider.setMinimumHeight(48)
        slider.setMaximumHeight(48)
        value_label = QLabel(str(value), self)
        value_label.setObjectName("colorPickerValue")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setFixedSize(VALUE_WIDTH, VALUE_HEIGHT)
        slider.valueChanged.connect(lambda new_value, target=value_label: self._sync_slider_value(target, new_value))
        row.addWidget(slider, 1)
        row.addWidget(value_label)
        parent_layout.addLayout(row)
        return slider, value_label

    def _validated_history(self, history: list[dict[str, int]]) -> list[dict[str, int]]:
        result: list[dict[str, int]] = []
        for item in history:
            try:
                red = max(0, min(255, int(item.get("r", 0))))
                green = max(0, min(255, int(item.get("g", 0))))
                blue = max(0, min(255, int(item.get("b", 0))))
            except (AttributeError, TypeError, ValueError):
                continue
            result.append({"r": red, "g": green, "b": blue})
        return result

    def _sync_slider_value(self, target: QLabel, value: int) -> None:
        target.setText(str(value))
        if self._syncing:
            return
        self._color = QColor(self.red_slider.value(), self.green_slider.value(), self.blue_slider.value())
        self.color_plane.set_color(self._color)
        if self._color.hue() >= 0:
            self.hue_bar.set_hue(self._color.hue())
        self.hex_swatch.set_color(self._color)
        self._sync_hex_input()

    def _set_color_from_picker(self, color: QColor) -> None:
        self._set_color(color, sync_hue=True)

    def _set_hue_from_picker(self, hue: int) -> None:
        self.color_plane.set_hue(hue)
        color = QColor.fromHsv(hue, self._color.saturation(), self._color.value())
        self._set_color(color, sync_hue=False)

    def _set_color(self, color: QColor, *, sync_hue: bool) -> None:
        self._color = QColor(color)
        self.hex_swatch.set_color(self._color)
        self._sync_hex_input()
        self._syncing = True
        try:
            self.red_slider.setValue(self._color.red())
            self.green_slider.setValue(self._color.green())
            self.blue_slider.setValue(self._color.blue())
            self.red_value.setText(str(self._color.red()))
            self.green_value.setText(str(self._color.green()))
            self.blue_value.setText(str(self._color.blue()))
        finally:
            self._syncing = False
        self.color_plane.set_color(self._color)
        if sync_hue and self._color.hue() >= 0:
            self.hue_bar.set_hue(self._color.hue())

    def _sync_hex_input(self) -> None:
        self._hex_syncing = True
        try:
            self.hex_input.setText(self._hex_text(self._color))
        finally:
            self._hex_syncing = False

    def _apply_hex_input(self) -> None:
        if self._hex_syncing:
            return
        text = self.hex_input.text().strip().lstrip("#")
        color = QColor(f"#{text}" if text else "")
        if color.isValid():
            self._set_color(color, sync_hue=True)
        else:
            self._sync_hex_input()

    @staticmethod
    def _hex_text(color: QColor) -> str:
        return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)

    def selected_color(self) -> QColor:
        return QColor(self._color)

    def accept(self) -> None:
        self.colorSelected.emit(QColor(self._color))
        self._finish()

    def reject(self) -> None:
        self._finish()

    def _finish(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
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
        self.setStyleSheet(
            f"""
            #colorPickerOverlay {{
                background: transparent;
            }}
            #colorPickerTitle {{
                color: {palette["text"]};
                font-size: 18px;
                font-weight: 700;
            }}
            #colorPickerLabel {{
                color: {palette["text_soft"]};
                font-size: 12px;
                font-weight: 700;
            }}
            #colorPickerValue {{
                background: {palette["chip"]};
                border: 1px solid {palette["chip_border"]};
                border-radius: 14px;
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 700;
            }}
            #colorPickerHexInput {{
                background: {palette["chip"]};
                border: 1px solid {palette["chip_border"]};
                border-radius: 16px;
                color: {palette["text"]};
                min-height: 36px;
                padding: 0 14px;
                font-size: 12px;
                font-weight: 700;
            }}
            #colorPickerHexInput:focus {{
                border: 1px solid {palette["surface_border"]};
            }}
            """
        )
