@echo off
setlocal

cd /d "%~dp0"

set "EDGE_EXE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE_EXE%" set "EDGE_EXE=C:\Program Files\Microsoft\Edge\Application\msedge.exe"

if not exist "%EDGE_EXE%" (
  echo Could not find Microsoft Edge.
  echo Please edit this file and set EDGE_EXE to your msedge.exe path.
  pause
  exit /b 1
)

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

echo.
echo Paste your Xiaoe course/lesson URL, then press Enter.
echo Leave blank to open the login page and navigate manually.
set /p "XIAOE_URL=> "

if "%XIAOE_URL%"=="" (
  python "%~dp0xiaoe_capture_download.py" --browser "%EDGE_EXE%"
) else (
  python "%~dp0xiaoe_capture_download.py" --browser "%EDGE_EXE%" "%XIAOE_URL%"
)

echo.
echo Finished. Press any key to close this window.
pause >nul
