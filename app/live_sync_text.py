"""Turning Live Sync numbers into lines a person can act on.

Kept apart from the measuring and free of Qt, so the wording can be pinned by
tests without a window, a strip or a screen.

Two blocks, because one hides the other: session totals say how the whole run
went, the recent window says how it is going now, and the gap between them is
the finding.

The labels carry the definitions. Every number here has a plausible wrong
reading, and a diagnostics report is read by someone who was not in this
conversation:

* **link rejections** sound like BLE errors. They are back-pressure — the link
  would not take a write because an earlier one was still going, and the same
  colour is offered again at the next tick.
* **drop ratio** sounds like failed writes. It is computed colours displaced by
  a newer frame before they were ever sent.
* **succeeded + failed** can be less than **submitted**, because writes are still
  in flight when the snapshot is taken. Made to add up, the numbers would lie
  about timing.
* a **stopped** report shows the last thirty seconds *of the run*, not the
  thirty seconds before the export — otherwise every report of a finished
  session would read as zeros.

Labels stay in one language on purpose: these are metric names that end up
pasted into bug reports, and one spelling makes two users' reports comparable.
"""

from __future__ import annotations

from app.live_sync_metrics import RECENT_WINDOW_SECONDS, LiveSyncReport


def _has_anything(report: LiveSyncReport) -> bool:
    session = report.session
    return bool(
        session.seconds
        or session.captured
        or session.processed
        or session.capture_errors
        or session.processing_errors
        or session.commands_submitted
        or session.link_rejections
        or session.reconnects
    )


def format_live_sync(
    report: LiveSyncReport,
    *,
    mode: str = "screen",
    running: bool = False,
    window_seconds: float = RECENT_WINDOW_SECONDS,
) -> list[str]:
    """Two blocks of report lines, or nothing at all.

    An empty list when no session has ever run: a block of zeros would say
    "measured, all quiet" when the truth is "never measured", and the report
    already leaves out sections it has no data for.
    """
    if not _has_anything(report):
        return []

    session = report.session
    recent = report.recent
    state = "running" if running else "stopped"
    window = int(window_seconds)

    in_flight = session.commands_submitted - session.commands_succeeded - session.command_errors
    settled = f"{session.commands_succeeded} succeeded, {session.command_errors} failed"
    if in_flight > 0:
        # Spelled out, or the reader does the subtraction and concludes the
        # numbers are broken.
        settled += f", {in_flight} still in flight"

    lines = [
        "",
        "Live Sync — session",
        f"mode: {mode} ({state})",
        f"duration: {session.seconds}s",
        f"frames: {session.captured} captured, {session.processed} processed, "
        f"{session.frames_coalesced} coalesced",
        f"frame errors: {session.capture_errors} capture, "
        f"{session.processing_errors} processing",
        f"commands: {session.commands_submitted} submitted, {settled}",
        f"link rejections: {session.link_rejections} (link busy, not a write error)",
        f"reconnects: {session.reconnects}",
    ]
    if session.worst_frame_ms:
        lines.append(
            f"worst frame: {session.worst_frame_ms} ms at {session.worst_frame_at}s into the run"
        )
    else:
        lines.append("worst frame: -")

    heading = f"Live Sync — last {window} seconds"
    if not running:
        heading += " of the run"
    lines.extend(
        [
            "",
            heading,
            f"measured over: {recent.seconds}s",
            f"capture: {recent.capture_fps} fps",
            f"commands: {recent.command_rate}/s",
            f"processing time: {recent.frame_ms_avg} ms avg, {recent.frame_ms_p95} ms p95",
            f"drop ratio: {recent.drop_ratio} (frames displaced before sending)",
            f"link rejection rate: {recent.rejection_rate} (share of attempts refused)",
        ]
    )
    return lines
