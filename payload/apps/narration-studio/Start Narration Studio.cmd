@echo off
setlocal
set "APP_DIR=%~dp0"
for %%I in ("%APP_DIR%..\..") do set "MELLISH_ASSISTANT_ROOT=%%~fI"
set "PYTHONNOUSERSITE=1"
set "PIP_USER=false"
set "PYTHON=%MELLISH_ASSISTANT_ROOT%\runtime\python\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%MELLISH_ASSISTANT_ROOT%\runtime\python\python.exe"
if not exist "%PYTHON%" (
  echo Contained Python was not found: %PYTHON%
  pause
  exit /b 1
)
cd /d "%APP_DIR%"
start "Mellish Narration Studio" /b "%PYTHON%" "%APP_DIR%run_app.py"
