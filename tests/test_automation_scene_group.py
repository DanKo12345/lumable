"""One scene, several BLE writes, one verdict — including the awkward orderings.

Each test is phrased as the consequence for the user: whether the rule counts as
having done its job, and whether the light may be touched again.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.automation.scene_group import SceneOperationGroup


@dataclass(frozen=True)
class Result:
    operation_id: int
    ok: bool
    code: str = ""


def _group(cancel_log: list | None = None):
    verdicts: list = []
    group = SceneOperationGroup(
        verdicts.append,
        cancel_operation=(lambda op: cancel_log.append(op) or True) if cancel_log is not None else None,
    )
    return group, verdicts


def test_a_fully_applied_scene_confirms_the_rule() -> None:
    group, verdicts = _group()

    for operation_id in (1, 2, 3):
        assert group.register(operation_id) is True
    group.seal()
    for operation_id in (1, 2, 3):
        group.handle_result(Result(operation_id, ok=True))

    assert len(verdicts) == 1
    assert verdicts[0].ok is True
    assert (verdicts[0].completed_steps, verdicts[0].total_steps) == (3, 3)


def test_the_group_does_not_finish_before_it_is_sealed() -> None:
    """The first write can finish before the last one is even submitted; calling
    the scene done there would confirm a rule that had barely started."""
    group, verdicts = _group()

    group.register(1)
    group.handle_result(Result(1, ok=True))
    assert verdicts == [], "the group settled while steps were still coming"

    group.register(2)
    group.seal()
    assert verdicts == [], "sealed, but one step has not answered yet"

    group.handle_result(Result(2, ok=True))
    assert len(verdicts) == 1
    assert verdicts[0].total_steps == 2


def test_results_that_arrive_before_seal_are_kept() -> None:
    group, verdicts = _group()

    group.register(1)
    group.register(2)
    group.handle_result(Result(1, ok=True))
    group.handle_result(Result(2, ok=True))
    assert verdicts == []

    group.seal()

    assert len(verdicts) == 1
    assert verdicts[0].completed_steps == 2


def test_a_half_applied_scene_does_not_confirm_the_rule() -> None:
    group, verdicts = _group()

    for operation_id in (1, 2, 3):
        group.register(operation_id)
    group.seal()
    group.handle_result(Result(1, ok=True))
    group.handle_result(Result(2, ok=False, code="ble_error"))
    group.handle_result(Result(3, ok=False, code="ble_error"))

    verdict = verdicts[0]
    assert verdict.ok is False, "a partly applied scene must leave the rule to retry"
    assert verdict.partial is True
    assert (verdict.completed_steps, verdict.total_steps) == (1, 3)


def test_a_scene_where_nothing_landed_is_not_called_partial() -> None:
    group, verdicts = _group()

    group.register(1)
    group.register(2)
    group.seal()
    group.handle_result(Result(1, ok=False, code="ble_error"))
    group.handle_result(Result(2, ok=False, code="ble_error"))

    assert verdicts[0].ok is False
    assert verdicts[0].partial is False


def test_a_scene_that_produced_no_operations_is_a_failure() -> None:
    """A report full of "skipped" means nothing was sent; there is nothing to
    call a success."""
    group, verdicts = _group()

    group.seal()

    assert verdicts[0].ok is False
    assert verdicts[0].total_steps == 0


def test_cancelling_stops_further_steps_from_being_registered() -> None:
    cancel_log: list = []
    group, _verdicts = _group(cancel_log)

    group.register(1)
    group.register(2)
    group.cancel()

    assert group.register(3) is False, "a cancelled scene accepted another step"
    assert cancel_log == [1, 2]


def test_a_cancelled_scene_admits_it_does_not_know_what_landed() -> None:
    """A write already handed to the stack may still arrive, so the verdict says
    "possibly", never a count presented as fact."""
    group, verdicts = _group([])

    group.register(1)
    group.register(2)
    group.handle_result(Result(1, ok=True))
    group.cancel()
    group.handle_result(Result(2, ok=False, code="cancelled"))

    verdict = verdicts[0]
    assert verdict.ok is False
    assert verdict.partial is False
    assert verdict.partial_possible is True
    assert verdict.completed_steps == 1


def test_a_result_landing_between_the_flag_and_the_cancel_is_not_counted_as_done() -> None:
    """The flag goes up first precisely so this ordering cannot confirm a scene
    the user has already called off."""
    cancel_log: list = []
    verdicts: list = []

    def cancel(operation_id: int) -> bool:
        # Simulates the worst interleaving: a result arrives while we are still
        # working through the cancellations.
        group.handle_result(Result(operation_id, ok=True))
        cancel_log.append(operation_id)
        return True

    group = SceneOperationGroup(verdicts.append, cancel_operation=cancel)
    group.register(1)
    group.register(2)
    group.cancel()

    assert verdicts[0].ok is False, "a scene cancelled by the user reported success"
    assert verdicts[0].partial_possible is True
    assert verdicts[0].completed_steps == 0, "a result after the cancel was counted as done"


def test_a_refused_submission_keeps_the_scene_from_counting_as_applied() -> None:
    """``_submit`` can decline outright (shutting down, loop stopped). That step
    did not happen, so the scene did not fully apply."""
    group, verdicts = _group()

    group.register(1)
    group.register_refused_step()
    group.seal()
    group.handle_result(Result(1, ok=True))

    verdict = verdicts[0]
    assert verdict.ok is False
    assert (verdict.completed_steps, verdict.total_steps) == (1, 2)


def test_the_verdict_is_delivered_exactly_once() -> None:
    group, verdicts = _group()

    group.register(1)
    group.seal()
    group.handle_result(Result(1, ok=True))
    group.handle_result(Result(1, ok=True))  # a duplicate from the BLE layer
    group.seal()
    group.cancel()

    assert len(verdicts) == 1


def test_a_result_for_someone_elses_operation_is_ignored() -> None:
    group, verdicts = _group()

    group.register(1)
    group.seal()
    group.handle_result(Result(99, ok=True))
    assert verdicts == []

    group.handle_result(Result(1, ok=True))
    assert len(verdicts) == 1


def test_a_step_cannot_be_added_once_the_scene_is_over() -> None:
    """Both doors: sealing and cancelling must stop steps arriving, including
    ones that failed to form."""
    group, verdicts = _group()

    group.register(1)
    group.seal()
    group.handle_result(Result(1, ok=True))

    assert group.register(2) is False
    group.register_refused_step()
    assert verdicts[0].total_steps == 1, "a step slipped in after the verdict"

    cancelled_group, cancelled_verdicts = _group([])
    cancelled_group.register(1)
    cancelled_group.cancel()
    cancelled_group.register_refused_step()
    # The group still waits for the cancelled operation to report; only then is
    # there a verdict to inspect.
    assert cancelled_verdicts == []
    cancelled_group.handle_result(Result(1, ok=False, code="cancelled"))
    assert cancelled_verdicts[0].total_steps == 1


def test_the_same_operation_counts_as_one_step() -> None:
    group, verdicts = _group()

    assert group.register(1) is True
    assert group.register(1) is False, "an operation offered twice became two steps"
    group.seal()
    group.handle_result(Result(1, ok=True))

    assert verdicts[0].total_steps == 1
    assert verdicts[0].ok is True


def test_registering_without_an_id_is_a_wiring_error() -> None:
    """``_submit`` returns an id even when it declines, so None here means the
    caller wired something wrong — hiding it as a refused step would bury it."""
    import pytest

    group, _verdicts = _group()

    with pytest.raises(ValueError):
        group.register(None)


def test_cancelling_twice_does_not_revive_a_late_success() -> None:
    """A second cancel must not re-take the snapshot: the result that arrived in
    between belongs to a scene the user had already called off."""
    cancel_log: list = []
    group, verdicts = _group(cancel_log)

    group.register(1)
    group.register(2)
    group.cancel()
    group.handle_result(Result(1, ok=True))  # lands after the user took over
    group.cancel()
    group.handle_result(Result(2, ok=False, code="cancelled"))

    assert len(verdicts) == 1
    assert verdicts[0].completed_steps == 0, "a late success was counted after a second cancel"
    assert verdicts[0].partial_possible is True
    assert sorted(cancel_log) == [1, 2], "an operation was cancelled more than once"


def test_a_scene_where_one_strip_refused_reports_partial_and_is_retried() -> None:
    """Primary took the scene, the mirror did not. Reporting that as done would
    leave one strip out of step with no second attempt."""
    group, verdicts = _group()

    primary_step = 1
    mirror_step = 2
    group.register(primary_step)
    group.register(mirror_step)
    group.seal()
    group.handle_result(Result(primary_step, ok=True))
    group.handle_result(Result(mirror_step, ok=False, code="unavailable"))

    verdict = verdicts[0]
    assert verdict.ok is False, "a rule was confirmed while one strip stayed behind"
    assert verdict.partial is True
    assert (verdict.completed_steps, verdict.total_steps) == (1, 2)
