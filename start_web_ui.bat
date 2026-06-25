@echo off
setlocal

cd /d "%~dp0"

python -c "import playwright" >nul 2>nul
if errorlevel 1 (
  echo Installing required Python package: playwright
  python -m pip install --user -r requirements.txt
  if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
  )
)

python -c "import faster_whisper" >nul 2>nul
if errorlevel 1 (
  echo Installing required Python package: faster-whisper
  python -m pip install --user -r requirements-transcribe.txt
  if errorlevel 1 (
    echo Failed to install transcription requirements.
    pause
    exit /b 1
  )
)

python "%~dp0web_ui\server.py"

echo.
echo Web UI stopped. Press any key to close this window.
pause >nul
