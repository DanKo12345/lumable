from __future__ import annotations

import pytest

from app.ble_reliability import (
    MIN_RECONNECT_DELAY_SECONDS,
    REASON_MANUAL,
    REASON_OUT_OF_RANGE,
    REASON_STACK_ERROR,
    REASON_UNKNOWN,
    RECONNECT_LADDER,
    WritePacer,
    classify_disconnect,
    reconnect_delay,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ── reconnect backoff ────────────────────────────────────────────────────
def test_backoff_climbs_the_ladder_and_then_holds() -> None:
    assert reconnect_delay(1) == RECONNECT_LADDER[0]
    assert reconnect_delay(3) == RECONNECT_LADDER[2]
    # Past the end it stays at the longest rung instead of growing forever.
    assert reconnect_delay(50) == RECONNECT_LADDER[-1]


def test_attempt_zero_or_negative_is_treated_as_the_first() -> None:
    assert reconnect_delay(0) == RECONNECT_LADDER[0]
    assert reconnect_delay(-5) == RECONNECT_LADDER[0]


def test_flapping_link_backs_off_faster() -> None:
    # The strip reconnected and dropped again within seconds: skip a rung.
    assert reconnect_delay(1, last_session_seconds=2.0) == RECONNECT_LADDER[1]
    # A long healthy session before the drop keeps the normal pace.
    assert reconnect_delay(1, last_session_seconds=600.0) == RECONNECT_LADDER[0]


def test_flapping_still_caps_at_the_longest_rung() -> None:
    assert reconnect_delay(99, last_session_seconds=1.0) == RECONNECT_LADDER[-1]


def test_jitter_spreads_around_the_rung_without_going_negative() -> None:
    base = RECONNECT_LADDER[0]
    assert reconnect_delay(1, jitter=0.5, random_unit=lambda: 0.5) == base  # centred
    assert reconnect_delay(1, jitter=0.5, random_unit=lambda: 1.0) > base  # upper edge
    low = reconnect_delay(1, jitter=0.5, random_unit=lambda: 0.0)
    assert low < base
    assert low >= MIN_RECONNECT_DELAY_SECONDS  # never schedules a stampede


def test_jitter_uses_real_randomness_when_not_injected(monkeypatch) -> None:
    # Without this the default was a fixed midpoint, i.e. no jitter at all — and
    # several strips would still retry in lockstep.
    import app.ble_reliability as module

    base = RECONNECT_LADDER[0]
    monkeypatch.setattr(module.random, "random", lambda: 1.0)
    assert reconnect_delay(1, jitter=0.5) > base
    monkeypatch.setattr(module.random, "random", lambda: 0.0)
    assert reconnect_delay(1, jitter=0.5) < base


def test_no_jitter_requested_stays_exact() -> None:
    assert reconnect_delay(2) == RECONNECT_LADDER[1]


# ── write pacing ─────────────────────────────────────────────────────────
def test_first_write_is_immediate() -> None:
    assert WritePacer(0.05, clock=_Clock()).reserve() == 0.0


def test_back_to_back_writes_are_spaced() -> None:
    clock = _Clock()
    pacer = WritePacer(0.05, clock=clock)
    assert pacer.reserve() == 0.0
    # Nothing has advanced, so the next write must wait a full interval.
    assert pacer.reserve() == pytest.approx(0.05)
    assert pacer.reserve() == pytest.approx(0.10)


def test_a_slow_caller_never_waits() -> None:
    clock = _Clock()
    pacer = WritePacer(0.05, clock=clock)
    pacer.reserve()
    clock.advance(1.0)  # plenty of idle time
    assert pacer.reserve() == 0.0


def test_reset_forgets_history() -> None:
    clock = _Clock()
    pacer = WritePacer(0.05, clock=clock)
    pacer.reserve()
    pacer.reset()
    assert pacer.reserve() == 0.0


def test_zero_interval_disables_pacing() -> None:
    pacer = WritePacer(0.0, clock=_Clock())
    assert pacer.reserve() == 0.0
    assert pacer.reserve() == 0.0


# ── disconnect reasons ───────────────────────────────────────────────────
def test_manual_disconnect_wins() -> None:
    assert classify_disconnect(manual=True, error_text="timeout") == REASON_MANUAL


def test_range_and_stack_errors_are_recognised() -> None:
    assert classify_disconnect(error_text="Device is not connected") == REASON_OUT_OF_RANGE
    assert classify_disconnect(error_text="The operation timed out") == REASON_OUT_OF_RANGE
    assert classify_disconnect(error_text="Access denied") == REASON_STACK_ERROR
    assert classify_disconnect(error_text="Element not found") == REASON_STACK_ERROR


def test_silent_instant_drop_reads_as_out_of_range() -> None:
    assert classify_disconnect(session_seconds=1.0) == REASON_OUT_OF_RANGE


def test_unexplained_drop_after_a_long_session_stays_unknown() -> None:
    # Better an honest "unknown" than a confidently wrong diagnosis.
    assert classify_disconnect(session_seconds=3600.0) == REASON_UNKNOWN
    assert classify_disconnect() == REASON_UNKNOWN
