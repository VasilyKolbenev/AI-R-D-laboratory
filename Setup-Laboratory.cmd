@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if "%~1"=="--python" goto explicit
if not "%~1"=="" goto usage
for %%V in (3.13 3.12 3.11) do (
  py -%%V -I -B "tools\setup_local.py" --probe >nul 2>&1
  if not errorlevel 1 (
    py -%%V -I -B "tools\setup_local.py"
    goto finish
  )
)
echo Install CPython 3.11-3.13 x64 from https://www.python.org/downloads/windows/
echo Include the Python launcher, or use Setup-Laboratory.cmd --python "C:\path\python.exe"
pause
exit /b 1
:explicit
if "%~2"=="" goto usage
if not "%~3"=="" goto usage
if not exist "%~2" (
  echo The specified Python executable does not exist.
  pause
  exit /b 1
)
"%~2" -I -B "tools\setup_local.py"
goto finish
:usage
echo Usage: Setup-Laboratory.cmd [--python "C:\path\python.exe"]
pause
exit /b 1
:finish
set "LAB_EXIT=%ERRORLEVEL%"
if "%LAB_EXIT%"=="0" echo Setup finished. Open-Laboratory.cmd starts the laboratory.
if not "%LAB_EXIT%"=="0" echo Setup failed. No research or publication was started.
pause
exit /b %LAB_EXIT%
