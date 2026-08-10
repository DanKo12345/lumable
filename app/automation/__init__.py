"""Automation engine: rules, and the resolver that decides which one wins.

Deliberately free of Qt and of any I/O — the engine is fed a snapshot of the
world and returns a decision, so every conflict rule can be tested directly.
"""

from app.automation.resolver import (
    AutomationEngine,
    Decision,
    Outcome,
    Skip,
    Snapshot,
)
from app.automation.rules import (
    ACTION_APPLY_SCENE,
    ACTION_SET_POWER,
    EXECUTION_BACKGROUND,
    EXECUTION_RUNTIME,
    SCHEMA_VERSION,
    TRIGGER_ALWAYS,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_LUMABLE_START,
    TRIGGER_NO_INPUT,
    TRIGGER_STRIP_CONNECTED,
    TRIGGER_TIME,
    TRIGGER_WINDOWS_LOCKED,
    TRIGGER_WINDOWS_SLEEP,
    TRIGGER_WINDOWS_UNLOCKED,
    TRIGGER_WINDOWS_WAKE,
    Action,
    Rule,
    Trigger,
    rule_to_dict,
    validate_rule,
    validate_rules,
)

__all__ = [
    "ACTION_APPLY_SCENE",
    "ACTION_SET_POWER",
    "EXECUTION_BACKGROUND",
    "EXECUTION_RUNTIME",
    "SCHEMA_VERSION",
    "TRIGGER_ALWAYS",
    "TRIGGER_APP_FOREGROUND",
    "TRIGGER_LUMABLE_START",
    "TRIGGER_NO_INPUT",
    "TRIGGER_STRIP_CONNECTED",
    "TRIGGER_TIME",
    "TRIGGER_WINDOWS_LOCKED",
    "TRIGGER_WINDOWS_SLEEP",
    "TRIGGER_WINDOWS_UNLOCKED",
    "TRIGGER_WINDOWS_WAKE",
    "Action",
    "AutomationEngine",
    "Decision",
    "Outcome",
    "Rule",
    "Skip",
    "Snapshot",
    "Trigger",
    "rule_to_dict",
    "validate_rule",
    "validate_rules",
]
