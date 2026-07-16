@echo off
set "ROOT=%~dp0"
cd /d "%ROOT%"

if not exist "%ROOT%.venv\Scripts\pythonw.exe" goto setup
"%ROOT%.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto setup
"%ROOT%.venv\Scripts\python.exe" -c "mods=['mss','numpy','segno','soundcard','sounddevice','winrt._winrt','winrt._winrt_windows_devices_bluetooth','winrt._winrt_windows_devices_bluetooth_advertisement','winrt._winrt_windows_devices_bluetooth_genericattributeprofile','winrt._winrt_windows_devices_enumeration','winrt._winrt_windows_devices_radios','winrt._winrt_windows_foundation','winrt._winrt_windows_foundation_collections','winrt._winrt_windows_storage_streams']; [__import__(m) for m in mods]" >nul 2>&1
if errorlevel 1 goto setup
goto run

:setup
where py >nul 2>&1
if not errorlevel 1 (
    py -3.11 -m venv "%ROOT%.venv" 2>nul || py -m venv "%ROOT%.venv"
) else (
    python -m venv "%ROOT%.venv"
)
if errorlevel 1 (
    echo Could not create virtual environment. Install Python 3.11+ and try again.
    pause
    exit /b 1
)
"%ROOT%.venv\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 (
    echo Could not install dependencies.
    pause
    exit /b 1
)
"%ROOT%.venv\Scripts\python.exe" -m pip install --force-reinstall winrt-runtime==3.2.1 winrt-Windows.Devices.Bluetooth==3.2.1 winrt-Windows.Devices.Bluetooth.Advertisement==3.2.1 winrt-Windows.Devices.Bluetooth.GenericAttributeProfile==3.2.1 winrt-Windows.Devices.Enumeration==3.2.1 winrt-Windows.Devices.Radios==3.2.1 winrt-Windows.Foundation==3.2.1 winrt-Windows.Foundation.Collections==3.2.1 winrt-Windows.Storage.Streams==3.2.1
if errorlevel 1 (
    echo Could not repair WinRT Bluetooth dependencies.
    pause
    exit /b 1
)

:run
start "" "%ROOT%.venv\Scripts\pythonw.exe" "%ROOT%main.py"
