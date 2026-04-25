from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, Qt, QSize
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
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

    def _ensure_popup(self) -> None:
        if self._popup is not None and self._list is not None:
            return
        popup = QFrame(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setObjectName("staticComboPopup")
        popup.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(popup)
        outer.setContentsMargins(0, 0, 0, 0)
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

        base = qcolor_from_token(tokens["surface_strong"])
        base.setAlpha(255)
        border = qcolor_from_token(tokens["field_border"])
        border.setAlpha(150 if is_dark else 110)
        selected = self._composite(qcolor_from_token(tokens["list_sel"]), base)
        hover = self._composite(qcolor_from_token(tokens["field_alt"]), base)
        text = qcolor_from_token(tokens["text"]).name()
        muted = qcolor_from_token(tokens["muted"]).name()

        self._popup.setStyleSheet(
            f"""
            QFrame#staticComboPopup {{
                background: {base.name(QColor.NameFormat.HexArgb)};
                border: 1px solid {border.name(QColor.NameFormat.HexArgb)};
                border-radius: 14px;
            }}
            QListWidget#staticComboPopupList {{
                background: transparent;
                color: {text};
                outline: none;
                padding: 4px;
            }}
            QListWidget#staticComboPopupList::item {{
                background: transparent;
                color: {text};
                border: none;
                border-radius: 0;
                margin: 0;
                padding: 10px 12px;
            }}
            QListWidget#staticComboPopupList::item:selected {{
                background: {selected.name(QColor.NameFormat.HexArgb)};
                color: {text};
                border-radius: 8px;
            }}
            QListWidget#staticComboPopupList::item:hover {{
                background: {hover.name(QColor.NameFormat.HexArgb)};
                color: {text};
                border-radius: 8px;
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
        for index in range(self.count()):
            item = QListWidgetItem(self.itemText(index))
            item.setData(Qt.ItemDataRole.UserRole, index)
            self._list.addItem(item)
        if self.count():
            self._list.setCurrentRow(max(0, self.currentIndex()))

    def _popup_size(self) -> QSize:
        if self._list is None:
            return QSize(self.width(), 200)
        row_height = max(32, self._list.sizeHintForRow(0))
        visible_rows = min(max(1, self.count()), max(1, self.maxVisibleItems()))
        height = row_height * visible_rows + 10
        width = max(self.width(), self._list.sizeHintForColumn(0) + 48)
        return QSize(width, height)

    def _popup_position(self, size: QSize) -> QPoint:
        anchor = self.mapToGlobal(QPoint(0, self.height() + 6))
        screen = QGuiApplication.screenAt(anchor) or self.screen()
        if screen is None:
            return anchor
        available = screen.availableGeometry()
        x = min(max(anchor.x(), available.left()), max(available.left(), available.right() - size.width()))
        y = anchor.y()
        if y + size.height() > available.bottom():
            above = self.mapToGlobal(QPoint(0, -size.height() - 6))
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
        self._popup.setGeometry(position.x(), position.y(), size.width(), size.height())
        self._popup.show()
        self._popup.raise_()
        self._list.setFocus()

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.hide()

    def _handle_item_clicked(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < self.count():
            self.setCurrentIndex(index)
        self.hidePopup()

