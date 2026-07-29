"""Turns the several BLE operations of one scene into a single verdict.

Applying a scene is not one command: power, colour, brightness and effect are
separate writes, each its own tracked operation. The rule that asked for the
scene, though, either did its job or it did not — so the results have to be
gathered and reduced to one :class:`ExecutionResult`.

A *step* is one tracked operation, not one BLE payload. That distinction is the
one the counts in the journal are based on.

The awkward part is timing. The first operation can finish before the last one
has even been submitted, so a naive "all results in, we are done" would call the
group complete when it had barely started. Hence ``seal()``: registration is
open until the caller says the scene has been fully dispatched, and only then can
the group finish. Results that arrive before that are kept, not dropped.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.automation.dispatcher import ExecutionResult

# Mirrors app.ble result codes without importing them: this package stays free
# of BLE and Qt so it can be tested with plain objects.
CODE_SUCCESS = "success"
CODE_CANCELLED = "cancelled"
CODE_UNAVAILABLE = "unavailable"


class OperationResult(Protocol):
    operation_id: int
    ok: bool
    code: str


class SceneOperationGroup:
    """Collects the operations of one scene and reports how it ended.

    Feed it: ``register`` for every submitted operation, ``handle_result`` for
    every result that comes back, ``seal`` once dispatching is over. It calls
    ``done`` exactly once, when sealed and every registered operation has
    answered.
    """

    def __init__(
        self,
        done: Callable[[ExecutionResult], None],
        cancel_operation: Callable[[int], bool] | None = None,
    ) -> None:
        self._done = done
        self._cancel_operation = cancel_operation
        self._registered: list[int] = []
        self._results: dict[int, Any] = {}
        self._sealed = False
        self._cancelled = False
        self._finished = False
        self._confirmed_at_cancel: set[int] | None = None
        self._in_flight_at_cancel = False
        self._cancel_code = CODE_CANCELLED

    # ── collecting ────────────────────────────────────────────────────
    def register(self, operation_id: int) -> bool:
        """Take responsibility for an operation. False when it was refused.

        A refusal means the group is already sealed or cancelled — the caller
        must not go on submitting steps.
        """
        if not self._accepting():
            return False
        if operation_id is None:
            # ``_submit`` returns an id even when it declines, so a None here is
            # a wiring mistake rather than a refused command. Surfacing it as an
            # untracked step would hide the bug — use register_refused_step().
            raise ValueError("register() needs an operation id; see register_refused_step()")
        if operation_id in self._registered:
            return False  # one operation is one step, however often it is offered
        self._registered.append(operation_id)
        return True

    def register_refused_step(self) -> None:
        """Record a step that could not be formed at all.

        It still belongs in ``total_steps``: without it, "two of the five things
        the scene wanted" would be reported as "two of two".
        """
        self._register_synthetic(ok=False, code=CODE_UNAVAILABLE)

    def register_completed_step(self) -> None:
        """Record a step that was done synchronously — starting a PC mode.

        Nothing went to BLE, so no result will ever arrive for it: the step is
        finished the moment it is registered. Without it a scene whose only field
        is screen sync would produce no operations at all and be reported as
        "nothing was sent".
        """
        self._register_synthetic(ok=True, code=CODE_SUCCESS)

    def _register_synthetic(self, *, ok: bool, code: str) -> None:
        """Add a step that has no BLE operation, answered on the spot.

        The placeholder id is negative so it can never collide with a real
        operation id, and unique because the list only ever grows.
        """
        if not self._accepting():
            return
        placeholder = -(len(self._registered) + 1)
        self._registered.append(placeholder)
        self._results[placeholder] = _SyntheticStep(placeholder, ok, code)
        self._maybe_finish()

    def _accepting(self) -> bool:
        return not (self._sealed or self._cancelled or self._finished)

    def handle_result(self, result: OperationResult) -> None:
        """Accept a result, including one that arrives before ``seal``."""
        if self._finished:
            return
        operation_id = getattr(result, "operation_id", None)
        if operation_id is None or operation_id not in self._registered:
            return  # not ours
        self._results.setdefault(operation_id, result)
        self._maybe_finish()

    def seal(self) -> None:
        """No more steps are coming. Only now may the group finish."""
        self._sealed = True
        self._maybe_finish()

    def cancel(self, *, code: str = CODE_CANCELLED) -> None:
        """Stop the scene part-way.

        The flag goes up *before* any cancellation is requested: a result that
        lands in between would otherwise be counted towards a group the user has
        already called off.

        ``code`` is what the verdict will be filed under. It defaults to the user
        taking over, but the same machinery ends a scene whose dispatch blew up
        half way through — and calling that "cancelled" in the journal would
        blame the user for a fault.
        """
        if self._finished or self._cancelled:
            return  # cancelling twice must not re-take the snapshot below
        self._cancelled = True
        self._cancel_code = code
        # Taken exactly once, right after the flag: only what was already
        # confirmed at this instant may count. A result arriving later — while
        # we work through the cancellations, or before a second call — belongs
        # to a scene the user has already called off.
        self._confirmed_at_cancel = {
            operation_id
            for operation_id, result in self._results.items()
            if getattr(result, "ok", False)
        }
        self._sealed = True
        pending = [
            operation_id
            for operation_id in self._registered
            if operation_id >= 0 and operation_id not in self._results
        ]
        # Whether anything could still be on its way, decided here rather than at
        # verdict time: by then every operation has answered, and the doubt would
        # be gone from the record even though it was real.
        self._in_flight_at_cancel = bool(pending)
        if self._cancel_operation is not None:
            for operation_id in pending:
                # True from here means only that the request was accepted. A write
                # already handed to the BLE stack still lands, and nothing is
                # undone — hence the doubt above rather than a claim.
                self._cancel_operation(operation_id)
        self._maybe_finish()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # ── verdict ───────────────────────────────────────────────────────
    def _maybe_finish(self) -> None:
        if self._finished or not self._sealed:
            return
        if any(operation_id not in self._results for operation_id in self._registered):
            return
        self._finished = True
        self._done(self._verdict())

    def _verdict(self) -> ExecutionResult:
        total = len(self._registered)
        completed = sum(1 for result in self._results.values() if getattr(result, "ok", False))

        if self._cancelled:
            # Checked before the "no operations" case below: a scene called off
            # before it managed to submit anything was cancelled, not targetless,
            # and saying "unavailable" would send the user looking for a strip
            # that was never the problem.
            #
            # Only steps confirmed *before* the cancellation count. A write
            # already handed to the stack may still have landed, so the honest
            # answer is "possibly partial", never a count presented as fact.
            return ExecutionResult(
                ok=False,
                code=self._cancel_code,
                completed_steps=len(self._confirmed_at_cancel or ()),
                total_steps=total,
                partial_possible=self._in_flight_at_cancel,
            )

        if total == 0:
            # The scene produced no operations at all — nothing was sent, so
            # there is nothing to call a success.
            return ExecutionResult(ok=False, code=CODE_UNAVAILABLE)

        if completed == total:
            return ExecutionResult(ok=True, completed_steps=completed, total_steps=total)

        if completed == 0:
            return ExecutionResult(ok=False, completed_steps=0, total_steps=total)

        return ExecutionResult(
            ok=False, completed_steps=completed, total_steps=total, partial=True
        )


@dataclass(frozen=True)
class _SyntheticStep:
    """Stands in for a step with no BLE operation behind it.

    Two kinds end up here: one that could not be formed at all, and one that was
    carried out synchronously. Both are steps the scene asked for, so both have to
    appear in the counts.
    """

    operation_id: int
    ok: bool
    code: str
