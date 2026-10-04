@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "LAUNCHER_DIR=%~dp0"
set "MELLISH_ASSISTANT_ROOT="
set "APP_DIR="

rem Installed layout: <root>\apps\narration-studio\this launcher
for %%I in ("%LAUNCHER_DIR%..\..") do set "CANDIDATE_ROOT=%%~fI"
call :try_root "%CANDIDATE_ROOT%"

rem Extracted-package layout: <root>\Mellish-Narration-Studio-vX.Y.Z\this launcher
if not defined MELLISH_ASSISTANT_ROOT (
  for %%I in ("%LAUNCHER_DIR%..") do set "CANDIDATE_ROOT=%%~fI"
  call :try_root "!CANDIDATE_ROOT!"
)

rem Backwards-compatible locations used by early releases.
if not defined MELLISH_ASSISTANT_ROOT call :try_root "W:\Qwen3.5-9B-abliterated"
if not defined MELLISH_ASSISTANT_ROOT call :try_root "%LOCALAPPDATA%\Mellish Portable AI Assistant"

if not defined MELLISH_ASSISTANT_ROOT (
  echo Mellish Assistant's contained Python installation could not be located.
  echo Enter the assistant installation folder, for example C:\_LLM
  set /p "CANDIDATE_ROOT=Installation folder: "
  for %%I in ("!CANDIDATE_ROOT!") do set "CANDIDATE_ROOT=%%~fI"
  call :try_root "!CANDIDATE_ROOT!"
)

if not defined MELLISH_ASSISTANT_ROOT (
  echo.
  echo The selected folder does not contain runtime\python\python.exe.
  echo Run Repair or Add Models.bat from the assistant installation folder first.
  pause
  exit /b 1
)

if not defined APP_DIR set "APP_DIR=%LAUNCHER_DIR%"
set "PYTHONNOUSERSITE=1"
set "PIP_USER=false"
set "PYTHON=%MELLISH_ASSISTANT_ROOT%\runtime\python\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%MELLISH_ASSISTANT_ROOT%\runtime\python\python.exe"
if not exist "%PYTHON%" (
  echo Contained Python was not found: %PYTHON%
  pause
  exit /b 1
)
if not exist "%APP_DIR%run_app.py" (
  echo Narration Studio was not found: %APP_DIR%run_app.py
  pause
  exit /b 1
)
if /I "%~1"=="--diagnose" (
  echo ROOT=%MELLISH_ASSISTANT_ROOT%
  echo APP_DIR=%APP_DIR%
  echo PYTHON=%PYTHON%
  exit /b 0
)
cd /d "%APP_DIR%"
start "Mellish Narration Studio" /b "%PYTHON%" "%APP_DIR%run_app.py"
exit /b 0

:try_root
if defined MELLISH_ASSISTANT_ROOT exit /b 0
if not exist "%~1\runtime\python\python.exe" exit /b 0
set "MELLISH_ASSISTANT_ROOT=%~1"
if exist "%~1\apps\narration-studio\run_app.py" (
  set "APP_DIR=%~1\apps\narration-studio\"
) else if exist "%LAUNCHER_DIR%run_app.py" (
  set "APP_DIR=%LAUNCHER_DIR%"
)
exit /b 0
