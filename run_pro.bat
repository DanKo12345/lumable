@echo off
set "ROOT=%~dp0"
cd /d "%ROOT%"

set "LUMABLE_FORCE_PRO=1"
call "%ROOT%run_app.bat"
