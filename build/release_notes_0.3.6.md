# LumaBLE 0.3.6 (beta)

Automations arrive as one understandable rule system: schedule the light, react to apps or idle time, pause everything safely, and see what happened afterwards.

## Added
- **One Automations screen.** Create, edit, enable and delete rules for time, foreground apps, idle time, LumaBLE startup and strip connections.
- **Rules that work with LumaBLE closed.** Supported Pro power schedules are registered with Windows and catch up after sleep without waking the computer just for the light.
- **Automation history.** See which rule ran, why another was skipped, how often it repeated and whether an operation failed or was cancelled.
- **A durable pause.** Pause and resume apply to both the open app and Windows background runs, survive restarts and clearly show when Windows has not received the request yet.

## Changed
- **Safe migration.** Existing Schedule and App Triggers become rules with a backup and a rollback-aware handoff from the old Windows tasks.
- **A clearer rule editor.** Consistent fields, weekday controls, advanced options, Pro marking and pinned actions remain usable on short windows.
- **Refreshed Pro experience.** The Pro window, badges, icons and accent controls use a calmer hierarchy and more consistent spacing.
- **A better phone remote.** Local API pairing and controls now use a compact mobile-first layout with sticky status, denser colour controls and room for the browser toolbar.

## Fixed
- Update checks retry while LumaBLE remains open, and a manual check opens the full update window immediately.
- Partial or failed scene writes can no longer be recorded as a successful automation.
- Overdue rules no longer fight each other or run twice when the app and a Windows task overlap.
- Pause, resume, cancellation and shutdown no longer leave stale work that can return later.
- Clicking a discovered controller now continues into the actual connection flow.
- Rule fields and footer actions no longer clip or jump when advanced settings are opened.

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX).
