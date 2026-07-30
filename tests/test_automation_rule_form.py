"""The rule form: what may be saved, and what is carried through untouched.

No Qt here. The form is a dict, so the decisions the editor makes on the user's
behalf — whether this rule can run headless, what is still wrong with it, what
happens to a migrated rule's provenance — are all testable on their own.
"""

from __future__ import annotations

import pytest

from app.automation.rules import ALL_DAYS, ORIGIN_LEGACY_SCHEDULE, validate_rule
from app.automation_rule_form import (
    CHOICE_POWER_OFF,
    CHOICE_SCENE,
    EXECUTION_BACKGROUND,
    EXECUTION_RUNTIME,
    PROBLEM_APP,
    PROBLEM_DAYS,
    PROBLEM_NAME,
    PROBLEM_SCENE,
    PROBLEM_SCENE_MISSING,
    PROBLEM_TIME,
    background_allowed,
    blank_form,
    cooldown_options,
    form_problems,
    form_to_rule,
    idle_options,
    new_rule_id,
    normalized,
    priority_options,
    rule_to_form,
)


def _rule(**overrides):
    data = {
        "id": "rule-1",
        "name": "Evening",
        "trigger": {"kind": "time", "time_at": "21:00", "days": list(ALL_DAYS)},
        "action": {"type": "set_power", "power": True, "target": "primary"},
    }
    data.update(overrides)
    rule = validate_rule(data)
    assert rule is not None
    return rule


# ── the id ────────────────────────────────────────────────────────────
def test_a_new_id_is_generated_and_never_collides() -> None:
    """The id is what a Windows task, the journal and the handled-occurrence record
    all point at, so it is generated rather than typed — and never reused."""
    first = new_rule_id()
    second = new_rule_id({first})

    assert first != second
    assert new_rule_id({first, second}) not in {first, second}


def test_a_generated_id_is_safe_everywhere_it_is_used() -> None:
    """It ends up in a Windows task name and on a command line, so the schema keeps
    it to a restricted alphabet. An id that could not be stored is not an id."""
    from app.automation.rules import _RULE_ID_RE

    for _ in range(20):
        assert _RULE_ID_RE.fullmatch(new_rule_id())


# ── what a form requires ──────────────────────────────────────────────
def test_a_new_rule_has_to_be_named() -> None:
    form = blank_form()

    assert PROBLEM_NAME in form_problems(form)
    assert form_problems(form | {"name": "Bedtime"}) == []


def test_an_existing_rule_without_a_name_is_still_saveable() -> None:
    """Migrated rules have no name — 0.3.5 never asked for one. Demanding one before
    an unrelated edit can be saved would make the app rewrite data the user did not
    come here to change."""
    form = rule_to_form(_rule(name=""))

    assert form["require_name"] is False
    assert form_problems(form) == []


def test_a_time_rule_cannot_be_saved_with_no_days() -> None:
    """An empty day list means no days, never "daily" — the schema is explicit about
    it — so a rule saved like this could never fire."""
    form = blank_form() | {"name": "Bedtime", "days": ()}

    assert form_problems(form) == [PROBLEM_DAYS]
    assert form_problems(form | {"days": (0,)}) == []


def test_a_time_rule_needs_a_real_time() -> None:
    form = blank_form() | {"name": "Bedtime"}

    assert form_problems(form | {"time_at": ""}) == [PROBLEM_TIME]
    assert form_problems(form | {"time_at": "24:00"}) == [PROBLEM_TIME]
    assert form_problems(form | {"time_at": "7:00"}) == [PROBLEM_TIME]
    assert form_problems(form | {"time_at": "07:00"}) == []


def test_an_app_rule_needs_an_app() -> None:
    """Blank, it would match every process."""
    form = blank_form() | {"name": "Coding", "trigger_kind": "app_foreground"}

    assert form_problems(form) == [PROBLEM_APP]
    assert form_problems(form | {"app": "code.exe"}) == []


def test_a_scene_action_needs_a_scene_that_exists() -> None:
    form = blank_form() | {"name": "Desk", "action": CHOICE_SCENE}

    assert form_problems(form, scene_ids=("s1",)) == [PROBLEM_SCENE]
    # A scene deleted after the rule was written is its own problem: "pick a scene"
    # and "the one this used is gone" send the user to different places.
    assert form_problems(form | {"scene_id": "gone"}, scene_ids=("s1",)) == [PROBLEM_SCENE_MISSING]
    assert form_problems(form | {"scene_id": "s1"}, scene_ids=("s1",)) == []


def test_the_problems_are_ordered_so_one_can_be_shown_alone() -> None:
    """A list of complaints is read as a wall; one sentence is read as an
    instruction. The name comes first because it is the field the user is on."""
    form = blank_form() | {"days": (), "time_at": ""}

    assert form_problems(form)[0] == PROBLEM_NAME


# ── background is a capability ────────────────────────────────────────
def test_only_a_timed_power_rule_may_run_with_the_app_closed() -> None:
    """A background rule becomes a Windows task that starts LumaBLE headless, and in
    0.3.6 that path can only switch power at a time of day."""
    timed_power = blank_form()
    assert background_allowed(timed_power) is True

    assert background_allowed(timed_power | {"action": CHOICE_SCENE}) is False
    assert background_allowed(timed_power | {"trigger_kind": "app_foreground"}) is False


def test_a_background_flag_the_rule_can_no_longer_hold_is_dropped() -> None:
    """Stored anyway, the schema would drop it on the next read: the user would be
    told their rule runs with the app closed, and it would not."""
    form = blank_form() | {"execution": EXECUTION_BACKGROUND, "action": CHOICE_SCENE}

    assert normalized(form)["execution"] == EXECUTION_RUNTIME
    # And the schema agrees, which is the point.
    stored = form_to_rule(form | {"name": "x", "scene_id": "s1"}, rule_id="rule-9")
    assert validate_rule(stored).execution == EXECUTION_RUNTIME


def test_a_scene_id_is_not_kept_on_a_power_rule() -> None:
    form = blank_form() | {"action": CHOICE_POWER_OFF, "scene_id": "s1"}

    assert normalized(form)["scene_id"] == ""


# ── round tripping ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "rule_kwargs",
    [
        {},
        {"trigger": {"kind": "app_foreground", "app": "code.exe"}},
        {"trigger": {"kind": "no_input", "minutes": 25}},
        {"trigger": {"kind": "lumable_start"}},
        {"trigger": {"kind": "always"}},
        {"action": {"type": "apply_scene", "scene_id": "s1"}},
        {"action": {"type": "set_power", "power": False, "target": "primary"}},
        {"priority": 7, "cooldown_seconds": 90},
        {"enabled": False},
    ],
)
def test_a_rule_survives_a_trip_through_the_form(rule_kwargs) -> None:
    """Opening the editor and saving without touching anything must give back the
    rule that was opened — otherwise every edit is also an unasked-for change."""
    original = _rule(**rule_kwargs)

    stored = form_to_rule(rule_to_form(original), rule_id=original.id)
    again = validate_rule(stored)

    assert again == original


def test_a_migrated_rule_keeps_its_provenance_through_an_edit() -> None:
    """``origin`` is what keeps the task compiler from arming a Windows task for a
    rule the 0.3.5 pair is still waking the machine for. Writing it back as
    "authored here" would give it a second executor and switch the light twice."""
    original = _rule(origin=ORIGIN_LEGACY_SCHEDULE, origin_ref="schedule")

    form = rule_to_form(original)
    form["name"] = "Renamed"
    again = validate_rule(form_to_rule(form, rule_id=original.id))

    assert again.origin == ORIGIN_LEGACY_SCHEDULE
    assert again.origin_ref == "schedule"
    assert again.name == "Renamed"


def test_the_form_does_not_decide_whether_a_rule_is_enabled() -> None:
    """The row's toggle owns that, and the editor must not undo it."""
    original = _rule(enabled=False)

    again = validate_rule(form_to_rule(rule_to_form(original), rule_id=original.id))

    assert again.enabled is False


def test_a_rule_written_by_the_form_is_one_the_schema_accepts() -> None:
    form = blank_form() | {"name": "Bedtime", "action": CHOICE_POWER_OFF, "days": (0, 1)}

    rule = validate_rule(form_to_rule(form, rule_id="rule-x"))

    assert rule is not None
    assert rule.trigger.days == (0, 1)
    assert rule.action.power is False
    assert rule.name == "Bedtime"


def test_an_app_name_is_stored_the_way_the_engine_matches_it() -> None:
    """The engine lower-cases the foreground process name, so a rule typed as
    "Code.exe" has to be stored that way or it would never match."""
    form = blank_form() | {"name": "Coding", "trigger_kind": "app_foreground", "app": " Code.EXE "}

    rule = validate_rule(form_to_rule(form, rule_id="rule-x"))

    assert rule.trigger.app == "code.exe"


# ── the offered values ────────────────────────────────────────────────
def test_a_stored_value_outside_the_presets_is_kept_as_its_own_choice() -> None:
    """Rounding 7 to 10 would be editing data the user never touched."""
    values = [value for value, _key, _args in priority_options(7)]

    assert 7 in values
    assert values == sorted(values)
    assert [value for value, _key, _args in priority_options(0)] == [-10, 0, 10]


def test_an_odd_cooldown_is_offered_in_the_unit_it_is_stored_in() -> None:
    options = {value: key for value, key, _args in cooldown_options(90)}

    assert options[90] == "automations.cooldown_seconds"
    # A round number of minutes reads as minutes, whether it is a preset or not.
    assert {v: k for v, k, _a in cooldown_options(120)}[120] == "automations.cooldown_minutes"
    assert {v: k for v, k, _a in cooldown_options(0)}[0] == "automations.cooldown_none"


def test_an_odd_idle_span_keeps_its_place_in_the_list() -> None:
    values = idle_options(7)

    assert 7 in values
    assert values == sorted(values)
