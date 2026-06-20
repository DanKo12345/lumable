# Changelog

All notable changes to LumaBLE will be documented here.

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
