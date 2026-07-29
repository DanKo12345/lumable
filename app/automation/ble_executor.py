"""The real executor: a decision in, tracked BLE work out, one verdict back.

This is the boundary module of the package — the only one that knows about Qt and
about :mod:`app.ble`. Everything above it (rules, resolver, journal, dispatcher,
scene group) stays pure, which is why the awkward parts all live here. It is
deliberately *not* re-exported from ``app.automation``: importing the engine must
not drag in Qt and BLE.

Scenes go through the same :class:`~app.scene_apply.SceneApplyService` the UI and
the phone remote use, so an automation applies a scene by exactly the same rules —
stream stopped first, capability skips, PC mode last. Only the writes differ: each
becomes one *tracked* operation whose result is correlated back to the scene, so
the rule is confirmed on what actually landed rather than on having sent
something.

Three things the design turns on:

* **One address per operation.** A tracked command covering several strips would
  report success as soon as any one of them accepted the write, hiding a scene
  that only half applied. So the target is expanded to concrete addresses before
  anything is sent, and every field of every strip is its own step.
* **One subscription.** ``operation_finished`` is connected once, before anything
  can be submitted, and results are routed by id. Connecting per scene would hand
  every later result to every scene that ever ran.
* **Never hang, never hide.** The dispatcher waits for exactly one callback, so
  every branch here — no scene, no strip, a dispatch that raised half way
  through — ends in a verdict. What the hardware or this build cannot do arrives
  through the scene report instead, which is why an *exception* is treated as this
  module being broken: it fails the run under its own code and leaves a crash log,
  rather than being recorded as one more field the strip would not take.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject

from app.automation.dispatcher import ExecutionResult
from app.automation.rules import ACTION_APPLY_SCENE, ACTION_SET_POWER
from app.automation.scene_group import CODE_UNAVAILABLE, SceneOperationGroup
from app.crash_logging import write_current_exception
from app.scene_apply import SceneApplyService

# Verdict codes for the branches that never reach a scene group.
CODE_MISSING_SCENE = "missing_scene"
CODE_UNSUPPORTED_ACTION = "unsupported_action"
# Dispatch itself broke down part-way. Distinct from "cancelled": the user did not
# ask for this, and the journal must not say they did.
CODE_APPLY_FAILED = "apply_failed"


class _SceneAborted(Exception):
    """Leaves ``SceneApplyService.apply()`` when the scene has been called off.

    The service applies a scene field by field with no way to stop early, so the
    only way out mid-loop is upwards. Private, and caught by the one call site.
    """


class BleActionExecutor(QObject):
    """Executes automation decisions against a live :class:`BleController`.

    ``scene_for`` looks a scene up by id. ``resolve_targets`` maps a scene's
    ``target`` to the concrete addresses it should reach, and may return ``None``
    for "every connected strip" — which is expanded here, before a single write
    goes out. ``capabilities_for`` and ``set_pc_mode`` are the same collaborators
    :class:`SceneApplyService` gets from the Local API backend.
    """

    def __init__(
        self,
        ble: Any,
        *,
        scene_for: Callable[[str], dict[str, Any] | None],
        resolve_targets: Callable[[dict[str, Any]], list[str] | None],
        capabilities_for: Callable[[str | None], dict[str, Any]] | None = None,
        set_pc_mode: Callable[[str, str | None], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._ble = ble
        self._scene_for = scene_for
        self._resolve_targets = resolve_targets
        self._capabilities_for = capabilities_for
        self._set_pc_mode = set_pc_mode
        # Which scene each operation in flight belongs to. Emptied as results
        # arrive, so it never grows past what is actually outstanding.
        self._groups: dict[int, SceneOperationGroup] = {}
        # Connected once, here, before anything can be submitted: a per-scene
        # connection would deliver every later result to every earlier scene, and
        # connecting after the first submit could miss its result outright. Being
        # a QObject, the connection dies with this executor (or with its parent).
        ble.operation_finished.connect(self._on_operation_finished)

    # ── the ActionExecutor contract ───────────────────────────────────
    def execute(self, decision: Any, done: Callable[[ExecutionResult], None]) -> Any:
        """Carry out ``decision``, calling ``done`` exactly once, eventually."""
        action = decision.action
        if action.type == ACTION_APPLY_SCENE:
            return self._apply_scene(str(action.scene_id or ""), done)
        if action.type == ACTION_SET_POWER:
            return self._set_power(bool(action.power), done)
        # A rule the schema let through but this build cannot run. Answered rather
        # than ignored: the dispatcher would otherwise wait out its whole timeout.
        done(ExecutionResult(ok=False, code=CODE_UNSUPPORTED_ACTION))
        return None

    # ── apply a scene ─────────────────────────────────────────────────
    def _apply_scene(self, scene_id: str, done: Callable[[ExecutionResult], None]) -> Any:
        scene = self._scene_for(scene_id)
        if not isinstance(scene, dict):
            # The resolver checks this too, but the scene can be deleted between
            # the decision and now.
            done(ExecutionResult(ok=False, code=CODE_MISSING_SCENE))
            return None

        addresses = self._scene_addresses(scene)
        if not addresses:
            # Nothing to write to. Reported and dropped *before* anything global
            # is touched: apply() stops the running stream first, so going on
            # would switch the user's screen sync off for a scene that cannot be
            # applied anyway.
            done(ExecutionResult(ok=False, code=CODE_UNAVAILABLE))
            return None

        group = SceneOperationGroup(done, cancel_operation=self._cancel_operation)
        backend = _TrackedBackend(self, group, self._set_pc_mode)
        try:
            report = SceneApplyService(backend).apply(
                scene, device_ids=addresses, capabilities_for=self._capabilities_for
            )
        except _SceneAborted:
            # Called off while we were still submitting. The group is already
            # cancelled and sealed, so its verdict is on its way — nothing to add.
            return _SceneHandle(group)
        except Exception:
            # Something in the dispatch broke: the light is in an unknown state and
            # some operations are still in flight. Cancelling what was registered
            # and sealing the group is what keeps the dispatcher from waiting on a
            # scene that will never report.
            self._report_fault("apply_scene")
            group.cancel(code=CODE_APPLY_FAILED)
            return _SceneHandle(group)

        self._account_for_report(group, report)
        # Only now may the group finish: until this point an early result would
        # have made a scene that had barely started look complete.
        group.seal()
        return _SceneHandle(group)

    @staticmethod
    def _account_for_report(group: SceneOperationGroup, report: Any) -> None:
        """Add the steps that never became BLE operations.

        The scene's writes registered themselves as they were submitted; what is
        left is everything the scene asked for and did not get, plus the PC mode,
        which is synchronous and has no operation to wait for.
        """
        report = report if isinstance(report, dict) else {}
        applied = report.get("applied")
        if isinstance(applied, (list, tuple)) and "pc_mode" in applied:
            group.register_completed_step()
        skipped = report.get("skipped")
        if isinstance(skipped, (list, tuple)):
            # Every field the scene wanted and could not have, per strip. Without
            # these the counts would read "two of two" for a scene that asked for
            # five things — and an unsupported field would vanish from the result.
            for _entry in skipped:
                group.register_refused_step()

    def _scene_addresses(self, scene: dict[str, Any]) -> list[str]:
        """The concrete strips this scene applies to, right now.

        A snapshot, taken before the first write: resolving "all strips" per field
        would let a mirror that connects mid-scene get some fields and not others.
        """
        target = scene.get("target")
        resolved = self._resolve_targets(target if isinstance(target, dict) else {})
        if resolved is None:
            # The resolver's shorthand for the whole set. Expanded here rather
            # than passed on as "no address": one operation for every strip would
            # confirm the scene as soon as any single strip took the write.
            resolved = self._connected_addresses()
        addresses: list[str] = []
        for entry in resolved:
            address = str(entry or "").strip()
            if address and address not in addresses:
                addresses.append(address)
        return addresses

    def _connected_addresses(self) -> list[str]:
        primary = str(self._ble.primary_address() or "").strip()
        mirrors = [str(address or "").strip() for address in self._ble.mirror_addresses() or ()]
        return ([primary] if primary else []) + [address for address in mirrors if address]

    # ── switch the main strip ─────────────────────────────────────────
    def _set_power(self, enabled: bool, done: Callable[[ExecutionResult], None]) -> Any:
        """The old schedule's action: power, main strip, nothing else.

        Deliberately not routed through the scene service — there is one field and
        one address, and the primary is the only target the schema allows.
        """
        address = str(self._ble.primary_address() or "").strip()
        if not address:
            # No main strip: the resolver's connectivity check can be a tick old,
            # and a tracked command without an address is not a thing we can send.
            done(ExecutionResult(ok=False, code=CODE_UNAVAILABLE))
            return None

        group = SceneOperationGroup(done, cancel_operation=self._cancel_operation)
        try:
            operation_id = self._ble.set_power_for_address_tracked(enabled, address)
            adopted = self._adopt(operation_id, group)
        except Exception:
            # Same reasoning as a scene: a tracked submit that raises is this
            # module being wrong, not the strip declining. It is reported as a
            # fault and the run fails — never dressed up as a refused step, which
            # would read as "the hardware would not do it".
            self._report_fault("set_power")
            group.cancel(code=CODE_APPLY_FAILED)
            return _SceneHandle(group)
        group.seal()
        return _SceneHandle(group) if adopted else None

    # ── operation bookkeeping ─────────────────────────────────────────
    def _adopt(self, operation_id: Any, group: SceneOperationGroup) -> bool:
        """Route this operation's result to ``group`` and count it as a step.

        False means the group would not take it (sealed or cancelled), and the
        operation has been called off — the caller must stop submitting.
        """
        if operation_id is None:
            # A tracked submit answers with an id in every branch, so this is a
            # wiring fault in the executor, not a command the strip refused.
            # Raised on purpose: recording it as a refused step would file a
            # broken executor as a scene the hardware could not manage, and the
            # bug would live on in the counts. The caller turns it into a
            # cancelled scene and a crash log.
            raise ValueError("a tracked command returned no operation id")
        # The map entry goes in before the step is registered: delivery is queued,
        # so a result cannot arrive before this returns today — but the ordering
        # costs nothing and losing a step to it would be invisible.
        self._groups[operation_id] = group
        if group.register(operation_id):
            return True
        self._groups.pop(operation_id, None)
        self._cancel_operation(operation_id)
        return False

    @staticmethod
    def _report_fault(context: str) -> None:
        """Leave a crash log for a broken dispatch, then carry on.

        The dispatcher must get exactly one answer, so the exception cannot be
        allowed out of here — but a fault that only ever shows up as one more
        failed automation is a fault nobody will ever find. This is the same
        channel the app uses for an unhandled exception anywhere else.
        """
        try:
            write_current_exception(context=f"automation_{context}")
        except Exception:  # pragma: no cover - the report must never mask the run
            pass

    def _cancel_operation(self, operation_id: int) -> bool:
        """Ask the controller to stop an operation.

        True means only that the request was accepted: a write already handed to
        the BLE stack still lands, and nothing is rolled back. Failures are
        swallowed because this runs in a loop over everything still in flight —
        one stubborn operation must not stop the rest from being called off.
        """
        try:
            return bool(self._ble.cancel_operation(operation_id))
        except Exception:
            return False

    def _on_operation_finished(self, result: object) -> None:
        operation_id = getattr(result, "operation_id", None)
        if operation_id is None:
            return
        # Popped rather than looked up: one operation reports exactly once, so
        # keeping the entry would grow the map for the life of the app. A result
        # for a scene that already ended still clears its entry here.
        group = self._groups.pop(operation_id, None)
        if group is None:
            return  # not ours: the UI's own writes are untracked, but be safe
        group.handle_result(result)


class _TrackedBackend:
    """A scene-apply backend whose every device write is a tracked operation.

    Same protocol :class:`SceneApplyService` gets from the Local API, so the scene
    logic is shared rather than reimplemented; only the writes are singular and
    correlated. PC modes are handed to the app as-is — they are global streams,
    not per-strip writes, and they answer synchronously.
    """

    def __init__(
        self,
        executor: BleActionExecutor,
        group: SceneOperationGroup,
        set_pc_mode: Callable[[str, str | None], bool] | None,
    ) -> None:
        self._executor = executor
        self._group = group
        self._set_pc_mode = set_pc_mode

    def set_power(self, on: bool, device_id: str | None) -> None:
        self._step(device_id, lambda address: self._ble.set_power_for_address_tracked(bool(on), address))

    def set_color(self, red: int, green: int, blue: int, device_id: str | None) -> None:
        self._step(
            device_id,
            lambda address: self._ble.set_color_for_address_tracked(int(red), int(green), int(blue), address),
        )

    def set_brightness(self, value: int, device_id: str | None) -> None:
        self._step(device_id, lambda address: self._ble.set_brightness_for_address_tracked(int(value), address))

    def set_effect(self, code: int, speed: int | None, device_id: str | None) -> None:
        self._step(device_id, lambda address: self._ble.set_effect_for_address_tracked(int(code), speed, address))

    def set_pc_mode(self, mode: str, preset: str | None = None) -> bool:
        """Start (or stop) a PC mode. Not a step in itself — see the report.

        ``apply()`` calls this first with ``"off"`` to hand the strip back from any
        running stream, and that is housekeeping, not something the rule asked
        for. Whether the scene's *own* mode counted is read off the report
        afterwards, so only the real one becomes a step.
        """
        if self._set_pc_mode is None:
            return False
        return bool(self._set_pc_mode(str(mode), preset))

    @property
    def _ble(self) -> Any:
        return self._executor._ble

    def _step(self, device_id: str | None, submit: Callable[[str], Any]) -> None:
        if self._group.cancelled:
            # Checked before submitting, never after: a write sent now would land
            # on a light the user has just taken back by hand.
            raise _SceneAborted
        address = str(device_id or "").strip()
        if not address:
            # Every target is expanded to a concrete address before apply(), so a
            # missing one is a step that cannot be formed — not a licence to write
            # to every strip at once.
            self._group.register_refused_step()
            return
        # Nothing is caught around the submit. What the hardware or this build
        # cannot do arrives through the scene report's ``skipped`` list, so an
        # exception here means the executor itself is broken — and a broken
        # executor recorded as "one field the strip refused" is a bug that hides
        # for good. It goes up to the handler that cancels what has already been
        # sent and reports the scene as failed.
        operation_id = submit(address)
        if not self._executor._adopt(operation_id, self._group):
            raise _SceneAborted


class _SceneHandle:
    """The dispatcher's handle on work in progress.

    ``cancel()`` puts the group's flag up *before* a single cancellation is
    requested and refuses any further steps, so nothing landing afterwards can be
    counted towards a scene the user has already taken back. It does not undo
    anything, and it cannot promise that nothing reached the strip.
    """

    __slots__ = ("_group",)

    def __init__(self, group: SceneOperationGroup) -> None:
        self._group = group

    def cancel(self) -> None:
        self._group.cancel()
