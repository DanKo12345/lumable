from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QEventLoop, QPoint, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.liquid_button import LiquidButton

ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"


class _AboutPanel(QFrame):
    RADIUS = 24.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(580, 620)

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
        shine.setColorAt(0.0, QColor(255, 255, 255, 26 if theme_manager.is_dark else 58))
        shine.setColorAt(0.42, QColor(255, 255, 255, 5 if theme_manager.is_dark else 16))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(92 if theme_manager.is_dark else 104)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class AboutOverlay(QWidget):
    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._loop: QEventLoop | None = None
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
        self._panel = _AboutPanel(self)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(28, 26, 28, 26)
        panel_layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.setContentsMargins(0, 0, 0, 2)
        icon_label = QLabel(self._panel)
        icon = QIcon(str(ICON_PATH))
        icon_label.setPixmap(icon.pixmap(52, 52))
        icon_label.setFixedSize(56, 56)
        icon_label.setAlignment(Qt.AlignCenter)
        header.addStretch(1)
        header.addWidget(icon_label)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(3)
        title = QLabel(labels["title"], self._panel)
        title.setObjectName("aboutTitle")
        meta = QLabel(labels["meta"], self._panel)
        meta.setObjectName("aboutMuted")
        title_stack.addWidget(title)
        title_stack.addWidget(meta)
        meta.setObjectName("aboutEditionPro" if "Pro" in labels["meta"] else "aboutMuted")
        header.addLayout(title_stack)
        header.addStretch(1)
        panel_layout.addLayout(header)

        scroll = QScrollArea(self._panel)
        scroll.setObjectName("aboutScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setMinimumHeight(360)
        content = QWidget(scroll)
        content.setObjectName("aboutScrollContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 8)
        content_layout.setSpacing(14)
        content_layout.addWidget(self._section(content, labels["author_title"], labels["author_text"]))
        content_layout.addWidget(self._section(content, labels["privacy_title"], labels["privacy_text"]))
        content_layout.addWidget(self._section(content, labels["components_title"], labels["components_text"]))
        content_layout.addStretch(1)
        scroll.setWidget(content)
        panel_layout.addWidget(scroll, 1)

        ok_row = QHBoxLayout()
        ok_row.setContentsMargins(0, 4, 0, 0)
        ok_row.addStretch(1)
        ok_button = LiquidButton(labels["ok"], "accent_soft", self._panel)
        ok_button.setFixedSize(100, 38)
        ok_button.clicked.connect(self.close_overlay)
        ok_row.addWidget(ok_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        panel_layout.addLayout(ok_row)

    def _section(self, parent: QWidget, title_text: str, body_text: str, *, min_height: int | None = None) -> QFrame:
        section = QFrame(parent)
        section.setObjectName("aboutSection")
        if min_height is not None:
            section.setMinimumHeight(min_height)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(7)
        title = QLabel(title_text, section)
        title.setObjectName("aboutSectionTitle")
        title.setMinimumHeight(20)
        body = QLabel(body_text, section)
        body.setObjectName("aboutBody")
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        lines = body_text.replace("&", "&amp;").replace("<", "&lt;").split("\n")
        html = "<br>".join(lines)
        body.setText(f"<div style='line-height: 145%;'>{html}</div>")
        body.setContentsMargins(0, 2, 0, 0)
        layout.addWidget(title)
        layout.addWidget(body)
        return section

    def exec(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self._start_open_animation()
        self._loop = QEventLoop(self)
        self._loop.exec()

    def _start_open_animation(self) -> None:
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

        self._fade_anim.start()
        self._panel_anim.start()

    def close_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
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
            #aboutTitle {{
                color: {palette["text"]};
                font-size: 22px;
                font-weight: 800;
            }}
            #aboutMuted {{
                color: {palette["muted"]};
                font-size: 12px;
                font-weight: 600;
            }}
            #aboutEditionPro {{
                color: #f0c060;
                font-size: 12px;
                font-weight: 700;
            }}
            #aboutSection {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 16px;
            }}
            #aboutSectionTitle {{
                color: {palette["text"]};
                font-size: 13px;
                font-weight: 800;
            }}
            #aboutBody {{
                color: {palette["text_soft"]};
                font-size: 12px;
                font-weight: 500;
                line-height: 1.35em;
            }}
            #aboutScroll, #aboutScrollContent {{
                background: transparent;
                border: none;
            }}
            """
        )
