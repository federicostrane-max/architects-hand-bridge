@echo off
echo ================================================
echo   TOOL SERVER v8.0 - Starting...
echo   (Hands Only - for Web App control)
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
echo Starting Tool Server on http://127.0.0.1:8766
echo Press Ctrl+C to stop
echo.
python tool_server.py
pause
