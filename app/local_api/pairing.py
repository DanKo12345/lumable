"""Phone pairing and short-lived sessions for the mobile remote.

The token that unlocks the whole API never travels to the phone. Instead the app
shows a short one-time code; the phone posts it to ``/pair`` and gets back a
session token that only works for a while and is thrown away when the API is
turned off or its token is regenerated. Pure and clock-injectable so it's easy
to test.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable

CODE_TTL_SECONDS = 300           # a pairing code is valid for 5 minutes
SESSION_TTL_SECONDS = 24 * 3600  # a paired phone stays authorised for a day
MAX_SESSIONS = 5
PAIR_ATTEMPTS_PER_MINUTE = 5
PAIR_ATTEMPT_WINDOW_SECONDS = 60
_MAX_TRACKED_CLIENTS = 256


class PairingAttemptLimiter:
    """Thread-safe per-client throttle for the unauthenticated pairing route.

    The code is only six digits, so LAN pairing must not accept unlimited
    guesses. Successful pairing clears the client's short attempt history.
    """

    def __init__(
        self,
        *,
        max_attempts: int = PAIR_ATTEMPTS_PER_MINUTE,
        window_seconds: float = PAIR_ATTEMPT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max(1, int(max_attempts))
        self._window = max(1.0, float(window_seconds))
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow_attempt(self, client: str) -> bool:
        """Reserve one pairing attempt for ``client`` if its window allows it."""
        now = self._clock()
        key = str(client or "unknown")
        with self._lock:
            self._prune_locked(now)
            attempts = self._attempts.setdefault(key, deque())
            cutoff = now - self._window
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self._max_attempts:
                return False
            attempts.append(now)
            return True

    def record_success(self, client: str) -> None:
        with self._lock:
            self._attempts.pop(str(client or "unknown"), None)

    def _prune_locked(self, now: float) -> None:
        cutoff = now - self._window
        for key, attempts in list(self._attempts.items()):
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                del self._attempts[key]
        while len(self._attempts) >= _MAX_TRACKED_CLIENTS:
            oldest = min(self._attempts, key=lambda key: self._attempts[key][0])
            del self._attempts[oldest]


class PairingManager:
    def __init__(
        self,
        *,
        session_ttl: float = SESSION_TTL_SECONDS,
        code_ttl: float = CODE_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._session_ttl = float(session_ttl)
        self._code_ttl = float(code_ttl)
        self._max_sessions = max(1, int(max_sessions))
        self._code = ""
        self._code_expires = 0.0
        self._sessions: dict[str, float] = {}  # session token -> expiry time
        self._lock = threading.RLock()

    # ── pairing code ──────────────────────────────────────────────────
    def new_code(self) -> str:
        """Generate a fresh 6-digit pairing code (shown in the app)."""
        with self._lock:
            self._code = f"{secrets.randbelow(1_000_000):06d}"
            self._code_expires = self._clock() + self._code_ttl
            return self._code

    def current_code(self) -> str:
        """The active code, or '' if none / expired."""
        with self._lock:
            if self._code and self._clock() <= self._code_expires:
                return self._code
            return ""

    # ── sessions ──────────────────────────────────────────────────────
    def pair(self, code: str) -> str | None:
        """Exchange a valid code for a session token, or None. The code is
        one-time: it's consumed on success."""
        with self._lock:
            candidate = str(code or "").strip()
            active_code = self.current_code()
            if not candidate or not active_code or not hmac.compare_digest(candidate, active_code):
                return None
            self.prune()
            while len(self._sessions) >= self._max_sessions:
                oldest = min(self._sessions, key=self._sessions.__getitem__)
                del self._sessions[oldest]
            token = secrets.token_urlsafe(24)
            self._sessions[token] = self._clock() + self._session_ttl
            self._clear_code()
            return token

    def is_valid_session(self, token: str) -> bool:
        with self._lock:
            key = str(token or "").strip()
            expiry = self._sessions.get(key)
            if expiry is None:
                return False
            if self._clock() > expiry:
                del self._sessions[key]
                return False
            return True

    def revoke_all(self) -> None:
        """Drop every session and any pending code (API disabled / token reset)."""
        with self._lock:
            self._sessions.clear()
            self._clear_code()

    def prune(self) -> None:
        with self._lock:
            now = self._clock()
            for token in [token for token, expiry in self._sessions.items() if now > expiry]:
                del self._sessions[token]

    def session_count(self) -> int:
        with self._lock:
            self.prune()
            return len(self._sessions)

    def _clear_code(self) -> None:
        self._code = ""
        self._code_expires = 0.0
