from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppRule:
    """Maps a foreground app to a scene: when a process whose name contains
    ``app`` is in focus, the strip switches to scene preset ``scene``."""

    app: str
    scene: str


def normalize_process_name(name: str) -> str:
    return str(name).strip().lower()


def match_rule(process_name: str, rules) -> AppRule | None:
    """Return the first rule whose ``app`` fragment is contained in the given
    foreground process name (case-insensitive). Pure, so it's unit-testable.

    e.g. a rule ``app="chrome"`` matches the process ``"chrome.exe"``.
    """
    process = normalize_process_name(process_name)
    if not process:
        return None
    for rule in rules:
        fragment = normalize_process_name(rule.app)
        if fragment and fragment in process:
            return rule
    return None
