from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.main_layout import select_section
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
        assert window.configs_card.header_layout.indexOf(window.import_profiles_button) == -1
        assert window.configs_card.header_layout.indexOf(window.export_profiles_button) == -1
        assert window.configs_card.header_layout.indexOf(window.configs_menu_button) == -1
        assert window.import_profiles_button.toolTip() == window._tr("configs.import_tooltip")
        assert window.export_profiles_button.toolTip() == window._tr("configs.export_tooltip")
        assert window.configs_menu_button.toolTip() == window._tr("configs.menu")
        assert window.import_profiles_button.accessibleName() == window._tr("configs.import_tooltip")
        assert window.export_profiles_button.accessibleName() == window._tr("configs.export_tooltip")
        assert window.configs_menu_button.accessibleName() == window._tr("configs.menu")
        assert window.reset_profiles_action.text() == window._tr("configs.menu_reset")
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_configs_save_row_fits_the_minimum_window(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    window = MainWindow()
    try:
        window.resize(860, 420)
        window.show()
        select_section(window, "profiles")
        window.body_scroll.ensureWidgetVisible(window.configs_card, 0, 12)
        for _ in range(8):
            app.processEvents()

        card_rect = window.configs_card.rect()
        for control in (
            window.profile_name,
            window.save_profile_button,
            window.import_profiles_button,
            window.export_profiles_button,
            window.configs_menu_button,
        ):
            top_left = control.mapTo(window.configs_card, control.rect().topLeft())
            bottom_right = control.mapTo(window.configs_card, control.rect().bottomRight())
            assert card_rect.contains(top_left)
            assert card_rect.contains(bottom_right)
        assert window.body_scroll.horizontalScrollBar().maximum() == 0

        def vertical_gap(upper, lower) -> int:
            upper_top = upper.mapTo(window.configs_card, upper.rect().topLeft()).y()
            lower_top = lower.mapTo(window.configs_card, lower.rect().topLeft()).y()
            return lower_top - (upper_top + upper.height())

        assert window.configs_card.subtitle_label.height() == window.configs_library_hint.height()
        assert window.configs_saved_hint.height() >= window.configs_library_hint.height()
        assert window.configs_saved_hint.height() >= window.configs_saved_hint.fontMetrics().boundingRect("Ag").height()
        assert window.configs_library_label.height() == window.configs_saved_label.height()
        assert vertical_gap(window.configs_card.subtitle_label, window.configs_library_label) <= 16
        assert vertical_gap(window.configs_library_label, window.configs_library_hint) == vertical_gap(
            window.configs_saved_label, window.configs_saved_hint
        )
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_delete_config_requires_confirmation(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("app.main_window.save_settings", lambda _settings: None)
    window = MainWindow()
    calls: list[str] = []
    overlays = []

    def fake_open(self):
        overlays.append(self)

    try:
        window.profile_list.setCurrentRow(0)
        window._profile_controller.delete_selected_profile = lambda *_args: calls.append("deleted")

        monkeypatch.setattr("app.profile_actions.ProfileConfirmOverlay.open", fake_open)
        window._profile_actions.delete_selected_profile()
        assert calls == []

        overlays[-1].confirmed.emit()
        assert calls == ["deleted"]
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()
