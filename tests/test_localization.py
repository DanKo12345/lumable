from __future__ import annotations

import json
from importlib import resources

from app import localization


def test_packaged_languages_are_available() -> None:
    manager = localization.LocalizationManager()

    assert manager.available_languages()[:3] == ["ru", "en", "zh"]
    assert manager.language_name("ru") == "Русский"
    assert manager.language_name("en") == "English"
    assert manager.language_name("zh") == "中文"


def test_packaged_translations_do_not_contain_replacement_question_marks() -> None:
    for resource in resources.files("app.i18n").iterdir():
        if resource.suffix.lower() != ".json":
            continue
        payload = json.loads(resource.read_text(encoding="utf-8"))
        translations = payload["translations"]
        broken = {
            key: value
            for key, value in translations.items()
            if isinstance(value, str) and "??" in value
        }

        assert broken == {}


def test_missing_translation_falls_back_to_russian() -> None:
    manager = localization.LocalizationManager()
    manager._translations["zz"] = {}
    manager._language_labels["zz"] = "Test"
    manager.set_language("zz")

    assert manager.t("hero.title") == manager._translations["ru"]["hero.title"]
    assert manager.t("missing.key") == "missing.key"


def test_reload_loads_user_language_without_restart(tmp_path, monkeypatch) -> None:
    user_i18n = tmp_path / "i18n"
    user_i18n.mkdir()
    payload = {
        "language": {"code": "fr", "label": "Français"},
        "translations": {"hero.title": "Contrôleur RGB"},
    }
    (user_i18n / "fr.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(localization, "USER_I18N_DIR", user_i18n)

    manager = localization.LocalizationManager()
    manager.reload()

    assert "fr" in manager.available_languages()
    assert manager.language_name("fr") == "Français"
    manager.set_language("fr")
    assert manager.t("hero.title") == "Contrôleur RGB"


def test_user_language_can_override_ble_error_text(tmp_path, monkeypatch) -> None:
    user_i18n = tmp_path / "i18n"
    user_i18n.mkdir()
    payload = {
        "language": {"code": "xx", "label": "Test"},
        "translations": {"error.bluetooth_off": "BT OFF CUSTOM"},
    }
    (user_i18n / "xx.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(localization, "USER_I18N_DIR", user_i18n)

    manager = localization.LocalizationManager()
    manager.set_language("xx")

    assert manager.normalize_error_message("Bluetooth radio is not powered on") == "BT OFF CUSTOM"


def test_bluetooth_off_error_variants_are_localized() -> None:
    manager = localization.LocalizationManager()
    manager.set_language("ru")

    assert manager.normalize_error_message("Bluetooth is turned off") == manager.t("error.bluetooth_off")
    assert manager.normalize_error_message("No Bluetooth adapters were found") == manager.t("error.bluetooth_off")
    assert manager.normalize_error_message("Bluetooth adapter is disabled") == manager.t("error.bluetooth_off")


def test_reload_falls_back_when_current_language_disappears(tmp_path, monkeypatch) -> None:
    user_i18n = tmp_path / "i18n"
    user_i18n.mkdir()
    monkeypatch.setattr(localization, "USER_I18N_DIR", user_i18n)
    manager = localization.LocalizationManager()
    manager._translations["zz"] = {"hero.title": "Temporary"}
    manager._language_labels["zz"] = "Temporary"
    manager.set_language("zz")

    manager.reload()

    assert manager.language == "ru"


def test_l10n_config_event_retranslates_profile_name() -> None:
    manager = localization.LocalizationManager()
    profile = {"preset_key": "polar_mint", "name": "Полярная мята"}
    message = manager.status_config_event("loaded", profile)

    manager.set_language("en")
    assert manager.normalize_status_message(message) == 'Config "Polar Mint" loaded.'

    manager.set_language("zh")
    assert "极地薄荷" in manager.normalize_status_message(message)


def test_ble_error_prefix_spacing_is_clean() -> None:
    manager = localization.LocalizationManager()
    manager.set_language("ru")

    message = manager.normalize_status_message("BLE error: Connect to the LED strip first.")

    assert message == "Ошибка BLE: Сначала подключитесь к LED-ленте."
    assert "BLE:Сначала" not in message


def test_triones_effect_labels_are_human_readable() -> None:
    manager = localization.LocalizationManager()
    triones_keys = [
        "effect.triones_rainbow",
        *[f"effect.triones_effect_{code:02x}" for code in range(0x26, 0x39)],
    ]

    for language in ("ru", "en", "zh"):
        manager.set_language(language)
        for key in triones_keys:
            label = manager.t(key)
            assert label != key
            assert "triones_effect" not in label
            assert "0x" not in label.lower()


def test_banlanx_effect_labels_are_human_readable() -> None:
    manager = localization.LocalizationManager()
    banlanx_keys = [f"effect.banlanx_effect_{code:02x}" for code in range(0x01, 0x18)]

    for language in ("ru", "en", "zh"):
        manager.set_language(language)
        for key in banlanx_keys:
            label = manager.t(key)
            assert label != key
            assert "banlanx_effect" not in label
            assert "0x" not in label.lower()


def test_magic_home_effect_labels_are_human_readable() -> None:
    manager = localization.LocalizationManager()
    magic_home_keys = [
        "effect.magic_home_rainbow",
        *[f"effect.magic_home_effect_{code:02x}" for code in range(0x26, 0x39)],
    ]

    for language in ("ru", "en", "zh"):
        manager.set_language(language)
        for key in magic_home_keys:
            label = manager.t(key)
            assert label != key
            assert "magic_home_effect" not in label
            assert "0x" not in label.lower()


def test_update_labels_are_translated() -> None:
    manager = localization.LocalizationManager()
    update_keys = [
        "updates.check",
        "updates.checking",
        "updates.open",
        "updates.open_releases",
        "updates.available",
        "updates.current",
        "updates.error",
        "updates.rate_limited",
        "updates.disabled",
        "updates.no_download_url",
        "app.version_stage.beta",
        "device.connecting",
        "device.status.connecting",
        "tray.tooltip",
        "tray.about",
        "tray.show",
        "tray.hide",
        "tray.quit",
        "tray.minimized",
        "tray.notice",
        "dialog.cancel",
        "color.hex",
        "color.power_on",
        "color.power_off",
        "power.label",
        "dialog.slider_value_title",
        "dialog.slider_value_label",
        "time_picker.hours",
        "time_picker.minutes",
        "error.unknown",
        "error.ble_unknown_detail",
        "error.bluetooth_off",
        "error.device_not_found",
        "error.no_writable_gatt",
        "error.protocol_not_supported",
        "error.write_failed",
        "error.protocol_mismatch",
        "error.unknown_protocol_send",
        "device.last",
        "device.last.autoconnecting",
        "device.last.none",
        "status.ble.unexpected_disconnect",
        "status.ble.reconnect_attempt",
        "status.ble.reconnect_failed_attempt",
        "status.ble.reconnect_success",
        "status.ble.reconnect_give_up",
        "status.ble.write_retry",
        "status.ble.write_failed",
        "about.title",
        "about.author_title",
        "about.privacy_title",
        "about.privacy_text",
        "about.components_title",
        "about.components_text",
        "about.meta_text",
        "diagnostics.report.version",
        "diagnostics.report.author",
        "diagnostics.report.generated",
        "diagnostics.report.os",
        "diagnostics.report.python",
        "diagnostics.report.yes",
        "diagnostics.report.no",
        "diagnostics.report.device_section",
        "diagnostics.report.connected",
        "diagnostics.report.name",
        "diagnostics.report.address",
        "diagnostics.report.rssi",
        "diagnostics.report.driver_section",
        "diagnostics.report.id",
        "diagnostics.report.transport",
        "diagnostics.report.notes",
        "diagnostics.report.write_section",
        "diagnostics.report.selected",
        "diagnostics.report.selected_properties",
        "diagnostics.report.candidates",
        "diagnostics.report.supported_commands_section",
        "diagnostics.report.power",
        "diagnostics.report.color",
        "diagnostics.report.brightness",
        "diagnostics.report.effects",
        "diagnostics.report.speed",
        "diagnostics.report.ble_summary_section",
        "diagnostics.report.last_command",
        "diagnostics.report.last_payload",
        "diagnostics.report.last_targets",
        "diagnostics.report.last_error",
        "diagnostics.report.recent_ble_history_section",
        "diagnostics.report.session_logs_section",
        "diagnostics.report.recent_crash_logs_section",
        "diagnostics.report.history_command",
        "diagnostics.report.history_retry",
        "diagnostics.report.history_protocol_mismatch",
        "diagnostics.report.history_error",
        "diagnostics.report.history_event",
        "diagnostics.report.payload",
        "diagnostics.report.targets",
    ]

    for language in ("ru", "en", "zh"):
        manager.set_language(language)
        for key in update_keys:
            assert manager.t(key) != key
