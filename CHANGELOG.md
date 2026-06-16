# Changelog

All notable changes to LumaBLE will be documented here.

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
