# Changelog

All notable changes to LumaBLE will be documented here.

## [0.2.4] - 2026-06-30

Drive several strips at once, smoother colour transitions, auto-scenes that follow the app you're using (now free), plus a tidier Configs list and cleaner diagnostics.

### Added
- Mirror across multiple controllers: add several strips in the Device card and control them together — every colour, brightness, power and effect change fans out to all connected controllers, so a multi-strip setup stays in sync from one window. ("Add strip" runs its own scan; single-strip behaviour is unchanged.)
- Auto-scenes by app (free): the strip automatically switches to a scene based on the app or game in the foreground. Map an app to a scene (e.g. `chrome` → Cool white, a game → Red), set a default scene for everything else, and it quietly steps aside while music, screen sync or animations are running.

### Changed
- Smooth colour & brightness fade: the strip now glides between colours and brightness levels instead of snapping, for a calmer look. Rapid changes stay responsive (the newest target always wins).
- Scenes are unified into Quick modes: the separate scene gallery is gone. The built-in quick modes (Chill / Gaming / Night / Rainbow) plus your own saved ones are now the single place for one-tap looks, with the colour wheel and sliders for fine-tuning — no more duplicate "presets vs saved scenes" split.
- Configs list polish: the edit/delete icons are now neutral graphite (no blue tint bleeding through), the colour sample is a slim pill so it clearly reads as a swatch rather than a button, and rows no longer label every plain colour as "Static" (the mode is shown only for effects).

### Fixed
- Live-light preview: the glow no longer clips at the card's edge.

### Install
- The installer now requires Windows 10 or newer (older Windows versions are blocked up front instead of installing a build that can't run).

### Internal
- Hardened licence validation against local config edits.
- Diagnostics no longer surfaces stale crash logs from older versions: logs left by a previous build are cleared on the first launch after an upgrade, and the crash-log history is kept tighter (shorter age window, fewer files).

## [0.2.3.1] - 2026-06-27

### Fixed
- Auto-connect regression from 0.2.3: a single supported controller now connects automatically again even when unrecognised BLE devices are nearby. (0.2.3 started listing unknown devices in the scan results, which broke the "exactly one device found" auto-connect check, so the app would say "1 controller found" but not connect.)

### Changed
- The "update available" pop-up shows a small accent download icon next to the title, matching the Pro/About windows.

## [0.2.3] - 2026-06-27

A reliability, music and device-support pass: stronger reconnection, beat-reactive music with an audio-source picker, a way to add support for unknown controllers, smarter screen-sync colour, and a safer build pipeline.

### Added
- Beat detection for music: a bass-onset detector punches the strip's brightness on the beat instead of only tracking volume, with a new "Beat" slider to set how hard it hits (0 turns it off).
- Audio source for music: choose which output device's sound the music reactivity listens to, instead of always the system default. (Tip in the picker's tooltip: route a specific player or streaming app to its own output device in Windows to make the strip react to just that app.)
- Unsupported controllers are no longer invisible: a scan now also lists nearby unrecognised devices that look like LED controllers, tagged "unsupported". You can select one and hit Connect to capture its GATT details, and the diagnostics report lists those nearby unknown devices (name, address, service UUIDs) so support can be added for them. If a scan finds nothing supported but spots unknown ones, a hint points you to Diagnostics.

### Changed
- BLE auto-reconnect keeps trying with escalating back-off (about 3 minutes) instead of giving up after a few seconds, so a strip switched off and back on re-pairs on its own. After reconnecting it restores the last colour/brightness (and effect), so the strip returns to how you left it.
- Screen sync no longer looks permanently washed out: the colour is now a saturation-weighted average, so vivid parts of the screen drive the strip while large grey/white areas barely count (fully grey frames stay grey).
- Connecting to an unsupported controller now shows a friendly "not supported yet — send diagnostics" message instead of a raw technical error (the technical GATT detail is still saved in the diagnostics history).
- Music uses less CPU: the FFT window and frequency masks are cached between blocks and the analysis runs in float32.
- Diagnostics: the Copy button now includes recent crash logs too (not just Export), and Export reveals the saved file in your file manager so it's ready to send.
- Dropdown lists no longer flash a scrollbar during their open animation.

### Build
- The build runs a startup smoke test on the packaged exe and fails if it crashes on launch (the kind of regression that shipped a non-starting 0.2.1). Added an optional code-signing step.

## [0.2.2] - 2026-06-25

App-driven lighting that works on any controller — react to your music and run smooth animations — plus a weekly schedule, a clearer Pro window, and a lot of UI polish.

### Added
- Music reactivity (Pro): the strip pulses to your system audio in real time. Per-band colours (bass / mids / treble) you can recolour, a Saturation control, and a Speed control that smooths how fast the colour follows the beat. Live colour preview.
- App animations: Breathing, Heartbeat, Candle, Storm, Gradient, Lava and Aurora — computed by the app and streamed, so they work on any controller regardless of its firmware effects. Speed control and live preview.
- Weekly schedule (Pro): choose which days of the week the on/off timer runs, using day-of-week chips. The Windows background tasks use matching weekly triggers, so it also fires when the app is closed.
- Schedule now has its own section in the navigation.
- "Available in Pro" badge on the Schedule card, matching Screen sync and Music — and every Pro badge is now clickable and opens the LumaBLE Pro window.
- The LumaBLE Pro window now lists what Pro unlocks (screen sync, music reactivity, weekly schedule, all effects & scenes, unlimited profiles with import/export) before asking for a key.
- Enabling a streaming mode (music / screen sync / animations) now turns the strip on automatically if it was off.

### Changed
- Connection status dot is now animated: a soft amber pulse while scanning, blue while connecting, green when connected; the scanning/connecting text shows an animated "…".
- Dropdown lists are fully neutral now (removed the blue tint and blue selection highlight) and open with a subtle "pop" animation.
- Redesigned the weekday chips — a glassy look with smooth select/hover animation.
- License activation runs off the UI thread, so the window no longer freezes during the check; the button shows "Checking…" while the request is in flight.
- About window: the open-source components list now includes mss, soundcard and numpy, and the panel got a matching accent halo so it reads as one family with the Pro window.
- Card subtitles are left-aligned on the grid; Settings value controls share one width; section and header icons line up with their titles.
- Music card dims/disables its controls while it's off (like the Schedule card).

### Fixed
- Packaged build crashed on startup with `ModuleNotFoundError: No module named 'PySide6.QtNetwork'` — the build script excluded QtNetwork, which the single-instance guard now needs. The build no longer excludes it or strips `Qt6Network.dll`.
- Device card no longer duplicates the MAC address or shows an empty "RSSI -" when the controller name is unavailable.

### Internal
- Test suite now runs in parallel (much faster); main-window logic split into focused controllers (diagnostics, colour).

## [0.2.1] - 2026-06-23

A maintenance release: a fourth language, smarter first-run defaults, and a calmer, fully neutral dark theme.

### Added
- Spanish (Español) interface translation — a fourth language alongside Russian, English and Chinese.
- Automatic language on first launch: LumaBLE now opens in your Windows system language when it recognises it (e.g. an English Windows opens in English), falling back to English otherwise. Your manual choice is always kept afterwards.
- Single-instance guard: launching LumaBLE again no longer starts a second copy (which could fight over the Bluetooth connection); it brings the existing window to the front instead.
- Screen-sync diagnostics: the diagnostics report now lists capture state, stream error count and the last stream error, making a misbehaving Ambient sync easier to troubleshoot.

### Changed
- Dark theme is now fully neutral graphite — removed the residual cold blue/slate tint from surfaces, cards, buttons and selection. The quick-mode accent no longer bleeds into the window background; the backdrop's only colour comes from the current strip colour.

### Fixed
- Configs panel header ("Configs") is now left-aligned and on-grid like every other card, instead of drifting to the centre.

## [0.2.0] - 2026-06-20

A full interface redesign. LumaBLE moves from a long scrolling card page to a focused, app-style layout with a premium dark look.

### Added
- New app-shell layout: a left navigation rail (Color · Effects · Screen sync · Profiles · Settings) that shows one focused section at a time.
- "Lumen" background: a calm near-black canvas with a soft, slowly breathing glow in the current strip colour.
- Persistent hero light bar that shows the live strip colour and brightness from every section.
- Always-visible connection status in the sidebar — coloured dot, controller name, and a "click to connect" hint while disconnected.
- Screen sync (Ambient): a Pro badge with locked controls until unlocked, plus a live "Capturing · N fps" status while running.
- Profile rows now show a second line with the saved scene (RGB · brightness · static/effect).
- A quiet "update available" pop-up shown by the daily background check — at most once per version, with Update / Later.

### Changed
- Reworked the visual language to a premium graphite theme; removed the heavy purple background and blue surfaces from cards, dropdowns and all overlays.
- Flattened the sidebar items (active item: subtle highlight + left accent bar) and unified the accent colour for active navigation and presets.
- Grouped device, schedule, diagnostics and the language / FPS / theme controls into a single Settings section; promoted Profiles to its own section; the power toggle carries the current strip colour.
- The window now opens at a sensible centered size instead of maximised, with a ceiling so it never reopens oversized.
- Tightened card padding, rounded the recent-colour swatches, compacted the quick-mode buttons and aligned the slider value boxes.
- The live-light preview shows the true colour at any brightness (brightness is conveyed by the glow), so a dim strip is no longer a near-black bar.
- Added spring motion to button presses and hovers.

### Fixed
- The colour glow now follows the applied colour reliably instead of depending on the power-toggle state.
- Stopped identical error dialogs from stacking (e.g. repeated "connect first" while disconnected).
- Fixed the effect-preview strip blending into the background and appearing to vanish.
- Fixed the theme switch so a single click reaches the light theme.
- Fixed the sidebar status text being clipped.
- Synced the version number across project metadata, the Windows build info and the in-app diagnostics.

## [0.1.3] - 2026-06-16

### Added
- Connected Lemon Squeezy Pro activation, validation and deactivation flow.
- Added a background license refresher so Pro checks no longer block the UI.
- Added a polished Pro activation experience with themed status UI and success celebration.
- Added styled app-wide tooltips that match dark and light themes.
- Added effect swatches, Pro lock icons and animated effect-list opening.
- Added smoother effect-preview transitions and active-effect highlighting.

### Improved
- Reduced Aurora background rendering from high refresh to a calmer 30 fps, with low-fps background mode.
- Cached tinted button icons to reduce repeated paint allocations.
- Improved Pro active/deactivate UX with a masked key chip and safer two-click deactivation.
- Reworked locked Pro effects to use visual swatches instead of text lock prefixes.
- Improved light-theme contrast for buttons, sliders, text and edition badges.
- Hardened startup deferred tasks so they cannot fire after the main window starts closing.

### Fixed
- Fixed a tooltip lifecycle leak that could hang the full test suite after many window creations.
- Fixed license state caching so `is_pro()` no longer writes settings or performs network requests during UI rendering.
- Fixed Lemon Squeezy activation instance names to use safe ASCII machine labels.
- Fixed deactivate recovery when the server succeeds but the response is lost.
- Fixed tests so they are isolated from the developer's real local license/settings data.

## [0.1.2] - 2026-06-05

### Fixed
- Fixed a background update-check signal crash that could appear during tests.
- Improved BLE disconnect handling so color commands do not hit a missing BLE client after connection loss.
- Cleared stale BLE error state after successful reconnect.
- Reduced GitHub update-check rate limit noise by throttling automatic checks to once per day.
- Localized diagnostics report labels and BLE history entries according to the selected app language.

### Improved
- Smoothed RGB slider interaction and kept the color preview responsive while dragging.
- Added clearer BLE error text when a controller is not selected, not found, or Windows still shows it as connected.
- Polished About, diagnostics, schedule and update-check microcopy.
- Added issue templates and diagnostics instructions for beta testers.

## [0.1.1] - 2026-06-02

### Changed
- Polished diagnostics and session logs: logs now open in a compact overlay instead of a full main-screen card.
- Improved diagnostic report readability and action button layout.
- Simplified color control flow with automatic RGB and brightness apply.
- Refined profile config actions, rename/delete dialogs and header controls.
- Added app edition information to the About dialog.

## [0.1.0] - 2026-05-06

### Added
- First beta Windows build.
- BLE support for BLEDOM, Triones, BanlanX and Magic Home compatible controllers.
- RGB, brightness, power and built-in effect controls.
- Effect preview strip with speed-aware animation.
- Profiles, scenes, import/export and color history.
- Local schedule timer while the app is running.
- Auto-connect to the last controller and BLE reconnect/retry history.
- Device diagnostics export without personal file paths.
- Tray support, dark/light/auto theme and multilingual UI.
- Freemium feature-gate foundation for future Pro features.

### Notes
- Auto-update checks are prepared but disabled until a public EXE release exists.
- Payment and Lemon Squeezy activation are not connected yet.
