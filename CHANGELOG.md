# Changelog

All notable changes to LumaBLE will be documented here.

## [0.3.9] - 2026-08-12

Windows integration and portability: everyday controls now stay close at hand, automations understand the PC's session state, settings can move safely between installations, and Music Sync learns the room instead of reacting to a fixed noise threshold.

### Added
- Tray actions for connection status, recent scenes, Screen Sync and Music Sync, refreshed immediately before the menu opens.
- Optional global hotkeys for Screen Sync and Music Sync, with visible invalid or conflicting bindings and no new shortcuts claimed automatically after an update.
- Automation triggers for Windows lock, unlock, sleep and wake, including a bounded wait for Bluetooth to return after resume.
- A versioned full backup for portable scenes, rules, groups and settings, with validation, an automatic copy of the current configuration and atomic restoration.
- Music Sync diagnostics for source, session duration, learned noise floor, detected beats, suppressed blocks and peak level.

### Changed
- Music Sync now uses an adaptive noise floor with hysteresis, a time-based beat cooldown and bass-share analysis that is less sensitive to changes in overall volume.
- The existing Beat control keeps its original meaning: it changes flash depth, while sensitivity adapts automatically.
- Recent scenes record only successful manual applications; recurring automations do not displace the user's choices.
- Backup and automation messages were simplified and reviewed across English, Russian, Spanish and Chinese.

### Fixed
- Clearing a global hotkey now leaves it unassigned instead of silently restoring its default.
- Invalid hotkey input no longer overwrites or re-registers working bindings, and common Screen Sync or Music combinations are suggestions rather than automatic defaults.
- Windows session events now reach the automation engine through Qt's native event dispatch, and lock/unlock trigger icons are present instead of blank placeholders.
- Music Sync resets its learned state when the source changes, a session restarts or audio capture fails, and old beat envelopes continue to decay in silence.
- Restoring a backup freezes every settings writer before shutdown, preventing live controllers from overwriting the restored file.

## [0.3.8] - 2026-08-07

Live Sync and visual consistency: Screen Sync now explains how it is performing and which frame produced its last colour, while the app's main editing cards share one clearer layout.

### Added
- Live Sync diagnostics for the complete session and the last 30 seconds, including capture rate, processing time, displaced frames, command outcomes, BLE link rejections and reconnects.
- The last Screen Sync sample now records its monitor, region, response profile, intensity, smoothness and detected-to-final RGB pair.
- A command-line frame analyser for comparing every response profile and capture region against a supplied image without running BLE.
- A visual capture-area selector whose Full, Centre, Top and Bottom drawings use the same geometry as the actual screen crop.

### Changed
- Screen capture schedules against an absolute frame deadline, so processing time no longer silently lowers the requested capture rate.
- Busy BLE writes are measured as back-pressure rather than failures, and refused colours remain pending for a later retry.
- Colour controls, the RGB picker, Profiles, Music reaction and Strip Groups now use the same section hierarchy, compact actions and spacing system.
- Screen Sync area selection and other segmented controls now support arrow keys, Home/End and keyboard-only focus rings.
- The README leads with the controller names people see on their strips and in companion apps.

### Fixed
- Late frames from a previous Screen Sync session can no longer update the current strip or its metrics.
- Concurrent BLE callbacks remain attached to the command that produced them; an immediate result cannot appear before its submission.
- Repeated or displaced frames are counted once and inside the same time window as their originating frame.
- Selected Cyrillic labels no longer clip their last glyph, and capture-area drawings stay inside their rounded icon frames.
- The RGB picker cursor remains inside the colour plane at every edge and corner.

## [0.3.7] - 2026-08-02

Controller compatibility: LumaBLE can now say what it found, what it cannot drive and why — and hand you a file that makes support possible for a controller nobody here owns.

### Added
- **BLE scan report** in Diagnostics: everything nearby devices broadcast, manufacturer data included, and devices filtered out of the visible list — which is exactly where an unrecognised controller ends up.
- **Check** replaces Connect for an unrecognised device: a read-only look at its services and characteristics that writes nothing, guesses no protocol and leaves the strip's state alone.
- **BanlanX SP630E is recognised** from its advertising signature and named as such. Control is not supported yet and no commands are sent to it.
- The device card now states one thing at a time — supported, unrecognised, checking, connected or a problem — with protocol, signal and capabilities.
- A guided welcome tour demonstrates colour control, scenes, screen sync, automations, connection status and Diagnostics without sending commands to a real strip.
- DIY effects now support up to 12 colour steps and eight per-step motions, including flicker, fade in and fade out.

### Changed
- Diagnostics has one clear reporting workflow, compact secondary tools and automatic scanning when a BLE report needs fresh data.
- The DIY editor has a denser library, duration-weighted colour timeline, visible step boundaries and a focused playback area.
- The welcome tour uses smoother simulated controls, stable focus frames and longer reading time while respecting Reduced Motion.

### Fixed
- Every anonymous device in range was offered as a possible LED strip: nameless devices arrive as "Unknown BLE Device", and the "ble" in that placeholder matched the name heuristic.
- Drawing the device card could change the light. The capability probe built a real 50% brightness payload, and drivers that remember the last brightness applied it to the next colour command.
- An unrecognised device was invited to connect, on the theory that a failed connect yields a diagnostic. It no longer is.
- Long DIY motion names no longer clip, and the timeline spacing remains consistent at scaled Windows DPI.

## [0.3.6] - 2026-07-30

Automations: schedules and App Triggers become one rule system that can explain what ran, why a rule was skipped and whether Windows can run it while LumaBLE is closed.

### Added
- A complete Automations section with an overview, master switch, durable pause, rule list, editor and recent history.
- Rules for a time of day, foreground applications, idle time, LumaBLE startup, strip connection and an always-active fallback.
- Scene and power actions, priorities, cooldowns, weekday selection and background execution for supported Pro rules.
- Windows Task Scheduler integration for power rules that must run while LumaBLE is closed, including missed-start handling after sleep and reconciliation of orphaned tasks.
- A durable automation journal with success, skip, cancellation and error reasons that remain readable after rules are renamed or removed.

### Changed
- Existing schedules and App Triggers migrate into rules with a backup and an explicit, rollback-aware handoff from the old scheduled tasks.
- Runtime and headless automation execution share one arbitration state, so the same occurrence is not applied twice when the app and Windows task overlap.
- The rule editor, Automations cards, Pro window, badges, icons and several compact controls now follow the newer spacing and accent system.
- The Local API phone remote has a compact mobile-first layout, a clearer pairing screen, sticky connection status and browser-safe bottom spacing.
- Background execution is clearly marked as Pro and unavailable in Free instead of silently accepting a setting that cannot run.

### Fixed
- Update checks repeat while the app stays open, retry after 30 minutes instead of six hours, and a manual check opens the full update window immediately.
- Partial scene writes no longer confirm a rule or start its cooldown; failed targets remain eligible for retry.
- Manual pause and resume survive restarts and are honoured by both the open app and scheduled background process.
- Overdue time rules choose one winner and settle older losing occurrences instead of switching the light back on the next tick.
- Already running BLE operations keep their ordering during cancellation, and late results cannot confirm an abandoned rule.
- Clicking the discovered-controller status now completes the connection flow instead of stopping at a scan result.
- Automation editor fields, advanced options and action buttons no longer clip or jump on short windows.

## [0.3.5] - 2026-07-26

Trust & Accessibility: update checks now understand beta releases and show what changed, the interface stays usable at Windows display scaling and short window heights, and motion and keyboard behaviour follow the user's needs.

### Added
- A redesigned update window shows the installed and available versions, the release title and notes, with clear actions to open the download page, be reminded later or skip that exact version.
- A Motion setting with three choices: **Match Windows**, **Reduce motion** and **Full motion**. Reduced Motion removes decorative movement while preserving live strip effects and the completion of real background work.
- Keyboard and assistive-technology support for weekday toggles, editable value readouts and scene tiles, including visible focus, automatic scrolling to focused controls and keyboard access to scene menus.

### Changed
- Update selection now handles beta / release-candidate / final ordering, ignores drafts, accepts prereleases in beta builds and treats build metadata correctly.
- Main navigation and content use independent scrolling where needed, keeping the brand and connection status visible in short windows.
- Logs, About, Pro, confirmations and the colour picker now fit the available window height. Their actions stay pinned while only the content that can overflow scrolls.
- Window restoration uses the real available work area and a conservative frame allowance, improving layouts at 125% and 150% Windows scaling.
- Theme and accent refreshes avoid unnecessary application-wide repolishing, making repeated interface updates lighter.
- Update titles and notes are length-limited and rendered as plain text; short notes no longer leave an oversized empty scroll area.

### Fixed
- Skipping an update now suppresses only that exact release in background checks; a newer beta or final release is still announced, and manual checks still report skipped releases.
- Closing the local API now wakes and joins open event-stream handlers instead of leaving a background thread and socket traceback behind.
- Scene-tile arrow navigation stays inside the visual grid, preserves columns on incomplete rows and never applies a scene merely by moving focus.
- Long confirmation messages remain readable and scroll when necessary instead of clipping their actions.
- The light theme no longer gains opaque dark blocks inside newly scrollable dialogs.

## [0.3.4] - 2026-07-21

Smart Atmosphere: screen sync that looks for the colours that matter instead of averaging the whole screen, with Work / Game / Movie response styles, a live source → strip preview, a flash guard, and extra strips that survive a restart.

### Added
- Smarter screen sync: edge-weighted sampling matches the light around the monitor, and dominant-colour detection keeps strong accents instead of blending to grey.
- Work, Game and Movie **response** profiles — how the strip reacts, for any content on the display, not application triggers. Work is smooth and neutral, Game reacts faster with richer colour, Movie softens transitions and ignores black bars.
- Screen → Strip dual preview: the colour detected on screen next to the final colour sent to the strip.
- Flash protection: sudden bright frames ramp into the output instead of strobing, consistently across capture frame rates and after a pause.
- Scenes remember their Screen Sync profile and restore it when applied.
- Additional strips survive a restart and reconnect in the background after the main strip comes online. Unavailable strips remain visible as saved instead of disappearing from groups and scene targets.

### Changed
- Screen Sync card rebuilt as a grouped list: capture status, response-profile selector with a live description, dual preview, and two adjustments — Intensity and Smoothness.
- Letterbox/pillarbox bars are excluded from colour analysis while genuinely dark scenes stay dark.
- Spatial sampling and black-bar detection optimised so dark Full-HD frames no longer cause needless UI load.
- Wording clarifies that Work / Game / Movie are response styles, not application triggers.
- The **Make main** flow now asks whether the previous main strip should stay connected as an extra or disconnect, and reports the result explicitly.
- Diagnostic reports list the main and extra strips with their current connection state.

### Fixed
- Screen Sync no longer flashes black when starting.
- Near-grey screen noise no longer turns into unstable saturated colour.
- Smoothing no longer stalls just before reaching the target colour.
- A large gap between frames no longer causes a sudden colour jump.
- Existing scenes keep loading after the Screen Sync profile format upgrade.

### API and storage
- `GET /status` keeps `pc_mode` and adds `pc_mode_preset` for the active Screen Sync profile.
- Scene storage moves to schema v3, with migration of scenes saved by earlier versions.

## [0.3.3] - 2026-07-20

Two strips, told apart: scenes and groups now target the strips you choose, the connection holds steadier, and the interface got a contrast and hierarchy pass.

### Added
- Scene targets: a scene applies to **all strips**, the **main strip**, or a **group** you define in the new Groups card. The result is reported honestly — which strips were reached, and which settings a controller couldn't do.
- Per-strip BLE addressing: commands go to individual strips, so a scene on one strip no longer disturbs the others. Global status and sliders keep following the main strip.
- **Make main**: every extra strip can swap roles with the main one without reconnecting. Names, saved settings, scene targets and auto-reconnect follow the new main strip.
- Scene tiles replace the saved-scenes dropdown: colour swatch, name and target, keyboard accessible, with the applied scene highlighted until the light is changed by hand.
- Driver capability matrix (BLEDOM / Triones / MagicHome / BanlanX): unsupported settings are skipped and reported instead of silently failing.
- The Pro window now shows what you get: six benefit cards with an icon and a one-line description, one clear "Buy LumaBLE Pro" action, and the licence key field tucked behind an "I already have a key" link. Added a close button, and the Activate button animates while a key is being checked.

### Changed
- Timers and Schedule rebuilt as grouped lists: one setting per row, the value beside its name, clearer on/off state, and Windows autostart as an explicit setting.
- Button hierarchy: one filled primary action per card, tinted secondary actions, quiet utilities, red destructive confirmations.
- Button labels pick their colour by measured contrast (WCAG 4.5:1), covering pastel quick-mode accents.
- Light theme: card shadows, visible language/FPS dropdowns, and grouped lists on their own panel.
- Colour card is about 18% more compact.
- Every dialog and popover (Pro, colour picker, About, logs, pairing, updates) now shares one graphite panel colour instead of ten copies of a blue-grey one.

### Fixed
- Saving a scene and then switching the theme could crash the app.
- Disabled buttons were indistinguishable from enabled ones.
- Diagnostics reported ancient crash dumps as recent; the fatal log now rotates at startup and ages out.
- Steadier reconnection: backoff with jitter, flapping detection, and per-connection write pacing so streaming modes don't flood a controller.
- Scenes were listed as a Pro feature on the purchase screen, but they are Free — the entry was removed and the stale flag deleted from the feature list.
- Closing the Pro window while a licence key was being verified could crash the app; the window now waits for the check to finish.

## [0.3.2] - 2026-07-17

Scenes: save a whole look and bring it back with one click, from the PC, your phone or the API — the first piece of a single lighting model that everything shares.

### Added
- Scenes (Free): a new **Scenes** section. Save the current look — power, colour, brightness and the active built-in effect — under a name, then recall it instantly. Saving under an existing name overwrites it (no duplicates), each scene shows a colour dot, and scenes are one shared model used by the desktop, the phone remote and the Local API.
- Scenes on the phone remote: a Scenes card lists your saved scenes with colour dots; tap to apply, or save the current look on the spot.
- Local API scene endpoints: `GET /scenes`, `POST /scenes/save`, `POST /scenes/apply` and `POST /scenes/delete`, documented in `docs/local-api.md`. `GET /status` now also reports `name`, the active built-in `effect`, and the active `pc_mode`.
- Interface icons were given distinct, meaningful glyphs (Scenes, screen sync, music, software effects, DIY) so cards no longer share a look-alike symbol.

### Fixed
- Scrolling the settings page no longer accidentally changes the value under the cursor (language, FPS, device or effect dropdowns); the page scrolls instead, and a closed dropdown ignores the wheel.

### Notes
- A scene applies to every connected strip in this release. Per-strip and group targeting (and a target selector in the UI) arrive with BLE addressed routing in **0.3.3**.

## [0.3.1] - 2026-07-16

Your phone becomes a remote for the whole light setup on your PC. Open a QR, pair once, and control screen sync, music reaction, DIY effects and quick scenes from any browser — no app to install.

### Added
- Phone remote (Free): scan a QR from the "Open on phone" window, enter a one-time code, and a touch-friendly remote opens in the browser — power, brightness, colour swatches, a full HSV colour picker, recent colours, and quick-mode scenes. Works on iPhone and Android, no install and no account.
- Control the PC's live modes from the phone: Screen sync, Music reaction, software Effect and DIY run as one-tap buttons that show which one is **active**, with a Stop, plus a "Turn everything off" master. This is the real difference from a manufacturer's Bluetooth app — the phone drives the powerful modes running on your PC, not just one strip.
- Live status over Server-Sent Events on the phone (with polling as a fallback), quiet "Sent" / "No connection" feedback, and the active strip's name in the header.
- Paired-phones controls in the API card: see how many phones are connected and disconnect them all with one button.

### Security
- The app token never leaves the PC: the QR carries only the address, and a phone pairs with a short one-time code that becomes a revocable, expiring session. Pairing attempts are rate-limited against code guessing. LAN access stays off by default; turning the API off or regenerating the token drops every paired phone.

## [0.3.0] - 2026-07-14

LumaBLE becomes a local automation node: a small, secure HTTP API lets Home Assistant, AutoHotkey and your own scripts control the strip.

### Added
- Local HTTP API (Free): a token-protected API on `127.0.0.1`, **off by default**. Endpoints for status, device list, power, colour, brightness, effect and quick-mode, plus a live status stream over Server-Sent Events (`GET /events`). Commands are idempotent (`{"on": true}`, never a toggle) so automations are safe to retry. `GET /` returns an endpoint index and `GET /health` a version probe.
- API settings card (Settings → Local API): the everyday view is just Enable + status; the token, port and network access sit under **Advanced** so it doesn't look like a developer panel. Includes a copy-and-regenerate token and a configurable port.
- "How to connect" window: one click copies a ready-to-paste Home Assistant config (token and address already filled in) or a ready curl example; a Stream Deck plugin is noted as coming later.
- Home Assistant integration: ready-to-paste `rest_command` and REST `sensor` YAML (no custom component or cloud), plus a full API reference with curl / PowerShell / AutoHotkey examples. See `docs/local-api.md` and `docs/home-assistant.yaml`.

### Security
- Off by default and loopback-only. "Allow LAN access" is an explicit, off-by-default choice that binds a specific local IP (never all interfaces); the app auto-detects this PC's address so you don't need ipconfig, and clearly reports if it can't. Every request except `/` and `/health` needs the token in an `Authorization: Bearer` header, and requests without a valid token are rejected before reaching the strip.
- The network address is hidden by default (masked, with a reveal toggle) so it can't be leaked on stream; the status simply reads "this PC only" when running locally.

## [0.2.8] - 2026-07-14

A reliability and compatibility release: steadier connections, more controllers that "just work", clearer status when the strip drops, and friendly names for multi-strip setups.

### Added
- Protocol auto-detect (Free): when you connect to an unrecognised controller, LumaBLE inspects what it exposes and, if it looks like a known protocol, offers to try it ("looks like a BLEDOM — try it?"). It only reads the device, never sending anything until you agree, so nothing flashes while it probes.
- Supported-controllers catalog: an in-app list of the controller families LumaBLE speaks (BLEDOM, BanlanX, Magic Home, Triones), reachable from the Device card and the About window.
- Report device (Free): one click copies the diagnostics and opens a prefilled GitHub issue, so adding support for a new controller is easy.
- Strip names (Free): name each controller (Desk, TV, Shelf) instead of reading bare MAC addresses — shown in the device list and the mirror list, with a Rename action on each.

### Changed
- Reconnect is now visible: when the strip goes out of range or is powered off, the status line shows a live countdown to the next attempt with a pulsing orange dot, the Connect button retries immediately, and a clear "strip off or out of range" message appears if it can't be reached.
- One owner at a time: music, screen sync, software effects, DIY and the sleep/sunrise timers now reliably hand the strip off to each other through a single coordinator, so two modes can't fight over it.
- The unsupported-device message now points at the Report and Supported-controllers actions directly.
- The diagnostics action buttons wrap onto two rows so nothing overlaps on narrower windows.

### Fixed
- A dropped BLE connection now stops any running stream instead of writing to a dead link, and nothing silently auto-resumes on reconnect.

## [0.2.7] - 2026-07-13

Wake up and wind down with light: a daily sunrise and a sleep timer, a friendly first-run tour, and global hotkeys are now free for everyone.

### Added
- Sleep & sunrise timers (Free): a **sleep** timer gently fades the current colour to off over N minutes and powers the strip down; a **sunrise** wake light ramps a colour of your choice up to full every day at a set time (starting a few minutes before). Both stream over the colour path, so they work on any controller.
- First-run onboarding: a short welcome carousel introduces the app the first time you open it, with painted icons and a scan shortcut to get connected right away.

### Changed
- Global hotkeys are now **Free** (previously Pro): power, brightness and scene shortcuts are available to everyone.
- Card header icons: the Settings and Hotkeys cards now carry matching line icons for a cleaner, more consistent look.

### Fixed
- The sunrise light is now a true daily alarm with a per-day guard: if it's missed (app closed or disconnected during the window) it no longer gets stuck — it simply runs again the next day.
- Onboarding starts on a window-owned timer and can no longer open twice.

## [0.2.6] - 2026-07-02

React to the room with your microphone, bring DIY effects to life with per-step motion, share them with a code, and enjoy more built-in effects — plus a rounder, more polished editor.

### Added
- Microphone as a music source (Pro): the strip can now react to sound in the room, not just the PC's own audio. Pick "System" or "Microphone" and choose the device. Captured via PortAudio so it opens real input devices reliably.
- Noise gate (Pro): a "Noise gate" slider (microphone only) so faint room noise/hiss doesn't make the strip react — it only lights up on real sound.
- DIY per-step motion (Pro): each colour step can breathe, pulse, twinkle or strobe instead of sitting static — set it per row.
- Share & import DIY effects (Pro): copy an effect to a short shareable code and paste one in to import — send your presets to anyone.
- More built-in effects (Free): Ocean, Sunset, Twinkle, Strobe and Police, alongside the existing set.

### Changed
- Live DIY preview: the preview strip now animates the actual effect with a glowing playhead, so you see the transitions, speed and per-step motion before you even hit Run.
- The DIY transition (Smooth / Cut) is now a single segmented toggle with a sliding highlight, and the Run button is more prominent with a ▶ glyph.
- Right-click menus on text fields (licence key, colour hex, rename, app triggers) are now dark-themed and localised instead of the native light menu, with paste still available.
- The value readouts (percent chips) settle more smoothly when you drag a slider quickly.

## [0.2.5] - 2026-07-01

Build your own colour animations, control the strip from anywhere with global hotkeys, and dial in a warm↔cool white — plus the app's own colour/number dialogs everywhere.

### Added
- DIY effect editor (Pro): build your own looping colour sequence — add colours, drag rows to reorder, set a duration per colour, pick a smooth-fade or hard-cut transition and a speed, with a live preview. It streams to any controller (no firmware effects needed). Save multiple named effects and switch between them from the card.
- Global hotkeys (Pro): control the strip with system-wide keyboard shortcuts even from a fullscreen game — power, brightness up/down, and next/previous scene. Press-to-set and fully rebindable, with a reset-to-defaults button and sensible defaults (Alt+L, Alt+PageUp/PageDown, Alt+N/B).
- Colour temperature (Free): a warm↔cool white slider in the Colour card (2000–6500K) with a gradient track. Emulated via RGB, so it works on any controller.

### Changed
- Colour and number inputs now use the app's own graphite dialogs instead of the native Windows ones: picking a DIY step colour opens the LumaBLE colour picker, and editing a value chip (RGB / brightness / temperature / speed) or a DIY duration opens the styled input.
- Auto-update check now runs up to every 6 hours instead of once a day, so a new release is noticed sooner.

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
