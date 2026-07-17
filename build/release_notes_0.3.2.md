# LumaBLE 0.3.2 (beta)

Scenes: save a whole look and bring it back with one click — from the PC, your phone or the API. It's the first piece of a single lighting model that every surface shares.

## Added
- **Scenes (Free).** A new **Scenes** section: save the current look — power, colour, brightness and the active built-in effect — under a name, then recall it instantly. Re-saving under the same name overwrites it (no duplicate clutter), every scene shows a colour dot, and the same scenes are used by the desktop, the phone remote and the Local API.
- **Scenes on the phone remote.** A Scenes card lists your saved scenes with colour dots; tap to apply, or save the current look on the spot.
- **Local API scene endpoints.** `GET /scenes`, `POST /scenes/save`, `POST /scenes/apply`, `POST /scenes/delete` (see `docs/local-api.md`). `GET /status` now also reports `name`, the active built-in `effect` and the active `pc_mode`.
- **Clearer card icons.** Scenes, screen sync, music, software effects and the DIY editor each got a distinct, meaningful glyph instead of sharing a look-alike symbol.

## Fixed
- Scrolling the settings page no longer accidentally changes the value under the cursor — a closed dropdown (language, FPS, device, effect) ignores the wheel and the page scrolls instead.

## Notes
- In this release a scene applies to **every connected strip**. Per-strip and group targeting — with a target selector in the UI — arrives together with BLE addressed routing in **0.3.3**.

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX).
