# LumaBLE 0.3.5 (beta)

Trust & Accessibility: update checks now understand beta releases and show what changed, the interface stays usable at Windows display scaling and short window heights, and motion and keyboard behaviour follow the user's needs.

## Added
- **A clearer update window.** See the installed and available versions, release title and notes before opening the download page. Choose **Remind later** or skip only that exact version.
- **Reduced Motion.** Choose **Match Windows**, **Reduce motion** or **Full motion** in Settings. Reduced Motion removes decorative ripples, slides, pulses and confetti while real operations and effects on the strip continue normally.
- **Better keyboard and screen-reader support.** Weekday toggles, editable value readouts and scene tiles now expose their real roles and state. Focused controls scroll into view, scene tiles support arrow navigation, and their menu opens from the keyboard.

## Changed
- **Reliable beta updates.** LumaBLE correctly orders beta, release-candidate and final versions, ignores drafts and does not mistake build metadata for a newer release.
- **Comfortable at 125% and 150%.** The main window respects the available Windows work area, and navigation remains reachable on short displays.
- **Dialogs that fit.** Logs, About, Pro, confirmations and the colour picker keep their actions visible and scroll only the content that can overflow.
- **Lighter theme refreshes.** Changing the theme or accent no longer repeats expensive application-wide styling when nothing global changed.
- **Safer release notes.** GitHub titles and notes are bounded and shown as plain text.

## Fixed
- Skipping one update no longer hides newer beta or final releases, and a manual check still reports the skipped version.
- Closing the local API no longer leaves an event-stream handler running or prints a socket traceback.
- Arrowing through scene tiles no longer leaves the grid, changes column on an incomplete row or applies a scene accidentally.
- Long confirmation text no longer clips the actions below it.
- Scrollable dialogs remain visually correct in the light theme.

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX).
