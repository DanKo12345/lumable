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
make the numbers unfalsifiable. A frame has three separate events, and each is
recorded at the moment it actually happens:

* **captured** — grabbed from the screen. Counted here and nowhere else.
* **processed** — a colour was computed from it and handed to the send path.
* **coalesced** — a newer frame displaced this one while it was still waiting.
  That happens *after* processing, so it must not count as another capture; one
  frame counted twice would push the ratios above one. The drop ratio is
  coalesced over processed: colours computed that never reached the strip.

Commands are counted at each stage they actually reach:

* **commands_submitted** — writes handed to the send path.
* **commands_succeeded** — writes the BLE layer confirmed.
* **command_errors** — writes it refused or failed. Submitted is deliberately
  not the sum of the other two: some are still in flight when the snapshot is
  taken, and pretending otherwise would make the numbers lie about timing.

Frame processing time never includes waiting on BLE — mixing them would make a
slow strip look like slow code. A capture failure and a BLE failure stay apart,
because which end is at fault is the first question worth answering.

Everything is scoped to a **session token**. The colour sliders, DIY and music
share the same streaming path as Screen Sync, so counting writes where they meet
would mix modes into one report. Only events carrying the current token are
recorded, which also drops the late callback of a session that has stopped.

Taking a snapshot never mutates a counter, and every method is cheap enough to
sit on the capture path — a metric that slows the thing down measures itself.
The lock is never held across a BLE call: callers record the outcome, they do not
perform it here.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field

RECENT_WINDOW_SECONDS = 30.0

# Per event kind, sized for the window at a rate no capture path will reach.
# One shared buffer silently evicted the oldest events on a fast session while
# the divisor stayed at the full window, so a healthy 120 fps run reported as a
# slow one — the metric inventing the very problem it exists to detect.
_SAMPLE_LIMIT = 8192


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
    """Nearest-rank percentile: rank = ceil(fraction × count), 1-based.

    Rounding instead of ceiling shifts the rank down on small samples, which
    turns a p95 into something between p90 and p95 exactly when the sample is
    small enough for one frame to matter. Computed on snapshot only — sorting
    per frame would put the cost of measuring onto the path being measured.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = min(len(ordered), max(1, math.ceil(fraction * len(ordered))))
    return ordered[rank - 1]


class LiveSyncMetrics:
    """Counters for one sync session.

    Written from the capture thread and read from the UI thread, so everything
    is guarded. The lock is held only for a few assignments.
    """

    def __init__(self, window_seconds: float = RECENT_WINDOW_SECONDS) -> None:
        self._lock = threading.Lock()
        self._window = float(window_seconds)
        # 0 means "no session running": every recording call is rejected, so a
        # stray write from the sliders or DIY cannot land in a stopped session.
        self._token = 0
        self._next_token = 0
        self._frozen: LiveSyncReport | None = None
        self._reset(0.0)

    def _reset(self, now: float) -> None:
        """Called with the lock held, or from __init__ before it exists."""
        self._started_at = now
        self._stopped_at: float | None = None
        self._captured = 0
        self._processed = 0
        self._coalesced = 0
        self._capture_errors = 0
        self._submitted = 0
        self._succeeded = 0
        self._command_errors = 0
        self._reconnects = 0
        self._queue_max = 0
        self._queue_depth = 0
        self._worst_ms = 0.0
        self._worst_at = 0.0
        # One bounded buffer per kind, so a burst of one cannot evict another.
        self._capture_times: deque[float] = deque(maxlen=_SAMPLE_LIMIT)
        self._frame_times: deque[tuple[float, float]] = deque(maxlen=_SAMPLE_LIMIT)
        self._drop_times: deque[float] = deque(maxlen=_SAMPLE_LIMIT)
        self._command_times: deque[float] = deque(maxlen=_SAMPLE_LIMIT)

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self, now: float) -> int:
        """Begin a session and return its token.

        The token is what every later call must carry. Numbers kept across a
        stop/start would average two different configurations together, and a
        callback from the previous run would land in the new one.
        """
        with self._lock:
            self._next_token += 1
            self._token = self._next_token
            self._frozen = None
            self._reset(now)
            return self._token

    def stop(self, now: float) -> None:
        """End the session, keeping its last snapshot.

        Diagnostics is usually exported *after* stopping — losing the numbers at
        that moment would leave nothing to report about the run just finished.

        Freezing and closing happen under one lock. Split across two, a result
        arriving in between is accepted by the still-current token and then
        vanishes from the very snapshot that was meant to be final.
        """
        with self._lock:
            self._stopped_at = now
            self._frozen = self._report_locked(now)
            self._token = 0

    def current_token(self) -> int:
        with self._lock:
            return self._token

    def _accepts(self, token: int) -> bool:
        """Called with the lock held."""
        return bool(self._token) and token == self._token

    # ── recording ─────────────────────────────────────────────────────
    def frame_captured(self, token: int, now: float) -> None:
        """A frame was grabbed from the screen. The only place captures count."""
        with self._lock:
            if not self._accepts(token):
                return
            self._captured += 1
            self._capture_times.append(now)

    def frame_processed(self, token: int, now: float, frame_ms: float = 0.0) -> None:
        """A colour was computed from a frame and handed to the send path."""
        with self._lock:
            if not self._accepts(token):
                return
            self._processed += 1
            self._frame_times.append((now, max(0.0, float(frame_ms))))
            if frame_ms > self._worst_ms:
                self._worst_ms = float(frame_ms)
                self._worst_at = max(0.0, now - self._started_at)

    def frame_coalesced(self, token: int, now: float) -> None:
        """A newer frame displaced this one before it reached the strip.

        The frame was already captured and processed by the time this happens,
        so it adds neither — only the drop.
        """
        with self._lock:
            if not self._accepts(token):
                return
            self._coalesced += 1
            self._drop_times.append(now)

    def capture_failed(self, token: int, now: float) -> None:
        """The screen could not be grabbed. A different problem from a BLE
        failure, and kept apart so the report says which end is at fault."""
        with self._lock:
            if not self._accepts(token):
                return
            self._capture_errors += 1

    def command_submitted(self, token: int, now: float, queue_depth: int = 0) -> None:
        with self._lock:
            if not self._accepts(token):
                return
            self._submitted += 1
            self._queue_depth = int(queue_depth)
            self._queue_max = max(self._queue_max, int(queue_depth))
            self._command_times.append(now)

    def command_succeeded(self, token: int, now: float) -> None:
        """The BLE layer confirmed the write."""
        with self._lock:
            if not self._accepts(token):
                return
            self._succeeded += 1

    def command_failed(self, token: int, now: float) -> None:
        """Refused or failed. Never counted as a success."""
        with self._lock:
            if not self._accepts(token):
                return
            self._command_errors += 1

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
            return self._report_locked(now)

    def _report_locked(self, now: float) -> LiveSyncReport:
        """Called with the lock held."""
        # Elapsed time comes from the clock, not from the last event. A session
        # watching a still screen sends almost nothing, and measuring it by its
        # final event would report ten quiet minutes as one busy one.
        end = now if self._stopped_at is None else self._stopped_at
        seconds = max(0.0, end - self._started_at)
        session = SessionTotals(
            seconds=round(seconds, 1),
            captured=self._captured,
            processed=self._processed,
            frames_coalesced=self._coalesced,
            capture_errors=self._capture_errors,
            commands_submitted=self._submitted,
            commands_succeeded=self._succeeded,
            command_errors=self._command_errors,
            reconnects=self._reconnects,
            queue_max=self._queue_max,
            worst_frame_ms=round(self._worst_ms, 1),
            worst_frame_at=round(self._worst_at, 1),
        )

        cutoff = end - self._window
        captures = sum(1 for at in self._capture_times if at >= cutoff)
        processed = [ms for at, ms in self._frame_times if at >= cutoff]
        drops = sum(1 for at in self._drop_times if at >= cutoff)
        commands = sum(1 for at in self._command_times if at >= cutoff)
        timed = [ms for ms in processed if ms > 0]
        elapsed = min(self._window, seconds)
        divisor = elapsed or 1.0

        return LiveSyncReport(
            session=session,
            recent=RecentWindow(
                seconds=round(elapsed, 1),
                capture_fps=round(captures / divisor, 1),
                command_rate=round(commands / divisor, 1),
                drop_ratio=round(drops / len(processed), 3) if processed else 0.0,
                frame_ms_avg=round(sum(timed) / len(timed), 1) if timed else 0.0,
                frame_ms_p95=round(_percentile(timed, 0.95), 1),
                queue_depth=self._queue_depth,
            ),
        )
