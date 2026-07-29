"""Moving the 0.3.5 schedule and App Triggers onto the automation engine.

The migration is the one step a user cannot repeat by hand, so what these tests pin
is mostly about *not* losing things: running it twice, finishing a run that was
interrupted, failing part way, and above all never having two executors act on the
same trigger.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app import scene_store, storage
from app.automation import migration as migration_module
from app.automation.migration import (
    APP_DEFAULT_ID,
    DEFAULT_RULE_PRIORITY,
    LEGACY_OFF_ID,
    LEGACY_ON_ID,
    MIGRATION_VERSION,
    complete_legacy_handoff,
    finish_pending_cleanup,
    migrate,
    plan_migration,
)
from app.automation.rules import (
    ORIGIN_APP_TRIGGER,
    ORIGIN_APP_TRIGGER_DEFAULT,
    ORIGIN_LEGACY_SCHEDULE,
    ORIGIN_PROFILE_SCHEDULE,
    validate_rules,
)
from app.automation.windows_tasks import TaskSyncResult
from app.scene_presets import get_scene_preset

WEEKDAYS = [0, 1, 2, 3, 4]


def _schedule(**overrides: Any) -> dict[str, Any]:
    schedule = {
        "enabled": True,
        "on_time": "19:00",
        "off_time": "23:00",
        "startup_enabled": False,
        "days": list(WEEKDAYS),
    }
    schedule.update(overrides)
    return schedule


def _triggers(**overrides: Any) -> dict[str, Any]:
    triggers = {
        "enabled": True,
        "default": "warm_white",
        "rules": [{"app": "chrome", "scene": "cool_white"}],
    }
    triggers.update(overrides)
    return triggers


def _settings(**overrides: Any) -> dict[str, Any]:
    settings = {"schedule": _schedule(), "app_triggers": _triggers()}
    settings.update(overrides)
    return settings


def _profile(**overrides: Any) -> dict[str, Any]:
    profile = {
        "preset_key": "movie",
        "name": "Movie",
        "schedule": _schedule(on_time="20:00", off_time="22:30", days=[5, 6]),
    }
    profile.update(overrides)
    return profile


def _rules(settings: dict[str, Any]) -> dict[str, Any]:
    return {rule.id: rule for rule in validate_rules(settings["automations"]["rules"])}


@pytest.fixture
def with_legacy_tasks(monkeypatch):
    """The 0.3.5 pair is on this machine, so there is a bridge to keep."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: True)


def _bridged(settings: dict[str, Any] | None = None, profiles=None):
    """Plan as if the old Windows tasks exist."""
    return plan_migration(settings or _settings(), profiles, legacy_tasks_present=True)


# ── the sources ───────────────────────────────────────────────────────
def test_the_global_schedule_becomes_two_background_rules() -> None:
    plan = _bridged()

    rules = _rules(plan.settings)
    on, off = rules[LEGACY_ON_ID], rules[LEGACY_OFF_ID]
    assert (on.trigger.time_at, on.action.power) == ("19:00", True)
    assert (off.trigger.time_at, off.action.power) == ("23:00", False)
    assert on.trigger.days == tuple(WEEKDAYS)
    assert on.runs_in_background, "the schedule's whole point is running with the app closed"
    assert on.origin == ORIGIN_LEGACY_SCHEDULE
    assert on.enabled is True


def test_a_switched_off_schedule_migrates_as_switched_off_rules() -> None:
    plan = _bridged(_settings(schedule=_schedule(enabled=False)))

    rules = _rules(plan.settings)
    assert rules[LEGACY_ON_ID].enabled is False
    assert plan.report.bridge is False, "there are no old tasks to bridge to"


def test_a_schedule_with_no_weekday_is_reported_not_invented() -> None:
    """It could never fire; a rule that can never come round would only be a puzzle
    in the user's list."""
    plan = plan_migration(_settings(schedule=_schedule(days=[])))

    assert LEGACY_ON_ID not in _rules(plan.settings)
    assert ("schedule", "no_days") in plan.report.skipped


def test_a_profile_schedule_migrates_switched_off_and_says_which_profile() -> None:
    """A profile's schedule was only ever live while that profile was loaded — it is
    copied over the global one. Migrated as active rules, every profile's schedule
    would fire at once."""
    plan = _bridged(_settings(), [_profile()])

    rules = _rules(plan.settings)
    profile_rules = [rule for rule in rules.values() if rule.origin == ORIGIN_PROFILE_SCHEDULE]
    assert len(profile_rules) == 2
    assert all(rule.enabled is False for rule in profile_rules)
    assert {rule.origin_ref for rule in profile_rules} == {"movie"}
    assert {rule.trigger.time_at for rule in profile_rules} == {"20:00", "22:30"}


def test_an_app_trigger_becomes_a_rule_pointing_at_a_real_scene() -> None:
    """App Triggers name a built-in preset, not one of the saved scenes an action can
    point at. Without materialising the preset the rule would resolve to a scene that
    does not exist, and quietly never run."""
    plan = plan_migration(_settings())

    rule = next(
        rule for rule in _rules(plan.settings).values() if rule.origin == ORIGIN_APP_TRIGGER
    )
    assert rule.trigger.app == "chrome"
    scene = scene_store.get_scene(plan.settings, rule.action.scene_id)
    assert scene is not None, "the migrated rule points at a scene that does not exist"

    preset = get_scene_preset("cool_white")
    assert scene["state"]["rgb"] == list(preset.rgb)
    assert scene["state"]["brightness"] == preset.brightness
    # Applying a preset also switched the strip on and put it back on static colour.
    assert scene["state"]["power"] is True
    assert scene["state"]["effect"] == {"kind": "firmware", "ref": 0, "speed": None}


def test_the_app_trigger_default_becomes_an_always_rule_that_loses_to_the_rest() -> None:
    plan = plan_migration(_settings())

    rules = _rules(plan.settings)
    default = rules[APP_DEFAULT_ID]
    assert default.trigger.kind == "always"
    assert default.origin == ORIGIN_APP_TRIGGER_DEFAULT
    assert default.priority == DEFAULT_RULE_PRIORITY
    specific = next(rule for rule in rules.values() if rule.origin == ORIGIN_APP_TRIGGER)
    assert default.priority < specific.priority, "the fallback outranked a real rule"


def test_a_preset_this_build_no_longer_has_is_reported_not_guessed() -> None:
    plan = plan_migration(_settings(app_triggers=_triggers(rules=[{"app": "vlc", "scene": "gone"}])))

    assert not [rule for rule in _rules(plan.settings).values() if rule.origin == ORIGIN_APP_TRIGGER]
    assert ("app_trigger:vlc", "unknown_preset") in plan.report.skipped


def test_two_apps_with_similar_names_get_their_own_rules() -> None:
    plan = plan_migration(
        _settings(
            app_triggers=_triggers(
                rules=[{"app": "chrome", "scene": "red"}, {"app": "chrome!", "scene": "blue"}]
            )
        )
    )

    app_rules = [rule for rule in _rules(plan.settings).values() if rule.origin == ORIGIN_APP_TRIGGER]
    assert len(app_rules) == 2
    assert len({rule.id for rule in app_rules}) == 2


def test_several_mappings_share_one_materialized_preset_scene() -> None:
    """A fresh scene planned for one mapping must be reused by the next mapping."""
    plan = plan_migration(
        _settings(
            app_triggers=_triggers(
                default="red",
                rules=[
                    {"app": "chrome", "scene": "red"},
                    {"app": "vlc", "scene": "red"},
                ],
            )
        )
    )

    rules = [
        rule
        for rule in _rules(plan.settings).values()
        if rule.origin in {ORIGIN_APP_TRIGGER, ORIGIN_APP_TRIGGER_DEFAULT}
    ]
    scene_ids = {rule.action.scene_id for rule in rules}
    owned_id = plan.settings["automations"]["preset_scenes"]["red"]

    assert len(rules) == 3
    assert scene_ids == {owned_id}, "one preset was materialized more than once"
    assert sum(
        scene["scene_id"] == owned_id for scene in scene_store.list_scenes(plan.settings)
    ) == 1


# ── never two executors for one trigger ───────────────────────────────
def test_the_old_app_watcher_stands_down() -> None:
    """Both would act on the same foreground app. The rules stay in the file for a
    rollback to find; only the executor is switched off."""
    plan = plan_migration(_settings())

    assert plan.settings["app_triggers"]["enabled"] is False
    assert plan.settings["app_triggers"]["rules"], "the old mappings were thrown away"
    assert "app_triggers" in plan.report.stood_down


def test_the_legacy_schedule_keeps_its_old_tasks_and_gets_no_new_ones() -> None:
    """The 0.3.5 pair is the rollback bridge, so it stays — and the rules it stands
    for must not be given native tasks as well."""
    plan = _bridged()

    assert plan.settings["schedule"]["enabled"] is True, "the bridge was disarmed too early"
    assert plan.report.bridge is True
    assert plan.settings["automations"]["legacy_bridge"] is True


def test_the_bridged_rules_are_kept_out_of_the_task_compiler(monkeypatch) -> None:
    """Two schedulers for one schedule would switch the light twice. The migrated
    schedule rules get native tasks only once the handoff retires the old pair."""
    from app.automation.task_sync import AutomationTaskSync

    migrated = _bridged().settings
    compiled: list[list[str]] = []
    monkeypatch.setattr(
        "app.automation.task_sync.sync_tasks",
        lambda rules, **kwargs: compiled.append([rule.id for rule in rules]) or TaskSyncResult(),
    )
    controller = AutomationTaskSync(lambda: migrated)
    finished: list = []
    controller.finished.connect(finished.append)

    controller.sync()
    _wait_for(finished)

    assert compiled, "the reconciliation never ran"
    assert LEGACY_ON_ID not in compiled[0], "a bridged rule was given a task of its own"
    assert LEGACY_OFF_ID not in compiled[0]
    # The runtime rules are handed over and the compiler declines them itself — the
    # bridge is the one exclusion that has to happen before it, because a bridged
    # rule is otherwise perfectly compilable.


def _wait_for(reported: list, timeout: float = 5.0) -> None:
    """Spin the Qt loop: the controller reports from a worker thread."""
    from time import monotonic, sleep

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    deadline = monotonic() + timeout
    while not reported and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)
    app.processEvents()
    assert reported, "the reconciliation never reported back"


# ── running it more than once ─────────────────────────────────────────
def test_migrating_twice_changes_nothing_the_second_time() -> None:
    first = plan_migration(_settings())

    second = plan_migration(first.settings)

    assert second.report.already_done is True
    assert second.settings["automations"] == first.settings["automations"]


def test_a_run_that_was_interrupted_before_it_finished_completes() -> None:
    """The rules were written but the version was not recorded — a crash between the
    two. Re-running must finish the job without a single duplicate."""
    partial = plan_migration(_settings()).settings
    partial["automations"]["migrated_version"] = 0

    resumed = plan_migration(partial)

    assert resumed.report.already_done is False
    ids = [rule["id"] for rule in resumed.settings["automations"]["rules"]]
    assert len(ids) == len(set(ids)), "a resumed migration duplicated its own rules"
    assert set(ids) == {rule["id"] for rule in partial["automations"]["rules"]}
    assert resumed.settings["automations"]["migrated_version"] == MIGRATION_VERSION


def test_an_edit_the_user_made_to_a_migrated_rule_survives_a_re_run() -> None:
    partial = plan_migration(_settings()).settings
    partial["automations"]["migrated_version"] = 0
    for rule in partial["automations"]["rules"]:
        if rule["id"] == LEGACY_ON_ID:
            rule["trigger"]["time_at"] = "06:30"

    resumed = plan_migration(partial)

    assert _rules(resumed.settings)[LEGACY_ON_ID].trigger.time_at == "06:30"


# ── writing it for real ───────────────────────────────────────────────
def test_migrating_writes_the_rules_and_a_backup_of_what_came_before() -> None:
    storage.save_settings(_settings())

    report = migrate()

    assert report.ok and report.changed
    stored = storage.load_settings()
    assert LEGACY_ON_ID in _rules(stored)
    assert stored["automations"]["migrated_version"] == MIGRATION_VERSION

    backup = json.loads(storage.automation_migration_backup_path().read_text(encoding="utf-8"))
    assert backup["settings"]["app_triggers"]["enabled"] is True, "the backup is post-migration"
    assert backup["settings"]["automations"]["migrated_version"] == 0
    assert "profiles" in backup


def test_the_backup_is_never_replaced_by_a_later_run() -> None:
    storage.save_settings(_settings())
    migrate()
    first = storage.automation_migration_backup_path().read_text(encoding="utf-8")

    storage.save_settings({**storage.load_settings(), "color_temperature": 3000})
    migrate()

    assert storage.automation_migration_backup_path().read_text(encoding="utf-8") == first


def test_a_backup_that_cannot_be_written_stops_the_migration(monkeypatch) -> None:
    """Without a way back, the migration does not happen — and the old executor is
    left exactly as it was."""
    storage.save_settings(_settings())

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk is full")

    monkeypatch.setattr(migration_module, "_write_backup", refuse)

    report = migrate()

    assert report.ok is False
    stored = storage.load_settings()
    assert stored["automations"]["rules"] == [], "rules were written without a backup"
    assert stored["automations"]["migrated_version"] == 0
    assert stored["app_triggers"]["enabled"] is True, "the old executor was stood down anyway"
    assert stored["schedule"]["enabled"] is True


def test_a_failed_write_leaves_the_old_executor_running(monkeypatch) -> None:
    storage.save_settings(_settings())

    def refuse(mutate: Any) -> None:
        raise OSError("settings are locked")

    monkeypatch.setattr(migration_module, "update_settings", refuse)

    report = migrate()

    assert report.ok is False
    stored = storage.load_settings()
    assert stored["app_triggers"]["enabled"] is True
    assert stored["schedule"]["enabled"] is True
    assert stored["automations"]["migrated_version"] == 0


def test_migrating_a_second_time_writes_nothing() -> None:
    storage.save_settings(_settings())
    migrate()
    before = storage.load_settings()

    report = migrate()

    assert report.already_done is True
    assert storage.load_settings() == before


# ── retiring the bridge ───────────────────────────────────────────────
class _FakeTaskSync:
    def __init__(self, result: TaskSyncResult) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    def __call__(self, rules, **kwargs) -> TaskSyncResult:
        self.calls.append([rule.id for rule in rules])
        return self.result


def _migrated(monkeypatch, *, legacy_tasks: bool = True) -> None:
    """Migrate for real, saying whether the 0.3.5 tasks exist on this machine."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: legacy_tasks)
    storage.save_settings(_settings())
    assert migrate().ok


def test_the_old_pair_is_only_removed_after_the_native_tasks_exist(monkeypatch) -> None:
    _migrated(monkeypatch)
    sync = _FakeTaskSync(TaskSyncResult(created=(LEGACY_ON_ID, LEGACY_OFF_ID)))
    monkeypatch.setattr("app.automation.windows_tasks.sync_tasks", sync)
    removed: list[bool] = []

    result = complete_legacy_handoff(remove_legacy=lambda: removed.append(True))

    assert result.done is True
    assert LEGACY_ON_ID in sync.calls[0], "the handoff must compile the bridged rules"
    assert removed == [True]
    stored = storage.load_settings()
    assert stored["automations"]["legacy_bridge"] is False
    assert stored["schedule"]["enabled"] is False, "the old schedule is still an executor"


def test_a_failed_sync_keeps_the_old_tasks(monkeypatch) -> None:
    _migrated(monkeypatch)
    sync = _FakeTaskSync(TaskSyncResult(errors=((LEGACY_ON_ID, "access is denied"),)))
    monkeypatch.setattr("app.automation.windows_tasks.sync_tasks", sync)
    removed: list[bool] = []

    result = complete_legacy_handoff(remove_legacy=lambda: removed.append(True))

    assert result.ok is False
    assert removed == [], "the old pair was removed although the new tasks failed"
    stored = storage.load_settings()
    assert stored["automations"]["legacy_bridge"] is True, "the bridge was taken down anyway"
    assert stored["schedule"]["enabled"] is True


def test_a_sync_that_left_the_schedule_without_a_task_keeps_the_old_pair(monkeypatch) -> None:
    """No error, but nothing was compiled for the bridged rule either — the old pair
    is still the only thing that would run it."""
    _migrated(monkeypatch)
    sync = _FakeTaskSync(TaskSyncResult(created=("something-else",)))
    monkeypatch.setattr("app.automation.windows_tasks.sync_tasks", sync)
    removed: list[bool] = []

    result = complete_legacy_handoff(remove_legacy=lambda: removed.append(True))

    assert result.ok is False
    assert removed == []
    assert storage.load_settings()["automations"]["legacy_bridge"] is True


def test_a_removal_that_failed_leaves_only_a_harmless_extra_wake_up(monkeypatch) -> None:
    """By this point the native tasks exist and the handoff is recorded, so the old
    pair no longer decides anything — it just starts a process that finds the work
    already done. The removal is remembered and tried again later."""
    _migrated(monkeypatch)
    sync = _FakeTaskSync(TaskSyncResult(unchanged=(LEGACY_ON_ID, LEGACY_OFF_ID)))
    monkeypatch.setattr("app.automation.windows_tasks.sync_tasks", sync)

    def refuse() -> None:
        raise OSError("access is denied")

    result = complete_legacy_handoff(remove_legacy=refuse)

    assert result.ok is False
    automations = storage.load_settings()["automations"]
    assert automations["legacy_bridge"] is False, "the handoff was not recorded"
    assert automations["legacy_cleanup_pending"] is True, "the removal was forgotten"


def test_the_owed_removal_is_finished_on_a_later_run(monkeypatch) -> None:
    _migrated(monkeypatch)
    monkeypatch.setattr(
        "app.automation.windows_tasks.sync_tasks",
        _FakeTaskSync(TaskSyncResult(unchanged=(LEGACY_ON_ID, LEGACY_OFF_ID))),
    )
    complete_legacy_handoff(remove_legacy=_raise)
    removed: list[bool] = []

    result = finish_pending_cleanup(remove_legacy=lambda: removed.append(True))

    assert result.done is True
    assert removed == [True]
    assert storage.load_settings()["automations"]["legacy_cleanup_pending"] is False


def test_nothing_is_owed_when_no_handoff_has_happened() -> None:
    result = finish_pending_cleanup(remove_legacy=lambda: pytest.fail("nothing to remove"))

    assert result.nothing_to_do is True


def _raise() -> None:
    raise OSError("access is denied")


def test_a_write_that_failed_leaves_the_old_pair_in_charge(monkeypatch) -> None:
    """The other order — removing first — would leave the user with no schedule at
    all: the old tasks gone, and the next reconciliation taking the new ones away
    again because the bridge flag still said to."""
    _migrated(monkeypatch)
    monkeypatch.setattr(
        "app.automation.windows_tasks.sync_tasks",
        _FakeTaskSync(TaskSyncResult(unchanged=(LEGACY_ON_ID, LEGACY_OFF_ID))),
    )
    monkeypatch.setattr(
        migration_module, "update_settings", lambda mutate: (_ for _ in ()).throw(OSError("locked"))
    )
    removed: list[bool] = []

    result = complete_legacy_handoff(remove_legacy=lambda: removed.append(True))

    assert result.ok is False
    assert removed == [], "the old pair was removed before the handoff was recorded"


def test_a_handoff_with_no_bridge_to_retire_does_nothing(monkeypatch) -> None:
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings(schedule=_schedule(enabled=False)))
    migrate()

    result = complete_legacy_handoff(remove_legacy=lambda: pytest.fail("nothing to remove"))

    assert result.nothing_to_do is True


# ── the legacy command line ───────────────────────────────────────────
def test_the_old_switch_is_handed_to_the_engine_once_migrated(monkeypatch) -> None:
    from app import scheduled_action

    _migrated(monkeypatch)
    woken: list[str] = []
    monkeypatch.setattr(
        "app.automation.headless.run_automations",
        lambda *, woken_by="", **kwargs: woken.append(woken_by) or 0,
    )
    monkeypatch.setattr(
        scheduled_action,
        "_ScheduledActionRunner",
        lambda *args, **kwargs: pytest.fail("the old executor ran alongside the engine"),
    )

    assert scheduled_action.run_scheduled_action("on") == 0
    assert woken == [LEGACY_ON_ID]


def test_the_old_switch_still_works_when_nothing_has_been_migrated(monkeypatch) -> None:
    """A build that never migrated, or a rule the user deleted: the 0.3.5 executor is
    what keeps their schedule working, so it stays in charge."""
    from app import scheduled_action

    storage.save_settings(_settings())
    monkeypatch.setattr(
        "app.automation.headless.run_automations",
        lambda **kwargs: pytest.fail("the engine took a wake-up it does not own"),
    )
    monkeypatch.setattr(scheduled_action, "can_use", lambda feature: False)

    # Reaching the Pro gate proves it went down the old path rather than the engine.
    assert scheduled_action.run_scheduled_action("on") == 3


def test_the_engine_is_not_handed_a_bridge_rule_the_user_disabled(monkeypatch) -> None:
    from app import scheduled_action

    _migrated(monkeypatch)
    settings = storage.load_settings()
    for rule in settings["automations"]["rules"]:
        if rule["id"] == LEGACY_ON_ID:
            rule["enabled"] = False
    storage.save_settings(settings)
    monkeypatch.setattr(
        "app.automation.headless.run_automations",
        lambda **kwargs: pytest.fail("a disabled rule was run"),
    )
    monkeypatch.setattr(scheduled_action, "can_use", lambda feature: False)

    assert scheduled_action.run_scheduled_action("on") == 3


# ── the scenes a migration makes are its own ──────────────────────────
def test_a_user_scene_with_the_same_name_is_not_replaced() -> None:
    """The store treats a matching name as the same scene, which is how a migration
    could overwrite something it did not create — and then point its rule at the id
    of the scene it destroyed."""
    settings = _settings()
    mine = scene_store.save_scene(
        settings, {"name": "Cool white", "state": {"rgb": [1, 2, 3], "brightness": 7}}
    )

    plan = plan_migration(settings)

    kept = scene_store.get_scene(plan.settings, mine["scene_id"])
    assert kept is not None, "the user's scene was removed"
    assert kept["state"]["rgb"] == [1, 2, 3], "the user's scene was overwritten"
    rule = next(
        rule for rule in _rules(plan.settings).values() if rule.origin == ORIGIN_APP_TRIGGER
    )
    assert rule.action.scene_id != mine["scene_id"], "the rule points at the user's scene"
    assert scene_store.get_scene(plan.settings, rule.action.scene_id) is not None


def test_a_scene_that_only_looks_like_ours_is_stepped_over() -> None:
    """An imported scene can carry any id, including one shaped like the ones this
    migration hands out. Ownership is what was recorded, not what an id looks like."""
    settings = _settings()
    settings["scenes"] = []
    scene_store.save_scene(
        settings,
        {"scene_id": "preset-cool_white", "name": "Someone else's", "state": {"rgb": [9, 9, 9]}},
    )

    plan = plan_migration(settings)

    rule = next(
        rule for rule in _rules(plan.settings).values() if rule.origin == ORIGIN_APP_TRIGGER
    )
    assert rule.action.scene_id != "preset-cool_white", "an unrelated scene was claimed"
    migrated = scene_store.get_scene(plan.settings, rule.action.scene_id)
    assert migrated["state"]["rgb"] == list(get_scene_preset("cool_white").rgb)
    assert plan.settings["automations"]["preset_scenes"]["cool_white"] == rule.action.scene_id


def test_a_full_scene_store_migrates_no_app_triggers_at_all(monkeypatch) -> None:
    """Half the triggers migrated and the watcher switched off is the one outcome
    with no honest story — and no preset scene may be left behind either."""
    monkeypatch.setattr(scene_store, "MAX_SCENES", 1)
    settings = _settings(
        app_triggers=_triggers(
            default="warm_white", rules=[{"app": "chrome", "scene": "cool_white"}]
        )
    )
    settings["scenes"] = []
    scene_store.save_scene(settings, {"name": "The only one", "state": {"rgb": [1, 2, 3]}})

    plan = plan_migration(settings)

    assert not [
        rule for rule in _rules(plan.settings).values() if rule.origin == ORIGIN_APP_TRIGGER
    ]
    assert plan.settings["app_triggers"]["enabled"] is True, "the watcher was stood down anyway"
    assert [scene["name"] for scene in scene_store.list_scenes(plan.settings)] == ["The only one"]
    assert ("app_trigger:chrome", "no_room_for_scene") in plan.report.skipped


def test_the_same_preset_scene_is_reused_on_a_second_migration() -> None:
    first = plan_migration(_settings())
    settings = first.settings
    settings["automations"]["migrated_version"] = 0

    second = plan_migration(settings)

    assert len(scene_store.list_scenes(second.settings)) == len(
        scene_store.list_scenes(first.settings)
    ), "a re-run made a second copy of the preset scene"
