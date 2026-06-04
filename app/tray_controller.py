from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.app_info import APP_NAME

if TYPE_CHECKING:
    from app.main_window import MainWindow


class TrayController:
    def __init__(self, host: MainWindow) -> None:
        self._host = host
        self._icon: QSystemTrayIcon | None = None
        self._about_action: QAction | None = None
        self._show_action: QAction | None = None
        self._hide_action: QAction | None = None
        self._quit_action: QAction | None = None
        self._notice_shown = False

    def setup(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)

        icon = QApplication.windowIcon()
        if icon.isNull():
            icon_path = Path(__file__).resolve().parent / "assets" / "icon.ico"
            if icon_path.exists():
                icon = QIcon(str(icon_path))

        tray_menu = QMenu(self._host)
        self._about_action = QAction(self._host)
        self._show_action = QAction(self._host)
        self._hide_action = QAction(self._host)
        self._quit_action = QAction(self._host)
        self._about_action.triggered.connect(self.show_about)
        self._show_action.triggered.connect(self.show_window)
        self._hide_action.triggered.connect(self._host.hide)
        self._quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(self._about_action)
        tray_menu.addSeparator()
        tray_menu.addAction(self._show_action)
        tray_menu.addAction(self._hide_action)
        tray_menu.addSeparator()
        tray_menu.addAction(self._quit_action)

        self._icon = QSystemTrayIcon(icon, self._host)
        self._icon.setContextMenu(tray_menu)
        self._icon.activated.connect(self.handle_activated)
        self.sync_texts()
        self._icon.show()

    def sync_texts(self) -> None:
        if self._icon is not None:
            self._icon.setToolTip(self._host._tr("tray.tooltip"))
        if self._about_action is not None:
            self._about_action.setText(self._host._tr("tray.about"))
        if self._show_action is not None:
            self._show_action.setText(self._host._tr("tray.show"))
        if self._hide_action is not None:
            self._hide_action.setText(self._host._tr("tray.hide"))
        if self._quit_action is not None:
            self._quit_action.setText(self._host._tr("tray.quit"))

    def handle_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick}:
            if self._host.isVisible() and not self._host.isMinimized():
                self._host.hide()
            else:
                self.show_window()

    def show_window(self) -> None:
        self._host.showMaximized()
        self._host.raise_()
        self._host.activateWindow()

    def show_about(self) -> None:
        self.show_window()
        self._host._show_about_overlay()

    def quit_app(self) -> None:
        self._host._force_quit_requested = True
        self._host.close()

    def should_minimize_on_close(self) -> bool:
        if self._host._force_quit_requested or self._host._close_requested:
            return False
        if self._icon is None or not self._icon.isVisible():
            return False
        return not getattr(self._host._ble, "_shutdown_started", False)

    def show_notice_once(self) -> None:
        if self._icon is None or self._notice_shown:
            return
        self._notice_shown = True
        self._icon.showMessage(
            APP_NAME,
            self._host._tr("tray.notice"),
            QSystemTrayIcon.Information,
            3000,
        )

    def hide_icon(self) -> None:
        if self._icon is not None:
            self._icon.hide()
