@echo off
echo ================================================
echo   TASKER SERVICE - Starting...
echo ================================================
echo.

cd /d "%~dp0"

echo Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found! Please install Python first.
    pause
    exit /b 1
)

echo.
echo Starting Tasker Service on http://127.0.0.1:8765
echo Press Ctrl+C to stop
echo.

python tasker_service.py

pause
