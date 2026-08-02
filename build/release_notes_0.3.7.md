# LumaBLE 0.3.7 (beta)

This release makes first contact with an unfamiliar controller safer and more useful, adds a guided welcome tour, and refreshes two of the app's densest tools.

## Added
- **BLE scan reports.** Diagnostics can save advertisement data, manufacturer data and service UUIDs for every device seen during a scan, including devices hidden from the visible controller list.
- **Read-only compatibility checks.** Unknown devices now offer **Check** instead of Connect. LumaBLE reads services and characteristics, sends no commands and disconnects when the inspection finishes.
- **Honest SP630E recognition.** BanlanX SP630E advertisements are identified by their known signature, while the UI remains explicit that control is not supported yet.
- **A guided welcome tour.** New users see colour control, scenes, screen sync, automations, connection status and Diagnostics through a safe visual demonstration that never controls the real strip.
- **More expressive DIY effects.** Custom effects now allow up to 12 colours and eight motions per step: steady, breathe, pulse, twinkle, flicker, fade in, fade out and strobe.

## Refreshed
- **Diagnostics** now presents one clear reporting action and a compact list of secondary tools.
- **DIY effects** now use a duration-weighted timeline with visible step boundaries, a cleaner library and a focused playback section.
- Welcome-tour focus frames and simulated controls animate smoothly, stay aligned after resizing and respect Reduced Motion.

## Fixed
- Anonymous BLE devices are no longer mistaken for possible LED controllers because of the words "Unknown BLE Device".
- Reading controller capabilities no longer builds a real brightness command or changes the next colour sent to the strip.
- Unknown devices are no longer encouraged down the normal connection path.
- Long DIY motion names, timeline rows and compact actions remain aligned at Windows display scaling.

## Before and after

![Animated before and after comparison of Diagnostics and DIY effects](https://raw.githubusercontent.com/DanKo12345/lumable/v0.3.7-beta/docs/images/release-0.3.7-before-after.gif)

---

Full changelog: [CHANGELOG.md](https://github.com/DanKo12345/lumable/blob/main/CHANGELOG.md) · API docs: [docs/local-api.md](https://github.com/DanKo12345/lumable/blob/main/docs/local-api.md)

Requires Windows 10/11 and a supported BLE RGB controller (BLEDOM / Triones / MagicHome / BanlanX). The installer is currently unsigned, so Windows SmartScreen may show an unknown-publisher warning.
