from __future__ import annotations

from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu

from app.localization import localization_manager
from app.styles import context_menu_qss
from app.theme import theme_manager


class ThemedLineEdit(QLineEdit):
    """A QLineEdit whose right-click menu is themed and localised.

    Qt's built-in context menu is drawn natively (light, English-only), which
    clashes with the app's dark UI. This rebuilds the usual editing actions with
    the app theme and the current interface language. Paste stays available on
    purpose — it's the handy way to drop in a licence key or hex colour.
    """

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(context_menu_qss(theme_manager.palette))
        t = localization_manager.t
        editable = not self.isReadOnly()
        has_selection = self.hasSelectedText()
        can_paste = editable and bool(QApplication.clipboard().text())

        def add(label: str, shortcut: str, enabled: bool, slot) -> None:
            action = menu.addAction(f"{label}\t{shortcut}")
            action.setEnabled(enabled)
            action.triggered.connect(slot)

        add(t("menu.undo"), "Ctrl+Z", editable and self.isUndoAvailable(), self.undo)
        add(t("menu.redo"), "Ctrl+Y", editable and self.isRedoAvailable(), self.redo)
        menu.addSeparator()
        add(t("menu.cut"), "Ctrl+X", editable and has_selection, self.cut)
        add(t("menu.copy"), "Ctrl+C", has_selection, self.copy)
        add(t("menu.paste"), "Ctrl+V", can_paste, self.paste)
        add(t("menu.delete"), "Del", editable and has_selection, lambda: self.insert(""))
        menu.addSeparator()
        add(t("menu.select_all"), "Ctrl+A", bool(self.text()), self.selectAll)
        menu.exec(event.globalPos())
