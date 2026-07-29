"""The executor that turns a decision into real BLE work, and one verdict.

Each test is phrased as the consequence for the user: whether the rule counts as
having done its job, which strips were actually written to, and whether anything
can be left hanging. No hardware and no Qt loop are involved — the fake controller
answers on the spot, which is exactly the ordering the real queued delivery makes
impossible, so the accounting is pinned rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import count
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal

from app.automation import ble_executor as ble_executor_module
from app.automation.ble_executor import (
    CODE_APPLY_FAILED,
    CODE_MISSING_SCENE,
    BleActionExecutor,
)
from app.automation.resolver import Decision
from app.automation.rules import (
    ACTION_APPLY_SCENE,
    ACTION_SET_POWER,
    TRIGGER_ALWAYS,
    Action,
    Rule,
    Trigger,
)
from app.automation.scene_group import CODE_CANCELLED, CODE_UNAVAILABLE
from app.scenes import make_scene

SCENE_ID = "scene-1"
PRIMARY = "AA:BB:CC:DD:EE:01"
MIRROR = "AA:BB:CC:DD:EE:02"


@dataclass(frozen=True)
class _Submitted:
    operation_id: int
    kind: str
    address: str
    payload: Any = None


@dataclass(frozen=True)
class _Result:
    operation_id: int
    ok: bool
    code: str


class FakeBle(QObject):
    """The tracked half of BleController, minus the BLE thread.

    Results are emitted straight from ``finish()`` so a test controls the exact
    interleaving. Every tracked submit answers exactly once, which is the
    guarantee the real controller is pinned to in test_ble_tracked_operations.
    """

    operation_finished = Signal(object)

    def __init__(self, *addresses: str) -> None:
        super().__init__()
        self.primary = addresses[0] if addresses else ""
        self.mirrors = list(addresses[1:])
        self.submitted: list[_Submitted] = []
        self.cancelled: list[int] = []
        self.raises: set[str] = set()  # kinds whose submit blows up
        self.answer_without_id: set[str] = set()  # kinds that break the id contract
        self._ids = count(1)

    def primary_address(self) -> str:
        return self.primary

    def mirror_addresses(self) -> list[str]:
        return list(self.mirrors)

    def set_power_for_address_tracked(self, enabled: bool, address: str) -> int:
        return self._submit("power", address, bool(enabled))

    def set_color_for_address_tracked(self, red: int, green: int, blue: int, address: str) -> int:
        return self._submit("color", address, (red, green, blue))

    def set_brightness_for_address_tracked(self, value: int, address: str) -> int:
        return self._submit("brightness", address, value)

    def set_effect_for_address_tracked(self, code: int, speed: int | None, address: str) -> int:
        return self._submit("effect", address, (code, speed))

    def cancel_operation(self, operation_id: int) -> bool:
        self.cancelled.append(operation_id)
        return True  # request accepted; says nothing about what already landed

    def _submit(self, kind: str, address: str, payload: Any) -> int | None:
        if kind in self.raises:
            raise RuntimeError(f"{kind} could not be submitted")
        if kind in self.answer_without_id:
            return None
        operation_id = next(self._ids)
        self.submitted.append(_Submitted(operation_id, kind, address, payload))
        return operation_id

    # ── the controller answering ──────────────────────────────────────
    def finish(self, operation_id: int, *, ok: bool = True, code: str = "") -> None:
        self.operation_finished.emit(
            _Result(operation_id, ok, code or ("success" if ok else "ble_error"))
        )

    def finish_all(self, *, ok: bool = True, code: str = "", address: str | None = None) -> None:
        for entry in list(self.submitted):
            if address is None or entry.address == address:
                self.finish(entry.operation_id, ok=ok, code=code)

    def steps(self) -> list[tuple[str, str]]:
        return [(entry.kind, entry.address) for entry in self.submitted]


class PcMode:
    """Stands in for the app's global streaming modes: synchronous, one answer."""

    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, str | None]] = []

    def set(self, mode: str, preset: str | None) -> bool:
        self.calls.append((mode, preset))
        if mode == "off":
            return True  # stopping a stream always works
        return self.allow


@pytest.fixture(autouse=True)
def faults(monkeypatch) -> list[str]:
    """Catch the crash reports instead of writing them to the user's real log dir.

    Also the assertion channel: a broken dispatch has to be *reported*, not just
    turned into a failed run.
    """
    reported: list[str] = []
    monkeypatch.setattr(
        ble_executor_module,
        "write_current_exception",
        lambda context="": reported.append(context),
    )
    return reported


def _scene(state: dict[str, Any], *, target: dict[str, Any] | None = None) -> dict[str, Any]:
    return make_scene("Evening", state, target=target or {"kind": "all", "group_id": None})


def _executor(
    ble: FakeBle,
    *,
    scene: dict[str, Any] | None = None,
    resolve: Any = None,
    capabilities_for: Any = None,
    pc_mode: PcMode | None = None,
) -> BleActionExecutor:
    return BleActionExecutor(
        ble,
        scene_for=lambda scene_id: scene if scene_id == SCENE_ID else None,
        # None is the resolver's shorthand for "every connected strip"; the
        # executor is the one that has to expand it.
        resolve_targets=resolve if resolve is not None else (lambda target: None),
        capabilities_for=capabilities_for,
        set_pc_mode=pc_mode.set if pc_mode is not None else None,
    )


def _decision(action: Action) -> Decision:
    rule = Rule(id="rule-1", name="Evening", trigger=Trigger(kind=TRIGGER_ALWAYS), action=action)
    now = datetime(2026, 7, 26, 21, 0)
    return Decision(rule=rule, action=action, occurred_at=now, decided_at=now, token=1)


def _apply_scene(scene_id: str = SCENE_ID) -> Decision:
    return _decision(Action(type=ACTION_APPLY_SCENE, scene_id=scene_id, target=""))


def _set_power(on: bool = True) -> Decision:
    return _decision(Action(type=ACTION_SET_POWER, power=on))


# ── a scene that works ────────────────────────────────────────────────
def test_a_fully_applied_scene_confirms_the_rule() -> None:
    """Every field of every strip is its own step, and the rule is confirmed only
    once all of them have answered."""
    ble = FakeBle(PRIMARY, MIRROR)
    executor = _executor(ble, scene=_scene({"power": True, "rgb": [10, 20, 30], "brightness": 50}))
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)

    assert ble.steps() == [
        ("power", PRIMARY),
        ("color", PRIMARY),
        ("brightness", PRIMARY),
        ("power", MIRROR),
        ("color", MIRROR),
        ("brightness", MIRROR),
    ], "a scene for every strip must become one addressed operation per field"
    assert verdicts == [], "the rule was confirmed before a single write answered"

    ble.finish_all()

    assert len(verdicts) == 1
    assert verdicts[0].ok is True
    assert (verdicts[0].completed_steps, verdicts[0].total_steps) == (6, 6)


def test_an_explicit_target_is_the_only_strip_written_to() -> None:
    ble = FakeBle(PRIMARY, MIRROR)
    executor = _executor(
        ble,
        scene=_scene({"power": True}, target={"kind": "primary", "group_id": None}),
        resolve=lambda target: [PRIMARY],
    )

    executor.execute(_apply_scene(), [].append)

    assert ble.steps() == [("power", PRIMARY)]


def test_a_mirror_that_refused_leaves_the_rule_unconfirmed() -> None:
    """Primary took the scene, the mirror did not. Calling that done would leave
    one strip out of step with no second attempt."""
    ble = FakeBle(PRIMARY, MIRROR)
    executor = _executor(ble, scene=_scene({"power": True, "brightness": 40}))
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)
    ble.finish_all(address=PRIMARY, ok=True)
    ble.finish_all(address=MIRROR, ok=False, code=CODE_UNAVAILABLE)

    verdict = verdicts[0]
    assert verdict.ok is False, "a rule was confirmed while one strip stayed behind"
    assert verdict.partial is True
    assert (verdict.completed_steps, verdict.total_steps) == (2, 4)


# ── steps that never become BLE operations ────────────────────────────
def test_a_scene_that_only_starts_screen_sync_counts_as_done() -> None:
    """A PC mode is synchronous and has no operation to wait for. Without counting
    it, a Screen Sync scene would look like a scene that sent nothing."""
    ble = FakeBle(PRIMARY)
    pc_mode = PcMode(allow=True)
    executor = _executor(
        ble, scene=_scene({"pc_mode": {"kind": "screen", "preset": None}}), pc_mode=pc_mode
    )
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)

    assert ble.submitted == []
    assert pc_mode.calls == [("off", None), ("screen", None)]
    assert len(verdicts) == 1
    assert verdicts[0].ok is True
    assert (verdicts[0].completed_steps, verdicts[0].total_steps) == (1, 1)


def test_a_pc_mode_the_app_refuses_leaves_the_rule_unconfirmed() -> None:
    ble = FakeBle(PRIMARY)
    executor = _executor(
        ble,
        scene=_scene({"pc_mode": {"kind": "music", "preset": None}}),
        pc_mode=PcMode(allow=False),
    )
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)

    assert verdicts[0].ok is False
    assert (verdicts[0].completed_steps, verdicts[0].total_steps) == (0, 1)


def test_a_field_the_strip_cannot_do_is_still_one_of_the_steps() -> None:
    """The scene asked for a white point this controller has no channel for. Left
    out of the count, "one of two" would be reported as "one of one" — done."""
    ble = FakeBle(PRIMARY)
    executor = _executor(
        ble,
        scene=_scene({"rgb": [255, 180, 90], "cct": 4000}),
        capabilities_for=lambda device_id: {"cct": False},
    )
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)
    assert ble.steps() == [("color", PRIMARY)]

    ble.finish_all()

    verdict = verdicts[0]
    assert verdict.ok is False, "a scene missing a field it asked for reported success"
    assert verdict.partial is True
    assert (verdict.completed_steps, verdict.total_steps) == (1, 2)


def test_a_submit_that_raised_fails_the_scene_and_is_reported(faults) -> None:
    """A tracked submit that throws is this module being broken, not a strip
    declining: capability refusals arrive through the scene report. Filed as a
    refused step it would read as "the hardware would not take it" and never be
    found, so it abandons the scene, leaves a crash log, and calls off the writes
    that had already gone out."""
    ble = FakeBle(PRIMARY)
    ble.raises = {"brightness"}
    executor = _executor(ble, scene=_scene({"power": True, "brightness": 30}))
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)

    assert ble.steps() == [("power", PRIMARY)]
    assert ble.cancelled == [1], "the write already sent was left running"
    assert faults == ["automation_apply_scene"], "a broken dispatch was not reported"

    ble.finish_all(ok=False, code=CODE_CANCELLED)

    assert verdicts[0].ok is False
    assert verdicts[0].code == CODE_APPLY_FAILED


def test_a_tracked_submit_that_answered_with_no_id_is_a_fault(faults) -> None:
    """The BLE layer returns an id in every branch, including the ones where it
    declines. A None is wiring, and wiring faults must not be counted as steps the
    strip refused."""
    ble = FakeBle(PRIMARY)
    ble.answer_without_id = {"power"}
    executor = _executor(ble, scene=_scene({"power": True}))
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)

    assert faults == ["automation_apply_scene"]
    assert len(verdicts) == 1
    assert verdicts[0].code == CODE_APPLY_FAILED
    assert verdicts[0].total_steps == 0, "a fault was recorded as a step of the scene"


# ── nothing to write to ───────────────────────────────────────────────
def test_a_scene_with_no_strips_is_unavailable_and_leaves_the_running_mode_alone() -> None:
    """Applying a scene stops any live stream first. For a scene that cannot apply
    at all, that would switch the user's screen sync off for nothing."""
    ble = FakeBle()  # nothing connected
    pc_mode = PcMode(allow=True)
    executor = _executor(ble, scene=_scene({"power": True}), pc_mode=pc_mode)
    verdicts: list = []

    handle = executor.execute(_apply_scene(), verdicts.append)

    assert handle is None
    assert ble.submitted == []
    assert pc_mode.calls == [], "a scene that could not apply stopped the user's stream"
    assert verdicts[0].ok is False
    assert verdicts[0].code == CODE_UNAVAILABLE
    assert verdicts[0].total_steps == 0


def test_a_target_that_resolved_to_nothing_is_unavailable() -> None:
    """A saved group whose strips are all offline. Same answer, and again without
    touching anything global."""
    ble = FakeBle(PRIMARY)
    pc_mode = PcMode(allow=True)
    executor = _executor(
        ble,
        scene=_scene({"power": True}, target={"kind": "group", "group_id": "desk"}),
        resolve=lambda target: [],
        pc_mode=pc_mode,
    )
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)

    assert ble.submitted == []
    assert pc_mode.calls == []
    assert verdicts[0].code == CODE_UNAVAILABLE


def test_a_scene_that_has_been_deleted_answers_at_once() -> None:
    ble = FakeBle(PRIMARY)
    executor = _executor(ble, scene=None)
    verdicts: list = []

    assert executor.execute(_apply_scene("gone"), verdicts.append) is None
    assert verdicts[0].code == CODE_MISSING_SCENE


# ── dispatch that broke down ──────────────────────────────────────────
def test_an_exception_half_way_through_a_scene_does_not_leave_it_hanging(faults) -> None:
    """The first strip's writes are already out when the second strip's lookup
    raises. They are called off, the group is sealed, and the verdict says the
    dispatch failed — not that the user cancelled it."""
    ble = FakeBle(PRIMARY, MIRROR)

    def capabilities_for(device_id: str | None) -> dict[str, Any]:
        if device_id == MIRROR:
            raise RuntimeError("the main-thread call timed out")
        return {}

    executor = _executor(
        ble,
        scene=_scene({"power": True, "brightness": 60}),
        capabilities_for=capabilities_for,
    )
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)

    assert ble.steps() == [("power", PRIMARY), ("brightness", PRIMARY)]
    assert ble.cancelled == [1, 2], "operations already submitted were left running"
    assert faults == ["automation_apply_scene"], "a broken dispatch was not reported"
    assert verdicts == [], "the writes still have to report before there is a verdict"

    ble.finish_all(ok=False, code=CODE_CANCELLED)

    verdict = verdicts[0]
    assert verdict.ok is False
    assert verdict.code == CODE_APPLY_FAILED
    assert verdict.partial_possible is True, "a write already sent may still have landed"
    assert verdict.total_steps == 2


def test_a_scene_that_broke_before_sending_anything_answers_at_once(faults) -> None:
    """Nothing was submitted, so there is nothing to wait for — and nothing that
    could have landed, so no doubt is invented either."""
    ble = FakeBle(PRIMARY)

    def capabilities_for(device_id: str | None) -> dict[str, Any]:
        raise RuntimeError("the main-thread call timed out")

    executor = _executor(
        ble, scene=_scene({"power": True}), capabilities_for=capabilities_for
    )
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)

    assert ble.submitted == []
    assert faults == ["automation_apply_scene"]
    assert len(verdicts) == 1
    assert verdicts[0].code == CODE_APPLY_FAILED
    assert verdicts[0].partial_possible is False
    assert verdicts[0].total_steps == 0


# ── the user taking over ──────────────────────────────────────────────
def test_cancelling_before_the_writes_answer_confirms_nothing() -> None:
    ble = FakeBle(PRIMARY)
    executor = _executor(ble, scene=_scene({"power": True, "brightness": 70}))
    verdicts: list = []

    handle = executor.execute(_apply_scene(), verdicts.append)
    ble.finish(1, ok=True)  # the power write landed
    handle.cancel()

    assert ble.cancelled == [2], "an operation that had already answered was cancelled"
    assert verdicts == []

    ble.finish(2, ok=False, code=CODE_CANCELLED)

    verdict = verdicts[0]
    assert verdict.ok is False, "a cancelled scene confirmed the rule"
    assert verdict.code == CODE_CANCELLED
    assert verdict.partial is False
    assert verdict.partial_possible is True
    assert (verdict.completed_steps, verdict.total_steps) == (1, 2)


def test_a_result_that_lands_after_the_cancel_is_not_counted_as_done() -> None:
    """Both writes were already on their way. They may well have reached the
    strip, but the user has taken over — so the rule is not confirmed, and the
    routing map does not keep the scene alive either."""
    ble = FakeBle(PRIMARY)
    executor = _executor(ble, scene=_scene({"power": True, "brightness": 70}))
    verdicts: list = []

    handle = executor.execute(_apply_scene(), verdicts.append)
    handle.cancel()
    ble.finish(1, ok=True)
    ble.finish(2, ok=True)

    assert len(verdicts) == 1
    assert verdicts[0].ok is False
    assert verdicts[0].completed_steps == 0, "a result after the cancel was counted as done"
    assert verdicts[0].partial_possible is True
    assert executor._groups == {}, "a finished scene stayed in the routing map"


def test_cancelling_after_the_verdict_changes_nothing() -> None:
    """The dispatcher can cancel late — on a pause, or on shutdown."""
    ble = FakeBle(PRIMARY)
    executor = _executor(ble, scene=_scene({"power": True}))
    verdicts: list = []

    handle = executor.execute(_apply_scene(), verdicts.append)
    ble.finish_all()
    handle.cancel()

    assert len(verdicts) == 1
    assert verdicts[0].ok is True
    assert ble.cancelled == []


# ── one subscription, many scenes ─────────────────────────────────────
def test_one_subscription_does_not_mix_two_scenes_up() -> None:
    """Results are routed by operation id, so a straggler from an abandoned scene
    cannot answer for the one that replaced it."""
    ble = FakeBle(PRIMARY)
    executor = _executor(ble, scene=_scene({"power": True}))
    first: list = []
    second: list = []

    executor.execute(_apply_scene(), first.append)
    executor.execute(_apply_scene(), second.append)
    ble.finish(2, ok=True)  # the second scene's write

    assert first == [], "one scene's verdict answered for another"
    assert len(second) == 1
    assert second[0].ok is True

    ble.finish(1, ok=False)

    assert len(first) == 1
    assert first[0].ok is False
    assert len(second) == 1


def test_a_result_for_an_unknown_operation_is_ignored() -> None:
    ble = FakeBle(PRIMARY)
    executor = _executor(ble, scene=_scene({"power": True}))
    verdicts: list = []

    executor.execute(_apply_scene(), verdicts.append)
    ble.finish(999, ok=True)  # the UI's own writes are untracked, but be safe

    assert verdicts == []


# ── the plain power rule ──────────────────────────────────────────────
def test_a_power_rule_touches_only_the_main_strip() -> None:
    """The old schedule switched the main strip and nothing else; migrating it
    must not start mirroring to every extra strip the user has since added."""
    ble = FakeBle(PRIMARY, MIRROR)
    executor = _executor(ble)
    verdicts: list = []

    executor.execute(_set_power(True), verdicts.append)

    assert ble.steps() == [("power", PRIMARY)]
    assert ble.submitted[0].payload is True

    ble.finish_all()

    assert verdicts[0].ok is True
    assert (verdicts[0].completed_steps, verdicts[0].total_steps) == (1, 1)


def test_a_power_rule_with_no_main_strip_is_unavailable() -> None:
    ble = FakeBle()
    executor = _executor(ble)
    verdicts: list = []

    assert executor.execute(_set_power(False), verdicts.append) is None
    assert ble.submitted == []
    assert verdicts[0].ok is False
    assert verdicts[0].code == CODE_UNAVAILABLE


def test_a_power_submit_that_raised_is_reported_not_dressed_up_as_a_refusal(faults) -> None:
    ble = FakeBle(PRIMARY)
    ble.raises = {"power"}
    executor = _executor(ble)
    verdicts: list = []

    executor.execute(_set_power(True), verdicts.append)

    assert faults == ["automation_set_power"]
    assert len(verdicts) == 1
    assert verdicts[0].code == CODE_APPLY_FAILED
    assert verdicts[0].total_steps == 0
    assert verdicts[0].partial_possible is False, "nothing was sent, so nothing is in doubt"


def test_a_power_rule_can_be_cancelled_like_a_scene() -> None:
    ble = FakeBle(PRIMARY)
    executor = _executor(ble)
    verdicts: list = []

    handle = executor.execute(_set_power(True), verdicts.append)
    handle.cancel()

    assert ble.cancelled == [1]
    ble.finish(1, ok=True)  # the write had already gone out
    assert verdicts[0].ok is False
    assert verdicts[0].partial_possible is True
