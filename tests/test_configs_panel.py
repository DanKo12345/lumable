from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.profile_actions import ProfileActions


def test_profile_click_loads_config_without_load_button(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    calls: list[str] = []
    monkeypatch.setattr(ProfileActions, "load_selected_profile", lambda _self: calls.append("loaded"))
    window = MainWindow()
    try:
        window._profile_actions.load_selected_profile = lambda: calls.append("loaded")
        item = window.profile_list.item(0)

        window.profile_list.itemClicked.emit(item)

        assert calls == ["loaded"]
        assert not hasattr(window, "load_profile_button")
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_config_header_uses_compact_actions(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    window = MainWindow()
    try:
        assert window.import_profiles_button.toolTip() == window._tr("configs.import_tooltip")
        assert window.export_profiles_button.toolTip() == window._tr("configs.export_tooltip")
        assert window.configs_menu_button.toolTip() == window._tr("configs.menu")
        assert window.reset_profiles_action.text() == window._tr("configs.menu_reset")
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_delete_config_requires_confirmation(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    window = MainWindow()
    calls: list[str] = []
    try:
        window.profile_list.setCurrentRow(0)
        window._profile_controller.delete_selected_profile = lambda *_args: calls.append("deleted")

        monkeypatch.setattr("app.profile_actions.ProfileConfirmOverlay.exec", lambda _self: False)
        window._profile_actions.delete_selected_profile()
        assert calls == []

        monkeypatch.setattr("app.profile_actions.ProfileConfirmOverlay.exec", lambda _self: True)
        window._profile_actions.delete_selected_profile()
        assert calls == ["deleted"]
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()
