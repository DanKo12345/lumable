"""Turning the 0.3.5 schedule and App Triggers into automation rules.

Three sources, and they are not alike:

* **The global schedule** — one on-time and one off-time on chosen weekdays. It is
  the only one that already runs with the app closed, through a pair of Windows
  tasks. Those tasks stay: they are the rollback bridge for 0.3.5, and 0.3.6 keeps
  them working by routing ``--scheduled-action`` into the new engine instead of
  replacing them. So the rules it produces are marked as belonging to that bridge
  and are deliberately *not* given native tasks of their own — two schedulers for
  one schedule would switch the light twice.
* **Schedules saved inside profiles** — these were never independently live. Loading
  a profile copies its schedule over the global one, so migrating them as active
  rules would have every profile's schedule firing at once. They become *disabled*
  rules that name their profile, ready for the profile system to switch on.
* **App Triggers** — "when this app is in front, apply this look". The look is a
  built-in *preset* (a colour and a brightness), not one of the saved scenes an
  automation action can point at, so the migration first materialises each preset
  it needs as a real scene. Without that every migrated trigger would resolve to a
  scene that does not exist and quietly never run.

The shape of the whole thing is: a pure function from the old settings to the new
ones plus a report, then one atomic write, and only then anything external. Nothing
here deletes an old block. The old data stays where 0.3.5 looks for it, and the
only thing switched off is the old *executor* of what has just been migrated —
otherwise both would act on the same trigger.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app import scene_store
from app.automation.rules import (
    ACTION_APPLY_SCENE,
    ACTION_SET_POWER,
    EXECUTION_BACKGROUND,
    EXECUTION_RUNTIME,
    ORIGIN_APP_TRIGGER,
    ORIGIN_APP_TRIGGER_DEFAULT,
    ORIGIN_LEGACY_SCHEDULE,
    ORIGIN_PROFILE_SCHEDULE,
    TRIGGER_ALWAYS,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_TIME,
    Rule,
    rule_to_dict,
    validate_rule,
    validate_rules,
)
from app.scene_presets import get_scene_preset
from app.scenes import make_scene, wrap_scene
from app.storage import (
    automation_migration_backup_path,
    load_profiles,
    load_settings,
    update_settings,
    validate_automations,
    validate_schedule,
)

MIGRATION_VERSION = 1
BACKUP_VERSION = 1

# The keys a migration writes. A caller holding settings in memory — the window does
# — has to take exactly these across afterwards, or it goes on running against the
# state from before and saves it back over the migration on the way out.
MIGRATED_KEYS = ("automations", "scenes", "app_triggers")

# The fallback App Trigger applies whenever nothing more specific matches, which is
# exactly what the resolver's "always" trigger is — at a priority low enough that
# any real rule outranks it.
DEFAULT_RULE_PRIORITY = -50

# Stable ids, so a second migration recognises what the first one made instead of
# making it again.
LEGACY_ON_ID = "legacy-schedule-on"
LEGACY_OFF_ID = "legacy-schedule-off"
APP_DEFAULT_ID = "app-trigger-default"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class MigrationReport:
    """What a migration did, or would do. Everything is ids, never objects."""

    rules: tuple[str, ...] = ()
    scenes: tuple[str, ...] = ()
    # The old subsystems switched off because the new engine now owns them.
    stood_down: tuple[str, ...] = ()
    # True while the 0.3.5 task pair is still the thing that wakes the machine.
    bridge: bool = False
    skipped: tuple[tuple[str, str], ...] = ()
    errors: tuple[tuple[str, str], ...] = ()
    already_done: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.rules or self.scenes or self.stood_down)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class MigrationPlan:
    """The new settings, and what it took to get there. Nothing is written yet."""

    settings: dict[str, Any] = field(default_factory=dict)
    report: MigrationReport = field(default_factory=MigrationReport)


# ── the pure part ─────────────────────────────────────────────────────
def plan_migration(
    settings: dict[str, Any],
    profiles: list[dict[str, Any]] | None = None,
    *,
    legacy_tasks_present: bool = False,
) -> MigrationPlan:
    """Old settings in, migrated settings and a report out. No I/O, no mutation.

    ``legacy_tasks_present`` is whether the 0.3.5 pair is actually on the machine.
    It decides two things that would otherwise be guesses: whether the migrated
    schedule may run with the app closed at all, and whether there is a bridge to
    keep up. The caller establishes it — asking Windows is not this function's job.

    Idempotent by construction: every rule and scene it creates has a derived id, so
    running it again — including after a run that was interrupted before the version
    was recorded — recognises its own work rather than duplicating it.
    """
    settings = json.loads(json.dumps(settings if isinstance(settings, dict) else {}))
    automations = validate_automations(settings.get("automations", {}))
    existing = {rule.id: rule for rule in validate_rules(automations.get("rules", []))}

    if int(automations.get("migrated_version", 0) or 0) >= MIGRATION_VERSION:
        return MigrationPlan(settings=settings, report=MigrationReport(already_done=True))

    rules: list[Rule] = []
    skipped: list[tuple[str, str]] = []
    stood_down: list[str] = []

    schedule_rules, schedule_skips = _from_global_schedule(
        settings.get("schedule"), background=legacy_tasks_present
    )
    rules.extend(schedule_rules)
    skipped.extend(schedule_skips)

    rules.extend(_from_profiles(profiles or []))

    triggers = _from_app_triggers(settings.get("app_triggers"), settings)
    rules.extend(triggers.rules)
    skipped.extend(triggers.skipped)

    # Only what is genuinely new: a rule the user has since edited keeps their edit,
    # and a re-run adds nothing.
    fresh = [rule for rule in rules if rule.id not in existing]
    merged = list(existing.values()) + fresh

    app_triggers = settings.get("app_triggers")
    if isinstance(app_triggers, dict) and app_triggers.get("enabled") and triggers.rules:
        # The old watcher and the new engine would both act on the same foreground
        # app. The data stays exactly where it is; only the executor stands down —
        # and only because everything it was watching for did make it across.
        app_triggers["enabled"] = False
        stood_down.append("app_triggers")

    # A bridge only exists where the old pair does. With no tasks on the machine the
    # schedule was an app-open feature, and it stays one.
    bridge = bool(legacy_tasks_present) and any(
        rule.enabled and rule.origin == ORIGIN_LEGACY_SCHEDULE for rule in merged
    )
    settings["automations"] = {
        "enabled": bool(automations.get("enabled")) or any(rule.enabled for rule in merged),
        "rules": [rule_to_dict(rule) for rule in merged],
        "migrated_version": MIGRATION_VERSION,
        # While this is set, the 0.3.5 task pair is still what wakes the machine and
        # the rules it stands for get no tasks of their own.
        "legacy_bridge": bridge,
        "legacy_cleanup_pending": bool(automations.get("legacy_cleanup_pending")),
        # Which scene each preset became. Ownership is recorded, never inferred from
        # the shape of an id — an imported scene could carry one of ours.
        "preset_scenes": triggers.preset_scenes,
    }
    return MigrationPlan(
        settings=settings,
        report=MigrationReport(
            rules=tuple(rule.id for rule in fresh),
            scenes=tuple(triggers.scenes),
            stood_down=tuple(stood_down),
            bridge=bridge,
            skipped=tuple(skipped),
        ),
    )


def _from_global_schedule(
    raw: Any, *, background: bool
) -> tuple[list[Rule], list[tuple[str, str]]]:
    """The global schedule as two power rules.

    ``background`` mirrors the user's existing choice rather than improving on it: a
    schedule with the 0.3.5 tasks in place ran with the app closed and keeps doing
    so, and one without them was an app-open feature. Promoting the second kind to
    background would start switching their light at times the app was never open —
    a change nobody asked for.
    """
    schedule = validate_schedule(raw)
    days = tuple(int(day) for day in schedule.get("days", ()) if 0 <= int(day) <= 6)
    enabled = bool(schedule.get("enabled"))
    if not days:
        # The old schedule with no weekday could never fire; a rule that can never
        # come round would only be a puzzle in the list.
        return [], [("schedule", "no_days")]
    execution = EXECUTION_BACKGROUND if background else EXECUTION_RUNTIME
    rules = [
        _power_rule(
            rule_id=LEGACY_ON_ID,
            name="Schedule on",
            time_text=str(schedule.get("on_time", "")),
            days=days,
            power=True,
            enabled=enabled,
            origin=ORIGIN_LEGACY_SCHEDULE,
            execution=execution,
        ),
        _power_rule(
            rule_id=LEGACY_OFF_ID,
            name="Schedule off",
            time_text=str(schedule.get("off_time", "")),
            days=days,
            power=False,
            enabled=enabled,
            origin=ORIGIN_LEGACY_SCHEDULE,
            execution=execution,
        ),
    ]
    return [rule for rule in rules if rule is not None], []


def _from_profiles(profiles: list[dict[str, Any]]) -> list[Rule]:
    """Profile schedules, as rules that are switched off.

    A profile's schedule only ever applied while that profile was loaded — loading
    one copies its schedule over the global one. Migrated as live rules they would
    all fire at once, so they arrive disabled, named after their profile, for the
    profile system to switch on when it takes this over.
    """
    rules: list[Rule] = []
    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict) or "schedule" not in profile:
            continue
        schedule = validate_schedule(profile.get("schedule"))
        days = tuple(int(day) for day in schedule.get("days", ()) if 0 <= int(day) <= 6)
        if not days:
            continue
        reference = str(profile.get("preset_key") or profile.get("name") or index).strip()
        slug = _slug(reference) or f"profile{index}"
        label = str(profile.get("name") or reference)[:40]
        for suffix, power, time_key in (("on", True, "on_time"), ("off", False, "off_time")):
            rule = _power_rule(
                rule_id=f"profile-{slug}-{suffix}",
                name=f"{label}: {suffix}",
                time_text=str(schedule.get(time_key, "")),
                days=days,
                power=power,
                enabled=False,
                origin=ORIGIN_PROFILE_SCHEDULE,
                origin_ref=reference,
            )
            if rule is not None:
                rules.append(rule)
    return rules


def _plan_preset_scenes(
    keys: list[str], settings: dict[str, Any], owned: dict[str, str]
) -> tuple[dict[str, str], list[dict[str, Any]], list[str]] | None:
    """Work out a scene for every preset needed, or decide none of them fit.

    All or nothing on purpose. Committing scenes one at a time and then finding the
    store full leaves preset scenes in the user's list for triggers that were never
    migrated — half a migration, with the tidying left to them.

    ``owned`` is the mapping this migration has written before, so a scene is known
    to be ours because we recorded making it — not because its id looks like ours.
    An id that turns out to belong to someone else's scene is stepped over.
    """
    stored = {scene["scene_id"]: scene for scene in scene_store.list_scenes(settings)}
    room = scene_store.MAX_SCENES - len(stored)
    mapping = dict(owned)
    fresh: list[dict[str, Any]] = []
    unknown: list[str] = []
    # Several app mappings commonly use the same preset. Plan that preset once:
    # otherwise the first fresh scene is not in ``stored`` yet, so a second use
    # would allocate another id, overwrite the mapping, and orphan the first.
    for key in dict.fromkeys(keys):
        preset = get_scene_preset(key)
        if preset is None:
            unknown.append(key)
            continue
        scene_id = mapping.get(key)
        if scene_id and scene_id in stored:
            continue  # ours from an earlier run, left exactly as the user has it
        scene_id = _free_scene_id(key, stored, set(mapping.values()))
        scene = _preset_scene(key, scene_id, settings, stored)
        if scene is None:
            continue
        mapping[key] = scene_id
        fresh.append(scene)
        if len(fresh) > room:
            # No room for the whole set, so the set does not happen.
            return None
    return mapping, fresh, unknown


def _free_scene_id(key: str, stored: dict[str, Any], claimed: set[str]) -> str:
    """A deterministic id for this preset that nothing else already answers to."""
    base = f"preset-{_slug(key)}"[:32]
    if base not in stored and base not in claimed:
        return base
    for suffix in range(2, 20):
        candidate = f"{base}-{suffix}"[:32]
        if candidate not in stored and candidate not in claimed:
            return candidate
    return f"{base}-{_digest(key)}"[:32]  # pragma: no cover - twenty collisions


def _from_app_triggers(raw: Any, settings: dict[str, Any]) -> _AppTriggerMigration:
    """App Trigger mappings, and the scenes they need in order to exist at all.

    Scenes are stored as they are resolved, because the id a rule must point at is
    the one the store actually gave out. If the store is full, the mapping cannot be
    represented — and rather than leave the user with some of their triggers
    migrated and the rest silently gone, the whole App Trigger migration stands
    down, old watcher and all.
    """
    config = raw if isinstance(raw, dict) else {}
    enabled = bool(config.get("enabled"))
    rules: list[Rule] = []
    skipped: list[tuple[str, str]] = []
    owned = _owned_preset_scenes(settings)

    entries = config.get("rules")
    wanted: list[tuple[str, str, str]] = []  # (subject, app, preset key)
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, dict):
            continue
        app = str(item.get("app", "")).strip().lower()
        if not app:
            continue
        wanted.append((f"app_trigger:{app}", app, str(item.get("scene", "")).strip()))
    default_key = str(config.get("default", "")).strip()
    if default_key:
        wanted.append(("app_trigger:default", "", default_key))

    planned = _plan_preset_scenes([key for _subject, _app, key in wanted], settings, owned)
    if planned is None:
        # Half a migration is the one outcome with no honest story: the old watcher
        # would be switched off for mappings that never made it across.
        return _AppTriggerMigration(
            rules=[],
            scenes=[],
            skipped=[(subject, "no_room_for_scene") for subject, _app, _key in wanted],
            blocked=True,
            preset_scenes=owned,
        )
    mapping, fresh, unknown = planned
    for scene in fresh:
        settings.setdefault(scene_store.SCENES_KEY, []).append(wrap_scene(scene))

    for subject, app, key in wanted:
        if key in unknown:
            # A preset this build no longer has. Dropping the mapping is honest: it
            # could not have applied anything anyway.
            skipped.append((subject, "unknown_preset"))
            continue
        scene_id = mapping[key]
        if not app:
            continue  # the fallback, built below
        rule = _rule(
            {
                "id": f"app-{_slug(app)}-{_digest(app)}",
                "name": f"App: {app}",
                "trigger": {"kind": TRIGGER_APP_FOREGROUND, "app": app},
                "action": {"type": ACTION_APPLY_SCENE, "scene_id": scene_id},
                "execution": EXECUTION_RUNTIME,
                "enabled": enabled,
                "origin": ORIGIN_APP_TRIGGER,
                "origin_ref": app,
            }
        )
        if rule is None:
            skipped.append((f"app_trigger:{app}", "invalid_rule"))
            continue
        rules.append(rule)

    if default_key and default_key not in unknown:
        rule = _rule(
            {
                "id": APP_DEFAULT_ID,
                "name": "App default",
                "trigger": {"kind": TRIGGER_ALWAYS},
                "action": {"type": ACTION_APPLY_SCENE, "scene_id": mapping[default_key]},
                "execution": EXECUTION_RUNTIME,
                # Always true, so it must lose to everything that is not: it is the
                # fallback, and the resolver settles that by priority.
                "priority": DEFAULT_RULE_PRIORITY,
                "enabled": enabled,
                "origin": ORIGIN_APP_TRIGGER_DEFAULT,
            }
        )
        if rule is not None:
            rules.append(rule)
    return _AppTriggerMigration(
        rules=rules,
        scenes=[scene["scene_id"] for scene in fresh],
        skipped=skipped,
        blocked=False,
        preset_scenes=mapping,
    )


@dataclass(frozen=True)
class _AppTriggerMigration:
    rules: list[Rule]
    scenes: list[str]
    skipped: list[tuple[str, str]]
    blocked: bool
    # preset key -> the scene id this migration gave it. Recorded rather than
    # re-derived, so a scene is ours because we made it, not because its id looks
    # the way ours do.
    preset_scenes: dict[str, str]


def _rule(data: dict[str, Any]) -> Rule | None:
    """Build a rule the way a stored one is built — through the schema.

    Constructing :class:`Rule` directly would let the migration write something
    ``validate_rules`` rejects on the next read, and the rule would vanish without
    anyone being told. Anything the schema will not take is dropped here instead,
    where it can be reported.
    """
    return validate_rule(data)


def _power_rule(
    *,
    rule_id: str,
    name: str,
    time_text: str,
    days: tuple[int, ...],
    power: bool,
    enabled: bool,
    origin: str,
    origin_ref: str = "",
    execution: str = EXECUTION_RUNTIME,
) -> Rule | None:
    return _rule(
        {
            "id": rule_id,
            "name": name,
            "trigger": {"kind": TRIGGER_TIME, "time_at": time_text, "days": list(days)},
            "action": {"type": ACTION_SET_POWER, "power": power, "target": "primary"},
            "execution": execution,
            "enabled": enabled,
            "origin": origin,
            "origin_ref": origin_ref,
        }
    )


def _preset_scene(
    key: str, scene_id: str, settings: dict[str, Any], stored: dict[str, Any]
) -> dict[str, Any] | None:
    """The saved scene that stands for a built-in preset.

    The state mirrors what applying the preset did: colour, brightness, the static
    effect, and the strip switched on so the look is actually visible.

    Never written through ``scene_store.save_scene``, which also matches on the
    *name*: a user scene called "Warm white" would be replaced by a preset of the
    same name, and the rule would then point at the id of the scene it destroyed.
    The name here is only used when it is free.
    """
    preset = get_scene_preset(key)
    if preset is None:
        return None
    red, green, blue = preset.rgb
    return make_scene(
        _preset_scene_name(key, stored),
        {
            "power": True,
            "rgb": [red, green, blue],
            "brightness": preset.brightness,
            "effect": {"kind": "firmware", "ref": 0, "speed": None},
        },
        scene_id=scene_id,
    )


def _preset_scene_name(key: str, stored: dict[str, Any]) -> str:
    name = str(key).replace("_", " ").strip().capitalize()[:40]
    taken = {scene["name"].casefold() for scene in stored.values()}
    if name.casefold() not in taken:
        return name
    return f"{name} (preset)"[:40]


def _owned_preset_scenes(settings: dict[str, Any]) -> dict[str, str]:
    """Which scenes this migration made, as it recorded at the time."""
    automations = settings.get("automations")
    raw = automations.get("preset_scenes") if isinstance(automations, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if key and value}


def _slug(value: str) -> str:
    return _UNSAFE.sub("-", str(value).strip().lower())[:32].strip("-")


def _digest(value: str) -> str:
    """Keeps two similar app fragments from claiming the same rule id."""
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:6]


# ── the part that writes ──────────────────────────────────────────────
def migrate() -> MigrationReport:
    """Plan, back up, then write — in that order, and only that order.

    The plan is made twice: once cheaply to see whether there is anything to do at
    all, and then again *inside* the settings lock, against what is actually on disk
    at that moment. Planning is pure and fast, so this costs nothing and means a
    change the user made while we were thinking cannot be written over.

    Nothing external happens here. The Windows tasks are reconciled afterwards by
    whoever asked for the migration, once the new rules are safely on disk — and if
    any step fails, the old blocks are untouched and the old executor still runs.
    """
    try:
        profiles = load_profiles()
        legacy_tasks = legacy_tasks_present()
        preview = plan_migration(load_settings(), profiles, legacy_tasks_present=legacy_tasks)
    except Exception as exc:
        return MigrationReport(errors=(("plan", str(exc)),))
    if preview.report.already_done:
        return preview.report

    reported: list[MigrationReport] = []

    def apply(stored: dict[str, Any]) -> None:
        plan = plan_migration(stored, profiles, legacy_tasks_present=legacy_tasks)
        reported.append(plan.report)
        if plan.report.already_done:
            return  # someone migrated while we waited for the lock
        # Before a single key changes, and only the first time: this is the state
        # someone reaching for a backup would want to find.
        if plan.report.changed:
            _write_backup(stored, profiles)
        # Written even when there was nothing to migrate. Otherwise a clean install
        # plans the same nothing on every launch and never records that it is done.
        for key in MIGRATED_KEYS:
            if key in plan.settings:
                stored[key] = plan.settings[key]

    try:
        update_settings(apply)
    except Exception as exc:
        # Includes a backup that could not be written: without a way back, the
        # migration does not happen at all.
        return MigrationReport(errors=(("write", str(exc)),))
    return reported[-1] if reported else preview.report


# ── retiring the bridge ───────────────────────────────────────────────
@dataclass(frozen=True)
class HandoffResult:
    """What became of an attempt to retire the 0.3.5 task pair."""

    done: bool = False
    nothing_to_do: bool = False
    errors: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def complete_legacy_handoff(
    *,
    scheduler: Any = None,
    remove_legacy: Any = None,
) -> HandoffResult:
    """Move the schedule from the 0.3.5 tasks to native ones. Explicit, never automatic.

    What made this unsafe to offer was that it switches the in-app schedule off,
    leaving the migrated rule to a separate headless process — which cannot take the
    strip while the app has it. Since :mod:`app.automation.runtime` began running
    background rules itself, under the same lock and handled-occurrence record, that
    is no longer true: with the app open the runtime carries them out, with it closed
    the tasks do, and the arbitration decides between them. The result is what 0.3.5
    did and a working schedule with the app closed besides.

    Still explicit, and still never automatic: it retires the rollback bridge, and
    that is the user's decision to make rather than a consequence of starting the
    app.

    The order is the whole safety argument:

    1. compile the migrated rules into native tasks, *with* the bridge rules this
       time, and prove they exist;
    2. only then take the old pair off the machine;
    3. only then record that the bridge is down.

    Between (1) and (2) both sets of tasks exist, and that is safe rather than
    lucky: each is only a wake-up, and the engine's handled-occurrence record and
    execution lock mean the rule is carried out once however many times it is woken.

    Any failure leaves the old pair in place and the bridge flag up, so the schedule
    keeps working exactly as it did and a later attempt starts from the same state.
    """
    from app.automation.windows_tasks import sync_tasks

    settings = load_settings()
    automations = validate_automations(settings.get("automations", {}))
    if not automations.get("legacy_bridge"):
        return HandoffResult(nothing_to_do=True)

    rules = validate_rules(automations.get("rules", []))
    bridge_ids = {rule.id for rule in rules if rule.origin == ORIGIN_LEGACY_SCHEDULE and rule.enabled}
    result = sync_tasks(rules, scheduler=scheduler)
    if not result.ok:
        return HandoffResult(errors=result.errors)
    if not result.available:
        return HandoffResult(errors=(("tasks", "this machine has no task scheduler"),))
    compiled = set(result.created) | set(result.updated) | set(result.unchanged)
    missing = sorted(bridge_ids - compiled)
    if missing:
        # The native task for the schedule is not there, so the old pair is still
        # the only thing that would run it.
        return HandoffResult(errors=tuple((rule_id, "no native task was created") for rule_id in missing))

    def apply(stored: dict[str, Any]) -> None:
        block = validate_automations(stored.get("automations", {}))
        block["legacy_bridge"] = False
        # Set before the old pair is touched, so a removal that fails is something a
        # later run can finish rather than something nobody remembers to do.
        block["legacy_cleanup_pending"] = True
        stored["automations"] = block
        # The old schedule is no longer an executor. It stays in the file so the
        # times are not lost, but nothing acts on it any more — which is what makes
        # this a handoff rather than a second copy of the same schedule.
        schedule = validate_schedule(stored.get("schedule", {}))
        schedule["enabled"] = False
        stored["schedule"] = schedule

    # The write comes before the removal, and that order is the whole argument. If it
    # fails, the bridge is still up and the old pair still runs the schedule. If it
    # succeeded and the removal then fails, all that is left behind is a pair of
    # harmless extra wake-ups — the engine decides what to do once, whoever woke it.
    # The other way round, a failed write after a successful removal would leave the
    # user with no schedule at all: the old tasks gone, and the next reconciliation
    # taking the new ones away again because the bridge flag said to.
    try:
        update_settings(apply)
    except Exception as exc:
        return HandoffResult(errors=(("write", str(exc)),))

    return finish_pending_cleanup(remove_legacy=remove_legacy)


def finish_pending_cleanup(*, remove_legacy: Any = None) -> HandoffResult:
    """Take the 0.3.5 pair off the machine, if that is still owed.

    Split out so a startup can retry it: the flags are already written by then, so
    the only thing left is a removal that may have failed while Windows was busy.
    """
    settings = load_settings()
    automations = validate_automations(settings.get("automations", {}))
    if not automations.get("legacy_cleanup_pending"):
        return HandoffResult(nothing_to_do=True)
    try:
        _remove_legacy_tasks(remove_legacy)
    except Exception as exc:
        # The marker stays, so this is tried again. Meanwhile the old tasks only
        # wake a process that finds the work already done.
        return HandoffResult(errors=(("legacy_tasks", str(exc)),))

    def clear(stored: dict[str, Any]) -> None:
        block = validate_automations(stored.get("automations", {}))
        block["legacy_cleanup_pending"] = False
        stored["automations"] = block

    try:
        update_settings(clear)
    except Exception as exc:
        # The tasks are gone, which is what mattered; the marker costs one extra
        # removal attempt next time and nothing else.
        return HandoffResult(errors=(("write", str(exc)),))
    return HandoffResult(done=True)


def _remove_legacy_tasks(remove_legacy: Any = None) -> None:
    if remove_legacy is not None:
        remove_legacy()
        return
    from app.startup_controller import set_schedule_tasks_enabled

    # The times are ignored when disabling; the call only deletes the pair.
    set_schedule_tasks_enabled(False, on_time="19:00", off_time="23:00")


def _write_backup(settings: dict[str, Any], profiles: list[dict[str, Any]] | None = None) -> None:
    """Keep the state from before the first migration, and only that.

    Never overwritten: a second run must not replace the original with a copy of
    the already-migrated settings, which is exactly what someone reaching for a
    backup would not want to find.
    """
    path = automation_migration_backup_path()
    if path.exists():
        return
    payload = {
        "version": BACKUP_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "settings": settings,
        "profiles": load_profiles() if profiles is None else profiles,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Through a temporary file: a backup half written by an interrupted run would be
    # kept for ever by the rule above, and it is the one file that has to be whole.
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - nothing more we can do
            pass
        raise


def resync_legacy_schedule_rules(settings: dict[str, Any]) -> bool:
    """Bring the migrated schedule rules back in step with the schedule block.

    The old schedule is still edited in two places after a migration: its own
    controls, and loading a profile — which copies that profile's schedule over the
    global one. Either way the rules derived from it would otherwise keep the times
    they were migrated with, and the light would follow whichever of the two the
    user was not looking at.

    Mutates ``settings`` in place and returns whether anything changed, so the
    caller can decide whether it needs to save.
    """
    automations = validate_automations(settings.get("automations", {}))
    if int(automations.get("migrated_version", 0) or 0) < MIGRATION_VERSION:
        return False  # nothing has been migrated, so nothing derives from it
    rules = validate_rules(automations.get("rules", []))
    if not any(rule.origin == ORIGIN_LEGACY_SCHEDULE for rule in rules):
        return False

    # Keep whatever the rules already are — background or runtime — since that
    # reflects whether this schedule ever had Windows tasks behind it.
    background = any(
        rule.origin == ORIGIN_LEGACY_SCHEDULE and rule.runs_in_background for rule in rules
    )
    replacements = {
        rule.id: rule
        for rule in _from_global_schedule(settings.get("schedule"), background=background)[0]
    }
    updated = [replacements.get(rule.id, rule) if rule.origin == ORIGIN_LEGACY_SCHEDULE else rule for rule in rules]
    if updated == rules:
        return False
    automations["rules"] = [rule_to_dict(rule) for rule in updated]
    automations["enabled"] = bool(automations.get("enabled")) or any(
        rule.enabled for rule in updated
    )
    settings["automations"] = automations
    return True


def legacy_tasks_present() -> bool:
    """Whether the 0.3.5 schedule tasks are actually on this machine.

    Asked of Windows rather than inferred from ``schedule.enabled``: the pair is
    created separately, so a schedule can be switched on with no tasks behind it —
    and treating that as a bridge would keep the migrated rules out of the task
    compiler with nothing left to wake them.

    One task is enough to count. A half-created pair still fires, and calling that
    "no bridge" is how the machine would end up with two things switching one light.
    """
    try:
        from app.startup_controller import schedule_tasks_present

        return bool(schedule_tasks_present())
    except Exception:
        return False
