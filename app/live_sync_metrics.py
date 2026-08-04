"""Hard numbers for Screen Sync and music, so "it feels slower" can be checked.

Live sync fails in ways nobody describes accurately: a little lag, an occasional
stutter, a strip that drifts out of step after twenty minutes. Words produce
impressions; a diagnostics report produces frame rates, dropped frames and queue
depth.

**Two layers, because one hides the other.** Session totals say how the whole run
went. They cannot show a degradation that started at minute twenty-five — a
healthy first half averages the bad ending away. So everything is also reported
over a recent window, and the difference between the two layers is the finding:
session 30 fps with recent 6 fps is a strip that fell behind and stayed there.

Definitions are fixed here rather than left to each call site, because loose ones
make the numbers unfalsifiable:

* **captured** — a frame was grabbed from the screen.
* **processed** — a colour was computed from it *and* handed to the send path.
* **coalesced** — a newer frame replaced one still waiting. Counted apart from
  errors: it means the sync is keeping up with the screen but not the strip.
* **commands_submitted** — writes handed to the send path.
* **commands_succeeded** — writes the BLE layer confirmed.
* **command_errors** — writes it refused or failed. Submitted is deliberately
  not the sum of the other two: some are still in flight when the snapshot is
  taken, and pretending otherwise would make the numbers lie about timing.
* Frame processing time never includes waiting on BLE. Mixing them would make a
  slow strip look like slow code.

Everything is scoped to a **session token**. The colour sliders, DIY and music
share the same streaming path as Screen Sync, so counting writes where they meet
would mix modes into one report. Only events carrying the current token are
recorded, which also drops the late callback of a session that has already
stopped.

Taking a snapshot never mutates a counter, and every method is cheap enough to
sit on the capture path — a metric that slows the thing down measures itself.
The lock is never held across a BLE call: callers record the outcome, they do not
perform it here.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field

# Frames arrive at up to ~60/s; this covers the recent window at that rate with
# room to spare, and is bounded so a long session cannot grow memory.
_SAMPLE_LIMIT = 4096
RECENT_WINDOW_SECONDS = 30.0


@dataclass(frozen=True)
class SessionTotals:
    """The whole run. Stable, and blind to when things went wrong."""

    seconds: float = 0.0
    captured: int = 0
    processed: int = 0
    frames_coalesced: int = 0
    capture_errors: int = 0
    commands_submitted: int = 0
    commands_succeeded: int = 0
    command_errors: int = 0
    reconnects: int = 0
    queue_max: int = 0
    worst_frame_ms: float = 0.0
    # When the worst frame happened, in seconds from the start of the session.
    # Without it a single stall from minute two reads as a problem happening now.
    worst_frame_at: float = 0.0


@dataclass(frozen=True)
class RecentWindow:
    """The last few seconds. This is where a degradation shows up."""

    seconds: float = 0.0
    capture_fps: float = 0.0
    command_rate: float = 0.0
    drop_ratio: float = 0.0
    frame_ms_avg: float = 0.0
    frame_ms_p95: float = 0.0
    queue_depth: int = 0


@dataclass(frozen=True)
class LiveSyncReport:
    session: SessionTotals = field(default_factory=SessionTotals)
    recent: RecentWindow = field(default_factory=RecentWindow)


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. Computed on snapshot only — sorting per frame
    would put the cost of measuring on the path being measured."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered)) - 1))
    return ordered[index]


class LiveSyncMetrics:
    """Counters for one sync session.

    Written from the capture thread and read from the UI thread, so everything
    is guarded. The lock is held only for a few assignments.
    """

    def __init__(self, window_seconds: float = RECENT_WINDOW_SECONDS) -> None:
        self._lock = threading.Lock()
        self._window = float(window_seconds)
        self._started_at = 0.0
        self._last_at = 0.0
        self._captured = 0
        self._processed = 0
        self._coalesced = 0
        self._commands = 0
        self._command_errors = 0
        self._reconnects = 0
        self._queue_max = 0
        self._queue_depth = 0
        self._worst_ms = 0.0
        self._worst_at = 0.0
        self._capture_errors = 0
        self._succeeded = 0
        # 0 means "no session running": every recording call is rejected, so a
        # stray write from the sliders or DIY cannot land in a stopped session.
        self._token = 0
        self._next_token = 0
        self._frozen: LiveSyncReport | None = None
        # (timestamp, kind, value) — kind: "frame" | "drop" | "command"
        self._events: deque = deque(maxlen=_SAMPLE_LIMIT)

    # ── recording ─────────────────────────────────────────────────────
    def start(self, now: float) -> int:
        """Begin a session and return its token.

        The token is what every later call must carry. Numbers kept across a
        stop/start would average two different configurations together, and a
        callback from the previous run would land in the new one.
        """
        with self._lock:
            self._next_token += 1
            self._token = self._next_token
            self._started_at = now
            self._last_at = now
            self._captured = self._processed = self._coalesced = 0
            self._capture_errors = 0
            self._commands = self._succeeded = self._command_errors = self._reconnects = 0
            self._queue_max = self._queue_depth = 0
            self._worst_ms = self._worst_at = 0.0
            self._frozen = None
            self._events.clear()
            return self._token

    def stop(self, now: float) -> None:
        """End the session, keeping its last snapshot.

        Diagnostics is usually exported *after* stopping — losing the numbers at
        that moment would leave nothing to report about the run just finished.
        """
        report = self.report(now)
        with self._lock:
            self._frozen = report
            self._token = 0

    def current_token(self) -> int:
        with self._lock:
            return self._token

    def _accepts(self, token: int) -> bool:
        """Called with the lock held."""
        return bool(self._token) and token == self._token

    def frame_processed(self, token: int, now: float, frame_ms: float = 0.0) -> None:
        """A captured frame became a colour and reached the send path."""
        with self._lock:
            if not self._accepts(token):
                return
            self._captured += 1
            self._processed += 1
            self._last_at = now
            if frame_ms > 0:
                self._events.append((now, "frame", float(frame_ms)))
                if frame_ms > self._worst_ms:
                    self._worst_ms = float(frame_ms)
                    self._worst_at = max(0.0, now - self._started_at)
            else:
                self._events.append((now, "frame", 0.0))

    def frame_coalesced(self, token: int, now: float) -> None:
        """A newer frame replaced one still waiting: keeping up with the screen,
        not with the strip. Counted once, on the frame that was displaced."""
        with self._lock:
            if not self._accepts(token):
                return
            self._captured += 1
            self._coalesced += 1
            self._last_at = now
            self._events.append((now, "drop", 0.0))

    def capture_failed(self, token: int, now: float) -> None:
        """The screen could not be grabbed. A different problem from a BLE
        failure, and kept apart so the report says which end is at fault."""
        with self._lock:
            if not self._accepts(token):
                return
            self._capture_errors += 1
            self._last_at = now

    def command_submitted(self, token: int, now: float, queue_depth: int = 0) -> None:
        with self._lock:
            if not self._accepts(token):
                return
            self._commands += 1
            self._queue_depth = int(queue_depth)
            self._queue_max = max(self._queue_max, int(queue_depth))
            self._events.append((now, "command", 0.0))

    def command_succeeded(self, token: int, now: float) -> None:
        """The BLE layer confirmed the write."""
        with self._lock:
            if not self._accepts(token):
                return
            self._succeeded += 1
            self._last_at = now

    def command_failed(self, token: int, now: float) -> None:
        """The write was refused or failed. Never counted as a success."""
        with self._lock:
            if not self._accepts(token):
                return
            self._command_errors += 1
            self._last_at = now

    def reconnected(self, token: int) -> None:
        with self._lock:
            if not self._accepts(token):
                return
            self._reconnects += 1

    # ── reading ───────────────────────────────────────────────────────
    def report(self, now: float) -> LiveSyncReport:
        """A snapshot. Reads only: taking one must never change what it measures."""
        with self._lock:
            if self._frozen is not None:
                return self._frozen
            session = SessionTotals(
                seconds=round(max(0.0, self._last_at - self._started_at), 1),
                captured=self._captured,
                processed=self._processed,
                frames_coalesced=self._coalesced,
                capture_errors=self._capture_errors,
                commands_submitted=self._commands,
                commands_succeeded=self._succeeded,
                command_errors=self._command_errors,
                reconnects=self._reconnects,
                queue_max=self._queue_max,
                worst_frame_ms=round(self._worst_ms, 1),
                worst_frame_at=round(self._worst_at, 1),
            )
            cutoff = now - self._window
            recent = [event for event in self._events if event[0] >= cutoff]
            queue_depth = self._queue_depth
            elapsed = min(self._window, max(0.0, now - self._started_at))

        frames = [value for _, kind, value in recent if kind == "frame"]
        drops = sum(1 for _, kind, _ in recent if kind == "drop")
        commands = sum(1 for _, kind, _ in recent if kind == "command")
        timed = [value for value in frames if value > 0]
        captured = len(frames) + drops
        divisor = elapsed or 1.0

        return LiveSyncReport(
            session=session,
            recent=RecentWindow(
                seconds=round(elapsed, 1),
                capture_fps=round(len(frames) / divisor, 1),
                command_rate=round(commands / divisor, 1),
                drop_ratio=round(drops / captured, 3) if captured else 0.0,
                frame_ms_avg=round(sum(timed) / len(timed), 1) if timed else 0.0,
                frame_ms_p95=round(_percentile(timed, 0.95), 1),
                queue_depth=queue_depth,
            ),
        )
