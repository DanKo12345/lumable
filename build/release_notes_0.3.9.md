# LumaBLE 0.3.9 (beta)

This release brings the controls you use most into Windows itself, adds safe portable backups, and makes Music Sync adapt to the room and recording source automatically.

## Closer to Windows
- **Useful tray controls.** See connection status, apply recent scenes and toggle Screen Sync or Music Sync without opening the main window.
- **Optional global hotkeys.** Screen Sync and Music Sync can be assigned shortcuts, but LumaBLE never claims new system-wide combinations during an update. Invalid and conflicting bindings are shown beside the affected field.
- **Windows-aware automations.** Rules can react when the PC locks, unlocks, sleeps or wakes. Wake actions wait briefly for Bluetooth to return instead of failing immediately.

## Portable backup
- Export scenes, rules, groups and portable settings into one versioned file.
- Restore only after the complete file passes validation; the current configuration is copied first and replacement is atomic.
- Licence data, API secrets, BLE addresses, controller names, diagnostics and temporary UI state are never included.
- Group identities remain linked to scenes, while physical strips must be assigned again on the new machine.

## Smarter Music Sync
- The silence threshold now learns each source and uses hysteresis, so microphone or sound-card noise does not make the strip flicker at rest.
- Beat detection follows changes in the share of bass rather than raw loudness, reducing false beats when the whole track simply gets louder.
- Beat cooldown uses real elapsed time, and the old pulse fades naturally when audio becomes quiet.
- The existing Beat slider still controls flash depth; sensitivity adapts automatically without adding another setting.
- Diagnostics report numerical Music Sync health without storing or exporting audio.

## Fixed and polished
- Clearing a hotkey now actually disables it, and a typing mistake cannot replace working shortcuts.
- Windows lock and unlock events now reach the automation engine through the real Qt event path and display the correct icons.
- Music analysis resets cleanly on source changes, restarts and capture failures.
- Backup and automation wording was simplified across English, Russian, Spanish and Chinese.

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX). The installer is currently unsigned, so Windows SmartScreen may show an unknown-publisher warning.
