@echo off
echo ================================================
echo   ARCHITECT'S HAND - Starting BOTH services...
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

echo [1/2] Starting Tasker Service (brain+hands) on port 8765...
start "Tasker Service 8765" cmd /k "cd /d %~dp0 && python tasker_service.py"

timeout /t 2 /nobreak >nul

echo [2/2] Starting Tool Server (hands only) on port 8766...
start "Tool Server 8766" cmd /k "cd /d %~dp0 && python tool_server.py"

echo.
echo ================================================
echo   Both services started!
echo.
echo   Tasker Service: http://127.0.0.1:8765
echo     - Brain + Hands (Electron UI)
echo.
echo   Tool Server:    http://127.0.0.1:8766
echo     - Hands Only (Web App control)
echo ================================================
echo.
echo Press any key to close this window...
echo (Services will continue running in their own windows)
pause >nul
