@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ================================================
echo   LumaBLE - checks
echo ================================================

rem Prefer the .venv311 you use for tests, fall back to .venv.
set "VENV=.venv311"
if not exist "%VENV%\Scripts\activate.bat" set "VENV=.venv"
if not exist "%VENV%\Scripts\activate.bat" (
  echo [ERROR] No virtual environment found ^(.venv311 or .venv^).
  echo Create one and install requirements first.
  echo.
  pause
  exit /b 1
)

echo Using %VENV%
call "%VENV%\Scripts\activate.bat"

echo.
echo [1/2] Ruff ^(lint^): ruff check app tests
echo ------------------------------------------------
python -m ruff check app tests
set RUFF_RC=!errorlevel!

echo.
echo [2/2] Pytest ^(tests^)
echo ------------------------------------------------
python -m pytest
set PYTEST_RC=!errorlevel!

echo.
echo ================================================
if !RUFF_RC!==0 (echo   Ruff:   PASSED) else (echo   Ruff:   FAILED)
if !PYTEST_RC!==0 (echo   Pytest: PASSED) else (echo   Pytest: FAILED)
echo ================================================
echo.
pause
