from __future__ import annotations

import platform
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.app_info import APP_AUTHOR, APP_NAME, APP_VERSION
from app.constants import CRASH_LOG_MAX_AGE_DAYS
from app.crash_logging import CRASH_LOG_DIR
from app.localization import localization_manager
from app.motion_policy import motion_policy


def _line(label: str, value: object) -> str:
    text = str(value).strip() if value is not None else ""
    return f"{label}: {text or '-'}"


def _t(key: str, **kwargs: object) -> str:
    return localization_manager.t(f"diagnostics.report.{key}", **kwargs)


def _line_key(key: str, value: object) -> str:
    return _line(_t(key), value)


def _yes_no(value: object) -> str:
    return _t("yes") if value else _t("no")


def _has_value(value: object) -> bool:
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(str(value).strip()) if value is not None else False


def _joined(values: Iterable[object]) -> str:
    items = [str(value).strip() for value in values if str(value).strip()]
    return ", ".join(items) if items else "-"


def _history_value(item: dict[str, Any], key: str) -> str:
    return sanitize_report_text(str(item.get(key, "")).strip()) or "-"


def _history_status_value(item: dict[str, Any], key: str) -> str:
    raw = str(item.get(key, "")).strip()
    if not raw:
        return "-"
    return sanitize_report_text(localization_manager.normalize_status_message(raw)) or "-"


def _history_error_value(item: dict[str, Any], key: str) -> str:
    raw = str(item.get(key, "")).strip()
    if not raw:
        return "-"
    return sanitize_report_text(localization_manager.normalize_error_message(raw)) or "-"


def _format_history_item(item: dict[str, Any]) -> str:
    event = str(item.get("event", "")).strip()
    if event == "command":
        return (
            f"- {_t('history_command')}: {_history_status_value(item, 'description')} | "
            f"{_t('payload')} {_history_value(item, 'payload')} | "
            f"{_t('targets')} {_history_value(item, 'targets')}"
        )
    if event == "retry":
        return (
            f"- {_t('history_retry')} {_history_value(item, 'attempt')}/{_history_value(item, 'total')}: "
            f"{_history_value(item, 'uuid')} | {_history_error_value(item, 'error')} | "
            f"{_t('payload')} {_history_value(item, 'payload')}"
        )
    if event == "protocol_mismatch":
        return f"- {_t('history_protocol_mismatch')}: {_history_error_value(item, 'details')}"
    if event == "error":
        return f"- {_t('history_error')}: {_history_error_value(item, 'message')}"
    return f"- {event or _t('history_event')}: {sanitize_report_text(str(item))}"


def _read_recent_crash_logs(limit: int = 3, max_chars: int = 800) -> list[str]:
    """Excerpts of genuinely recent crash logs.

    Empty files and logs older than the crash-log retention window are skipped.
    Without the age gate the report showed whatever files existed — including a
    ``fatal-crashes.log`` whose single persistent name carried dumps from long
    ago (startup rotation now splits it into dated per-session files).
    """
    if not CRASH_LOG_DIR.exists():
        return []
    cutoff = datetime.now() - timedelta(days=CRASH_LOG_MAX_AGE_DAYS)
    candidates: list[tuple[float, Path]] = []
    for path in CRASH_LOG_DIR.glob("*.log"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size == 0:
            continue
        if datetime.fromtimestamp(stat.st_mtime) < cutoff:
            continue
        candidates.append((stat.st_mtime, path))
    candidates.sort(key=lambda item: item[0], reverse=True)
    excerpts: list[str] = []
    for _mtime, path in candidates[:limit]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = sanitize_report_text(text[-max_chars:])
        excerpts.append(f"{path.name}\n{text.strip()}")
    return excerpts


def sanitize_report_text(text: str) -> str:
    home_path = str(Path.home())
    variants = {
        home_path,
        home_path.replace("\\", "/"),
    }
    sanitized = text
    for variant in variants:
        sanitized = sanitized.replace(variant, "~")
    return sanitized


def _ambient_section(ambient: dict[str, Any] | None) -> list[str]:
    if not ambient or not (ambient.get("errors") or ambient.get("running")):
        return []
    lines = [
        "",
        _t("ambient_section"),
        _line_key("ambient_running", _yes_no(ambient.get("running"))),
        _line_key("ambient_errors", int(ambient.get("errors", 0) or 0)),
    ]
    error_text = sanitize_report_text(str(ambient.get("last_error", "") or ""))
    if error_text.strip():
        lines.append(_line_key("ambient_last_error", error_text))
    return lines


def _strips_section(snapshot: dict[str, Any]) -> list[str]:
    """Every strip the app drives, with its role and live state.

    Multi-strip setups were invisible in the report before: it described only
    the active primary, so "the other strip also lit up" or "the extra one is
    gone" had nothing to point at.
    """
    raw = snapshot.get("strips")
    items = [item for item in raw if isinstance(item, dict) and _has_value(item.get("address"))] if isinstance(raw, list) else []
    if len(items) < 2:
        return []  # a single strip is already covered by the device section
    lines: list[str] = ["", _t("strips_section")]
    for item in items:
        role = _t("strip_primary") if item.get("role") == "primary" else _t("strip_extra")
        state = _t("strip_connected") if item.get("connected") else _t("strip_offline")
        name = str(item.get("name") or "").strip() or str(item.get("address"))
        lines.append(f"- {role}: {name} ({item.get('address')}) — {state}")
    return lines


def _nearby_unknown_section(snapshot: dict[str, Any]) -> list[str]:
    raw = snapshot.get("nearby_unknown")
    items = raw if isinstance(raw, list) else []
    if not items:
        return []
    lines = ["", _t("nearby_unknown_section")]
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        name = sanitize_report_text(str(item.get("name", "")).strip()) or "-"
        address = str(item.get("address", "")).strip() or "-"
        services = sanitize_report_text(str(item.get("services", "")).strip()) or "-"
        rssi = str(item.get("rssi", "")).strip() or "-"
        lines.append(f"- {name} ({address}) | {_t('services')} {services} | RSSI {rssi}")
    return lines


def _ble_summary_section(history: dict[str, Any], last_command: dict[str, Any]) -> list[str]:
    last_error = sanitize_report_text(localization_manager.normalize_error_message(str(history.get("last_error", ""))))
    disconnect_reason = str(history.get("last_disconnect_reason", "") or "")
    session_seconds = history.get("last_session_seconds")
    if not (last_command or last_error.strip() or disconnect_reason):
        return []

    lines = ["", _t("ble_summary_section")]
    if last_command:
        lines.append(_line_key("last_command", _history_status_value(last_command, "description")))
        if _has_value(last_command.get("payload")):
            lines.append(_line_key("last_payload", _history_value(last_command, "payload")))
        if _has_value(last_command.get("targets")):
            lines.append(_line_key("last_targets", _history_value(last_command, "targets")))
    if last_error.strip():
        lines.append(_line_key("last_error", last_error))
    if disconnect_reason:
        # Why the last link ended, plus how long it had lasted — the pair is what
        # distinguishes "out of range" from "flapping every few seconds".
        reason_text = localization_manager.t(f"ble.reason_{disconnect_reason}")
        if isinstance(session_seconds, (int, float)) and session_seconds >= 0:
            reason_text = f"{reason_text} ({int(session_seconds)}s)"
        lines.append(_line_key("last_disconnect", reason_text))
    return lines


def build_diagnostics_report(
    snapshot: dict[str, Any],
    session_logs: Iterable[str],
    *,
    include_crashes: bool = True,
    ambient: dict[str, Any] | None = None,
) -> str:
    device = snapshot.get("device") or {}
    driver = snapshot.get("driver") or {}
    write = snapshot.get("write") or {}
    commands = snapshot.get("commands") or {}
    history = snapshot.get("history") or {}
    last_command = history.get("last_command") if isinstance(history.get("last_command"), dict) else {}
    history_events = history.get("events") if isinstance(history.get("events"), list) else []

    has_driver = any(_has_value(driver.get(key)) for key in ("id", "name", "transport", "notes"))
    has_write = any(_has_value(write.get(key)) for key in ("selected_uuid", "selected_properties", "candidates"))
    has_commands = has_driver or any(
        bool(commands.get(key)) for key in ("power", "color", "brightness", "effects", "speed")
    )
    command_lines = []
    if has_commands:
        command_lines = [
            _line_key("power", _yes_no(commands.get("power"))),
            _line_key("color", _yes_no(commands.get("color"))),
            _line_key("brightness", _yes_no(commands.get("brightness"))),
            _line_key("effects", commands.get("effects") or _t("no")),
            _line_key("speed", _yes_no(commands.get("speed"))),
        ]
    candidate_lines = [
        f"- {item.get('uuid', '-')} ({_joined(item.get('properties', []))})"
        for item in write.get("candidates", [])
    ]
    log_lines = [
        sanitize_report_text(localization_manager.normalize_status_message(str(message)))
        for message in session_logs
    ]
    history_lines = [
        _format_history_item(item)
        for item in history_events[-25:]
        if isinstance(item, dict)
    ]

    sections = [
        APP_NAME,
        _line_key("version", APP_VERSION),
        _line_key("author", APP_AUTHOR),
        _line_key("generated", datetime.now().isoformat(timespec="seconds")),
        _line_key("os", platform.platform()),
        _line_key("python", platform.python_version()),
        _line_key("motion_mode", motion_policy.mode),
        _line_key("motion_reduced", _yes_no(motion_policy.reduced)),
        "",
        _t("device_section"),
        _line_key("connected", _yes_no(snapshot.get("connected"))),
    ]
    for label_key, key in (("name", "name"), ("address", "address"), ("rssi", "rssi")):
        if _has_value(device.get(key)):
            sections.append(_line_key(label_key, device.get(key)))

    if has_driver:
        sections.extend(["", _t("driver_section")])
        for label_key, key in (("id", "id"), ("name", "name"), ("transport", "transport"), ("notes", "notes")):
            if _has_value(driver.get(key)):
                sections.append(_line_key(label_key, driver.get(key)))

    if has_write:
        sections.extend(["", _t("write_section")])
        if _has_value(write.get("selected_uuid")):
            sections.append(_line_key("selected", write.get("selected_uuid")))
        if _has_value(write.get("selected_properties")):
            sections.append(_line_key("selected_properties", _joined(write.get("selected_properties", []))))
        if candidate_lines:
            sections.extend([f"{_t('candidates')}:", *candidate_lines])

    if command_lines:
        sections.extend(["", _t("supported_commands_section"), *command_lines])

    sections.extend(_ble_summary_section(history, last_command))

    if history_lines:
        sections.extend(["", _t("recent_ble_history_section"), *history_lines])

    sections.extend(_strips_section(snapshot))
    sections.extend(_ambient_section(ambient))
    sections.extend(_nearby_unknown_section(snapshot))

    sections.extend(["", _t("session_logs_section"), *(log_lines[-80:] if log_lines else ["-"])])

    if include_crashes:
        crashes = _read_recent_crash_logs()
        if crashes:
            sections.extend(["", _t("recent_crash_logs_section"), *crashes])

    return "\n".join(sections).strip() + "\n"
