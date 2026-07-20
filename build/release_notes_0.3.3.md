# LumaBLE 0.3.3 (beta)

Two strips, told apart. Scenes and groups now speak to the strips you choose instead of shouting at all of them, the connection holds steadier, and the whole interface got a pass for contrast and hierarchy.

## Added
- **Scene targets.** A scene can now apply to **all strips**, the **main strip**, or a **group** you define. Groups are built from the connected strips in a new Groups card, and the result is reported honestly: LumaBLE tells you which strips it reached and which settings a controller couldn't do.
- **Per-strip control over BLE.** Commands are addressed to individual strips, so changing a scene on the TV strip no longer disturbs the desk one. The global status and sliders keep reflecting the main strip.
- **Make a strip the main one.** Every extra strip has a **Make main** button: confirm, and it swaps roles with the current main strip — no reconnection, no re-pairing. Names, saved settings, scene targets and auto-reconnect all follow the new main strip.
- **Scene tiles.** Saved scenes moved from a dropdown to a grid of tiles with a colour swatch, name and target. Click or press Enter to apply; the applied scene stays highlighted until you change the light by hand.
- **Capability awareness.** LumaBLE knows what each controller family (BLEDOM / Triones / MagicHome / BanlanX) actually supports and skips what a strip can't do rather than pretending it worked.
- **A Pro window that explains itself.** Six benefit cards with an icon and a one-line description replace the checklist, there's one clear action instead of three competing buttons, and the licence key field stays out of the way behind "I already have a key" until you need it.

## Changed
- **Timers and Schedule redesigned.** Both cards became grouped lists: an icon per setting, the value beside its name, a clearer on/off state, and Windows autostart is now an obvious setting instead of a stray button.
- **Button hierarchy.** Each card has one filled primary action; secondary actions are tinted and utilities stay quiet. Destructive confirmations are red.
- **Readable labels everywhere.** Button text colour is now chosen by measuring real contrast, so pastel quick-mode accents no longer produce washed-out labels. Locked in by tests.
- **Light theme.** Cards gained a soft shadow, the language and FPS dropdowns are no longer white-on-white, and grouped lists have their own panel so they read as a group.
- **Denser Color card.** Sliders and value chips got slimmer — about 18% less vertical space.
- **Graphite everywhere.** Dialogs and popovers were drifting blue-grey while the app's cards were graphite; they now all take one shared panel colour.

## Fixed
- Saving a scene and then switching the theme could crash the app.
- Disabled buttons looked exactly like enabled ones.
- Diagnostics reported ancient crash dumps as "recent crashes"; the fatal log is now rotated at startup and aged out.
- Reconnection is steadier: retry delays back off with jitter, connection flapping is detected, and writes are paced per connection so streaming modes don't flood a controller.
- Scenes were advertised as a Pro feature on the purchase screen. They are Free — the claim is gone.
- Closing the Pro window in the middle of a licence check could crash the app.

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX).
