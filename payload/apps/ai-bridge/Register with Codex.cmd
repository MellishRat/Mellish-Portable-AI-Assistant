@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "MELLISH_ROOT=%%~fI"
where codex >nul 2>nul
if errorlevel 1 (
  echo Codex CLI was not found. Open README.md for the manual command.
  pause
  exit /b 1
)
codex mcp get mellish-ai >nul 2>nul
if not errorlevel 1 codex mcp remove mellish-ai
codex mcp add mellish-ai --env "MELLISH_ASSISTANT_ROOT=%MELLISH_ROOT%" -- "%MELLISH_ROOT%\runtime\python\python.exe" "%MELLISH_ROOT%\apps\ai-bridge\run_mcp.py"
if errorlevel 1 (
  echo Registration failed.
  pause
  exit /b 1
)
echo Mellish AI Bridge was registered with Codex.
if exist "%MELLISH_ROOT%\apps\narration-studio\run_mcp.py" (
  codex mcp get mellish-narration >nul 2>nul
  if not errorlevel 1 codex mcp remove mellish-narration
  codex mcp add mellish-narration --env "MELLISH_ASSISTANT_ROOT=%MELLISH_ROOT%" -- "%MELLISH_ROOT%\runtime\python\python.exe" "%MELLISH_ROOT%\apps\narration-studio\run_mcp.py"
  if errorlevel 1 (
    echo Narration Studio MCP registration failed.
    pause
    exit /b 1
  )
  echo Narration Studio's 11 project tools were also registered.
)
echo Start a new Codex task/session to load its tools.
pause
