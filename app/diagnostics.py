from __future__ import annotations

import platform
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.app_info import APP_AUTHOR, APP_NAME, APP_VERSION
from app.crash_logging import CRASH_LOG_DIR
from app.localization import localization_manager


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
    if not CRASH_LOG_DIR.exists():
        return []
    logs = sorted(CRASH_LOG_DIR.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]
    excerpts: list[str] = []
    for path in logs:
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


def build_diagnostics_report(
    snapshot: dict[str, Any],
    session_logs: Iterable[str],
    *,
    include_crashes: bool = True,
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

    last_error = sanitize_report_text(localization_manager.normalize_error_message(str(history.get("last_error", ""))))
    has_ble_summary = bool(last_command) or bool(last_error.strip())
    if has_ble_summary:
        sections.extend(["", _t("ble_summary_section")])
        if last_command:
            sections.append(_line_key("last_command", _history_status_value(last_command, "description")))
            if _has_value(last_command.get("payload")):
                sections.append(_line_key("last_payload", _history_value(last_command, "payload")))
            if _has_value(last_command.get("targets")):
                sections.append(_line_key("last_targets", _history_value(last_command, "targets")))
        if last_error.strip():
            sections.append(_line_key("last_error", last_error))

    if history_lines:
        sections.extend(["", _t("recent_ble_history_section"), *history_lines])

    sections.extend(["", _t("session_logs_section"), *(log_lines[-80:] if log_lines else ["-"])])

    if include_crashes:
        crashes = _read_recent_crash_logs()
        if crashes:
            sections.extend(["", _t("recent_crash_logs_section"), *crashes])

    return "\n".join(sections).strip() + "\n"
