# LumaBLE

Windows-приложение для управления BLE RGB-контроллерами светодиодных лент.

LumaBLE ищет поддерживаемые Bluetooth-контроллеры, подключается к устройству, меняет RGB-цвет,
яркость и питание, применяет встроенные эффекты, настраивает скорость эффектов и сохраняет
пользовательские профили подсветки.

Автор: `dollza`

Версия: `0.1.1 beta`

Другие языки:

- [English](README.md)
- [中文](README.zh.md)

## Поддерживаемые Контроллеры

- BLEDOM / ELK-BLEDOM совместимые контроллеры.
- Magic Home / MagicLight BLE контроллеры.
- BanlanX SP61x / SP62x BLE контроллеры.
- Triones / Happy Lighting совместимые BLE LED-контроллеры.

## Установка На Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Инструменты для тестов и релизной сборки:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Запуск

```powershell
.\run_app.bat
```

Запуск в Free-режиме:

```powershell
.\run_free.bat
```

## Тесты

```powershell
.\.venv311\Scripts\python.exe -m pytest
```

```powershell
.\.venv311\Scripts\python.exe -m ruff check .
```

## Данные Приложения

Данные приложения хранятся в стандартной пользовательской папке через `platformdirs`.
На Windows это обычно:

```text
%APPDATA%\LumaBLE
```

Пользовательские переводы можно положить JSON-файлами в:

```text
%APPDATA%\LumaBLE\i18n
```

Папка `data/` в проекте используется только как legacy-источник для первой миграции старых
профилей и настроек. Её не нужно коммитить или добавлять в публичные архивы.
