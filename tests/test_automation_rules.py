"""rule.v1 validation: settings files are hand-edited and survive downgrades, so
a bad rule must cost the user that rule and nothing more."""

from __future__ import annotations

from app.automation.rules import (
    ACTION_APPLY_SCENE,
    ACTION_SET_POWER,
    ALL_DAYS,
    EXECUTION_BACKGROUND,
    EXECUTION_RUNTIME,
    TARGET_PRIMARY,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_NO_INPUT,
    TRIGGER_TIME,
    WARN_BACKGROUND_DOWNGRADED,
    WARN_NO_DAYS,
    rule_to_dict,
    validate_rule,
    validate_rules,
)


def _time_power_rule(**overrides) -> dict:
    rule = {
        "id": "r1",
        "name": "Evening on",
        "trigger": {"kind": TRIGGER_TIME, "time_at": "21:00", "days": [0, 1, 2]},
        "action": {"type": ACTION_SET_POWER, "power": True},
        "execution": EXECUTION_BACKGROUND,
    }
    rule.update(overrides)
    return rule


def test_a_time_power_rule_survives_a_round_trip() -> None:
    rule = validate_rule(_time_power_rule())

    assert rule is not None
    assert rule.trigger.time_at == "21:00"
    assert rule.trigger.days == (0, 1, 2)
    assert rule.action.type == ACTION_SET_POWER
    assert rule.action.power is True
    assert rule.execution == EXECUTION_BACKGROUND
    assert validate_rule(rule_to_dict(rule)) == rule


def test_sloppy_times_and_days_are_coerced() -> None:
    rule = validate_rule(
        _time_power_rule(trigger={"kind": TRIGGER_TIME, "time_at": "9:5", "days": [3, 3, 9, "1", None]})
    )

    assert rule is not None
    assert rule.trigger.time_at == "09:05"
    assert rule.trigger.days == (1, 3)  # deduplicated, sorted, out-of-range dropped


def test_a_rule_that_could_never_fire_is_dropped() -> None:
    assert validate_rule(_time_power_rule(trigger={"kind": TRIGGER_TIME, "time_at": "25:00"})) is None
    assert validate_rule(_time_power_rule(trigger={"kind": TRIGGER_TIME})) is None
    assert validate_rule(_time_power_rule(trigger={"kind": "teleport"})) is None
    assert validate_rule(_time_power_rule(id="")) is None
    # An app trigger with no app would match every process.
    assert validate_rule(_time_power_rule(trigger={"kind": TRIGGER_APP_FOREGROUND, "app": "  "})) is None
    # "Apply scene" with no scene has nothing to apply.
    assert validate_rule(_time_power_rule(action={"type": ACTION_APPLY_SCENE, "scene_id": ""})) is None
    assert validate_rule(_time_power_rule(action={"type": "launch_missiles"})) is None


def test_background_is_downgraded_where_it_cannot_work() -> None:
    """Background means a Windows task that starts LumaBLE headless, and in
    0.3.6 that path can only switch power on a schedule. The rule is kept and
    still works while the app is open — silently dropping it would be worse."""
    scene_rule = validate_rule(
        _time_power_rule(action={"type": ACTION_APPLY_SCENE, "scene_id": "s1"})
    )
    assert scene_rule is not None
    assert scene_rule.execution == EXECUTION_RUNTIME

    app_rule = validate_rule(
        _time_power_rule(trigger={"kind": TRIGGER_APP_FOREGROUND, "app": "game.exe"})
    )
    assert app_rule is not None
    assert app_rule.execution == EXECUTION_RUNTIME

    assert validate_rule(_time_power_rule(execution="whenever")).execution == EXECUTION_RUNTIME


def test_numbers_are_clamped_rather_than_rejected() -> None:
    rule = validate_rule(_time_power_rule(priority="9999", cooldown_seconds=-5))
    assert rule is not None
    assert rule.priority == 100
    assert rule.cooldown_seconds == 0

    idle = validate_rule(_time_power_rule(trigger={"kind": TRIGGER_NO_INPUT, "minutes": 0}))
    assert idle is not None
    assert idle.trigger.minutes == 1


def test_validate_rules_keeps_the_good_ones_and_the_first_of_each_id() -> None:
    rules = validate_rules(
        [
            _time_power_rule(id="a", name="first"),
            "not a rule",
            _time_power_rule(id="a", name="duplicate"),
            _time_power_rule(id="b"),
            {"id": "c"},  # no trigger, no action
        ]
    )

    assert [rule.id for rule in rules] == ["a", "b"]
    assert rules[0].name == "first"


def test_serialisation_only_writes_the_fields_the_kind_uses() -> None:
    rule = validate_rule(_time_power_rule(trigger={"kind": TRIGGER_APP_FOREGROUND, "app": "Game.EXE"}))
    assert rule is not None
    assert rule.trigger.app == "game.exe"  # matched case-insensitively later

    data = rule_to_dict(rule)
    assert data["trigger"] == {"kind": TRIGGER_APP_FOREGROUND, "app": "game.exe"}
    assert "time_at" not in data["trigger"]
    assert data["action"] == {"type": ACTION_SET_POWER, "power": True, "target": TARGET_PRIMARY}


def test_a_corrupt_power_value_is_refused_not_guessed() -> None:
    """Defaulting to True would switch the user's lights on at a time they never
    asked for. The rule is dropped instead."""
    assert validate_rule(_time_power_rule(action={"type": ACTION_SET_POWER, "power": "banana"})) is None
    assert validate_rule(_time_power_rule(action={"type": ACTION_SET_POWER})) is None
    assert validate_rule(_time_power_rule(action={"type": ACTION_SET_POWER, "power": "off"})).action.power is False


def test_an_explicit_empty_day_list_is_not_every_day() -> None:
    """The old schedule stored [] for "switched off by weekday". Reading that as
    a shorthand for daily would make a disabled schedule fire every morning the
    moment it is migrated."""
    warnings: list[str] = []
    rule = validate_rule(
        _time_power_rule(trigger={"kind": TRIGGER_TIME, "time_at": "21:00", "days": []}), warnings
    )

    assert rule is not None
    assert rule.trigger.days == ()
    assert any(warning.startswith(WARN_NO_DAYS) for warning in warnings)

    # An absent key still means daily, which is the natural reading of a rule
    # written without days at all.
    daily = validate_rule(_time_power_rule(trigger={"kind": TRIGGER_TIME, "time_at": "21:00"}))
    assert daily.trigger.days == ALL_DAYS


def test_a_background_downgrade_is_reported_rather_than_silent() -> None:
    warnings: list[str] = []
    rule = validate_rule(
        _time_power_rule(action={"type": ACTION_APPLY_SCENE, "scene_id": "s1"}), warnings
    )

    assert rule.execution == EXECUTION_RUNTIME
    assert any(warning.startswith(WARN_BACKGROUND_DOWNGRADED) for warning in warnings)


def test_power_actions_state_their_target() -> None:
    """Pinned in the schema so the runtime path cannot start mirroring to extra
    strips while the headless one still switches only the primary."""
    rule = validate_rule(_time_power_rule())

    assert rule.action.target == TARGET_PRIMARY
    assert rule_to_dict(rule)["action"]["target"] == TARGET_PRIMARY
    assert validate_rule(_time_power_rule(action={"type": ACTION_SET_POWER, "power": True, "target": "all"})) is None


def test_a_scene_action_may_not_carry_a_target() -> None:
    """The scene owns its target, which may be a group. A rule stating one too
    would look like it scoped the scene while overriding or ignoring the group."""
    assert validate_rule(
        _time_power_rule(action={"type": ACTION_APPLY_SCENE, "scene_id": "s1", "target": "primary"})
    ) is None

    rule = validate_rule(_time_power_rule(action={"type": ACTION_APPLY_SCENE, "scene_id": "s1"}))
    assert rule.action.target == ""
    assert "target" not in rule_to_dict(rule)["action"]


def test_rule_ids_are_restricted_to_a_safe_grammar() -> None:
    """The id reaches a command line (--run-rule) and a Windows task name, so it
    is restricted at the door instead of escaped at every use."""
    for bad in ("a b", "rm -rf", "id/../x", 'quote"', "a" * 65, "", "ключ"):
        assert validate_rule(_time_power_rule(id=bad)) is None, bad
    for good in ("r1", "rule.time-on_1", "A" * 64):
        assert validate_rule(_time_power_rule(id=good)) is not None, good
