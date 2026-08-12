# LumaBLE 0.3.9 (beta)

Windows controls & Music: use your lights without keeping the main window open, move your setup safely to another installation, and get steadier music reactions in quiet rooms and at different volume levels.

## Added
- **More useful tray controls.** Check the connection, apply a recent scene, or start and stop Screen Sync and Music Sync without opening LumaBLE.
- **New hotkey actions.** Screen Sync and Music Sync can now have global shortcuts. They are optional and stay unassigned until you choose them.
- **Windows automation triggers.** Rules can run when the PC locks, unlocks, goes to sleep or wakes up.
- **Full backup and restore.** Move scenes, rules, groups and portable settings in one file. LumaBLE keeps a copy of the current setup before restoring it.

## Improved
- **Music Sync adapts to the room.** Background noise from a microphone or sound card is less likely to make the strip flicker in silence.
- **Better beat detection.** Reactions follow the rhythm instead of treating every increase in volume as a new beat.
- **Natural fade after a beat.** The last pulse now settles smoothly when the music stops.
- **Recent scenes stay useful.** The tray remembers scenes you applied successfully instead of filling the list with automatic rules.
- Backup and automation messages were simplified across English, Russian, Spanish and Chinese.

## Fixed
- Clearing a hotkey now leaves it disabled instead of silently bringing the old shortcut back.
- Invalid or conflicting shortcuts are shown beside the affected action and do not replace working ones.
- Lock and unlock rules now receive the real Windows events and show the correct icons.
- Wake rules wait briefly for Bluetooth to return instead of failing as soon as the PC resumes.
- Music Sync starts fresh after changing the audio source, restarting a session or losing the recording device.
- Restored settings can no longer be overwritten by the old session while LumaBLE is closing.

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX). The installer is currently unsigned, so Windows SmartScreen may show an unknown-publisher warning.
