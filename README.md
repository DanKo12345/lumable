# LumaBLE

Windows-first desktop app for controlling BLE RGB LED strip controllers.

LumaBLE scans nearby supported Bluetooth LED controllers, connects to a device, changes RGB color,
brightness and power, applies built-in effects, tunes effect speed, and saves reusable lighting
profiles.

Author: `dollza`

Version: `0.1.1 beta`

Download the latest Windows build from the [Releases page](https://github.com/DanKo12345/lumable/releases).

Translations:

- [Русский](README.ru.md)
- [中文](README.zh.md)

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

Free-mode run:

```powershell
.\run_free.bat
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
