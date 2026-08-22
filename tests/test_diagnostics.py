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
        "device": {"name": "Main demo strip", "address": "AA:BB:CC:DD:EE:01"},
        "strips": [
            {"role": "primary", "name": "Main demo strip", "address": "AA:BB:CC:DD:EE:01", "connected": True},
            {"role": "extra", "name": "Extra demo strip", "address": "AA:BB:CC:DD:EE:02", "connected": False},
        ],
    }

    report = build_diagnostics_report(snapshot, [], include_crashes=False)

    assert "Strips" in report
    assert "Main: Main demo strip (AA:BB:CC:DD:EE:01) — connected" in report
    assert "Extra: Extra demo strip (AA:BB:CC:DD:EE:02) — unavailable" in report


def test_report_omits_the_strips_block_for_a_single_strip() -> None:
    localization_manager.set_language("en")
    snapshot = {
        "connected": True,
        "device": {"name": "Main demo strip", "address": "AA:BB:CC:DD:EE:01"},
        "strips": [
            {"role": "primary", "name": "Main demo strip", "address": "AA:BB:CC:DD:EE:01", "connected": True}
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

    assert "Версия: 0.4.1" in report
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


# ── the combined mode ─────────────────────────────────────────────────
def _fusion_stats(**overrides) -> dict:
    stats = {
        "running": True,
        "mode": "screen_music",
        "errors": 0,
        "last_error": "",
        "frame_reason": "composed",
        "strip_brightness": "50%",
        "brightness_factor": 0.65,
        "music_activity": 0.8,
        "music_stale": False,
        "dropped_screen_samples": 0,
        "dropped_music_samples": 0,
    }
    stats.update(overrides)
    return stats


def test_the_two_brightnesses_are_reported_apart() -> None:
    """The strip keeps the level a person set and Fusion scales the colour
    underneath it. At 50% hardware and a 0.65 factor the wall shows about a
    third of full — one number standing for both makes every "too dim" report
    impossible to answer."""
    report = build_diagnostics_report({}, [], include_crashes=False, fusion=_fusion_stats())

    assert "strip brightness: 50%" in report
    assert "fusion brightness factor: 0.65" in report
    # And no line that merges them into one figure.
    assert "brightness: 0.65" not in report


def test_a_mode_that_is_not_running_says_nothing() -> None:
    """A report from someone who never used it should not carry a block of
    zeroes for them to read past."""
    report = build_diagnostics_report(
        {}, [], include_crashes=False, fusion=_fusion_stats(running=False)
    )

    assert "Fusion" not in report


def test_refused_samples_are_shown_when_there_are_any() -> None:
    """A rising count is the signature of a source restarting underneath."""
    quiet = build_diagnostics_report({}, [], include_crashes=False, fusion=_fusion_stats())
    noisy = build_diagnostics_report(
        {}, [], include_crashes=False, fusion=_fusion_stats(dropped_music_samples=12)
    )

    assert "refused samples" not in quiet
    assert "refused samples: 0 screen, 12 music" in noisy


def test_why_nothing_was_sent_is_in_the_report() -> None:
    report = build_diagnostics_report(
        {}, [], include_crashes=False, fusion=_fusion_stats(frame_reason="base_stale")
    )

    assert "last frame: base_stale" in report


def test_a_stream_error_goes_through_the_same_scrubbing() -> None:
    """Which means the home path, and only that — the strip's own address is
    the user's own and is already elsewhere in the report. What must not travel
    is the name of the person whose folder the app is installed in."""
    from pathlib import Path

    home = str(Path.home())
    report = build_diagnostics_report(
        {},
        [],
        include_crashes=False,
        fusion=_fusion_stats(errors=3, last_error="write failed from " + home + "/logs"),
    )

    assert "stream errors: 3" in report
    assert home not in report
    assert "~" in report


def test_the_screen_block_stops_reporting_writes_it_no_longer_makes() -> None:
    """While Fusion owns the output the capture is still Screen Sync's and its
    frames are still counted, but the commands are not — and zeros there would
    describe a run that plainly lit the strip as having sent nothing."""
    from app.live_sync_metrics import LiveSyncMetrics

    metrics = LiveSyncMetrics()
    token = metrics.start(100.0)
    for index in range(1, 31):
        at = 100.0 + index / 30.0
        metrics.frame_captured(token, at)
        metrics.frame_processed(token, at, frame_ms=4.0)
    report = metrics.report(101.0)

    alone = build_diagnostics_report(
        {}, [], include_crashes=False,
        ambient={"running": True, "live_sync": report, "link_owned_by_fusion": False},
    )
    borrowed = build_diagnostics_report(
        {}, [], include_crashes=False,
        ambient={"running": True, "live_sync": report, "link_owned_by_fusion": True},
    )

    assert "link rejections:" in alone
    assert "link rejections:" not in borrowed
    assert "written by Fusion" in borrowed
    assert "frames:" in borrowed, "the frames stopped being reported too"


def test_the_beat_delay_says_what_it_does_not_include() -> None:
    """A figure called "latency" next to a beat will be read as the delay a
    person hears. It is not: it starts when the audio block was handed over and
    ends when the command was accepted, and three unmeasured stages sit outside
    it. Saying so is part of the number."""
    report = build_diagnostics_report(
        {}, [], include_crashes=False, fusion=_fusion_stats(beat_delay=(48.0, 91.0, 37))
    )

    assert "beat -> command accepted (software): 48.0 ms p50, 91.0 ms p95, 37 beats" in report
    assert "excludes audio device buffering, BLE transport" in report


def test_no_beat_delay_line_before_any_beat_has_been_carried() -> None:
    """Zeros would read as an instant response rather than as no measurement."""
    report = build_diagnostics_report(
        {}, [], include_crashes=False, fusion=_fusion_stats(beat_delay=(0.0, 0.0, 0))
    )

    assert "beat -> command accepted" not in report


def test_a_preview_run_says_not_applicable_instead_of_zeroes() -> None:
    """Every command figure describes a radio this run did not have.

    Zeroes in their place read as a link that was never busy, never failed and
    answered instantly — a flawless connection, invented by omission. The
    absence has to be stated, because a reader comparing two reports will
    otherwise conclude the preview had the better link.
    """
    report = build_diagnostics_report(
        {}, [], include_crashes=False,
        fusion=_fusion_stats(previewing=True, beat_delay=(0.0, 0.0, 0)),
    )

    assert "output: preview only — nothing was sent to a strip" in report
    assert "beat -> command accepted (software): not applicable (preview)" in report
    assert "commands: not applicable (preview)" in report
    assert "link rejections: not applicable (preview)" in report
    assert "submitted" not in report, "a preview reported commands it never sent"


def test_a_preview_never_reports_a_delay_even_if_one_was_recorded() -> None:
    """Belt and braces: the coordinator does not record them, and if a future
    change ever let one through, the report still refuses to print it as a
    measurement of a link."""
    report = build_diagnostics_report(
        {}, [], include_crashes=False,
        fusion=_fusion_stats(previewing=True, beat_delay=(48.0, 91.0, 37)),
    )

    assert "48.0 ms p50" not in report
    assert "not applicable (preview)" in report


def test_a_live_run_still_reports_its_commands() -> None:
    """The other half of the same switch: nothing was taken away from a run that
    did have a strip."""
    report = build_diagnostics_report(
        {}, [], include_crashes=False,
        fusion=_fusion_stats(beat_delay=(48.0, 91.0, 37), commands_submitted=12),
    )

    assert "output: strip" in report
    assert "12 submitted" in report
    assert "48.0 ms p50" in report
