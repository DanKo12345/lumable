# LumaBLE 0.3.4 (beta) — Smart Atmosphere

Screen sync that looks for the colours that matter instead of averaging the whole screen into a muddy tone — with three response styles, a live preview, a flash guard, and extra strips that now survive a restart.

## Added
- **Smarter screen sync.** LumaBLE now weights the edges of the display (where the light around a monitor actually comes from) and keeps strong accent colours instead of blending everything into grey.
- **Work, Game and Movie profiles.** Choose how the strip *reacts* without changing what's captured: Work stays smooth and neutral, Game reacts faster with richer colour, Movie softens transitions and ignores black bars. These are response styles for any content on the display — not application triggers.
- **Screen → Strip preview.** A live dual preview shows the colour detected on screen next to the final colour sent to the strip, so intensity, smoothness and profile changes are immediately clear.
- **Flash protection.** Sudden bright frames ramp into the output instead of strobing the room, consistently across capture frame rates and after a capture pause.
- **Screen profiles in scenes.** A scene that starts Screen Sync remembers its exact Work, Game or Movie profile and restores it when applied.
- **Remembered extra strips.** Additional strips now survive a restart and reconnect in the background after the main strip comes online. An unavailable strip stays visible as saved instead of silently disappearing from groups and scene targets.

## Changed
- **Screen Sync redesigned.** The card follows the same grouped-list design as the rest of LumaBLE: a clear capture status, a response-profile selector with a live description, the dual preview, and two focused adjustments — Intensity and Smoothness.
- **Better dark scenes.** Letterbox and pillarbox bars are excluded from colour analysis, while genuinely dark scenes are allowed to stay dark.
- **Faster Full-HD analysis.** Spatial sampling and black-bar detection were optimised so dark frames no longer cause needless UI load.
- **Clearer wording.** The interface explains that Work, Game and Movie are response styles, not application triggers.
- **Clearer Make main flow.** When using **Make main**, choose whether the previous main strip should stay connected as an extra or disconnect. The result is stated explicitly.
- **Multi-strip diagnostics.** Diagnostic reports now list the main and extra strips with their connection state.

## Fixed
- Screen Sync no longer flashes black when starting.
- Near-grey screen noise no longer turns into unstable saturated colour.
- Smoothing no longer stalls just before reaching the target colour.
- A large gap between frames no longer causes a sudden colour jump.
- Existing scenes keep loading after the Screen Sync profile format upgrade.

## API and storage
- `GET /status` keeps `pc_mode` and adds `pc_mode_preset` for the active Screen Sync profile.
- Scene storage moves to schema v3, with automatic migration of scenes saved by earlier versions.

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX).
