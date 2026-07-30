from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.theme import overlay_panel_colors, qcolor_from_token, theme_manager
from app.widgets.animation_helpers import play_or_complete
from app.widgets.liquid_button import LiquidButton
from app.widgets.themed_line_edit import ThemedLineEdit


class _ProfileActionPanel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None, *, height: int = 248) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Width is fixed for a stable dialog shape, but the height only sets a
        # floor: long localized messages must be able to grow the panel instead
        # of being clipped.
        self.setFixedWidth(460)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        panel_top, panel_bottom = overlay_panel_colors()
        fill.setColorAt(0.0, panel_top)
        fill.setColorAt(1.0, panel_bottom)
        painter.fillPath(path, fill)

        shine = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        shine.setColorAt(0.0, QColor(255, 255, 255, 28 if theme_manager.is_dark else 60))
        shine.setColorAt(0.48, QColor(255, 255, 255, 6 if theme_manager.is_dark else 16))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(96 if theme_manager.is_dark else 108)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class ProfileRenameOverlay(QWidget):
    nameSelected = Signal(str)
    closed = Signal()

    def __init__(self, labels: dict[str, str], current_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _ProfileActionPanel(self, height=258)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(28, 24, 28, 24)
        panel_layout.setSpacing(14)
        title = QLabel(labels["title"], self._panel)
        title.setObjectName("profileActionTitle")
        title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        panel_layout.addWidget(title)

        field_box = QFrame(self._panel)
        field_box.setObjectName("profileActionFieldBox")
        field_layout = QVBoxLayout(field_box)
        field_layout.setContentsMargins(16, 12, 16, 12)
        field_layout.setSpacing(8)
        field_label = QLabel(labels["prompt"], field_box)
        field_label.setObjectName("profileActionFieldLabel")
        self.name_input = ThemedLineEdit(field_box)
        self.name_input.setObjectName("profileActionInput")
        self.name_input.setText(current_name)
        self.name_input.selectAll()
        self.name_input.returnPressed.connect(self._accept)
        field_layout.addWidget(field_label)
        field_layout.addWidget(self.name_input)
        panel_layout.addWidget(field_box)
        panel_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(18)
        buttons.addStretch(1)
        cancel_button = LiquidButton(labels["cancel"], "ghost", self._panel)
        cancel_button.setFixedSize(136, 42)
        cancel_button.clicked.connect(self.close_overlay)
        ok_button = LiquidButton(labels["ok"], "accent", self._panel)
        ok_button.setFixedSize(136, 42)
        ok_button.clicked.connect(self._accept)
        buttons.addWidget(cancel_button)
        buttons.addWidget(ok_button)
        buttons.addStretch(1)
        panel_layout.addLayout(buttons)

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self.name_input.setFocus(Qt.PopupFocusReason)
        self._start_open_animation()

    def _accept(self) -> None:
        self.nameSelected.emit(self.name_input.text())
        self.close_overlay()

    def _start_open_animation(self) -> None:
        self.layout().activate()
        end_pos = self._panel.pos()
        self._panel.move(end_pos + QPoint(0, 12))
        self._opacity_effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(170)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anim = QPropertyAnimation(self._panel, b"pos", self)
        self._panel_anim.setDuration(205)
        self._panel_anim.setStartValue(end_pos + QPoint(0, 12))
        self._panel_anim.setEndValue(end_pos)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        play_or_complete(self._fade_anim)
        play_or_complete(self._panel_anim)

    def close_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 44 if theme_manager.is_dark else 26))
        painter.drawRect(self.rect())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
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
            #profileActionTitle {{
                color: {palette["text"]};
                font-size: 21px;
                font-weight: 800;
            }}
            #profileActionFieldBox {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 16px;
            }}
            #profileActionFieldLabel {{
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 800;
            }}
            #profileActionInput {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 14px;
                color: {palette["text"]};
                padding: 0 14px;
                min-height: 40px;
                font-size: 13px;
                font-weight: 700;
                selection-background-color: {palette["list_sel"]};
                selection-color: {palette["text"]};
            }}
            """
        )


class ProfileConfirmOverlay(ProfileRenameOverlay):
    confirmed = Signal()

    def __init__(
        self,
        labels: dict[str, str],
        parent: QWidget | None = None,
        *,
        confirm_role: str = "accent",
        toggle_label: str = "",
        toggle_checked: bool = True,
    ) -> None:
        QWidget.__init__(self, parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _ProfileActionPanel(self, height=218)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(28, 22, 28, 22)
        panel_layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addStretch(1)
        warning_icon = QLabel("\u26a0\ufe0f", self._panel)
        warning_icon.setObjectName("profileActionWarningIcon")
        warning_icon.setFixedSize(30, 30)
        warning_icon.setAlignment(Qt.AlignCenter)
        title = QLabel(labels["title"], self._panel)
        title.setObjectName("profileActionTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._title_label = title
        title_row.addWidget(warning_icon, 0, Qt.AlignVCenter)
        title_row.addWidget(title, 0, Qt.AlignVCenter)
        title_row.addStretch(1)

        message = QLabel(labels["message"])
        message.setObjectName("profileActionMessage")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        message.setFixedWidth(382)  # fixed width keeps the wrap predictable
        self._message_label = message

        # A compact scroll around the message: it sizes to the text and scrolls
        # only when a very long profile/device name would overflow the height the
        # window allows — so nothing is silently clipped, and no length limit has
        # to be imposed on names across storage/API/import. Heights set in open().
        msg_scroll = QScrollArea(self._panel)
        self._message_scroll = msg_scroll
        msg_scroll.setObjectName("profileMessageScroll")
        msg_scroll.setWidgetResizable(False)
        msg_scroll.setFrameShape(QFrame.NoFrame)
        msg_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        msg_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        msg_scroll.setAttribute(Qt.WA_TranslucentBackground)
        msg_scroll.viewport().setAutoFillBackground(False)
        msg_scroll.setFixedWidth(382 + 16)  # leave room for the scrollbar
        msg_scroll.setWidget(message)

        panel_layout.addLayout(title_row)
        panel_layout.addStretch(1)
        panel_layout.addWidget(msg_scroll, 0, Qt.AlignHCenter)

        # Optional choice attached to the confirmation (e.g. whether the strip
        # being replaced stays connected). Checked by default so the existing
        # behaviour is what happens when the user just confirms.
        self._toggle: LiquidButton | None = None
        if toggle_label:
            toggle = LiquidButton(toggle_label, "accent_soft" if toggle_checked else "ghost", self._panel)
            toggle.setCheckable(True)
            toggle.setChecked(bool(toggle_checked))
            toggle.setMinimumHeight(38)
            toggle.toggled.connect(
                lambda on, button=toggle: button.set_role("accent_soft" if on else "ghost")
            )
            self._toggle = toggle
            self._panel.setMinimumHeight(self._panel.minimumHeight() + 52)
            panel_layout.addSpacing(2)
            panel_layout.addWidget(toggle)

        panel_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(20)
        buttons.addStretch(1)
        cancel_button = LiquidButton(labels["cancel"], "ghost", self._panel)
        cancel_button.setFixedSize(144, 42)
        cancel_button.clicked.connect(self.close_overlay)
        self._cancel_button = cancel_button
        # The same dialog confirms both constructive actions ("make primary",
        # "try driver") and destructive ones (delete) — the caller picks the
        # role so a destructive confirm reads as red, not as the default action.
        confirm_button = LiquidButton(labels["confirm"], confirm_role, self._panel)
        confirm_button.setFixedSize(156, 42)
        confirm_button.clicked.connect(self._accept_confirm)
        self._confirm_button = confirm_button
        buttons.addWidget(cancel_button)
        buttons.addWidget(confirm_button)
        buttons.addStretch(1)
        panel_layout.addLayout(buttons)

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()  # after show(), the stylesheet font is applied to the label
        self._fit_message_height()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self._start_open_animation()

    def _fit_message_height(self) -> None:
        # The label always holds the full wrapped text; the scroll around it is
        # sized to the window. When the text is taller than the window allows,
        # the scroll shows a scrollbar instead of clipping — so even an
        # arbitrarily long profile/device name stays fully readable.
        if getattr(self, "_message_scroll", None) is None:
            return  # not built yet (an early resizeEvent during construction)
        message = self._message_label
        # heightForWidth ignores the label's own QSS padding (8px 14px) + border,
        # so measure the text on the real content width and add the box padding.
        content_width = 382 - 2 * 14 - 2
        text_height = QFontMetrics(message.font()).boundingRect(
            0, 0, content_width, 100_000, int(Qt.TextWordWrap), message.text()
        ).height()
        wrapped = max(58, text_height + 2 * 8 + 2 + 6)
        message.setFixedSize(382, wrapped)
        visible = wrapped
        parent = self.parentWidget()
        if parent is not None:
            non_message = max(0, self._panel.minimumHeight() - 58)
            visible = max(58, min(wrapped, parent.height() - 24 - non_message))
        self._message_scroll.setFixedHeight(visible)
        # Cap the panel to the window so it can never overflow, regardless of when
        # the internal layout re-computes its size hint. The scroll already keeps
        # the message within this budget, so nothing is clipped.
        if parent is not None:
            self._panel.setMaximumHeight(max(self._panel.minimumHeight(), parent.height() - 24))
        self._panel.updateGeometry()
        self.layout().activate()

    def resizeEvent(self, event) -> None:
        # The base eventFilter resizes the overlay to the parent on every window
        # resize; recomputing here (rather than filtering the parent event
        # directly) reliably re-fits the message whenever the overlay's own size
        # changes — the window may have shrunk or grown.
        super().resizeEvent(event)
        self._fit_message_height()

    def toggle_checked(self) -> bool:
        """State of the optional choice; True when there is no toggle."""
        return True if self._toggle is None else bool(self._toggle.isChecked())

    def _accept_confirm(self) -> None:
        # Emitted before close_overlay, so a slot can still read toggle_checked().
        self.confirmed.emit()
        self.close_overlay()

    def _apply_style(self) -> None:
        super()._apply_style()
        palette = theme_manager.palette
        self.setStyleSheet(
            self.styleSheet()
            + f"""
            #profileActionWarningIcon {{
                color: #ffd66e;
                font-size: 22px;
                font-weight: 800;
            }}
            #profileMessageScroll, #profileMessageScroll > QWidget {{
                background: transparent;
                border: none;
            }}
            #profileActionMessage {{
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 600;
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 14px;
                padding: 8px 14px;
            }}
            """
        )
