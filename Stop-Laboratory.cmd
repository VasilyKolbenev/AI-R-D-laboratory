@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo No project environment. Run Setup-Laboratory.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -E -s -B -m laboratory --stop %*
set "LAB_EXIT=%ERRORLEVEL%"
if not "%LAB_EXIT%"=="0" pause
exit /b %LAB_EXIT%
