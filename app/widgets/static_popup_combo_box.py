from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.theme import qcolor_from_token


class StaticPopupComboBox(QComboBox):
    def __init__(
        self,
        theme_provider: Callable[[], dict[str, str]],
        is_dark_provider: Callable[[], bool],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme_provider = theme_provider
        self._is_dark_provider = is_dark_provider
        self._popup: QFrame | None = None
        self._list: QListWidget | None = None
        self._popup_parent: QWidget | None = None
        self._app_filter_installed = False
        self._open_fade: QPropertyAnimation | None = None
        self._open_slide: QPropertyAnimation | None = None

    def _popup_host(self):
        return self.window()

    def _ensure_popup(self) -> None:
        host = self._popup_host()
        if self._popup is not None and self._list is not None and self._popup_parent is host:
            return
        if self._popup is not None:
            self._popup.hide()
            self._popup.deleteLater()
        popup = QFrame(host)
        popup.setObjectName("staticComboPopup")
        popup.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        popup.hide()

        outer = QVBoxLayout(popup)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(0)

        list_widget = QListWidget(popup)
        list_widget.setObjectName("staticComboPopupList")
        list_widget.setFrameShape(QFrame.Shape.NoFrame)
        list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_widget.setAlternatingRowColors(False)
        list_widget.setUniformItemSizes(True)
        list_widget.setMouseTracking(False)
        list_widget.itemClicked.connect(self._handle_item_clicked)

        outer.addWidget(list_widget)
        self._popup = popup
        self._list = list_widget
        self._popup_parent = host

    def _composite(self, top: QColor, base: QColor) -> QColor:
        alpha = top.alphaF()
        inv = 1.0 - alpha
        return QColor(
            round(top.red() * alpha + base.red() * inv),
            round(top.green() * alpha + base.green() * inv),
            round(top.blue() * alpha + base.blue() * inv),
            255,
        )

    def _apply_popup_style(self) -> None:
        if self._popup is None or self._list is None:
            return
        tokens = self._theme_provider()
        is_dark = bool(self._is_dark_provider())

        if is_dark:
            base = qcolor_from_token(tokens["surface_strong"])
            base.setAlpha(255)
            surface_soft = qcolor_from_token(tokens["surface_soft"])
            surface_soft.setAlpha(255)
            bottom = QColor(12, 13, 16, 255)  # neutral graphite, not navy blue
        else:
            surface_soft = QColor(255, 255, 255, 255)
            base = QColor(245, 246, 249, 255)
            bottom = QColor(231, 232, 236, 255)
        border = qcolor_from_token(tokens["field_border"])
        border.setAlpha(130 if is_dark else 118)

        # Neutral graphite selection (no blue accent): a soft light highlight in
        # dark mode, a soft dark tint in light mode — matches the rest of the UI.
        if is_dark:
            top_light = QColor(255, 255, 255, 44)
            selected = QColor(255, 255, 255, 30)
            selected_bottom = QColor(255, 255, 255, 16)
            selected_border = QColor(255, 255, 255, 64)
            hover = QColor(255, 255, 255, 10)
            hover_border = QColor(255, 255, 255, 12)
        else:
            top_light = QColor(22, 26, 34, 34)
            selected = QColor(22, 26, 34, 22)
            selected_bottom = QColor(22, 26, 34, 12)
            selected_border = QColor(22, 26, 34, 48)
            hover = QColor(22, 26, 34, 16)
            hover_border = QColor(22, 26, 34, 22)
        text = qcolor_from_token(tokens["text"]).name()

        self._popup.setStyleSheet(
            f"""
            QFrame#staticComboPopup {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {surface_soft.name(QColor.NameFormat.HexArgb)},
                    stop:0.46 {base.name(QColor.NameFormat.HexArgb)},
                    stop:1 {bottom.name(QColor.NameFormat.HexArgb)});
                border: 1px solid {border.name(QColor.NameFormat.HexArgb)};
                border-radius: 18px;
            }}
            QListWidget#staticComboPopupList {{
                background: transparent;
                color: {text};
                outline: none;
                padding: 4px;
                border: none;
            }}
            QListWidget#staticComboPopupList::item {{
                background: rgba(255, 255, 255, 0.00);
                color: {text};
                border: 1px solid transparent;
                border-radius: 12px;
                margin: 2px 0;
                padding: 10px 13px;
            }}
            QListWidget#staticComboPopupList::item:selected {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {top_light.name(QColor.NameFormat.HexArgb)},
                    stop:0.42 {selected.name(QColor.NameFormat.HexArgb)},
                    stop:1 {selected_bottom.name(QColor.NameFormat.HexArgb)});
                color: {text};
                border: 1px solid {selected_border.name(QColor.NameFormat.HexArgb)};
            }}
            QListWidget#staticComboPopupList::item:hover {{
                background: {hover.name(QColor.NameFormat.HexArgb)};
                color: {text};
                border: 1px solid {hover_border.name(QColor.NameFormat.HexArgb)};
            }}
            QListWidget#staticComboPopupList::item:selected:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {top_light.name(QColor.NameFormat.HexArgb)},
                    stop:0.42 {selected.name(QColor.NameFormat.HexArgb)},
                    stop:1 {selected_bottom.name(QColor.NameFormat.HexArgb)});
                color: {text};
                border: 1px solid {selected_border.name(QColor.NameFormat.HexArgb)};
            }}
            QScrollBar:vertical {{
                width: 14px;
                margin: 8px 3px 8px 7px;
                background: rgba(255, 255, 255, 0.06);
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {tokens["scroll"]};
                border-radius: 5px;
                min-height: 28px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
                border: none;
            }}
            """
        )

    def _sync_popup_items(self) -> None:
        if self._list is None:
            return
        self._list.clear()
        self._list.setIconSize(QSize(34, 18))
        muted = qcolor_from_token(self._theme_provider()["muted"])
        for index in range(self.count()):
            text = self.itemText(index)
            item = QListWidgetItem()
            combo_icon = self.itemIcon(index)
            if text.startswith("↻ "):
                item.setText(text[2:])
                item.setIcon(self._reload_icon())
            else:
                item.setText(text)
                if not combo_icon.isNull():
                    item.setIcon(combo_icon)
            # A None payload on an item that carries its own icon marks a locked
            # (Pro) effect: keep it visible but clearly muted.
            if self.itemData(index) is None and not combo_icon.isNull():
                item.setForeground(muted)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item.setSizeHint(QSize(0, 42))
            self._list.addItem(item)
        if self.count():
            self._list.setCurrentRow(max(0, self.currentIndex()))

    def _reload_icon(self) -> QIcon:
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(qcolor_from_token(self._theme_provider()["text"]))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "↻")
        painter.end()
        return QIcon(pixmap)

    def _popup_size(self) -> QSize:
        if self._list is None:
            return QSize(self.width(), 200)
        row_height = max(32, self._list.sizeHintForRow(0))
        visible_rows = min(max(1, self.count()), max(1, self.maxVisibleItems()))
        height = row_height * visible_rows + 18
        metrics = self._list.fontMetrics()
        content_width = 0
        for index in range(self.count()):
            text = self.itemText(index)
            icon_width = 0
            if text.startswith("\u21bb "):
                text = text[2:]
                icon_width = self._list.iconSize().width() + 10
            content_width = max(content_width, metrics.horizontalAdvance(text) + icon_width)
        width = max(self.width(), content_width + 64)
        return QSize(width, height)

    def _popup_position(self, size: QSize) -> QPoint:
        host = self._popup_host()
        anchor = host.mapFromGlobal(self.mapToGlobal(QPoint(0, self.height() + 6)))
        available = host.rect().adjusted(8, 8, -8, -8)
        x = min(max(anchor.x(), available.left()), max(available.left(), available.right() - size.width() + 1))
        y = anchor.y()
        if y + size.height() > available.bottom() + 1:
            above = host.mapFromGlobal(self.mapToGlobal(QPoint(0, -size.height() - 6)))
            y = max(available.top(), above.y())
        return QPoint(x, y)

    def showPopup(self) -> None:
        if self.count() <= 0:
            return
        self._ensure_popup()
        self._apply_popup_style()
        self._sync_popup_items()
        if self._popup is None or self._list is None:
            return
        size = self._popup_size()
        position = self._popup_position(size)
        target = QRect(position.x(), position.y(), size.width(), size.height())
        self._popup.setGeometry(target)
        self._animate_open(target)
        self._popup.show()
        self._popup.raise_()
        self._list.setFocus()
        if self._popup_parent is not None:
            self._popup_parent.installEventFilter(self)
        app = QApplication.instance()
        if app is not None and not self._app_filter_installed:
            app.installEventFilter(self)
            self._app_filter_installed = True

    def _animate_open(self, target: QRect) -> None:
        if self._popup is None:
            return
        effect = QGraphicsOpacityEffect(self._popup)
        self._popup.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        self._open_fade = QPropertyAnimation(effect, b"opacity", self._popup)
        self._open_fade.setDuration(150)
        self._open_fade.setStartValue(0.0)
        self._open_fade.setEndValue(1.0)
        self._open_fade.setEasingCurve(QEasingCurve.OutCubic)
        # Subtle "pop": grow from ~94% (centred on the final spot) + a small drop,
        # while fading in — a lively, modern open instead of a flat appear.
        start = QRect(0, 0, int(target.width() * 0.94), int(target.height() * 0.94))
        start.moveCenter(target.center())
        start.translate(0, -6)
        self._open_slide = QPropertyAnimation(self._popup, b"geometry", self._popup)
        self._open_slide.setDuration(185)
        self._open_slide.setStartValue(start)
        self._open_slide.setEndValue(target)
        self._open_slide.setEasingCurve(QEasingCurve.OutCubic)
        # While the popup grows from 94% it's briefly shorter than its content,
        # which flashes a scrollbar. Hide it during the animation and restore the
        # as-needed policy once it settles (so long lists still get a scrollbar).
        if self._list is not None:
            self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._open_slide.finished.connect(self._restore_scrollbar_policy)
        self._open_fade.start()
        self._open_slide.start()

    def _restore_scrollbar_policy(self) -> None:
        if self._list is not None:
            self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.hide()
        if self._popup_parent is not None:
            self._popup_parent.removeEventFilter(self)
        app = QApplication.instance()
        if app is not None and self._app_filter_installed:
            app.removeEventFilter(self)
            self._app_filter_installed = False

    def _handle_item_clicked(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < self.count():
            self.setCurrentIndex(index)
        self.hidePopup()

    def _is_popup_widget(self, widget) -> bool:
        if self._popup is None or not isinstance(widget, QWidget):
            return False
        current: QWidget | None = widget
        while current is not None:
            if current is self._popup:
                return True
            current = current.parentWidget()
        return False

    def eventFilter(self, watched, event) -> bool:
        if self._popup is not None and self._popup.isVisible():
            if event.type() == QEvent.Type.MouseButtonPress:
                global_pos = event.globalPosition().toPoint()
                popup_pos = self._popup.mapFromGlobal(global_pos)
                combo_pos = self.mapFromGlobal(global_pos)
                if self._popup.rect().contains(popup_pos) or self.rect().contains(combo_pos):
                    return super().eventFilter(watched, event)
                self.hidePopup()
            elif event.type() in {
                QEvent.Type.Hide,
                QEvent.Type.Move,
                QEvent.Type.Resize,
                QEvent.Type.Scroll,
                QEvent.Type.Wheel,
                QEvent.Type.WindowDeactivate,
            }:
                if self._is_popup_widget(watched):
                    return super().eventFilter(watched, event)
                if event.type() == QEvent.Type.Wheel and hasattr(event, "globalPosition"):
                    popup_pos = self._popup.mapFromGlobal(event.globalPosition().toPoint())
                    if self._popup.rect().contains(popup_pos):
                        return super().eventFilter(watched, event)
                self.hidePopup()
        return super().eventFilter(watched, event)
