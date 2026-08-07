# LumaBLE 0.3.8 (beta)

This release makes Screen Sync measurable and more reliable, then brings the app's everyday controls into one clearer visual system.

## Screen Sync
- **Live Sync diagnostics.** Reports now show the whole session and the last 30 seconds separately: capture rate, processing time, displaced frames, BLE submissions, failures, link rejections and reconnects.
- **A report that explains colour.** The last completed frame records its monitor, capture area, response profile, intensity and smoothness alongside the detected and final RGB values.
- **Correct frame cadence.** Processing time is no longer added on top of the requested frame interval, so capture can hold its configured pace when the machine has enough headroom.
- **Honest BLE back-pressure.** A busy link is reported separately from a failed write, and a refused colour is retried instead of leaving a static screen on the wrong colour.
- **Visual capture-area control.** Full, Centre, Top and Bottom are now illustrated inside the selector, use the exact same geometry as capture, and work with mouse or keyboard.

## Refreshed
- The main Colour card and RGB picker have clearer grouping, consistent spacing and cursor bounds that stay inside the colour plane.
- Profiles now separate saving from the saved list and keep compact actions aligned.
- Music reaction now groups its state, source, device, response controls and bass/mid/treble colours without unnecessary scrolling.
- Strip Groups now separate creating a group from managing saved groups, with compact member choices and a quiet delete action.

## Fixed
- A late Screen Sync frame from a stopped session can no longer reach either the metrics or the strip.
- BLE results are attributed to the command that produced them even when callbacks complete on another thread.
- Selected segmented-control labels no longer lose their final glyph, including Cyrillic text at Windows display scaling.
- Capture-area glyphs and colour-picker cursors remain inside their rounded frames.

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX). The installer is currently unsigned, so Windows SmartScreen may show an unknown-publisher warning.
