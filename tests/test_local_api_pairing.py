from __future__ import annotations

from app.local_api.pairing import PairingAttemptLimiter, PairingManager


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _manager(clock=None) -> PairingManager:
    return PairingManager(session_ttl=100, code_ttl=10, clock=clock or _Clock())


def test_new_code_is_six_digits() -> None:
    code = _manager().new_code()
    assert len(code) == 6 and code.isdigit()


def test_code_expires() -> None:
    clock = _Clock()
    mgr = _manager(clock)
    code = mgr.new_code()
    assert mgr.current_code() == code
    clock.advance(11)
    assert mgr.current_code() == ""


def test_pair_with_correct_code_issues_session() -> None:
    mgr = _manager()
    code = mgr.new_code()
    token = mgr.pair(code)
    assert token
    assert mgr.is_valid_session(token)


def test_pair_with_wrong_code_fails() -> None:
    mgr = _manager()
    mgr.new_code()
    assert mgr.pair("000000") is None
    assert mgr.pair("") is None


def test_code_is_one_time() -> None:
    mgr = _manager()
    code = mgr.new_code()
    assert mgr.pair(code)
    assert mgr.current_code() == ""      # consumed
    assert mgr.pair(code) is None         # can't reuse


def test_session_expires() -> None:
    clock = _Clock()
    mgr = _manager(clock)
    token = mgr.pair(mgr.new_code())
    assert mgr.is_valid_session(token)
    clock.advance(101)
    assert not mgr.is_valid_session(token)


def test_revoke_all_drops_sessions_and_code() -> None:
    mgr = _manager()
    token = mgr.pair(mgr.new_code())
    mgr.new_code()
    mgr.revoke_all()
    assert not mgr.is_valid_session(token)
    assert mgr.current_code() == ""
    assert mgr.session_count() == 0


def test_invalid_session_tokens_are_rejected() -> None:
    mgr = _manager()
    assert not mgr.is_valid_session("")
    assert not mgr.is_valid_session("nope")


def test_session_limit_evicts_the_oldest_phone() -> None:
    mgr = PairingManager(max_sessions=2)
    first = mgr.pair(mgr.new_code())
    second = mgr.pair(mgr.new_code())
    third = mgr.pair(mgr.new_code())

    assert not mgr.is_valid_session(first)
    assert mgr.is_valid_session(second)
    assert mgr.is_valid_session(third)
    assert mgr.session_count() == 2


def test_pairing_attempt_limiter_allows_a_small_window_then_throttles() -> None:
    clock = _Clock()
    limiter = PairingAttemptLimiter(max_attempts=2, window_seconds=10, clock=clock)

    assert limiter.allow_attempt("192.168.1.20")
    assert limiter.allow_attempt("192.168.1.20")
    assert not limiter.allow_attempt("192.168.1.20")
    assert limiter.allow_attempt("192.168.1.21")

    clock.advance(11)
    assert limiter.allow_attempt("192.168.1.20")


def test_pairing_attempt_limiter_clears_after_success() -> None:
    limiter = PairingAttemptLimiter(max_attempts=2)

    assert limiter.allow_attempt("192.168.1.20")
    limiter.record_success("192.168.1.20")
    assert limiter.allow_attempt("192.168.1.20")
    assert limiter.allow_attempt("192.168.1.20")
