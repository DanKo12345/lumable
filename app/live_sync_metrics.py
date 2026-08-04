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

A drop is recorded against the frame it belongs to, which is why
``frame_processed`` hands back an id and ``frame_coalesced`` takes it. Filtering
the two by their own timestamps instead lets a frame processed just before the
window opens be dropped just after it: the numerator and denominator would then
describe different sets of frames, hiding drops at one edge and reporting a
ratio above one at the other. Clamping the result would only hide the miscount.

Commands are counted at each stage they actually reach:

* **commands_submitted** — writes the BLE layer accepted.
* **commands_succeeded** — writes it confirmed.
* **command_errors** — writes that failed. Submitted is deliberately not the sum
  of the other two: some are still in flight when the snapshot is taken, and
  pretending otherwise would make the numbers lie about timing.
* **link_rejections** — frames the link would not take because an earlier write
  was still going. Not an error and not a coalesced frame: nothing displaced it
  and the same colour is offered again at the next tick. It is the honest
  measure of back-pressure, and it replaced a queue depth that could only ever
  read 0 or 1 — a number dressed as a queue when the link permits one write at
  a time says nothing at all.

Frame processing time never includes waiting on BLE — mixing them would make a
slow strip look like slow code. Failures are kept in three separate counts,
because which end is at fault is the first question worth answering:
``capture_errors`` is the screen refusing to be read, ``processing_errors`` is
this application's own colour code raising, and ``command_errors`` is the strip.
Folding the middle one into the first would make a bug here look like a driver
problem on the user's machine.

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
    processing_errors: int = 0
    commands_submitted: int = 0
    commands_succeeded: int = 0
    command_errors: int = 0
    link_rejections: int = 0
    reconnects: int = 0
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
    rejection_rate: float = 0.0


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
        self._processing_errors = 0
        self._submitted = 0
        self._succeeded = 0
        self._command_errors = 0
        self._link_rejections = 0
        self._reconnects = 0
        self._worst_ms = 0.0
        self._worst_at = 0.0
        # One bounded buffer per kind, so a burst of one cannot evict another.
        self._capture_times: deque[float] = deque(maxlen=_SAMPLE_LIMIT)
        self._command_times: deque[float] = deque(maxlen=_SAMPLE_LIMIT)
        self._rejection_times: deque[float] = deque(maxlen=_SAMPLE_LIMIT)
        # Processed frames as [at, ms, dropped]. The drop lives on the frame's
        # own entry, so both sides of the ratio are filtered by one timestamp.
        self._frames: deque[list] = deque(maxlen=_SAMPLE_LIMIT)
        # Ids are consecutive, so the entry for a frame is found by arithmetic
        # rather than by a lookup table that would outlive the buffer.
        self._frame_seq = 0

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

        Stopping an already-stopped session does nothing. Without that guard a
        second call moves ``_stopped_at`` forward and the finished run grows
        longer every time something asks it to stop again.
        """
        with self._lock:
            if not self._token:
                return
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

    def frame_processed(self, token: int, now: float, frame_ms: float = 0.0) -> int:
        """A colour was computed from a frame and handed to the send path.

        Returns an id for the frame, to be passed to :meth:`frame_coalesced` if
        a newer frame displaces it. Returns 0 when nothing was recorded.
        """
        with self._lock:
            if not self._accepts(token):
                return 0
            self._processed += 1
            self._frame_seq += 1
            self._frames.append([now, max(0.0, float(frame_ms)), False])
            if frame_ms > self._worst_ms:
                self._worst_ms = float(frame_ms)
                self._worst_at = max(0.0, now - self._started_at)
            return self._frame_seq

    def frame_coalesced(self, token: int, frame_id: int) -> None:
        """A newer frame displaced this one before it reached the strip.

        The frame was already captured and processed by the time this happens,
        so it adds neither — only the drop, recorded against that frame rather
        than against the moment of displacement.
        """
        with self._lock:
            if not self._accepts(token) or frame_id <= 0:
                return
            entry = self._frame_entry(frame_id)
            if entry is None:
                # Older than the buffer keeps. It cannot affect the window, and
                # there is nothing left to deduplicate against.
                self._coalesced += 1
                return
            if entry[2]:
                return  # already dropped: one frame, one drop
            entry[2] = True
            self._coalesced += 1

    def _frame_entry(self, frame_id: int) -> list | None:
        """Called with the lock held."""
        oldest_id = self._frame_seq - len(self._frames) + 1
        index = frame_id - oldest_id
        if index < 0 or index >= len(self._frames):
            return None
        return self._frames[index]

    def capture_failed(self, token: int, now: float) -> None:
        """The screen could not be grabbed — the machine's end."""
        with self._lock:
            if not self._accepts(token):
                return
            self._capture_errors += 1

    def processing_failed(self, token: int, now: float) -> None:
        """The frame arrived but our own colour code raised.

        Separate from a capture failure on purpose: a bug in the filter or the
        colour maths reported as "screen capture failed" sends everyone looking
        at drivers and permissions instead of at this application.
        """
        with self._lock:
            if not self._accepts(token):
                return
            self._processing_errors += 1

    def command_submitted(self, token: int, now: float) -> None:
        """The BLE layer took the write."""
        with self._lock:
            if not self._accepts(token):
                return
            self._submitted += 1
            self._command_times.append(now)

    def link_rejected(self, token: int, now: float) -> None:
        """The link would not take the write: an earlier one was still going.

        Neither an error nor a coalesced frame — nothing displaced this colour,
        and the next tick offers it again.
        """
        with self._lock:
            if not self._accepts(token):
                return
            self._link_rejections += 1
            self._rejection_times.append(now)

    def command_succeeded(self, token: int, now: float) -> None:
        """The BLE layer confirmed the write."""
        with self._lock:
            if not self._accepts(token):
                return
            self._succeeded += 1

    def command_failed(self, token: int, now: float) -> None:
        """An accepted write that ended badly. Never counted as a success.

        A write the link would not take is not one of these — see
        :meth:`link_rejected`.
        """
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
            processing_errors=self._processing_errors,
            commands_submitted=self._submitted,
            commands_succeeded=self._succeeded,
            command_errors=self._command_errors,
            link_rejections=self._link_rejections,
            reconnects=self._reconnects,
            worst_frame_ms=round(self._worst_ms, 1),
            worst_frame_at=round(self._worst_at, 1),
        )

        cutoff = end - self._window
        captures = sum(1 for at in self._capture_times if at >= cutoff)
        commands = sum(1 for at in self._command_times if at >= cutoff)
        rejections = sum(1 for at in self._rejection_times if at >= cutoff)
        # Both sides of the drop ratio come from the same frames: a frame in the
        # window contributes its own drop, and one outside it contributes
        # neither. The ratio cannot exceed one without a real miscount.
        windowed = [frame for frame in self._frames if frame[0] >= cutoff]
        processed = len(windowed)
        drops = sum(1 for frame in windowed if frame[2])
        timed = [frame[1] for frame in windowed if frame[1] > 0]
        elapsed = min(self._window, seconds)
        divisor = elapsed or 1.0

        return LiveSyncReport(
            session=session,
            recent=RecentWindow(
                seconds=round(elapsed, 1),
                capture_fps=round(captures / divisor, 1),
                command_rate=round(commands / divisor, 1),
                drop_ratio=round(drops / processed, 3) if processed else 0.0,
                frame_ms_avg=round(sum(timed) / len(timed), 1) if timed else 0.0,
                frame_ms_p95=round(_percentile(timed, 0.95), 1),
                # Of everything offered to the link, the share it would not take.
                rejection_rate=(
                    round(rejections / (commands + rejections), 3)
                    if commands + rejections
                    else 0.0
                ),
            ),
        )
