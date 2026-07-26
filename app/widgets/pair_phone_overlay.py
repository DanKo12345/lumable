from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

from app.theme import overlay_panel_colors, qcolor_from_token, theme_manager
from app.widgets.animation_helpers import play_or_complete
from app.widgets.liquid_button import LiquidButton


def qr_pixmap(data: str, size: int = 220) -> QPixmap | None:
    """A QR of ``data`` drawn from segno's module matrix, or None if segno isn't
    available (the overlay then just shows the address + code)."""
    try:
        import segno
    except ImportError:
        return None
    matrix = list(segno.make(data, error="m").matrix)
    modules = len(matrix)
    if modules == 0:
        return None
    quiet = 2
    total = modules + quiet * 2
    scale = max(1, size // total)
    side = total * scale
    pixmap = QPixmap(side, side)
    pixmap.fill(QColor("white"))
    painter = QPainter(pixmap)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("black"))
    for r, row in enumerate(matrix):
        for c, bit in enumerate(row):
            if bit:
                painter.drawRect((c + quiet) * scale, (r + quiet) * scale, scale, scale)
    painter.end()
    return pixmap


class _Panel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(456, 548)

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
        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(92 if theme_manager.is_dark else 104)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class PairPhoneOverlay(QWidget):
    """Shows a QR of the remote's URL plus a one-time pairing code to type on the
    phone. The URL is in the QR; the code is never in it."""

    closed = Signal()

    def __init__(
        self,
        labels: dict[str, str],
        url: str,
        code: str,
        parent: QWidget | None = None,
        *,
        display_url: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
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
        self._panel = _Panel(self)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(30, 26, 30, 22)
        pl.setSpacing(8)

        title = QLabel(labels["title"], self._panel)
        title.setObjectName("aboutTitle")
        pl.addWidget(title, 0, Qt.AlignHCenter)

        steps = QLabel(labels["steps"], self._panel)
        steps.setObjectName("pairBody")
        steps.setWordWrap(True)
        steps.setAlignment(Qt.AlignHCenter)
        pl.addWidget(steps)

        qr = qr_pixmap(url, 232)
        if qr is not None:
            qr_label = QLabel(self._panel)
            qr_label.setObjectName("pairQr")
            qr_label.setAlignment(Qt.AlignCenter)
            qr_label.setPixmap(qr)
            # The QR already carries a small quiet zone; size the white frame to
            # the image plus an even 8px inset so it hugs the code, not floats.
            qr_label.setFixedSize(qr.width() + 16, qr.height() + 16)
            pl.addWidget(qr_label, 0, Qt.AlignHCenter)

        # Keep the real URL only in the QR. The text follows the privacy state
        # of the API settings, so it cannot reveal a LAN address on stream.
        url_label = QLabel(display_url if display_url is not None else url, self._panel)
        url_label.setObjectName("pairAddress")
        url_label.setAlignment(Qt.AlignHCenter)
        url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(url_label, 0, Qt.AlignHCenter)

        code_box = QFrame(self._panel)
        code_box.setObjectName("pairCodeBox")
        code_layout = QVBoxLayout(code_box)
        code_layout.setContentsMargins(12, 8, 12, 10)
        code_layout.setSpacing(0)

        code_caption = QLabel(labels["code_caption"], code_box)
        code_caption.setObjectName("pairCodeCaption")
        code_caption.setAlignment(Qt.AlignHCenter)
        code_layout.addWidget(code_caption)

        self._code_label = QLabel(self._format_code(code), code_box)
        self._code_label.setObjectName("pairCode")
        self._code_label.setAlignment(Qt.AlignHCenter)
        code_layout.addWidget(self._code_label)
        pl.addWidget(code_box)
        pl.addStretch(1)

        ok = LiquidButton(labels["ok"], "accent_soft", self._panel)
        ok.setFixedSize(120, 40)
        ok.clicked.connect(self.close_overlay)
        pl.addWidget(ok, 0, Qt.AlignHCenter)

    @staticmethod
    def _format_code(code: str) -> str:
        code = str(code or "")
        return f"{code[:3]} {code[3:]}" if len(code) == 6 else code

    def set_code(self, code: str) -> None:
        self._code_label.setText(self._format_code(code))

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self.layout().activate()
        end_pos = self._panel.pos()
        self._panel.move(end_pos + QPoint(0, 14))
        self._opacity_effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(170)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anim = QPropertyAnimation(self._panel, b"pos", self)
        self._panel_anim.setDuration(210)
        self._panel_anim.setStartValue(end_pos + QPoint(0, 14))
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
            #aboutTitle {{ color: {palette["text"]}; font-size: 20px; font-weight: 800; }}
            #pairBody {{ color: {palette["text_soft"]}; font-size: 12px; font-weight: 500; }}
            #pairQr {{
                background: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.58);
                border-radius: 10px;
            }}
            #pairAddress {{ color: {palette["text_soft"]}; font-size: 12px; font-weight: 600; }}
            #pairCodeBox {{
                background: {palette["field_alt"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 12px;
            }}
            #pairCodeCaption {{ color: {palette["text_soft"]}; font-size: 11px; font-weight: 600; }}
            #pairCode {{ color: {palette["accent_start"]}; font-size: 31px; font-weight: 800; letter-spacing: 5px; }}
            """
        )
