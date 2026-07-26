"""The conflict model. Every rule here is one the user could hit in a day of
normal use, so the reasons the journal shows have to be right."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.automation.resolver import (
    SKIP_COOLDOWN,
    SKIP_DISCONNECTED,
    SKIP_MISSING_SCENE,
    SKIP_OUTRANKED,
    SKIP_PAUSED,
    AutomationEngine,
    Event,
    Snapshot,
)
from app.automation.rules import (
    ACTION_APPLY_SCENE,
    ACTION_SET_POWER,
    TRIGGER_ALWAYS,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_LUMABLE_START,
    TRIGGER_NO_INPUT,
    TRIGGER_STRIP_CONNECTED,
    TRIGGER_TIME,
    validate_rule,
)

T0 = datetime(2026, 7, 27, 20, 0)  # a Monday evening


def _rule(
    rule_id: str, trigger: dict, *, scene: str = "", priority: int = 0,
    action_power: bool = True, **extra,
):
    action = (
        {"type": ACTION_APPLY_SCENE, "scene_id": scene}
        if scene
        else {"type": ACTION_SET_POWER, "power": action_power}
    )
    rule = validate_rule(
        {"id": rule_id, "name": rule_id, "trigger": trigger, "action": action,
         "priority": priority, **extra}
    )
    assert rule is not None
    return rule


def _app(rule_id: str, app: str, scene: str, **extra):
    return _rule(rule_id, {"kind": TRIGGER_APP_FOREGROUND, "app": app}, scene=scene, **extra)


def _snap(now: datetime, **kwargs) -> Snapshot:
    return Snapshot(now=now, **kwargs)


def _settle(engine: AutomationEngine, rules, snapshot: Snapshot):
    """Evaluate and confirm success — the engine only records acknowledged work."""
    outcome = engine.evaluate(rules, snapshot)
    if outcome.decision is not None:
        engine.ack(outcome.decision, success=True)
    return outcome


def test_switching_between_two_matched_apps_applies_one_scene() -> None:
    """The reason on_exit was dropped: leaving one app and entering another must
    not pass through the fallback scene on the way."""
    rules = [
        _app("game", "game.exe", "scene-game"),
        _app("work", "work.exe", "scene-work"),
        _rule("fallback", {"kind": TRIGGER_ALWAYS}, scene="scene-default", priority=-10),
    ]
    engine = AutomationEngine()

    _settle(engine, rules, _snap(T0, foreground_app="game.exe"))
    outcome = engine.evaluate(rules, _snap(T0 + timedelta(seconds=2), foreground_app="work.exe"))

    assert outcome.decision is not None
    assert outcome.decision.rule_id == "work"
    assert outcome.decision.action.scene_id == "scene-work"


def test_leaving_every_matched_app_falls_back() -> None:
    rules = [
        _app("game", "game.exe", "scene-game"),
        _rule("fallback", {"kind": TRIGGER_ALWAYS}, scene="scene-default", priority=-10),
    ]
    engine = AutomationEngine()

    _settle(engine, rules, _snap(T0, foreground_app="game.exe"))
    outcome = engine.evaluate(rules, _snap(T0 + timedelta(seconds=2), foreground_app="explorer.exe"))

    assert outcome.decision is not None
    assert outcome.decision.rule_id == "fallback"


def test_a_steady_winner_is_not_re_applied_every_tick() -> None:
    """Otherwise the strip would be rewritten on every poll while one app stays
    in front, and manual tweaks would be stamped over непрерывно."""
    rules = [_app("game", "game.exe", "scene-game")]
    engine = AutomationEngine()

    first = _settle(engine, rules, _snap(T0, foreground_app="game.exe"))
    second = engine.evaluate(rules, _snap(T0 + timedelta(seconds=2), foreground_app="game.exe"))

    assert first.decision is not None
    assert second.decision is None
    assert second.skips == ()


def test_priority_beats_recency_and_the_loser_is_reported() -> None:
    rules = [
        _app("game", "game.exe", "scene-game", priority=5),
        _rule("idle", {"kind": TRIGGER_NO_INPUT, "minutes": 1}, scene="scene-idle", priority=1),
    ]
    engine = AutomationEngine()

    outcome = engine.evaluate(rules, _snap(T0, foreground_app="game.exe", idle_seconds=600))

    assert outcome.decision is not None
    assert outcome.decision.rule_id == "game"
    assert ("idle", SKIP_OUTRANKED) in [(skip.rule_id, skip.reason) for skip in outcome.skips]


def test_rule_order_in_the_list_changes_nothing() -> None:
    """Dragging a row to tidy the list must not change behaviour."""
    forward = [
        _app("a", "game.exe", "scene-a", priority=3),
        _app("b", "game.exe", "scene-b", priority=7),
    ]
    outcome_forward = AutomationEngine().evaluate(forward, _snap(T0, foreground_app="game.exe"))
    outcome_reversed = AutomationEngine().evaluate(
        list(reversed(forward)), _snap(T0, foreground_app="game.exe")
    )

    assert outcome_forward.decision.rule_id == "b"
    assert outcome_reversed.decision.rule_id == "b"


def test_a_time_rule_fires_when_the_clock_crosses_it() -> None:
    rules = [_rule("night", {"kind": TRIGGER_TIME, "time_at": "21:00"})]
    engine = AutomationEngine()

    engine.evaluate(rules, _snap(T0))  # 20:00 — establishes the previous tick
    before = engine.evaluate(rules, _snap(T0.replace(hour=20, minute=59)))
    crossing = engine.evaluate(rules, _snap(T0.replace(hour=21, minute=0)))
    engine.ack(crossing.decision, success=True)  # or the next call is merely "busy"
    after = engine.evaluate(rules, _snap(T0.replace(hour=21, minute=1)))

    assert before.decision is None
    assert crossing.decision is not None
    assert crossing.decision.action.type == ACTION_SET_POWER
    assert after.decision is None  # fires once, not for the rest of the evening


def test_the_first_tick_never_replays_a_time_that_already_passed() -> None:
    """Launching the app at 21:05 must not act as if 21:00 just happened."""
    rules = [_rule("night", {"kind": TRIGGER_TIME, "time_at": "21:00"})]

    outcome = AutomationEngine().evaluate(rules, _snap(T0.replace(hour=21, minute=5)))

    assert outcome.decision is None


def test_a_time_rule_slept_through_still_fires() -> None:
    """A laptop that was asleep from 20:00 to 23:00 crossed 21:00 on the way."""
    rules = [_rule("night", {"kind": TRIGGER_TIME, "time_at": "21:00"})]
    engine = AutomationEngine()

    engine.evaluate(rules, _snap(T0))
    outcome = engine.evaluate(rules, _snap(T0 + timedelta(hours=3)))

    assert outcome.decision is not None


def test_a_time_rule_only_fires_on_its_own_days() -> None:
    tuesday_only = [_rule("night", {"kind": TRIGGER_TIME, "time_at": "21:00", "days": [1]})]
    engine = AutomationEngine()

    engine.evaluate(tuesday_only, _snap(T0))  # Monday 20:00
    monday = engine.evaluate(tuesday_only, _snap(T0.replace(hour=21)))

    assert monday.decision is None  # T0 is a Monday


def test_an_event_trigger_fires_once_when_it_is_reported() -> None:
    rules = [_rule("welcome", {"kind": TRIGGER_LUMABLE_START}, scene="scene-hello")]
    engine = AutomationEngine()

    fired = engine.evaluate(rules, _snap(T0), events=(TRIGGER_LUMABLE_START,))
    engine.ack(fired.decision, success=True)  # or the next call is merely "busy"
    quiet = engine.evaluate(rules, _snap(T0 + timedelta(seconds=1)))

    assert fired.decision is not None
    assert quiet.decision is None


def test_a_manual_pause_holds_everything_off_and_says_so() -> None:
    rules = [_app("game", "game.exe", "scene-game")]
    engine = AutomationEngine()
    engine.pause(T0, seconds=3600)

    outcome = engine.evaluate(rules, _snap(T0 + timedelta(seconds=1), foreground_app="game.exe"))

    assert outcome.decision is None
    assert [skip.reason for skip in outcome.skips] == [SKIP_PAUSED]
    assert engine.paused_until() == T0 + timedelta(seconds=3600)


def test_the_pause_expires_by_itself() -> None:
    """A pause with no end is indistinguishable from automations being broken."""
    rules = [_app("game", "game.exe", "scene-game")]
    engine = AutomationEngine()
    engine.pause(T0, seconds=60)

    engine.evaluate(rules, _snap(T0 + timedelta(seconds=1), foreground_app="game.exe"))
    later = engine.evaluate(rules, _snap(T0 + timedelta(seconds=120), foreground_app="game.exe"))

    assert later.decision is not None
    assert engine.paused_until() is None


def test_cooldown_blocks_a_repeat_and_names_the_reason() -> None:
    rules = [_rule("welcome", {"kind": TRIGGER_LUMABLE_START}, scene="s", cooldown_seconds=300)]
    engine = AutomationEngine()

    first = engine.evaluate(rules, _snap(T0), events=(TRIGGER_LUMABLE_START,))
    engine.ack(first.decision, success=True)
    soon = engine.evaluate(rules, _snap(T0 + timedelta(seconds=10)), events=(TRIGGER_LUMABLE_START,))
    later = engine.evaluate(rules, _snap(T0 + timedelta(seconds=400)), events=(TRIGGER_LUMABLE_START,))

    assert first.decision is not None
    assert soon.decision is None
    assert [skip.reason for skip in soon.skips] == [SKIP_COOLDOWN]
    assert later.decision is not None


def test_a_rule_pointing_at_a_deleted_scene_is_skipped_with_that_reason() -> None:
    rules = [_app("game", "game.exe", "scene-gone")]
    engine = AutomationEngine()

    outcome = engine.evaluate(
        rules,
        _snap(T0, foreground_app="game.exe", available_scene_ids=frozenset({"scene-other"})),
    )

    assert outcome.decision is None
    assert [skip.reason for skip in outcome.skips] == [SKIP_MISSING_SCENE]


def test_nothing_runs_while_the_strip_is_disconnected() -> None:
    rules = [_app("game", "game.exe", "scene-game")]
    engine = AutomationEngine()

    outcome = engine.evaluate(rules, _snap(T0, foreground_app="game.exe", connected=False))

    assert outcome.decision is None
    assert [skip.reason for skip in outcome.skips] == [SKIP_DISCONNECTED]


def test_disabled_rules_are_invisible_to_the_resolver() -> None:
    rules = [
        _app("game", "game.exe", "scene-game", priority=9, enabled=False),
        _rule("fallback", {"kind": TRIGGER_ALWAYS}, scene="scene-default", priority=-10),
    ]

    outcome = AutomationEngine().evaluate(rules, _snap(T0, foreground_app="game.exe"))

    assert outcome.decision is not None
    assert outcome.decision.rule_id == "fallback"


# ── the four ways a decision can be wrongly remembered ────────────────────
def test_a_blocked_rule_is_applied_once_the_obstacle_clears() -> None:
    """The strip was offline when the game started; connecting must still light
    it. Recording the winner before checking eligibility made this a dead end."""
    rules = [_app("game", "game.exe", "scene-game")]
    engine = AutomationEngine()

    offline = engine.evaluate(rules, _snap(T0, foreground_app="game.exe", connected=False))
    online = engine.evaluate(
        rules, _snap(T0 + timedelta(seconds=2), foreground_app="game.exe", connected=True)
    )

    assert offline.decision is None
    assert [skip.reason for skip in offline.skips] == [SKIP_DISCONNECTED]
    assert online.decision is not None
    assert online.decision.rule_id == "game"


def test_a_failed_execution_is_retried_rather_than_remembered() -> None:
    rules = [_app("game", "game.exe", "scene-game")]
    engine = AutomationEngine()

    first = engine.evaluate(rules, _snap(T0, foreground_app="game.exe"))
    assert first.decision is not None
    engine.ack(first.decision, success=False)  # the BLE write failed

    second = engine.evaluate(rules, _snap(T0 + timedelta(seconds=2), foreground_app="game.exe"))
    assert second.decision is not None, "a failed apply must not count as applied"

    engine.ack(second.decision, success=True)
    third = engine.evaluate(rules, _snap(T0 + timedelta(seconds=4), foreground_app="game.exe"))
    assert third.decision is None


def test_a_failed_execution_does_not_start_the_cooldown() -> None:
    rules = [_rule("welcome", {"kind": TRIGGER_LUMABLE_START}, scene="s", cooldown_seconds=300)]
    engine = AutomationEngine()

    first = engine.evaluate(rules, _snap(T0), events=(TRIGGER_LUMABLE_START,))
    engine.ack(first.decision, success=False)
    retry = engine.evaluate(rules, _snap(T0 + timedelta(seconds=5)), events=(TRIGGER_LUMABLE_START,))

    assert retry.decision is not None


def test_a_broken_high_priority_rule_does_not_shadow_the_fallback() -> None:
    """Its scene was deleted. It loses its turn and says so; the light still
    follows the next best rule instead of freezing on the broken one."""
    rules = [
        _app("game", "game.exe", "scene-gone", priority=9),
        _rule("fallback", {"kind": TRIGGER_ALWAYS}, scene="scene-default", priority=-10),
    ]
    engine = AutomationEngine()

    outcome = engine.evaluate(
        rules,
        _snap(T0, foreground_app="game.exe", available_scene_ids=frozenset({"scene-default"})),
    )

    assert outcome.decision is not None
    assert outcome.decision.rule_id == "fallback"
    assert ("game", SKIP_MISSING_SCENE) in [(skip.rule_id, skip.reason) for skip in outcome.skips]


def test_sleeping_through_on_and_off_lands_on_the_later_one() -> None:
    """Asleep from 18:00 to 23:30, crossing "on at 19:00" and "off at 23:00".
    Waking up to the lights on would be wrong — and with only a boolean crossing
    both carried the same timestamp and the tie fell through to the rule id."""
    rules = [
        _rule("aaa_on", {"kind": TRIGGER_TIME, "time_at": "19:00"}),
        _rule("zzz_off", {"kind": TRIGGER_TIME, "time_at": "23:00"}, action_power=False),
    ]
    engine = AutomationEngine()

    engine.evaluate(rules, _snap(T0.replace(hour=18, minute=0)))
    outcome = engine.evaluate(rules, _snap(T0.replace(hour=23, minute=30)))

    assert outcome.decision is not None
    assert outcome.decision.rule_id == "zzz_off"
    assert outcome.decision.action.power is False


# ── one decision at a time ────────────────────────────────────────────────
def test_the_same_decision_is_not_handed_out_twice_before_it_is_acked() -> None:
    """A sequential dispatcher would otherwise queue the same command twice."""
    rules = [_app("game", "game.exe", "scene-game")]
    engine = AutomationEngine()

    first = engine.evaluate(rules, _snap(T0, foreground_app="game.exe"))
    again = engine.evaluate(rules, _snap(T0 + timedelta(seconds=1), foreground_app="game.exe"))

    assert first.decision is not None
    assert again.decision is None
    assert engine.pending() is first.decision

    engine.ack(first.decision, success=True)
    assert engine.pending() is None


def test_an_old_or_repeated_ack_is_rejected() -> None:
    """Game was applied, then Work. The straggling callback for Game must not
    drag the engine back, and Work must not be acked twice.

    Note there is no true "superseded" case to test: pending means a second
    decision cannot be issued until the first is answered, so the token guards
    stale and duplicate acks rather than overtaking ones."""
    rules = [
        _app("game", "game.exe", "scene-game"),
        _app("work", "work.exe", "scene-work"),
    ]
    engine = AutomationEngine()

    game = engine.evaluate(rules, _snap(T0, foreground_app="game.exe")).decision
    engine.ack(game, success=True)
    work = engine.evaluate(rules, _snap(T0 + timedelta(seconds=2), foreground_app="work.exe")).decision
    assert engine.ack(work, success=True) is True

    assert engine.ack(game, success=True) is False  # stale
    assert engine.ack(work, success=True) is False  # and not twice either

    quiet = engine.evaluate(rules, _snap(T0 + timedelta(seconds=4), foreground_app="work.exe"))
    assert quiet.decision is None, "the stale ack re-opened a settled state"


def test_a_pending_decision_does_not_swallow_a_time_crossing() -> None:
    """The tick window stays open while we wait, so 21:00 is still there."""
    rules = [
        _app("game", "game.exe", "scene-game"),
        _rule("night", {"kind": TRIGGER_TIME, "time_at": "21:00"}, priority=5),
    ]
    engine = AutomationEngine()

    first = engine.evaluate(rules, _snap(T0, foreground_app="game.exe"))
    engine.evaluate(rules, _snap(T0.replace(hour=21, minute=30), foreground_app="game.exe"))
    engine.ack(first.decision, success=True)
    after = engine.evaluate(rules, _snap(T0.replace(hour=21, minute=31), foreground_app="game.exe"))

    assert after.decision is not None
    assert after.decision.rule_id == "night"


def test_an_edge_action_settles_the_stateful_context_it_ran_in() -> None:
    """Same event, same result, whether or not the fallback happened to be acked
    earlier: a scheduled "off" must not be undone a second later."""

    def run(pre_ack_fallback: bool) -> str | None:
        rules = [
            _rule("fallback", {"kind": TRIGGER_ALWAYS}, scene="scene-default", priority=-10),
            _rule("night_off", {"kind": TRIGGER_TIME, "time_at": "21:00"}, action_power=False),
        ]
        engine = AutomationEngine()
        first = engine.evaluate(rules, _snap(T0))
        engine.ack(first.decision, success=pre_ack_fallback)

        crossing = engine.evaluate(rules, _snap(T0.replace(hour=21, minute=0)))
        assert crossing.decision.rule_id == "night_off"
        engine.ack(crossing.decision, success=True)

        after = engine.evaluate(rules, _snap(T0.replace(hour=21, minute=1)))
        return after.decision.rule_id if after.decision else None

    assert run(pre_ack_fallback=True) is None
    assert run(pre_ack_fallback=False) is None, "behaviour depended on ack history"


def test_the_journal_gets_both_times_for_a_rule_slept_through() -> None:
    rules = [_rule("night", {"kind": TRIGGER_TIME, "time_at": "23:00"})]
    engine = AutomationEngine()

    engine.evaluate(rules, _snap(T0.replace(hour=18, minute=0)))
    outcome = engine.evaluate(rules, _snap(T0.replace(day=28, hour=8, minute=10)))

    assert outcome.decision is not None
    assert outcome.decision.occurred_at == T0.replace(hour=23, minute=0)
    assert outcome.decision.decided_at == T0.replace(day=28, hour=8, minute=10)


def test_an_event_arriving_during_pending_is_handled_afterwards() -> None:
    """Unlike a time of day, a one-off event leaves no trace to rediscover, so
    dropping it on a busy tick would lose it for good."""
    rules = [
        _app("game", "game.exe", "scene-game"),
        _rule("on_connect", {"kind": TRIGGER_STRIP_CONNECTED}, scene="scene-hello", priority=5),
    ]
    engine = AutomationEngine()

    busy = engine.evaluate(rules, _snap(T0, foreground_app="game.exe"))
    assert busy.decision is not None and busy.decision.rule_id == "game"

    connected_at = T0 + timedelta(seconds=1)
    held = engine.evaluate(
        rules,
        _snap(connected_at, foreground_app="game.exe"),
        events=(Event(kind=TRIGGER_STRIP_CONNECTED, occurred_at=connected_at),),
    )
    assert held.decision is None  # busy

    engine.ack(busy.decision, success=True)
    after = engine.evaluate(rules, _snap(T0 + timedelta(seconds=5), foreground_app="game.exe"))

    assert after.decision is not None
    assert after.decision.rule_id == "on_connect"
    # The journal must still show when it really happened, not when we got to it.
    assert after.decision.occurred_at == connected_at
    assert after.decision.decided_at == T0 + timedelta(seconds=5)


def test_a_pause_abandons_the_decision_that_was_in_flight() -> None:
    """The user has just taken the light somewhere by hand. A command that was
    already on its way must not report success and hand control back."""
    rules = [_app("game", "game.exe", "scene-game")]
    engine = AutomationEngine()

    decision = engine.evaluate(rules, _snap(T0, foreground_app="game.exe")).decision
    assert decision is not None

    engine.pause(T0 + timedelta(seconds=1), seconds=60)
    assert engine.ack(decision, success=True) is False, "a paused engine accepted a stale ack"
    assert engine.pending() is None

    paused = engine.evaluate(rules, _snap(T0 + timedelta(seconds=2), foreground_app="game.exe"))
    assert paused.decision is None
    assert [skip.reason for skip in paused.skips] == [SKIP_PAUSED]

    engine.resume()
    after = engine.evaluate(rules, _snap(T0 + timedelta(seconds=3), foreground_app="game.exe"))
    assert after.decision is not None, "resume must offer the current rule again"
    assert after.decision.rule_id == "game"


def test_a_pause_also_drops_events_held_behind_the_decision() -> None:
    """An event from before the user took over must not come back to life on
    resume and move the light again."""
    rules = [
        _app("game", "game.exe", "scene-game"),
        _rule("on_connect", {"kind": TRIGGER_STRIP_CONNECTED}, scene="scene-hello", priority=5),
    ]
    engine = AutomationEngine()

    decision = engine.evaluate(rules, _snap(T0, foreground_app="game.exe")).decision
    connected_at = T0 + timedelta(seconds=1)
    engine.evaluate(
        rules,
        _snap(connected_at, foreground_app="game.exe"),
        events=(Event(kind=TRIGGER_STRIP_CONNECTED, occurred_at=connected_at),),
    )

    engine.pause(T0 + timedelta(seconds=2), seconds=60)
    assert engine.ack(decision, success=True) is False
    engine.resume()

    after = engine.evaluate(rules, _snap(T0 + timedelta(seconds=3), foreground_app="game.exe"))

    assert after.decision is not None
    assert after.decision.rule_id == "game", "a pre-pause event came back after resume"
