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

from collections.abc import Mapping

from app.live_sync_metrics import RECENT_WINDOW_SECONDS, LiveSyncReport


def _hex(rgb: object) -> str:
    if not isinstance(rgb, (tuple, list)) or len(rgb) != 3:
        return "-"
    try:
        r, g, b = (max(0, min(255, int(channel))) for channel in rgb)
    except (TypeError, ValueError):
        return "-"
    return f"#{r:02X}{g:02X}{b:02X}"


def _settings_lines(settings: Mapping | None) -> list[str]:
    """The settings of the last completed frame, and what it came out as.

    Without these a "wrong colour" report cannot be checked at all: the same
    frame gives a muted lilac on one profile and a saturated blue on another,
    and full-screen versus centre changes it from sky to sunset. Reconstructing
    that from a photograph of a wall is guesswork.

    They belong to the sample rather than to the moment of export, because the
    profile can be changed while syncing and after stopping. Pairing a colour
    with settings it was never made under would describe a run that never
    happened.
    """
    if not settings:
        return []
    if not settings.get("sampled", True):
        # Nothing was produced, so there are no settings that produced it.
        # Naming the current ones here would invent a sample.
        return ["last sample: none, no frame completed this run"]
    return [
        "last sample settings: profile {profile}, region {region}, monitor {monitor}, "
        "intensity {intensity}, smoothness {smoothness}".format(
            profile=settings.get("profile", "-"),
            region=settings.get("region", "-"),
            monitor=settings.get("monitor", "-"),
            intensity=settings.get("intensity", "-"),
            smoothness=settings.get("smoothness", "-"),
        ),
        # Raw is what the frame averaged to; final is after shaping and
        # smoothing. Which of the two is already wrong says whether to look at
        # the sampling or at the profile.
        f"last colour: raw {_hex(settings.get('raw_rgb'))} "
        f"-> final {_hex(settings.get('final_rgb'))}",
    ]


def _has_anything(report: LiveSyncReport) -> bool:
    """Whether anything at all was measured.

    Results are checked separately from submissions even though a result cannot
    exist without one. If that invariant ever breaks, the formatter's job is to
    show the broken numbers, not to decide they cannot have happened and print
    nothing — a diagnostics report that hides a contradiction is worse than one
    that displays it.
    """
    session = report.session
    return bool(
        session.seconds
        or session.captured
        or session.processed
        or session.capture_errors
        or session.processing_errors
        or session.commands_submitted
        or session.commands_succeeded
        or session.command_errors
        or session.link_rejections
        or session.reconnects
    )


def format_live_sync(
    report: LiveSyncReport,
    *,
    mode: str = "screen",
    running: bool = False,
    window_seconds: float = RECENT_WINDOW_SECONDS,
    settings: Mapping | None = None,
    link_measured: bool = True,
) -> list[str]:
    """Two blocks of report lines, or nothing at all.

    An empty list when no session has ever run: a block of zeros would say
    "measured, all quiet" when the truth is "never measured", and the report
    already leaves out sections it has no data for.

    ``link_measured`` is False when the capture is feeding a composer rather
    than writing to the strip itself. The frames are still counted here; the
    commands are not, because they are no longer this controller's. Printing
    their zeros would be the same lie in a smaller place — a run that plainly
    lit the strip, reported as having sent nothing.
    """
    if not _has_anything(report):
        return []
    settings_lines = _settings_lines(settings)

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
        *settings_lines,
        f"duration: {session.seconds}s",
        f"frames: {session.captured} captured, {session.processed} processed, "
        f"{session.frames_coalesced} coalesced",
        f"frame errors: {session.capture_errors} capture, "
        f"{session.processing_errors} processing",
    ]
    if link_measured:
        lines.extend(
            [
                f"commands: {session.commands_submitted} submitted, {settled}",
                f"link rejections: {session.link_rejections} (link busy, not a write error)",
            ]
        )
    else:
        lines.append("commands: written by Fusion — see the Fusion block")
    lines.append(f"reconnects: {session.reconnects}")
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
            *(
                [f"commands: {recent.command_rate}/s"]
                if link_measured
                else []
            ),
            f"processing time: {recent.frame_ms_avg} ms avg, {recent.frame_ms_p95} ms p95",
            *(
                [
                    f"drop ratio: {recent.drop_ratio} (frames displaced before sending)",
                    f"link rejection rate: {recent.rejection_rate} "
                    "(share of attempts refused)",
                ]
                if link_measured
                else []
            ),
        ]
    )
    return lines
