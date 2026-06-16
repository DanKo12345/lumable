from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.celebration_overlay import CelebrationOverlay
from app.widgets.clickable_label import ClickableLabel
from app.widgets.liquid_button import LiquidButton


class _LicensePanel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(560, 424)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if theme_manager.is_dark:
            fill.setColorAt(0.0, QColor(43, 60, 108, 248))
            fill.setColorAt(1.0, QColor(15, 22, 52, 252))
        else:
            fill.setColorAt(0.0, QColor(250, 252, 255, 252))
            fill.setColorAt(1.0, QColor(222, 235, 255, 252))
        painter.fillPath(path, fill)

        shine = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        shine.setColorAt(0.0, QColor(255, 255, 255, 30 if theme_manager.is_dark else 62))
        shine.setColorAt(0.48, QColor(255, 255, 255, 6 if theme_manager.is_dark else 16))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        # Soft accent halo behind the title for a more premium, branded feel.
        halo = QRadialGradient(rect.center().x(), rect.top() + rect.height() * 0.16, rect.width() * 0.6)
        accent = qcolor_from_token(theme_manager.palette["accent_start"])
        halo.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 60 if theme_manager.is_dark else 46))
        halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.fillPath(path, halo)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(98 if theme_manager.is_dark else 110)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class _ProEmblem(QWidget):
    """A small painted sparkle badge shown above the title."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # Fixed width too, and tall enough that the glow fades inside the bounds
        # (so the round halo is never clipped into a square).
        self.setFixedSize(132, 60)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        accent_start = qcolor_from_token(theme_manager.palette["accent_start"])
        accent_end = qcolor_from_token(theme_manager.palette["accent_end"])

        glow_radius = 26.0
        glow = QRadialGradient(cx, cy, glow_radius)
        glow.setColorAt(0.0, QColor(accent_start.red(), accent_start.green(), accent_start.blue(), 150))
        glow.setColorAt(0.6, QColor(accent_start.red(), accent_start.green(), accent_start.blue(), 60))
        glow.setColorAt(1.0, QColor(accent_start.red(), accent_start.green(), accent_start.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        fill = QLinearGradient(cx - 16.0, cy - 16.0, cx + 16.0, cy + 16.0)
        fill.setColorAt(0.0, accent_start)
        fill.setColorAt(1.0, accent_end)
        painter.setBrush(fill)
        self._draw_sparkle(painter, cx, cy, 15.0)
        self._draw_sparkle(painter, cx + 16.0, cy - 11.0, 6.0)

    def _draw_sparkle(self, painter: QPainter, cx: float, cy: float, size: float) -> None:
        waist = size * 0.32
        path = QPainterPath()
        path.moveTo(cx, cy - size)
        path.cubicTo(cx + waist, cy - waist, cx + waist, cy - waist, cx + size, cy)
        path.cubicTo(cx + waist, cy + waist, cx + waist, cy + waist, cx, cy + size)
        path.cubicTo(cx - waist, cy + waist, cx - waist, cy + waist, cx - size, cy)
        path.cubicTo(cx - waist, cy - waist, cx - waist, cy - waist, cx, cy - size)
        painter.drawPath(path)


class _ProStatusBadge(QWidget):
    """A green checkmark crest with a slow breathing glow for the active state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # The widget must be larger than the glow so the soft halo fades to zero
        # *inside* the bounds — otherwise the rect clips it into a square.
        self.setFixedSize(132, 116)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _tick(self) -> None:
        self._phase += 0.06
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = 31.0
        pulse = (math.sin(self._phase) + 1.0) * 0.5

        start = qcolor_from_token(theme_manager.palette["success_start"])
        end = qcolor_from_token(theme_manager.palette["success_end"])

        # Fixed radius (< half the widget height) keeps the halo perfectly round;
        # the breathing is driven by alpha only, never by the radius.
        glow_radius = 52.0
        glow = QRadialGradient(cx, cy, glow_radius)
        glow.setColorAt(0.0, QColor(start.red(), start.green(), start.blue(), int(60 + 60 * pulse)))
        glow.setColorAt(0.55, QColor(start.red(), start.green(), start.blue(), int(24 + 26 * pulse)))
        glow.setColorAt(1.0, QColor(start.red(), start.green(), start.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        fill = QRadialGradient(cx, cy - radius * 0.3, radius * 1.7)
        fill.setColorAt(0.0, start)
        fill.setColorAt(1.0, end)
        painter.setBrush(fill)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1.4))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        pen = QPen(QColor(255, 255, 255), 5.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        check = QPainterPath()
        check.moveTo(cx - 14.0, cy + 1.0)
        check.lineTo(cx - 3.5, cy + 11.0)
        check.lineTo(cx + 15.0, cy - 11.0)
        painter.drawPath(check)


class LicenseOverlay(QWidget):
    activated = Signal()
    deactivated = Signal()
    closed = Signal()

    def __init__(
        self,
        labels: dict[str, str],
        activate_callback: Callable[[str], tuple[bool, str]],
        parent: QWidget | None = None,
        *,
        mode: str = "free",
        buy_callback: Callable[[], bool] | None = None,
        deactivate_callback: Callable[[], tuple[bool, str]] | None = None,
        license_key: str = "",
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._activate_callback = activate_callback
        self._buy_callback = buy_callback
        self._deactivate_callback = deactivate_callback
        self._mode = mode
        self._license_key = str(license_key or "").strip()
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        self._panel_opacity: QGraphicsOpacityEffect | None = None
        self._celebration: CelebrationOverlay | None = None
        self._deactivate_armed = False
        self._disarm_timer = QTimer(self)
        self._disarm_timer.setSingleShot(True)
        self._disarm_timer.setInterval(4000)
        self._disarm_timer.timeout.connect(self._disarm_deactivate)
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _LicensePanel(self)
        if self._is_active_mode():
            self._panel.setFixedSize(560, 460)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(30, 22, 30, 24)
        panel_layout.setSpacing(12)

        active = self._is_active_mode()
        badge = _ProStatusBadge(self._panel) if active else _ProEmblem(self._panel)
        panel_layout.addWidget(badge, 0, Qt.AlignHCenter)

        title = QLabel(labels["active_title"] if active else labels["title"], self._panel)
        title.setObjectName("licenseTitle")
        title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        subtitle = QLabel(self._active_message() if active else labels["subtitle"], self._panel)
        subtitle.setObjectName("licenseSubtitle")
        subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        subtitle.setWordWrap(True)
        panel_layout.addWidget(title)

        if active:
            status_card = QFrame(self._panel)
            status_card.setObjectName("licenseStatusCard")
            status_layout = QVBoxLayout(status_card)
            status_layout.setContentsMargins(18, 14, 18, 16)
            status_layout.setSpacing(12)
            subtitle.setParent(status_card)
            status_layout.addWidget(subtitle)
            masked = self._masked_key()
            if masked:
                key_chip = QLabel(masked, status_card)
                key_chip.setObjectName("licenseKeyChip")
                key_chip.setAlignment(Qt.AlignHCenter)
                status_layout.addWidget(key_chip, 0, Qt.AlignHCenter)
            panel_layout.addWidget(status_card)
        else:
            panel_layout.addWidget(subtitle)

        field_box = QFrame(self._panel)
        self._field_box = field_box
        field_box.setObjectName("licenseFieldBox")
        field_layout = QVBoxLayout(field_box)
        field_layout.setContentsMargins(16, 12, 16, 12)
        field_layout.setSpacing(8)
        field_label = QLabel(labels["key_label"], field_box)
        field_label.setObjectName("licenseFieldLabel")
        self.key_input = QLineEdit(field_box)
        self.key_input.setObjectName("licenseKeyInput")
        self.key_input.setPlaceholderText(labels["placeholder"])
        self.key_input.returnPressed.connect(self._activate)
        self.key_input.installEventFilter(self)
        field_layout.addWidget(field_label)
        field_layout.addWidget(self.key_input)
        panel_layout.addWidget(field_box)
        field_box.setVisible(not self._is_active_mode())

        self.message_label = QLabel("", self._panel)
        self.message_label.setObjectName("licenseMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setMinimumHeight(30)
        panel_layout.addWidget(self.message_label)
        panel_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.buy_button = LiquidButton(labels["buy"], "accent_soft", self._panel)
        self.buy_button.setMinimumSize(142, 40)
        self.buy_button.clicked.connect(self._show_buy_message)
        cancel_button = LiquidButton(labels["cancel"] if not active else labels["ok"], "ghost", self._panel)
        self._cancel_button = cancel_button
        cancel_button.setMinimumSize(122, 40)
        cancel_button.clicked.connect(self.close_overlay)
        activate_button = LiquidButton(labels["activate"], "accent_soft", self._panel)
        self._activate_button = activate_button
        activate_button.setMinimumSize(150, 40)
        activate_button.clicked.connect(self._activate)
        self.buy_button.setVisible(not active)
        activate_button.setVisible(not active)
        buttons.addStretch(1)
        if not active:
            buttons.addWidget(self.buy_button)
        buttons.addWidget(cancel_button)
        if not active:
            buttons.addWidget(activate_button)
        buttons.addStretch(1)
        panel_layout.addLayout(buttons)

        # Deactivation is a rare, destructive action: keep it as a quiet link
        # under the primary button and require a second click to confirm.
        self.deactivate_link: ClickableLabel | None = None
        if self._mode == "license":
            link = ClickableLabel(labels.get("deactivate", ""), self._panel)
            link.setObjectName("licenseDeactivateLink")
            link.setAlignment(Qt.AlignHCenter)
            link.setCursor(Qt.PointingHandCursor)
            link_font = link.font()
            link_font.setUnderline(True)
            link.setFont(link_font)
            link.clicked.connect(self._on_deactivate_link)
            self.deactivate_link = link
            panel_layout.addSpacing(2)
            panel_layout.addWidget(link, 0, Qt.AlignHCenter)

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self._prepare_open_animation()
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        if self._is_active_mode():
            self.setFocus(Qt.PopupFocusReason)
        else:
            self.key_input.setFocus(Qt.PopupFocusReason)
        QTimer.singleShot(0, self._start_open_animation)

    def _is_active_mode(self) -> bool:
        return self._mode in {"dev", "license"}

    def _active_message(self) -> str:
        return self._labels["active_dev"] if self._mode == "dev" else self._labels["active_license"]

    def _masked_key(self) -> str:
        """A privacy-preserving preview of the saved key, e.g. ``ABCD ···· WXYZ``."""
        key = self._license_key
        if len(key) < 8:
            return ""
        return f"{key[:4]} ···· {key[-4:]}"

    def _activate(self) -> None:
        ok, message = self._activate_callback(self.key_input.text())
        self.message_label.setText("" if ok else message)
        self.message_label.setProperty("state", "success" if ok else "error")
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)
        if ok:
            self.activated.emit()
            self._play_success(message)

    def _play_success(self, message: str) -> None:
        """Celebrate a successful activation, then close the overlay."""
        # Lock further input and gently fade the panel away so the confetti and
        # the checkmark badge own the moment.
        self.key_input.setEnabled(False)
        self._activate_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self.buy_button.setEnabled(False)

        self._panel_opacity = QGraphicsOpacityEffect(self._panel)
        self._panel.setGraphicsEffect(self._panel_opacity)
        self._panel_anim = QPropertyAnimation(self._panel_opacity, b"opacity", self)
        self._panel_anim.setDuration(260)
        self._panel_anim.setStartValue(1.0)
        self._panel_anim.setEndValue(0.0)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anim.start()

        self._celebration = CelebrationOverlay(self, message=message)
        self._celebration.finished.connect(self.close_overlay)
        self._celebration.start()

    def _show_buy_message(self) -> None:
        if self._buy_callback is not None and self._buy_callback():
            return
        self.message_label.setText(self._labels["buy_unavailable"])
        self.message_label.setProperty("state", "info")
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)

    def _on_deactivate_link(self) -> None:
        if self._deactivate_callback is None or self.deactivate_link is None:
            return
        if not self._deactivate_armed:
            # First click only arms the action; a second click confirms it.
            self._deactivate_armed = True
            self.deactivate_link.setText(self._labels.get("deactivate_confirm", self._labels.get("deactivate", "")))
            self.deactivate_link.setProperty("armed", True)
            self.deactivate_link.style().unpolish(self.deactivate_link)
            self.deactivate_link.style().polish(self.deactivate_link)
            self._disarm_timer.start()
            return
        self._disarm_timer.stop()
        self._deactivate()
        self._disarm_deactivate()

    def _disarm_deactivate(self) -> None:
        self._deactivate_armed = False
        if self.deactivate_link is None:
            return
        self.deactivate_link.setText(self._labels.get("deactivate", ""))
        self.deactivate_link.setProperty("armed", False)
        self.deactivate_link.style().unpolish(self.deactivate_link)
        self.deactivate_link.style().polish(self.deactivate_link)

    def _deactivate(self) -> None:
        if self._deactivate_callback is None:
            return
        ok, message = self._deactivate_callback()
        self.message_label.setText(message)
        self.message_label.setProperty("state", "success" if ok else "error")
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)
        if ok:
            self.deactivated.emit()
            self.close_overlay()

    def _prepare_open_animation(self) -> None:
        self.layout().activate()
        self._opacity_effect.setOpacity(0.0)

    def _start_open_animation(self) -> None:
        if not self.isVisible():
            return
        self.layout().activate()
        self._panel.raise_()

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(210)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()

        # Let the panel rise into place for a softer, more polished entrance.
        target = self._panel.geometry()
        self._panel_anim = QPropertyAnimation(self._panel, b"geometry", self)
        self._panel_anim.setDuration(300)
        self._panel_anim.setStartValue(target.translated(0, 26))
        self._panel_anim.setEndValue(target)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
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
        elif watched is self.key_input and event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut}:
            self._field_box.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            self._field_box.style().unpolish(self._field_box)
            self._field_box.style().polish(self._field_box)
        return super().eventFilter(watched, event)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        self.setStyleSheet(
            f"""
            #licenseTitle {{
                color: {palette["text"]};
                font-size: 22px;
                font-weight: 800;
            }}
            #licenseSubtitle {{
                color: {palette["text_soft"]};
                font-size: 12px;
                font-weight: 500;
                line-height: 1.35em;
            }}
            #licenseStatusCard {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 18px;
            }}
            #licenseKeyChip {{
                color: {palette["text"]};
                font-size: 14px;
                font-weight: 800;
            }}
            #licenseFieldBox {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 16px;
            }}
            #licenseFieldBox[focused="true"] {{
                border: 1px solid {palette["accent_start"]};
                background: {palette["field_alt"]};
            }}
            #licenseFieldLabel {{
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 800;
            }}
            #licenseKeyInput {{
                background: transparent;
                border: none;
                color: {palette["text"]};
                padding: 0 4px;
                min-height: 40px;
                font-size: 13px;
                font-weight: 700;
            }}
            #licenseMessage {{
                color: {palette["muted"]};
                font-size: 12px;
                font-weight: 600;
            }}
            #licenseDeactivateLink {{
                color: {palette["muted"]};
                font-size: 12px;
                font-weight: 700;
                padding: 4px 8px;
            }}
            #licenseDeactivateLink:hover {{
                color: {palette["text_soft"]};
            }}
            #licenseDeactivateLink[armed="true"] {{
                color: #ff9aa9;
            }}
            #licenseMessage[state="error"] {{
                color: #ff9aa9;
            }}
            #licenseMessage[state="success"] {{
                color: #83f0c9;
            }}
            """
        )
