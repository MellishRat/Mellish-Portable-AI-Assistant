@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "LAUNCHER_DIR=%~dp0"
set "MELLISH_ASSISTANT_ROOT="
for %%I in ("%LAUNCHER_DIR%..\..") do set "CANDIDATE_ROOT=%%~fI"
call :try_root "%CANDIDATE_ROOT%"
if not defined MELLISH_ASSISTANT_ROOT (
  for %%I in ("%LAUNCHER_DIR%..") do set "CANDIDATE_ROOT=%%~fI"
  call :try_root "!CANDIDATE_ROOT!"
)
if not defined MELLISH_ASSISTANT_ROOT call :try_root "W:\Qwen3.5-9B-abliterated"
if not defined MELLISH_ASSISTANT_ROOT call :try_root "%LOCALAPPDATA%\Mellish Portable AI Assistant"
if not defined MELLISH_ASSISTANT_ROOT (
  echo Enter the Mellish installation folder, for example C:\_LLM
  set /p "CANDIDATE_ROOT=Installation folder: "
  for %%I in ("!CANDIDATE_ROOT!") do set "CANDIDATE_ROOT=%%~fI"
  call :try_root "!CANDIDATE_ROOT!"
)
if not defined MELLISH_ASSISTANT_ROOT (
  echo Contained Python could not be found.
  pause
  exit /b 1
)
set "APP_DIR=%MELLISH_ASSISTANT_ROOT%\apps\dyslexic-aid"
if not exist "%APP_DIR%\run_app.py" set "APP_DIR=%LAUNCHER_DIR:~0,-1%"
set "PYTHONNOUSERSITE=1"
set "PIP_USER=false"
set "PYTHON=%MELLISH_ASSISTANT_ROOT%\runtime\python\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%MELLISH_ASSISTANT_ROOT%\runtime\python\python.exe"
if not exist "%PYTHON%" (
  echo Contained Python was not found: %PYTHON%
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
start "Mellish Dyslexic Aid" /b "%PYTHON%" "%APP_DIR%\run_app.py"
exit /b 0

:try_root
if defined MELLISH_ASSISTANT_ROOT exit /b 0
if exist "%~1\runtime\python\python.exe" set "MELLISH_ASSISTANT_ROOT=%~1"
exit /b 0

