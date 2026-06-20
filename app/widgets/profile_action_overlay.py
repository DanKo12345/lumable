from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton


class _ProfileActionPanel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None, *, height: int = 248) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(460, height)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if theme_manager.is_dark:
            fill.setColorAt(0.0, QColor(34, 38, 50, 250))
            fill.setColorAt(1.0, QColor(18, 20, 28, 252))
        else:
            fill.setColorAt(0.0, QColor(250, 252, 255, 252))
            fill.setColorAt(1.0, QColor(222, 235, 255, 252))
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
        self.name_input = QLineEdit(field_box)
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
        ok_button = LiquidButton(labels["ok"], "accent_soft", self._panel)
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
        self._fade_anim.start()
        self._panel_anim.start()

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

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
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
        title_row.addWidget(warning_icon, 0, Qt.AlignVCenter)
        title_row.addWidget(title, 0, Qt.AlignVCenter)
        title_row.addStretch(1)

        message = QLabel(labels["message"], self._panel)
        message.setObjectName("profileActionMessage")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        message.setFixedSize(382, 58)
        panel_layout.addLayout(title_row)
        panel_layout.addWidget(message, 0, Qt.AlignHCenter)
        panel_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(20)
        buttons.addStretch(1)
        cancel_button = LiquidButton(labels["cancel"], "ghost", self._panel)
        cancel_button.setFixedSize(144, 42)
        cancel_button.clicked.connect(self.close_overlay)
        delete_button = LiquidButton(labels["delete"], "accent_soft", self._panel)
        delete_button.setFixedSize(156, 42)
        delete_button.clicked.connect(self._accept_confirm)
        buttons.addWidget(cancel_button)
        buttons.addWidget(delete_button)
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
        self._start_open_animation()

    def _accept_confirm(self) -> None:
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
            #profileActionMessage {{
                color: {palette["text_soft"]};
                font-size: 12px;
                font-weight: 600;
                line-height: 1.35em;
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 14px;
                padding: 8px 14px;
            }}
            """
        )
