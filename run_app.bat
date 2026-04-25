@echo off
set "ROOT=%~dp0"
cd /d "%ROOT%"
start "" "%ROOT%.venv\Scripts\pythonw.exe" "%ROOT%main.py"
