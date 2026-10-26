@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup-Laboratory.cmd first. Python 3.11-3.13 x64 is required.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -I -B "tools\setup_local.py" --check
if errorlevel 1 (
  echo Setup is incomplete. Run Setup-Laboratory.cmd again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -E -s -B -m laboratory --supervised %*
set "LAB_EXIT=%ERRORLEVEL%"
if not "%LAB_EXIT%"=="0" pause
exit /b %LAB_EXIT%
