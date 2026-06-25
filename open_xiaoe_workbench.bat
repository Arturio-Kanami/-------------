@echo off
setlocal

cd /d "%~dp0"
set "URL=http://127.0.0.1:8765/"

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%URL%api/state' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 (
  start "" "%URL%"
  exit /b 0
)

call "%~dp0start_web_ui.bat"
