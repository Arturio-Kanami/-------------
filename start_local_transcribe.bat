@echo off
setlocal

cd /d "%~dp0"

if "%HF_ENDPOINT%"=="" set "HF_ENDPOINT=https://hf-mirror.com"

python -c "import faster_whisper" >nul 2>nul
if errorlevel 1 (
  echo Installing required Python package: faster-whisper
  echo This may take a few minutes the first time.
  python -m pip install --user -r requirements-transcribe.txt
  if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
  )
)

echo.
echo Paste a video file path or a folder path.
echo Leave blank to transcribe the default downloads folder.
set /p "MEDIA_PATH=> "
if "%MEDIA_PATH%"=="" set "MEDIA_PATH=%~dp0downloads"

echo.
echo Choose model: small / medium / large-v3
echo Recommended for RTX 4060: medium
set /p "MODEL_NAME=Model [medium]> "
if "%MODEL_NAME%"=="" set "MODEL_NAME=medium"

echo.
echo Language code. Chinese courses: zh
set /p "LANGUAGE_CODE=Language [zh]> "
if "%LANGUAGE_CODE%"=="" set "LANGUAGE_CODE=zh"

echo.
echo Checking local model files...
set "LOCAL_MODEL=%~dp0models\faster-whisper-%MODEL_NAME%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_faster_whisper_model.ps1" -Model "%MODEL_NAME%"

if not exist "%LOCAL_MODEL%\model.bin" (
  echo Model download failed or model.bin is missing.
  pause
  exit /b 1
)

python "%~dp0transcribe_local.py" "%MEDIA_PATH%" --model "%LOCAL_MODEL%" --language "%LANGUAGE_CODE%" --output "%~dp0transcripts"

echo.
echo Finished. Press any key to close this window.
pause >nul
