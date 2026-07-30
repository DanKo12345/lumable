"""The automations screen, stood up without an engine behind it.

Shared by the screen's own tests and by the rule editor's, deliberately: both are
looking at the same screen, and a second fake facade would drift from this one until
one of the two suites was quietly testing a contract the app does not have.

Not a test module — the name keeps pytest from collecting it. The ``screen`` fixture
that assembles all of this lives in conftest.py, so neither test file has to import
a fixture (which reads to every linter as a redefinition).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.automation.controller import PAUSE_ACTIVE, PAUSE_OFF
from app.automation.rules import ALL_DAYS, validate_rule, with_enabled
from app.automation.windows_tasks import TaskSyncResult
from app.localization import localization_manager
from app.widgets import GlassCard, LiquidButton


def make_rule(**overrides: object):
    """A valid rule, daily at 21:00, switching the light on. Override any field."""
    data = {
        "id": "rule-1",
        "name": "",
        "trigger": {"kind": "time", "time_at": "21:00", "days": list(ALL_DAYS)},
        "action": {"type": "set_power", "power": True, "target": "primary"},
    }
    data.update(overrides)
    rule = validate_rule(data)
    assert rule is not None
    return rule


class FakeAutomations(QObject):
    """The facade as a screen sees it. Every call is recorded."""

    changed = Signal()
    tasks_synced = Signal(object)
    tasks_sync_started = Signal()
    handoff_started = Signal()
    handoff_finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.enabled = True
        self.running = True
        self.status = PAUSE_OFF
        self.ends_at: datetime | None = None
        self.stored_rules: list = []
        # Newest first, as the facade hands them over.
        self.entries: list = []
        self.task_result: TaskSyncResult | None = None
        self.syncing = False
        self.bridge = False
        self.handoff_running = False
        self.writes_land = True
        self.calls: list[tuple] = []

    # ── what the screen reads ──
    def is_enabled(self) -> bool:
        return self.enabled

    def is_running(self) -> bool:
        return self.running

    def rules(self) -> list:
        return list(self.stored_rules)

    def rule(self, rule_id: str):
        return next((rule for rule in self.stored_rules if rule.id == str(rule_id)), None)

    def journal(self, limit: int = 100) -> list:
        self.calls.append(("journal", int(limit)))
        return list(self.entries[: int(limit)])

    def pause_status(self) -> str:
        return self.status

    def paused_until(self) -> datetime | None:
        return self.ends_at

    def last_task_result(self):
        return self.task_result

    def tasks_syncing(self) -> bool:
        return self.syncing

    def bridge_active(self) -> bool:
        return self.bridge

    def handoff_in_progress(self) -> bool:
        return self.handoff_running

    # ── what the screen asks for ──
    def set_enabled(self, enabled: bool) -> bool:
        self.calls.append(("set_enabled", enabled))
        if not self.writes_land:
            return False
        self.enabled = enabled
        self.changed.emit()
        return True

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        self.calls.append(("set_rule_enabled", rule_id, enabled))
        if not self.writes_land:
            return False
        self.stored_rules = [
            with_enabled(rule, enabled) if rule.id == rule_id else rule
            for rule in self.stored_rules
        ]
        self.changed.emit()
        return True

    def save_rule(self, data: dict):
        """Stores through the real schema, so a form the schema refuses fails here."""
        self.calls.append(("save_rule", dict(data)))
        if not self.writes_land:
            return None
        rule = validate_rule(data)
        if rule is None:
            return None
        self.stored_rules = [existing for existing in self.stored_rules if existing.id != rule.id]
        self.stored_rules.append(rule)
        self.changed.emit()
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        self.calls.append(("delete_rule", str(rule_id)))
        if not self.writes_land:
            return False
        self.stored_rules = [rule for rule in self.stored_rules if rule.id != str(rule_id)]
        self.changed.emit()
        return True

    def pause(self, seconds: int = 3600) -> bool:
        self.calls.append(("pause", seconds))
        self.status = PAUSE_ACTIVE
        self.ends_at = datetime.now() + timedelta(seconds=seconds)
        return True

    def resume(self) -> bool:
        self.calls.append(("resume",))
        self.status = PAUSE_OFF
        self.ends_at = None
        return True

    def complete_handoff(self) -> bool:
        self.calls.append(("complete_handoff",))
        self.handoff_running = True
        self.handoff_started.emit()
        return True


class Host(QWidget):
    """The least a window has to be for this screen to build."""

    def __init__(self) -> None:
        super().__init__()
        self._ui_scale = 1.0
        self._control_height = 38
        self._chip_height = 34
        self._theme_tokens: dict[str, str] = {}
        self._is_dark = True
        self._settings: dict = {}
        self._nav_buttons: dict = {}
        self._automations = FakeAutomations()
        self.logged: list[str] = []
        self._column = QVBoxLayout(self)

    def _sz(self, value: float) -> int:
        return max(1, round(value))

    def _tr(self, key: str, **kwargs: object) -> str:
        return localization_manager.t(key, **kwargs)

    def _card(self, title: str, subtitle: str | None = None, icon: str | None = None) -> GlassCard:
        return GlassCard(title, subtitle, icon=icon)

    def _button(self, text: str, role: str) -> LiquidButton:
        return LiquidButton(text, role)

    def _log(self, message: str) -> None:
        self.logged.append(message)
