from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.app_info import APP_NAME
from app.feature_gate import can_use
from app.localization import localization_manager

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
        self._quick_menu: QMenu | None = None
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
        self._quick_menu = QMenu(self._host)
        self._about_action.triggered.connect(self.show_about)
        self._show_action.triggered.connect(self.show_window)
        self._hide_action.triggered.connect(self._host.hide)
        self._quit_action.triggered.connect(self.quit_app)
        self._quick_menu.aboutToShow.connect(self.rebuild_quick_menu)
        tray_menu.addAction(self._about_action)
        tray_menu.addSeparator()
        tray_menu.addMenu(self._quick_menu)
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
        if self._quick_menu is not None:
            self._quick_menu.setTitle(self._host._tr("tray.quick_controls"))
            self.rebuild_quick_menu()

    def rebuild_quick_menu(self) -> None:
        if self._quick_menu is None:
            return
        self._quick_menu.clear()
        if not can_use("tray_quick_controls"):
            locked = QAction(self._host._tr("tray.quick_locked"), self._quick_menu)
            locked.setEnabled(False)
            unlock = QAction(self._host._tr("tray.unlock_pro"), self._quick_menu)
            unlock.triggered.connect(self.show_license)
            self._quick_menu.addAction(locked)
            self._quick_menu.addAction(unlock)
            return

        power_text = self._host._tr("color.power_off") if self._host.power_button.isChecked() else self._host._tr("color.power_on")
        power_action = QAction(power_text, self._quick_menu)
        power_action.triggered.connect(self.toggle_power)
        self._quick_menu.addAction(power_action)
        self._quick_menu.addMenu(self._brightness_menu())
        self._quick_menu.addMenu(self._recent_colors_menu())
        self._quick_menu.addMenu(self._profiles_menu())

    def _brightness_menu(self) -> QMenu:
        menu = QMenu(self._host._tr("tray.brightness"), self._quick_menu)
        for value in (25, 50, 75, 100):
            action = QAction(f"{value}%", menu)
            action.triggered.connect(lambda _checked=False, brightness=value: self.set_brightness(brightness))
            menu.addAction(action)
        return menu

    def _recent_colors_menu(self) -> QMenu:
        menu = QMenu(self._host._tr("tray.recent_colors"), self._quick_menu)
        history = self._host._color_history()[:6]
        if not history:
            empty = QAction(self._host._tr("tray.empty"), menu)
            empty.setEnabled(False)
            menu.addAction(empty)
            return menu
        for item in history:
            red = int(item.get("r", 0))
            green = int(item.get("g", 0))
            blue = int(item.get("b", 0))
            action = QAction(f"#{red:02X}{green:02X}{blue:02X}", menu)
            action.triggered.connect(
                lambda _checked=False, r=red, g=green, b=blue: self.apply_color(r, g, b)
            )
            menu.addAction(action)
        return menu

    def _profiles_menu(self) -> QMenu:
        menu = QMenu(self._host._tr("tray.profiles"), self._quick_menu)
        profiles = list(self._host._profile_controller.profiles)[:10]
        if not profiles:
            empty = QAction(self._host._tr("tray.empty"), menu)
            empty.setEnabled(False)
            menu.addAction(empty)
            return menu
        for profile in profiles:
            action = QAction(localization_manager.profile_name(profile), menu)
            action.triggered.connect(lambda _checked=False, payload=profile: self.apply_profile(payload))
            menu.addAction(action)
        return menu

    def handle_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick}:
            if self._host.isVisible() and not self._host.isMinimized():
                self._host.hide()
            else:
                self.show_window()

    def show_window(self) -> None:
        if self._host.isMinimized():
            self._host.showNormal()
        else:
            self._host.show()
        self._host.raise_()
        self._host.activateWindow()

    def show_about(self) -> None:
        self.show_window()
        self._host._show_about_overlay()

    def show_license(self) -> None:
        self.show_window()
        self._host._show_license_overlay()

    def toggle_power(self) -> None:
        self._host.power_button.setChecked(not self._host.power_button.isChecked())
        self._host._toggle_power()
        self.rebuild_quick_menu()

    def set_brightness(self, value: int) -> None:
        self._host.brightness_slider.setValue(max(0, min(100, int(value))))
        self._host._apply_current_color()

    def apply_color(self, red: int, green: int, blue: int) -> None:
        with self._host._suppress_signals():
            self._host.red_slider.setValue(red)
            self._host.green_slider.setValue(green)
            self._host.blue_slider.setValue(blue)
        self._host._apply_current_color()

    def apply_profile(self, profile: dict) -> None:
        self._host._profile_actions.apply_profile_payload(profile, announce_load=True)

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
