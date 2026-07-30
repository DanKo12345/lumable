"""The ``rule.v1`` schema and its validation.

A rule is "when <trigger> then <action>". Actions are tagged rather than a bare
scene id because the two kinds are not interchangeable: the old schedule only
ever switched power on and off, so migrating it to "apply scene" would silently
change the user's colour and brightness at 21:00.

Validation follows the same contract as ``app.storage``: never raise on bad
input, coerce what can be coerced, drop what cannot. Settings files are edited by
hand and survive downgrades, so a single bad rule must not cost the user the
rest of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

SCHEMA_VERSION = "rule.v1"

# A rule id ends up on a command line (``--run-rule <id>``) and inside a Windows
# task name, so it is restricted at the door rather than escaped at each use.
_RULE_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")

# ── triggers ──────────────────────────────────────────────────────────────
TRIGGER_TIME = "time"  # edge: fires when the clock crosses a time on a listed day
TRIGGER_APP_FOREGROUND = "app_foreground"  # stateful: that app is in front
TRIGGER_NO_INPUT = "no_input"  # stateful: no keyboard/mouse input for N minutes
TRIGGER_LUMABLE_START = "lumable_start"  # edge: the app launched
TRIGGER_STRIP_CONNECTED = "strip_connected"  # edge: the main strip connected
TRIGGER_ALWAYS = "always"  # stateful: always true — the App Trigger fallback

TRIGGER_KINDS = (
    TRIGGER_TIME,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_NO_INPUT,
    TRIGGER_LUMABLE_START,
    TRIGGER_STRIP_CONNECTED,
    TRIGGER_ALWAYS,
)

# Stateful triggers describe a situation that lasts, so the resolver keeps
# choosing a winner among them; the rest happen once and are dispatched on the
# spot. Mixing the two was the flaw in the on_exit design: leaving app A and
# entering app B would have applied A's exit scene before B's scene.
STATEFUL_TRIGGERS = (TRIGGER_APP_FOREGROUND, TRIGGER_NO_INPUT, TRIGGER_ALWAYS)
EDGE_TRIGGERS = (TRIGGER_TIME, TRIGGER_LUMABLE_START, TRIGGER_STRIP_CONNECTED)

# ── actions ───────────────────────────────────────────────────────────────
ACTION_APPLY_SCENE = "apply_scene"
ACTION_SET_POWER = "set_power"
ACTION_TYPES = (ACTION_APPLY_SCENE, ACTION_SET_POWER)

# ── execution ─────────────────────────────────────────────────────────────
EXECUTION_RUNTIME = "runtime"  # only while LumaBLE is running
EXECUTION_BACKGROUND = "background"  # compiled into a Windows task, runs headless
EXECUTION_MODES = (EXECUTION_RUNTIME, EXECUTION_BACKGROUND)

# In 0.3.6 a power action always addresses the main strip, exactly as the old
# schedule did. Stated in the schema rather than left to each executor, so the
# runtime path cannot quietly start mirroring to extra strips while the headless
# one still switches only the primary.
TARGET_PRIMARY = "primary"
ACTION_TARGETS = (TARGET_PRIMARY,)

# ── provenance ────────────────────────────────────────────────────────────
# Where a rule came from. A rule the user wrote and one the migration derived from
# the 0.3.5 schedule are not interchangeable: the migrated one has an old executor
# still standing behind it, it must not be given a Windows task of its own while
# that bridge is up, and a second migration has to recognise it rather than make
# another. ``origin_ref`` says *which* one — the profile, or the app fragment.
ORIGIN_MANUAL = ""  # authored in the app
ORIGIN_LEGACY_SCHEDULE = "legacy_schedule"
ORIGIN_PROFILE_SCHEDULE = "profile_schedule"
ORIGIN_APP_TRIGGER = "app_trigger"
ORIGIN_APP_TRIGGER_DEFAULT = "app_trigger_default"

ORIGINS = (
    ORIGIN_MANUAL,
    ORIGIN_LEGACY_SCHEDULE,
    ORIGIN_PROFILE_SCHEDULE,
    ORIGIN_APP_TRIGGER,
    ORIGIN_APP_TRIGGER_DEFAULT,
)

MAX_PRIORITY = 100
# A name is a label, not a document. Stated as a constant because an editor has to
# stop the user at the same length the schema stores: typed past it and truncated
# here, they would name a rule one thing and be shown another after saving.
MAX_NAME_LENGTH = 80
MAX_COOLDOWN_SECONDS = 24 * 60 * 60
MAX_NO_INPUT_MINUTES = 24 * 60
DEFAULT_NO_INPUT_MINUTES = 10

ALL_DAYS = (0, 1, 2, 3, 4, 5, 6)

# Emitted through the optional `warnings` collector so a caller can surface what
# was quietly changed instead of the user wondering why a rule behaves oddly.
WARN_BACKGROUND_DOWNGRADED = "background_downgraded"
WARN_NO_DAYS = "no_days_selected"


def _clamp_int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _coerce_bool(value: Any, fallback: bool) -> bool:
    parsed = _parse_bool(value)
    return fallback if parsed is None else parsed


def _parse_bool(value: Any) -> bool | None:
    """Strict: None when the value is not recognisably a boolean.

    Used for the power command, where guessing is not acceptable — a corrupt
    ``"power": "banana"`` must not turn the lights on by itself.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return None


def _coerce_time_text(value: Any) -> str | None:
    """"21:5" -> "21:05"; anything that is not a real time of day -> None."""
    text = str(value or "").strip()
    if ":" not in text:
        return None
    hours, _, minutes = text.partition(":")
    try:
        hour = int(hours)
        minute = int(minutes)
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _coerce_days(value: Any) -> tuple[int, ...]:
    """Weekdays as Monday=0 … Sunday=6.

    An empty result means *no* days, never "every day". The old schedule stored
    an empty list for "switched off by weekday", so treating it as a shorthand
    for daily would turn a disabled schedule into one that fires every morning
    the moment it is migrated. "Every day" is spelled out as all seven.
    """
    if not isinstance(value, (list, tuple, set)):
        return ()
    days: set[int] = set()
    for item in value:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            days.add(day)
    return tuple(sorted(days))


@dataclass(frozen=True)
class Trigger:
    kind: str
    time_at: str = ""  # TRIGGER_TIME, "HH:MM"
    days: tuple[int, ...] = ()  # TRIGGER_TIME; empty = no days, never "daily"
    app: str = ""  # TRIGGER_APP_FOREGROUND, matched as a substring
    minutes: int = DEFAULT_NO_INPUT_MINUTES  # TRIGGER_NO_INPUT

    @property
    def is_stateful(self) -> bool:
        return self.kind in STATEFUL_TRIGGERS


@dataclass(frozen=True)
class Action:
    type: str
    scene_id: str = ""  # ACTION_APPLY_SCENE
    power: bool = False  # ACTION_SET_POWER
    target: str = TARGET_PRIMARY


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    trigger: Trigger
    action: Action
    execution: str = EXECUTION_RUNTIME
    priority: int = 0
    cooldown_seconds: int = 0
    enabled: bool = True
    # Where this rule came from; see the ORIGIN_* constants.
    origin: str = ORIGIN_MANUAL
    origin_ref: str = ""

    @property
    def runs_in_background(self) -> bool:
        return self.execution == EXECUTION_BACKGROUND

    @property
    def is_migrated(self) -> bool:
        return self.origin != ORIGIN_MANUAL


def _validate_trigger(data: Any, warnings: list[str] | None, rule_id: str) -> Trigger | None:
    if not isinstance(data, dict):
        return None
    kind = str(data.get("kind", "")).strip()
    if kind not in TRIGGER_KINDS:
        return None
    if kind == TRIGGER_TIME:
        time_at = _coerce_time_text(data.get("time_at"))
        if time_at is None:
            return None  # a time rule without a time can never fire
        # An absent key means daily; an explicit list is taken at face value,
        # including an empty one — see _coerce_days.
        days = _coerce_days(data.get("days")) if "days" in data else ALL_DAYS
        if not days:
            _warn(warnings, WARN_NO_DAYS, rule_id)
        return Trigger(kind=kind, time_at=time_at, days=days)
    if kind == TRIGGER_APP_FOREGROUND:
        app = str(data.get("app", "")).strip().lower()
        if not app:
            return None  # would match every process
        return Trigger(kind=kind, app=app)
    if kind == TRIGGER_NO_INPUT:
        minutes = _clamp_int(
            data.get("minutes"), 1, MAX_NO_INPUT_MINUTES, DEFAULT_NO_INPUT_MINUTES
        )
        return Trigger(kind=kind, minutes=minutes)
    return Trigger(kind=kind)


def _warn(warnings: list[str] | None, code: str, rule_id: str) -> None:
    if warnings is not None:
        warnings.append(f"{code}:{rule_id}")


def _validate_action(data: Any) -> Action | None:
    if not isinstance(data, dict):
        return None
    action_type = str(data.get("type", "")).strip()
    target = str(data.get("target", TARGET_PRIMARY)).strip() or TARGET_PRIMARY
    if action_type == ACTION_APPLY_SCENE:
        scene_id = str(data.get("scene_id", "")).strip()
        if not scene_id:
            return None
        if "target" in data:
            # A scene already carries its own target, which may well be a group.
            # Letting a rule state one too would look like it scoped the scene
            # while silently doing nothing — or worse, overriding the group.
            return None
        return Action(type=action_type, scene_id=scene_id, target="")
    if action_type == ACTION_SET_POWER:
        if target not in ACTION_TARGETS:
            return None
        power = _parse_bool(data.get("power"))
        if power is None:
            # Refused rather than defaulted: guessing "on" from a corrupt value
            # would switch the user's lights on at a time they never asked for.
            return None
        return Action(type=action_type, power=power, target=target)
    return None


def _validate_execution(value: Any, trigger: Trigger, action: Action) -> str:
    """Background execution is only honoured where it can actually work.

    A background rule becomes a Windows task that starts LumaBLE headless, and
    in 0.3.6 that path can only switch power on a schedule. Anything else is
    downgraded to runtime rather than dropped: the user keeps the rule and it
    still works whenever the app is open.
    """
    mode = str(value or EXECUTION_RUNTIME).strip()
    if mode not in EXECUTION_MODES:
        return EXECUTION_RUNTIME
    if mode == EXECUTION_BACKGROUND:
        if trigger.kind != TRIGGER_TIME or action.type != ACTION_SET_POWER:
            return EXECUTION_RUNTIME
    return mode


def validate_rule(data: Any, warnings: list[str] | None = None) -> Rule | None:
    """One rule, or None when it could never do anything useful.

    Pass ``warnings`` to collect what was silently adjusted (see the WARN_*
    codes); the caller can then tell the user instead of leaving them to wonder.
    """
    if not isinstance(data, dict):
        return None
    rule_id = str(data.get("id", "")).strip()
    if not _RULE_ID_RE.fullmatch(rule_id):
        return None
    trigger = _validate_trigger(data.get("trigger"), warnings, rule_id)
    action = _validate_action(data.get("action"))
    if trigger is None or action is None:
        return None
    execution = _validate_execution(data.get("execution"), trigger, action)
    if execution != data.get("execution") and str(data.get("execution", "")) == EXECUTION_BACKGROUND:
        _warn(warnings, WARN_BACKGROUND_DOWNGRADED, rule_id)
    origin = str(data.get("origin", ORIGIN_MANUAL)).strip()
    return Rule(
        id=rule_id,
        name=str(data.get("name", "")).strip()[:MAX_NAME_LENGTH],
        trigger=trigger,
        action=action,
        execution=execution,
        priority=_clamp_int(data.get("priority"), -MAX_PRIORITY, MAX_PRIORITY, 0),
        cooldown_seconds=_clamp_int(data.get("cooldown_seconds"), 0, MAX_COOLDOWN_SECONDS, 0),
        enabled=_coerce_bool(data.get("enabled"), True),
        # An unknown origin becomes "authored here". Claiming a provenance we do not
        # recognise would be worse than claiming none: the bridge rules are excluded
        # from Windows tasks by exactly this field.
        origin=origin if origin in ORIGINS else ORIGIN_MANUAL,
        origin_ref=str(data.get("origin_ref", "")).strip()[:64],
    )


def validate_rules(data: Any, warnings: list[str] | None = None) -> list[Rule]:
    """Every valid rule, with duplicate ids dropped.

    Duplicate ids would make the background task per rule ambiguous and the
    journal unreadable, so the first one wins.
    """
    if not isinstance(data, list):
        return []
    rules: list[Rule] = []
    seen: set[str] = set()
    for entry in data:
        rule = validate_rule(entry, warnings)
        if rule is None or rule.id in seen:
            continue
        seen.add(rule.id)
        rules.append(rule)
    return rules


def rule_to_dict(rule: Rule) -> dict[str, Any]:
    """Serialise for settings.json. Only the fields the trigger/action actually
    uses are written, so a stored rule reads the way it was authored."""
    trigger: dict[str, Any] = {"kind": rule.trigger.kind}
    if rule.trigger.kind == TRIGGER_TIME:
        trigger["time_at"] = rule.trigger.time_at
        trigger["days"] = list(rule.trigger.days)
    elif rule.trigger.kind == TRIGGER_APP_FOREGROUND:
        trigger["app"] = rule.trigger.app
    elif rule.trigger.kind == TRIGGER_NO_INPUT:
        trigger["minutes"] = rule.trigger.minutes

    action: dict[str, Any] = {"type": rule.action.type}
    if rule.action.type == ACTION_APPLY_SCENE:
        action["scene_id"] = rule.action.scene_id  # the scene owns its own target
    else:
        action["power"] = rule.action.power
        action["target"] = rule.action.target

    stored: dict[str, Any] = {
        "id": rule.id,
        "name": rule.name,
        "trigger": trigger,
        "action": action,
        "execution": rule.execution,
        "priority": rule.priority,
        "cooldown_seconds": rule.cooldown_seconds,
        "enabled": rule.enabled,
    }
    if rule.origin != ORIGIN_MANUAL:
        # Only written when there is something to say, so a hand-authored rule
        # reads the way it was authored.
        stored["origin"] = rule.origin
        if rule.origin_ref:
            stored["origin_ref"] = rule.origin_ref
    return stored


def with_enabled(rule: Rule, enabled: bool) -> Rule:
    return replace(rule, enabled=bool(enabled))
