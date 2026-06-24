from __future__ import annotations

from app.diagnostics import build_diagnostics_report, sanitize_report_text
from app.localization import localization_manager


def test_diagnostics_report_includes_device_driver_and_write_characteristic() -> None:
    localization_manager.set_language("en")
    snapshot = {
        "connected": True,
        "device": {"name": "ELK-BLEDOM", "address": "AA:BB:CC", "rssi": "-54"},
        "driver": {
            "id": "bledom",
            "name": "BLEDOM / ELK-BLEDOM",
            "transport": "BLE",
            "notes": "Bluetooth controller.",
        },
        "write": {
            "selected_uuid": "0000fff3-0000-1000-8000-00805f9b34fb",
            "selected_properties": ["write-without-response"],
            "candidates": [
                {
                    "uuid": "0000fff3-0000-1000-8000-00805f9b34fb",
                    "properties": ["write-without-response"],
                }
            ],
        },
        "commands": {"power": True, "color": True, "brightness": True, "effects": 23, "speed": True},
    }

    report = build_diagnostics_report(snapshot, ["Connected"], include_crashes=False)

    assert "Name: ELK-BLEDOM" in report
    assert "Address: AA:BB:CC" in report
    assert "ID: bledom" in report
    assert "Copyright" not in report
    assert "Transport: BLE" in report
    assert "Notes: Bluetooth controller." in report
    assert "Selected: 0000fff3-0000-1000-8000-00805f9b34fb" in report
    assert "Effects: 23" in report
    assert "Connected" in report


def test_sanitize_report_text_hides_home_path(monkeypatch) -> None:
    class FakeHomePath:
        @staticmethod
        def home():
            return "C:\\Users\\ExampleUser"

    monkeypatch.setattr("app.diagnostics.Path", FakeHomePath)

    assert sanitize_report_text("C:\\Users\\ExampleUser\\Desktop\\report.txt") == "~\\Desktop\\report.txt"


def test_diagnostics_report_normalizes_localized_session_logs() -> None:
    localization_manager.set_language("en")
    report = build_diagnostics_report(
        {
            "connected": False,
            "device": {},
            "driver": {},
            "write": {},
            "commands": {},
        },
        ['__L10N__{"kind":"ble","event":"connecting","address":"AA:BB"}__END__'],
        include_crashes=False,
    )

    assert "__L10N__" not in report
    assert "Connecting to AA:BB..." in report
    assert "Name: -" not in report
    assert "Driver" not in report
    assert "Write characteristic" not in report
    assert "Supported commands" not in report
    assert "Recent BLE history" not in report
    assert "Recent crash logs" not in report


def test_diagnostics_report_normalizes_localized_ble_history() -> None:
    localization_manager.set_language("en")
    report = build_diagnostics_report(
        {
            "connected": True,
            "device": {"name": "Desk strip", "address": "AA:BB", "rssi": "-42"},
            "driver": {"id": "bledom", "name": "BLEDOM"},
            "write": {},
            "commands": {"power": True, "color": True, "brightness": True, "effects": 22, "speed": True},
            "history": {
                "last_error": "Command could not be written to any compatible GATT characteristic.",
                "last_command": {
                    "event": "command",
                    "description": '__L10N__{"kind":"ble","event":"brightness_set","value":57}__END__',
                    "payload": "7e 00 01 39 00 00 00 00 ef",
                    "targets": "0000fff3",
                },
                "events": [
                    {
                        "event": "command",
                        "description": '__L10N__{"kind":"ble","event":"brightness_set","value":57}__END__',
                        "payload": "7e 00 01 39 00 00 00 00 ef",
                        "targets": "0000fff3",
                    }
                ],
            },
        },
        [],
        include_crashes=False,
    )

    assert "__L10N__" not in report
    assert "Last command: Brightness set to 57%" in report
    assert "- command: Brightness set to 57%" in report
    assert "Last error: The Bluetooth command could not be written to this controller." in report


def test_diagnostics_report_includes_ble_history_without_home_paths(monkeypatch) -> None:
    localization_manager.set_language("en")

    class FakeHomePath:
        @staticmethod
        def home():
            return "C:\\Users\\ExampleUser"

    monkeypatch.setattr("app.diagnostics.Path", FakeHomePath)
    report = build_diagnostics_report(
        {
            "connected": True,
            "device": {"name": "Desk strip", "address": "AA:BB:CC", "rssi": "-42"},
            "driver": {"id": "bledom", "name": "BLEDOM"},
            "write": {},
            "commands": {"power": True, "color": True, "brightness": True, "effects": 22, "speed": True},
            "history": {
                "last_error": "C:\\Users\\ExampleUser\\bad\\trace.log",
                "last_command": {
                    "event": "command",
                    "description": "Power on",
                    "payload": "7e 00 04 f0 00 01 ff 00 ef",
                    "targets": "0000fff3",
                },
                "events": [
                    {
                        "event": "retry",
                        "uuid": "0000fff3",
                        "attempt": "1",
                        "total": "2",
                        "error": "temporary failure",
                        "payload": "7e 00 04 f0 00 01 ff 00 ef",
                    },
                    {
                        "event": "protocol_mismatch",
                        "details": "Device found, protocol differs.",
                    },
                ],
            },
        },
        [],
        include_crashes=False,
    )

    assert "BLE summary" in report
    assert "Last command: Power on" in report
    assert "Last payload: 7e 00 04 f0 00 01 ff 00 ef" in report
    assert "Last targets: 0000fff3" in report
    assert "Last error: ~\\bad\\trace.log" in report
    assert "Recent BLE history" in report
    assert "retry 1/2" in report
    assert "protocol mismatch" in report


def test_diagnostics_report_uses_current_language_for_report_labels() -> None:
    localization_manager.set_language("ru")
    report = build_diagnostics_report(
        {
            "connected": True,
            "device": {"name": "ELK-BLEDOM", "address": "AA:BB"},
            "driver": {"id": "bledom", "name": "BLEDOM", "transport": "BLE"},
            "write": {"selected_uuid": "0000fff3", "selected_properties": ["write-without-response"]},
            "commands": {"power": True, "color": True, "brightness": True, "effects": 22, "speed": True},
            "history": {
                "last_command": {
                    "event": "command",
                    "description": '__L10N__{"kind":"ble","event":"color_set","red":1,"green":2,"blue":3}__END__',
                    "payload": "7e",
                    "targets": "0000fff3",
                },
                "events": [
                    {
                        "event": "command",
                        "description": '__L10N__{"kind":"ble","event":"color_set","red":1,"green":2,"blue":3}__END__',
                        "payload": "7e",
                        "targets": "0000fff3",
                    }
                ],
            },
        },
        ["Connected"],
        include_crashes=False,
    )

    assert "Версия: 0.2.2" in report
    assert "Устройство" in report
    assert "Подключено: да" in report
    assert "Поддерживаемые команды" in report
    assert "Последняя команда: Установлен цвет RGB(1, 2, 3)" in report
    assert "- команда: Установлен цвет RGB(1, 2, 3)" in report
    assert "Session logs" not in report
    assert "Connected: yes" not in report
