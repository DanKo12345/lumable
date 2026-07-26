from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.theme import overlay_panel_colors, qcolor_from_token, theme_manager
from app.widgets.animation_helpers import play_or_complete
from app.widgets.clickable_label import ClickableLabel
from app.widgets.liquid_button import LiquidButton


class _UpdatePanel(QFrame):
    RADIUS = 22.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(500)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if theme_manager.is_dark:
            panel_top, panel_bottom = overlay_panel_colors()
        else:
            # Update is an operational dialog. Keep its light surface neutral;
            # blue belongs to the icon and primary action, not the whole panel.
            panel_top = QColor(253, 253, 254, 252)
            panel_bottom = QColor(247, 248, 250, 252)
        fill.setColorAt(0.0, panel_top)
        fill.setColorAt(1.0, panel_bottom)
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


class _UpdateBadge(QWidget):
    """Compact icon tile for the update header."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(36, 36)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        start = qcolor_from_token(theme_manager.palette["accent_start"])
        end = qcolor_from_token(theme_manager.palette["accent_end"])

        tile = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        tile_path = QPainterPath()
        tile_path.addRoundedRect(tile, 10.0, 10.0)
        tint = QColor(start)
        tint.setAlpha(42 if theme_manager.is_dark else 28)
        painter.setPen(Qt.NoPen)
        painter.fillPath(tile_path, tint)
        outline = QColor(start)
        outline.setAlpha(72 if theme_manager.is_dark else 54)
        painter.setPen(QPen(outline, 1.0))
        painter.drawPath(tile_path)

        pen = QPen(end, 2.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        # Download glyph: a downward arrow over a short tray line.
        painter.drawLine(QPointF(cx, cy - 6.5), QPointF(cx, cy + 3.0))
        head = QPainterPath()
        head.moveTo(cx - 4.5, cy - 0.5)
        head.lineTo(cx, cy + 4.5)
        head.lineTo(cx + 4.5, cy - 0.5)
        painter.drawPath(head)
        painter.drawLine(QPointF(cx - 5.5, cy + 7.5), QPointF(cx + 5.5, cy + 7.5))


class UpdateOverlay(QWidget):
    """Quiet, modern 'update available' pop-up shown at most once per version."""

    update_requested = Signal()
    skip_requested = Signal(str)
    closed = Signal()

    # Release name and notes come from GitHub — external, untrusted text. Cap
    # their length so neither can stretch the window; the scroll area (used only
    # for genuinely long notes) additionally caps the height.
    TITLE_LIMIT = 140
    NOTES_LIMIT = 600
    NOTES_INLINE_MAX = 200  # below this, show notes inline without a scroll area
    MAX_PREFERRED_HEIGHT = 450
    MIN_FITTED_HEIGHT = 300
    PARENT_MARGIN = 12

    def __init__(self, labels: dict[str, str], version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._version = str(version)
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
        self._panel = _UpdatePanel(self)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(24, 20, 24, 18)
        panel_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_UpdateBadge(self._panel), 0, Qt.AlignVCenter)
        title = QLabel(labels["title"], self._panel)
        title.setObjectName("updateTitle")
        header.addWidget(title, 1, Qt.AlignVCenter)
        close_button = ClickableLabel("\u00d7", self._panel)
        close_button.setObjectName("updateClose")
        close_button.setFixedSize(30, 30)
        close_button.setAlignment(Qt.AlignCenter)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setToolTip(labels.get("close", ""))
        close_button.setAccessibleName(labels.get("close", "Close"))
        close_button.clicked.connect(self.close_overlay)
        header.addWidget(close_button, 0, Qt.AlignVCenter)
        panel_layout.addLayout(header)

        # Keep the title and actions available at short window heights. Only
        # release details yield space and become scrollable.
        self._content_scroll = QScrollArea(self._panel)
        self._content_scroll.setObjectName("updateContentScroll")
        self._content_scroll.setWidgetResizable(True)
        self._content_scroll.setFrameShape(QFrame.NoFrame)
        self._content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._content_scroll.setAttribute(Qt.WA_TranslucentBackground)
        self._content_scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("updateContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        self._content_scroll.setWidget(content)
        panel_layout.addWidget(self._content_scroll, 1)

        release = str(labels.get("release") or "").strip()
        if release:
            if len(release) > self.TITLE_LIMIT:
                release = release[: self.TITLE_LIMIT].rstrip() + "…"
            release_label = QLabel(release, content)
            release_label.setObjectName("updateRelease")
            release_label.setTextFormat(Qt.PlainText)
            release_label.setWordWrap(True)
            content_layout.addWidget(release_label)

        current_version = str(labels.get("current_version") or "").strip()
        latest_version = str(labels.get("latest_version") or self._version).strip()
        version_card = QFrame(content)
        version_card.setObjectName("updateVersionCard")
        version_layout = QHBoxLayout(version_card)
        version_layout.setContentsMargins(14, 9, 14, 9)
        version_layout.setSpacing(12)

        def add_version(caption: str, value: str) -> None:
            column = QVBoxLayout()
            column.setSpacing(1)
            caption_label = QLabel(caption, version_card)
            caption_label.setObjectName("updateVersionCaption")
            value_label = QLabel(value, version_card)
            value_label.setObjectName("updateVersionValue")
            value_label.setTextFormat(Qt.PlainText)
            column.addWidget(caption_label)
            column.addWidget(value_label)
            version_layout.addLayout(column, 1)

        if current_version:
            add_version(labels.get("installed", "Installed"), current_version)
            arrow = QLabel("\u2192", version_card)
            arrow.setObjectName("updateVersionArrow")
            arrow.setAlignment(Qt.AlignCenter)
            version_layout.addWidget(arrow)
            add_version(labels.get("available", "Available"), latest_version)
        else:
            # Compatibility for older callers while the controller supplies
            # structured versions in normal application use.
            versions = QLabel(labels.get("versions", latest_version), version_card)
            versions.setObjectName("updateVersionValue")
            versions.setTextFormat(Qt.PlainText)
            version_layout.addWidget(versions)
        content_layout.addWidget(version_card)

        notes = str(labels.get("notes") or "").strip()
        if notes:
            notes_title = QLabel(labels.get("whats_new", "What's new"), content)
            notes_title.setObjectName("updateSectionTitle")
            content_layout.addWidget(notes_title)

            if len(notes) > self.NOTES_LIMIT:
                notes = notes[: self.NOTES_LIMIT].rstrip() + "…"
            notes_card = QFrame(content)
            notes_card.setObjectName("updateNotesCard")
            notes_layout = QVBoxLayout(notes_card)
            notes_layout.setContentsMargins(14, 10, 10, 10)
            notes_layout.setSpacing(0)
            notes_label = QLabel(notes, notes_card)
            notes_label.setObjectName("updateBody")
            notes_label.setTextFormat(Qt.PlainText)  # never interpret GitHub HTML
            notes_label.setWordWrap(True)
            notes_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            if len(notes) > self.NOTES_INLINE_MAX:
                # Long changelog: bound the height and let it scroll.
                scroll = QScrollArea(notes_card)
                scroll.setObjectName("updateNotesScroll")
                scroll.setWidget(notes_label)
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.NoFrame)
                scroll.setMaximumHeight(104)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                scroll.setAttribute(Qt.WA_TranslucentBackground)
                scroll.viewport().setAutoFillBackground(False)
                notes_layout.addWidget(scroll)
            else:
                notes_layout.addWidget(notes_label)
            content_layout.addWidget(notes_card)

        content_layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        later_button = LiquidButton(labels["later"], "ghost", self._panel)
        later_button.setObjectName("updateLaterButton")
        later_button.setMinimumHeight(42)
        later_button.clicked.connect(self.close_overlay)
        open_button = LiquidButton(labels["open"], "accent", self._panel)
        open_button.setObjectName("updateOpenButton")
        open_button.setMinimumHeight(42)
        open_button.clicked.connect(self._on_update)
        actions.addWidget(later_button, 2)
        actions.addWidget(open_button, 3)
        panel_layout.addLayout(actions)

        skip_link = ClickableLabel(labels["skip"], self._panel)
        skip_link.setObjectName("updateSkipLink")
        skip_link.setAlignment(Qt.AlignCenter)
        skip_link.setCursor(Qt.PointingHandCursor)
        skip_link.setAccessibleName(labels["skip"])
        skip_link.clicked.connect(self._on_skip)
        panel_layout.addWidget(skip_link, 0, Qt.AlignHCenter)
        self._preferred_height = min(
            self.MAX_PREFERRED_HEIGHT,
            max(self.MIN_FITTED_HEIGHT, self._panel.sizeHint().height()),
        )
        self._fit_to_parent()

    def _on_update(self) -> None:
        self.update_requested.emit()
        self.close_overlay()

    def _on_skip(self) -> None:
        # Carry the exact version the window was built for — never re-read it
        # later from a controller field that may have changed.
        self.skip_requested.emit(self._version)
        self.close_overlay()

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self._start_open_animation()

    def _start_open_animation(self) -> None:
        self._fit_to_parent()
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
                self._fit_to_parent()
        return super().eventFilter(watched, event)

    def _fit_to_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            target = self._preferred_height
        else:
            available = parent.height() - (self.PARENT_MARGIN * 2)
            target = min(self._preferred_height, max(self.MIN_FITTED_HEIGHT, available))
        self._panel.setFixedHeight(target)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        self.setStyleSheet(
            f"""
            #updateTitle {{
                color: {palette["text"]};
                font-size: 18px;
                font-weight: 800;
            }}
            #updateClose {{
                color: {palette["muted"]};
                font-size: 19px;
                font-weight: 600;
            }}
            #updateClose:hover {{
                color: {palette["text"]};
                background: {palette["list_hover"]};
                border-radius: 8px;
            }}
            #updateRelease {{
                color: {palette["text"]};
                font-size: 13px;
                font-weight: 700;
            }}
            #updateVersionCard, #updateNotesCard {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 8px;
            }}
            #updateVersionCaption {{
                color: {palette["muted"]};
                font-size: 10px;
                font-weight: 600;
            }}
            #updateVersionValue {{
                color: {palette["text"]};
                font-size: 13px;
                font-weight: 750;
            }}
            #updateVersionArrow {{
                color: {palette["muted"]};
                font-size: 16px;
                font-weight: 600;
            }}
            #updateSectionTitle {{
                color: {palette["text"]};
                font-size: 11px;
                font-weight: 700;
            }}
            #updateBody {{
                color: {palette["text_soft"]};
                font-size: 12px;
                font-weight: 500;
                line-height: 1.4em;
            }}
            #updateContentScroll, #updateContentScroll > QWidget, #updateContent,
            #updateNotesScroll, #updateNotesScroll > QWidget, #updateNotesScroll QLabel {{
                background: transparent;
                border: none;
            }}
            #updateSkipLink {{
                color: {palette["muted"]};
                font-size: 11px;
                font-weight: 600;
                padding: 3px 8px;
            }}
            #updateSkipLink:hover {{
                color: {palette["text_soft"]};
                text-decoration: underline;
            }}
            """
        )
