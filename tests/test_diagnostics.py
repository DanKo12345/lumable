from __future__ import annotations

import os
import time

import app.diagnostics as diagnostics
from app.diagnostics import _read_recent_crash_logs, build_diagnostics_report, sanitize_report_text
from app.localization import localization_manager


def test_report_lists_every_strip_with_its_role_and_state() -> None:
    """A multi-strip setup must be visible in the report — "the other strip
    also lit up" needs something to point at."""
    localization_manager.set_language("en")
    snapshot = {
        "connected": True,
        "device": {"name": "ELK-BLEDOM 8E", "address": "BE:68:46:09:19:00"},
        "strips": [
            {"role": "primary", "name": "ELK-BLEDOM 8E", "address": "BE:68:46:09:19:00", "connected": True},
            {"role": "extra", "name": "ELK-BLEDOM CE", "address": "BE:68:3D:0C:5C:03", "connected": False},
        ],
    }

    report = build_diagnostics_report(snapshot, [], include_crashes=False)

    assert "Strips" in report
    assert "Main: ELK-BLEDOM 8E (BE:68:46:09:19:00) — connected" in report
    assert "Extra: ELK-BLEDOM CE (BE:68:3D:0C:5C:03) — unavailable" in report


def test_report_omits_the_strips_block_for_a_single_strip() -> None:
    localization_manager.set_language("en")
    snapshot = {
        "connected": True,
        "device": {"name": "ELK-BLEDOM 8E", "address": "BE:68:46:09:19:00"},
        "strips": [
            {"role": "primary", "name": "ELK-BLEDOM 8E", "address": "BE:68:46:09:19:00", "connected": True}
        ],
    }

    report = build_diagnostics_report(snapshot, [], include_crashes=False)

    assert "Strips" not in report  # already covered by the device section


def test_recent_crash_logs_skip_empty_and_stale_files(tmp_path, monkeypatch) -> None:
    """An old fatal dump must not resurface in every report: empty logs and
    logs past the retention window are excluded, fresh ones stay."""
    monkeypatch.setattr(diagnostics, "CRASH_LOG_DIR", tmp_path)

    fresh = tmp_path / "20260718-120000-unhandled.log"
    fresh.write_text("Traceback: recent crash", encoding="utf-8")

    stale = tmp_path / "20250101-000000-fatal.log"
    stale.write_text("Fatal Python error: ancient dump", encoding="utf-8")
    old = time.time() - 60 * 60 * 24 * 30  # 30 days — past the 14-day window
    os.utime(stale, (old, old))

    empty_fatal = tmp_path / "fatal-crashes.log"  # freshly rotated → empty
    empty_fatal.write_text("", encoding="utf-8")

    excerpts = _read_recent_crash_logs()

    assert len(excerpts) == 1
    assert excerpts[0].startswith(fresh.name)
    assert "ancient dump" not in "\n".join(excerpts)


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


def test_diagnostics_report_explains_the_last_disconnect() -> None:
    # The reason plus how long the link lasted is what separates "out of range"
    # from "flapping every few seconds" when reading a user's report.
    localization_manager.set_language("en")
    report = build_diagnostics_report(
        {
            "connected": False,
            "device": {"name": "Desk strip", "address": "AA:BB"},
            "driver": {"id": "bledom", "name": "BLEDOM"},
            "write": {},
            "commands": {},
            "history": {"last_disconnect_reason": "out_of_range", "last_session_seconds": 7.4},
        },
        [],
        include_crashes=False,
    )
    assert "Last disconnect" in report
    assert "out of range" in report
    assert "(7s)" in report


def test_diagnostics_report_omits_disconnect_line_when_never_dropped() -> None:
    localization_manager.set_language("en")
    report = build_diagnostics_report(
        {
            "connected": True,
            "device": {"name": "Desk strip", "address": "AA:BB"},
            "driver": {"id": "bledom", "name": "BLEDOM"},
            "write": {},
            "commands": {},
            "history": {},
        },
        [],
        include_crashes=False,
    )
    assert "Last disconnect" not in report


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

    assert "Версия: 0.3.6" in report
    assert "Устройство" in report
    assert "Подключено: да" in report
    assert "Поддерживаемые команды" in report
    assert "Последняя команда: Установлен цвет RGB(1, 2, 3)" in report
    assert "- команда: Установлен цвет RGB(1, 2, 3)" in report
    assert "Session logs" not in report
    assert "Connected: yes" not in report


def test_diagnostics_report_includes_motion_mode_and_resolved_state(preserve_motion_policy) -> None:
    from app.motion_policy import motion_policy

    localization_manager.set_language("en")
    motion_policy.set_provider(None)
    motion_policy.set_mode("reduced")

    report = build_diagnostics_report(
        {"connected": False, "device": {}},
        [],
        include_crashes=False,
    )

    # The report states the chosen mode and the resolved reduced flag without
    # probing the OS provider a second time (it reflects motion_policy state).
    assert "Motion mode: reduced" in report
    assert "Motion reduced: yes" in report
