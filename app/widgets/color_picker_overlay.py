from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.theme import overlay_panel_colors, qcolor_from_token, theme_manager
from app.widgets.clickable_label import ClickableLabel
from app.widgets.color_swatch import ColorSwatch
from app.widgets.liquid_button import LiquidButton
from app.widgets.liquid_slider import LiquidSlider
from app.widgets.themed_line_edit import ThemedLineEdit

PANEL_WIDTH = 540
PANEL_HEIGHT_WITH_HISTORY = 632
PANEL_HEIGHT_COMPACT = 584
PANEL_MARGIN_X = 24
PANEL_MARGIN_TOP = 20
PANEL_MARGIN_BOTTOM = 20
ROW_SIDE_MARGIN = 0
ROW_SPACING = 12
LABEL_WIDTH = 72
VALUE_WIDTH = 54
VALUE_HEIGHT = 36
SCROLLBAR_GUTTER = 16
PICKER_WIDTH = PANEL_WIDTH - (PANEL_MARGIN_X * 2) - (ROW_SIDE_MARGIN * 2) - SCROLLBAR_GUTTER
HUE_BAR_WIDTH = 28
PICKER_SPACING = 12
PICKER_SURFACE_INSET = 10
COLOR_PLANE_WIDTH = PICKER_WIDTH - (PICKER_SURFACE_INSET * 2) - HUE_BAR_WIDTH - PICKER_SPACING
COLOR_PLANE_HEIGHT = 168


class _ColorPreview(QFrame):
    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(44, 44)
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
        path.addRoundedRect(rect, 9.0, 9.0)
        painter.fillPath(path, self._color)

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
        # Fixed width; the owner drives height (min/max) so the panel fits a short
        # window with its middle controls scrolling.
        self.setFixedWidth(PANEL_WIDTH)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        panel_top, panel_bottom = overlay_panel_colors()
        fill.setColorAt(0.0, panel_top)
        fill.setColorAt(1.0, panel_bottom)
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

        self._has_history = bool(history_items)
        self._panel = _ColorPickerPanel(has_history=self._has_history, parent=self)
        panel = self._panel
        panel.setMinimumHeight(320)
        panel.setMaximumHeight(self._preferred_height())
        layout.addWidget(panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(PANEL_MARGIN_X, PANEL_MARGIN_TOP, PANEL_MARGIN_X, PANEL_MARGIN_BOTTOM)
        panel_layout.setSpacing(12)

        # --- Pinned title ---
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 0, 0)
        header.setSpacing(12)
        title_label = QLabel(title, panel)
        title_label.setObjectName("colorPickerTitle")
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(title_label, 1)
        close_button = ClickableLabel("✕", panel)
        close_button.setObjectName("colorPickerClose")
        close_button.setFixedSize(32, 32)
        close_button.setAlignment(Qt.AlignCenter)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setAccessibleName(labels["cancel"])
        close_button.setToolTip(labels["cancel"])
        close_button.clicked.connect(self.reject)
        self._close_button = close_button
        header.addWidget(close_button, 0, Qt.AlignVCenter)
        panel_layout.addLayout(header)

        # --- Scrollable centre: plane + hue, HEX, RGB sliders, history. On a
        # short window this yields height while the title and actions stay put.
        # The colour plane keeps its full 145px — shrinking it would hurt precise
        # picking without removing the need to scroll anyway.
        self._scroll = QScrollArea(panel)
        self._scroll.setObjectName("colorPickerScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setAttribute(Qt.WA_TranslucentBackground)
        self._scroll.viewport().setAutoFillBackground(False)
        centre = QWidget()
        centre.setObjectName("colorPickerScrollContent")
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(12)

        picker_surface = QFrame(centre)
        picker_surface.setObjectName("colorPickerSurface")
        picker_row = QHBoxLayout()
        picker_row.setContentsMargins(
            PICKER_SURFACE_INSET, PICKER_SURFACE_INSET, PICKER_SURFACE_INSET, PICKER_SURFACE_INSET
        )
        picker_row.setSpacing(PICKER_SPACING)
        picker_surface.setLayout(picker_row)
        hue = max(0, self._color.hue())
        self.color_plane = _ColorPlane(self._color, panel)
        self.hue_bar = _HueBar(hue, panel)
        self.color_plane.colorChanged.connect(self._set_color_from_picker)
        self.hue_bar.hueChanged.connect(self._set_hue_from_picker)
        picker_row.addWidget(self.color_plane, 1)
        picker_row.addWidget(self.hue_bar)
        centre_layout.addWidget(picker_surface)

        hex_row = self._control_row(labels["hex"])
        self.hex_input = ThemedLineEdit(panel)
        self.hex_input.setObjectName("colorPickerHexInput")
        self.hex_input.setMaxLength(7)
        self.hex_input.setText(self._hex_text(self._color))
        self.hex_input.editingFinished.connect(self._apply_hex_input)
        self.hex_input.installEventFilter(self)  # focus → scroll it into view
        hex_row.addWidget(self.hex_input, 1)
        self.hex_swatch = _ColorPreview(self._color, panel)
        hex_row.addWidget(self.hex_swatch)
        centre_layout.addLayout(hex_row)

        self.red_slider, self.red_value = self._add_slider(centre_layout, labels["red"], "red", self._color.red())
        self.green_slider, self.green_value = self._add_slider(centre_layout, labels["green"], "green", self._color.green())
        self.blue_slider, self.blue_value = self._add_slider(centre_layout, labels["blue"], "blue", self._color.blue())

        if history_items:
            history_row = self._control_row(labels["recent"])
            swatches = QHBoxLayout()
            swatches.setSpacing(8)
            for item in history_items[:8]:
                color_item = QColor(item["r"], item["g"], item["b"])
                swatch = ColorSwatch(lambda: theme_manager.palette, panel)
                swatch.setFixedSize(34, 34)
                swatch.set_color(color_item)
                swatch.clicked.connect(lambda picked=color_item: self._set_color(picked, sync_hue=True))
                swatches.addWidget(swatch)
            swatches.addStretch(1)
            history_row.addLayout(swatches, 1)
            history_spacer = QWidget(panel)
            history_spacer.setFixedSize(VALUE_WIDTH, VALUE_HEIGHT)
            history_row.addWidget(history_spacer)
            centre_layout.addLayout(history_row)

        centre_layout.addStretch(1)
        self._scroll.setWidget(centre)
        panel_layout.addWidget(self._scroll, 1)

        # --- Pinned actions ---
        footer_line = QFrame(panel)
        footer_line.setObjectName("colorPickerDivider")
        footer_line.setFixedHeight(1)
        panel_layout.addWidget(footer_line)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        cancel_button = LiquidButton(labels["cancel"], "ghost", panel)
        ok_button = LiquidButton(labels["ok"], "accent_soft", panel)
        cancel_button.setFixedSize(132, 42)
        ok_button.setFixedSize(152, 42)
        cancel_button.clicked.connect(self.reject)
        ok_button.clicked.connect(self.accept)
        self._cancel_button = cancel_button
        self._ok_button = ok_button
        actions.addStretch(1)
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
        self._fit_to_parent()
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)

    def _preferred_height(self) -> int:
        return PANEL_HEIGHT_WITH_HISTORY if self._has_history else PANEL_HEIGHT_COMPACT

    def _fit_to_parent(self) -> None:
        # min(preferred, available); recomputed every time so growing the window
        # restores the full preferred height.
        parent = self.parentWidget()
        height = self._preferred_height()
        if parent is not None:
            height = max(320, min(height, parent.height() - 24))
        self._panel.setMinimumHeight(height)
        self._panel.setMaximumHeight(height)

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
                self._fit_to_parent()
        elif watched is self.hex_input and event.type() == QEvent.Type.FocusIn:
            # Bring the HEX field into view when it's focused (e.g. on a short
            # window where it lives below the fold). Deferred so the scroll has
            # settled. Dragging the plane/hue/sliders never triggers this.
            QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(self.hex_input, 0, 40))
        return super().eventFilter(watched, event)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        self.setStyleSheet(
            f"""
            #colorPickerOverlay {{
                background: transparent;
            }}
            #colorPickerScroll, #colorPickerScroll > QWidget, #colorPickerScrollContent {{
                background: transparent;
                border: none;
            }}
            #colorPickerTitle {{
                color: {palette["text"]};
                font-size: 20px;
                font-weight: 700;
            }}
            #colorPickerClose {{
                color: {palette["text_soft"]};
                font-size: 19px;
                font-weight: 500;
            }}
            #colorPickerClose:hover {{ color: {palette["text"]}; }}
            #colorPickerSurface {{
                background: {palette["field_alt"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 16px;
            }}
            #colorPickerDivider {{
                background: {palette["field_border"]};
                border: none;
            }}
            #colorPickerLabel {{
                color: {palette["text_soft"]};
                font-size: 12px;
                font-weight: 700;
            }}
            #colorPickerValue {{
                background: {palette["chip"]};
                border: 1px solid {palette["chip_border"]};
                border-radius: 10px;
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 700;
            }}
            #colorPickerHexInput {{
                background: {palette["chip"]};
                border: 1px solid {palette["chip_border"]};
                border-radius: 10px;
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
