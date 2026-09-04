@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ================================================
echo   LumaBLE - checks
echo ================================================

rem A copied venv can still contain python.exe while pointing at an interpreter
rem on the old computer. Select the first environment that can actually start.
set "PYTHON="
for %%V in (.venv311 .venv) do (
  if not defined PYTHON if exist "%%V\Scripts\python.exe" (
    "%%V\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if !errorlevel!==0 set "PYTHON=%%V\Scripts\python.exe"
  )
)
if not defined PYTHON (
  echo [ERROR] No virtual environment found ^(.venv311 or .venv^).
  echo Create one and install requirements first.
  echo.
  pause
  exit /b 1
)

set "WORKERS=2"
if defined LUMABLE_TEST_WORKERS set "WORKERS=%LUMABLE_TEST_WORKERS%"
echo Using %PYTHON%
echo Pytest workers: %WORKERS%

echo.
echo [1/2] Ruff ^(lint^): whole repository
echo ------------------------------------------------
"%PYTHON%" -m ruff check .
set RUFF_RC=!errorlevel!

echo.
echo [2/2] Pytest ^(tests^)
echo ------------------------------------------------
"%PYTHON%" -m pytest -n %WORKERS% --dist loadfile --max-worker-restart=0
set PYTEST_RC=!errorlevel!

echo.
echo ================================================
if !RUFF_RC!==0 (echo   Ruff:   PASSED) else (echo   Ruff:   FAILED)
if !PYTEST_RC!==0 (echo   Pytest: PASSED) else (echo   Pytest: FAILED)
echo ================================================
echo.
set "EXIT_RC=0"
if not !RUFF_RC!==0 set "EXIT_RC=1"
if not !PYTEST_RC!==0 set "EXIT_RC=1"
pause
exit /b !EXIT_RC!
