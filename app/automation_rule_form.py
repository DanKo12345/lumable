"""What a rule looks like while it is being edited, and when it may be saved.

Kept apart from both the overlay that draws it and the controller that saves it,
and free of Qt, because the interesting parts here are decisions rather than
widgets: whether this rule may run with the app closed, what is still wrong with
it, what to call it when the user has not said. A form is a plain dict so all of
that can be tested without building a window.

Three rules that are not obvious, each of which would cost the user something:

* **A rule's provenance survives editing.** A migrated schedule rule carries
  ``origin: legacy_schedule``, and that is what keeps the task compiler from
  arming a Windows task for it while the 0.3.5 pair is still doing the waking.
  Editing such a rule and writing it back as "authored here" would give it a
  second executor and switch the light twice.
* **Nothing is silently renumbered.** Priority and cooldown are offered as a few
  sensible choices, but a rule already holding some other value keeps it as its
  own option: a form that quietly rounded 7 to 10 would be editing data the user
  never touched.
* **Background is a capability, not a preference.** In 0.3.6 only a time trigger
  with a power action can run headless, so switching the action of a background
  rule takes the capability away with it. The form says so rather than storing a
  wish the schema will drop on the next read.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from app.automation.controller import (
    ACTION_APPLY_SCENE,
    ACTION_SET_POWER,
    ALL_DAYS,
    TRIGGER_ALWAYS,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_LUMABLE_START,
    TRIGGER_NO_INPUT,
    TRIGGER_STRIP_CONNECTED,
    TRIGGER_TIME,
    Rule,
)

# Execution modes, spelled here so the form does not have to reach for another
# module to name the one thing it decides about them.
EXECUTION_RUNTIME = "runtime"
EXECUTION_BACKGROUND = "background"

# The action a rule performs, as the editor offers it: three choices rather than
# two controls, because "apply a scene" and "switch the light off" are the same
# kind of decision to the person making it.
CHOICE_SCENE = "scene"
CHOICE_POWER_ON = "power_on"
CHOICE_POWER_OFF = "power_off"

# Trigger kinds in the order they are offered. Time first: it is what most people
# come here for, and it is the only one that works with the app closed.
TRIGGER_CHOICES = (
    TRIGGER_TIME,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_NO_INPUT,
    TRIGGER_LUMABLE_START,
    TRIGGER_STRIP_CONNECTED,
    TRIGGER_ALWAYS,
)

ACTION_CHOICES = (CHOICE_SCENE, CHOICE_POWER_ON, CHOICE_POWER_OFF)

# Which extra field each trigger needs. Used by the overlay to show one row and
# hide the rest, and by the tests to prove nothing is left visible that the
# chosen trigger has no use for.
TRIGGER_FIELDS = {
    TRIGGER_TIME: ("time_at", "days"),
    TRIGGER_APP_FOREGROUND: ("app",),
    TRIGGER_NO_INPUT: ("minutes",),
    TRIGGER_LUMABLE_START: (),
    TRIGGER_STRIP_CONNECTED: (),
    TRIGGER_ALWAYS: (),
}

# Problem codes, in the order they are reported. Stable identifiers: the message
# is looked up as ``automations.problem_<code>``, so wording can change freely.
PROBLEM_NAME = "name"
PROBLEM_TIME = "time"
PROBLEM_DAYS = "days"
PROBLEM_APP = "app"
PROBLEM_SCENE = "scene"
PROBLEM_SCENE_MISSING = "scene_missing"

PROBLEM_CODES = (
    PROBLEM_NAME,
    PROBLEM_TIME,
    PROBLEM_DAYS,
    PROBLEM_APP,
    PROBLEM_SCENE,
    PROBLEM_SCENE_MISSING,
)

IDLE_PRESETS = (5, 10, 15, 20, 30, 45, 60, 120)
PRIORITY_PRESETS = ((-10, "low"), (0, "normal"), (10, "high"))
COOLDOWN_PRESETS = (0, 60, 300, 900, 3600)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# A rule id ends up in a Windows task name and on a command line, so it is
# generated from a fixed alphabet rather than from anything the user typed.
_ID_PREFIX = "rule-"


def new_rule_id(existing: Any = ()) -> str:
    """A fresh id that no existing rule holds.

    Generated, never edited: it is the identity a Windows task, the journal and
    the handled-occurrence record all refer to, so letting it change would orphan
    every one of them.
    """
    taken = {str(item) for item in existing}
    while True:
        candidate = f"{_ID_PREFIX}{uuid4().hex[:12]}"
        if candidate not in taken:
            return candidate


def blank_form() -> dict[str, Any]:
    """A new rule, set up as the most useful thing to be editing: a daily time."""
    return {
        "name": "",
        "trigger_kind": TRIGGER_TIME,
        "time_at": "21:00",
        "days": ALL_DAYS,
        "app": "",
        "minutes": 10,
        "action": CHOICE_POWER_ON,
        "scene_id": "",
        "execution": EXECUTION_RUNTIME,
        "priority": 0,
        "cooldown_seconds": 0,
        # Carried through untouched; see the module docstring.
        "origin": "",
        "origin_ref": "",
        "enabled": True,
        "require_name": True,
    }


def rule_to_form(rule: Rule) -> dict[str, Any]:
    """An existing rule as a form.

    ``require_name`` is False here on purpose. Migrated rules have no name — the
    0.3.5 schedule never asked for one — and demanding one before an unrelated
    edit can be saved would make the app rewrite data the user did not come to
    change. New rules do have to be named; see :func:`blank_form`.
    """
    form = blank_form()
    form.update(
        {
            "name": rule.name,
            "trigger_kind": rule.trigger.kind,
            "time_at": rule.trigger.time_at or "21:00",
            "days": tuple(rule.trigger.days) if rule.trigger.kind == TRIGGER_TIME else ALL_DAYS,
            "app": rule.trigger.app,
            "minutes": rule.trigger.minutes,
            "action": _action_choice(rule),
            "scene_id": rule.action.scene_id,
            "execution": rule.execution,
            "priority": rule.priority,
            "cooldown_seconds": rule.cooldown_seconds,
            "origin": rule.origin,
            "origin_ref": rule.origin_ref,
            "enabled": rule.enabled,
            "require_name": False,
        }
    )
    return form


def _action_choice(rule: Rule) -> str:
    if rule.action.type == ACTION_APPLY_SCENE:
        return CHOICE_SCENE
    return CHOICE_POWER_ON if rule.action.power else CHOICE_POWER_OFF


def background_allowed(form: dict[str, Any]) -> bool:
    """Whether this rule could run with LumaBLE closed.

    A background rule becomes a Windows task that starts the app headless, and in
    0.3.6 that path can only switch power at a time of day. The schema enforces
    the same thing on the way in — this is the form knowing it in advance, so the
    control can be switched off with a reason instead of accepting a setting that
    disappears on the next read.
    """
    return form.get("trigger_kind") == TRIGGER_TIME and form.get("action") in (
        CHOICE_POWER_ON,
        CHOICE_POWER_OFF,
    )


def normalized(form: dict[str, Any]) -> dict[str, Any]:
    """The form with anything the current choices cannot hold put back.

    Called after every change, so a rule whose action moved away from power does
    not keep a background flag that the schema would drop anyway.
    """
    settled = dict(form)
    if not background_allowed(settled):
        settled["execution"] = EXECUTION_RUNTIME
    if settled.get("action") != CHOICE_SCENE:
        settled["scene_id"] = ""
    return settled


def form_problems(form: dict[str, Any], *, scene_ids: Any = ()) -> list[str]:
    """Everything standing between this form and a rule that works.

    Ordered, so the first one can be shown on its own: a list of complaints is
    read as a wall, one sentence is read as an instruction.
    """
    problems: list[str] = []
    if form.get("require_name") and not str(form.get("name", "")).strip():
        problems.append(PROBLEM_NAME)

    kind = form.get("trigger_kind")
    if kind == TRIGGER_TIME:
        if not _TIME_RE.match(str(form.get("time_at", ""))):
            problems.append(PROBLEM_TIME)
        if not tuple(form.get("days") or ()):
            # An empty day list means no days, never "daily" — a rule saved like
            # this could never fire, and the schema keeps it exactly that way.
            problems.append(PROBLEM_DAYS)
    elif kind == TRIGGER_APP_FOREGROUND and not str(form.get("app", "")).strip():
        problems.append(PROBLEM_APP)

    if form.get("action") == CHOICE_SCENE:
        scene_id = str(form.get("scene_id", "")).strip()
        known = {str(item) for item in scene_ids}
        if not scene_id:
            problems.append(PROBLEM_SCENE)
        elif scene_id not in known:
            # The scene was deleted after the rule was written. Named as its own
            # problem: "pick a scene" and "the scene this used is gone" send the
            # user to different places.
            problems.append(PROBLEM_SCENE_MISSING)
    return problems


def form_to_rule(form: dict[str, Any], *, rule_id: str) -> dict[str, Any]:
    """The form as a rule dict for :meth:`AutomationController.save_rule`.

    Only the fields the chosen trigger and action actually use are written, so a
    stored rule reads the way it was authored — and ``origin``/``origin_ref``/
    ``enabled`` are carried through rather than defaulted, because none of the
    three is the editor's to decide.
    """
    settled = normalized(form)
    kind = settled["trigger_kind"]
    trigger: dict[str, Any] = {"kind": kind}
    if kind == TRIGGER_TIME:
        trigger["time_at"] = settled["time_at"]
        trigger["days"] = list(settled.get("days") or ())
    elif kind == TRIGGER_APP_FOREGROUND:
        trigger["app"] = str(settled["app"]).strip().lower()
    elif kind == TRIGGER_NO_INPUT:
        trigger["minutes"] = int(settled["minutes"])

    if settled["action"] == CHOICE_SCENE:
        action: dict[str, Any] = {"type": ACTION_APPLY_SCENE, "scene_id": settled["scene_id"]}
    else:
        action = {
            "type": ACTION_SET_POWER,
            "power": settled["action"] == CHOICE_POWER_ON,
            "target": "primary",
        }

    stored: dict[str, Any] = {
        "id": rule_id,
        "name": str(settled.get("name", "")).strip()[:80],
        "trigger": trigger,
        "action": action,
        "execution": settled["execution"],
        "priority": int(settled.get("priority", 0)),
        "cooldown_seconds": int(settled.get("cooldown_seconds", 0)),
        "enabled": bool(settled.get("enabled", True)),
    }
    origin = str(settled.get("origin", "")).strip()
    if origin:
        stored["origin"] = origin
        if settled.get("origin_ref"):
            stored["origin_ref"] = str(settled["origin_ref"])
    return stored


def priority_options(current: int) -> list[tuple[int, str, dict[str, Any]]]:
    """The priority choices, with any other stored value kept as its own.

    (value, i18n key, format arguments). A rule holding 7 keeps 7: rounding it to
    the nearest offered value would change behaviour nobody asked to change.
    """
    options = [(value, f"automations.priority_{name}", {}) for value, name in PRIORITY_PRESETS]
    if all(value != int(current) for value, _key, _args in options):
        options.append((int(current), "automations.priority_custom", {"value": int(current)}))
        options.sort(key=lambda option: option[0])
    return options


def cooldown_options(current: int) -> list[tuple[int, str, dict[str, Any]]]:
    """The cooldown choices, in seconds, with any other stored value kept."""
    options: list[tuple[int, str, dict[str, Any]]] = []
    for seconds in COOLDOWN_PRESETS:
        if seconds == 0:
            options.append((0, "automations.cooldown_none", {}))
        else:
            options.append((seconds, "automations.cooldown_minutes", {"minutes": seconds // 60}))
    current = int(current)
    if all(seconds != current for seconds, _key, _args in options):
        if current % 60 == 0:
            options.append((current, "automations.cooldown_minutes", {"minutes": current // 60}))
        else:
            options.append((current, "automations.cooldown_seconds", {"seconds": current}))
        options.sort(key=lambda option: option[0])
    return options


def idle_options(current: int) -> list[int]:
    """Idle spans in minutes, with any other stored value kept in its place."""
    values = list(IDLE_PRESETS)
    if int(current) not in values:
        values.append(int(current))
        values.sort()
    return values
