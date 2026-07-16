# LumaBLE

Windows-first desktop app for controlling BLE RGB LED strip controllers.

LumaBLE scans nearby supported Bluetooth LED controllers, connects to a device, changes RGB color,
brightness and power, applies built-in effects, tunes effect speed, and saves reusable lighting
profiles. It also includes screen sync, tray controls, schedules, diagnostics, themes, and a Pro
license flow for advanced features.

Author: `dollza`

Version: `0.3.1 beta`

Download the latest Windows build from the [Releases page](https://github.com/DanKo12345/lumable/releases).

If you find a bug or your controller does not work, please open an
[Issue](https://github.com/DanKo12345/lumable/issues).

Translations:

- [Русский](README.ru.md)
- [Español](README.es.md)
- [中文](README.zh.md)

## Highlights

- RGB sliders, HEX/HSV color picker, brightness and power control.
- Built-in BLE effects with speed support where the controller protocol allows it.
- Reusable lighting profiles and quick modes.
- Screen sync / Ambient mode for matching the strip to the average screen color.
- Local schedules while the app is open or running in the tray.
- Single-instance startup protection, so a second launch brings the existing window forward instead
  of fighting over the Bluetooth connection.
- Diagnostics export for unsupported controllers and BLE troubleshooting.
- Interface languages: English, Russian, Spanish and Chinese, with first-run language detection.

## Supported Controllers

- BLEDOM / ELK-BLEDOM compatible controllers.
- Magic Home / MagicLight BLE controllers.
- BanlanX SP61x / SP62x BLE controllers.
- Triones / Happy Lighting compatible BLE LED controllers.

## Windows Install

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Developer tools for tests and release builds:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Run

```powershell
.\run_app.bat
```

## Tests

```powershell
.\.venv311\Scripts\python.exe -m pytest
```

```powershell
.\.venv311\Scripts\python.exe -m ruff check .
```

## App Data

Application data is stored in the standard per-user app data folder through `platformdirs`.
On Windows this is usually:

```text
%APPDATA%\LumaBLE
```

Custom translations can be added as JSON files in:

```text
%APPDATA%\LumaBLE\i18n
```

The local `data/` folder is only a legacy migration source for old development profiles/settings.
It should not be committed or included in public archives.

## Reporting Issues

When reporting a bug or unsupported controller, please include:

- Windows version.
- LumaBLE version.
- Controller name shown in the app.
- What you tried to do.
- What happened instead.
- Diagnostics report, if possible.

To export diagnostics:

1. Open LumaBLE.
2. Open Device diagnostics.
3. Click Copy diagnostics or Export diagnostics.
4. Paste the report into the GitHub issue, or attach the exported `.txt` file.
