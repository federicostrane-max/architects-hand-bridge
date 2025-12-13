@echo off
echo ================================================
echo   ARCHITECT'S HAND - Starting All Services
echo ================================================
echo.

:: Start Tasker Service in a new window
echo Starting Tasker Service...
start "Tasker Service" cmd /k "cd /d D:\downloads\Lux\app lux 1\architects-hand-bridge\python-service && python tasker_service.py"

:: Wait a moment for service to start
timeout /t 3 /nobreak > nul

:: Start Electron app
echo Starting Architect's Hand Bridge...
cd /d "D:\downloads\Lux\app lux 1\architects-hand-bridge"
npm start -- --dev

pause
