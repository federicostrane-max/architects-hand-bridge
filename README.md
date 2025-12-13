# Architect's Hand - Python Tasker Service Setup

## Overview

The Python Tasker Service wraps the official OAGI TaskerAgent to enable proper step-by-step browser automation with reflection and error recovery.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Lovable Web App                       │
│                   (Cloud - Supabase)                     │
└─────────────────────────┬───────────────────────────────┘
                          │
                          │ Creates tasks with todos
                          ▼
┌─────────────────────────────────────────────────────────┐
│              Architect's Hand Bridge                     │
│                  (Electron App)                          │
│                                                          │
│  1. Polls Supabase for pending tasks                     │
│  2. Extracts todos from task                             │
│  3. Delegates to Python Tasker Service                   │
└─────────────────────────┬───────────────────────────────┘
                          │
                          │ HTTP POST /execute
                          ▼
┌─────────────────────────────────────────────────────────┐
│             Python Tasker Service                        │
│               (FastAPI + OAGI)                           │
│                                                          │
│  1. Receives task description + todos                    │
│  2. Creates TaskerAgent with OAGI SDK                    │
│  3. Executes todos sequentially with reflection          │
│  4. Uses pyautogui for browser control                   │
│  5. Returns success/failure status                       │
└─────────────────────────────────────────────────────────┘
```

## Setup Instructions

### 1. Create Python Service Directory

```cmd
mkdir "D:\downloads\Lux\app lux 1\architects-hand-bridge\python-service"
```

### 2. Copy Files

Copy these files to `python-service` folder:
- `tasker_service.py`
- `start-tasker-service.bat`

Copy these files to `src/bridge` folder (replace existing):
- `index.js`
- `lux-client.js`

### 3. File Locations

```
architects-hand-bridge/
├── python-service/
│   ├── tasker_service.py       # Python FastAPI service
│   └── start-tasker-service.bat # Start script
├── src/
│   └── bridge/
│       ├── index.js            # Updated bridge (delegates to Python)
│       ├── lux-client.js       # Updated client (calls Python service)
│       └── supabase-client.js  # Keep existing
├── start-all.bat               # Starts everything
```

## Running

### Option 1: Start Separately (Recommended for debugging)

**Terminal 1 - Start Tasker Service:**
```cmd
cd "D:\downloads\Lux\app lux 1\architects-hand-bridge\python-service"
python tasker_service.py
```

**Terminal 2 - Start Electron App:**
```cmd
cd "D:\downloads\Lux\app lux 1\architects-hand-bridge"
npm start -- --dev
```

### Option 2: Start Together

```cmd
cd "D:\downloads\Lux\app lux 1\architects-hand-bridge"
start-all.bat
```

## Verifying Setup

1. Start Tasker Service - should show:
   ```
   ================================================
     TASKER SERVICE
     Local OAGI TaskerAgent Wrapper
   ================================================
   INFO:     Uvicorn running on http://127.0.0.1:8765
   ```

2. Start Electron App - should show:
   ```
   [Bridge] [SUCCESS] Tasker Service connected - using TaskerAgent mode
   ```

3. Test in browser:
   ```
   http://127.0.0.1:8765/status
   ```
   Should return: `{"status":"running","oagi_available":true,"version":"1.0.0"}`

## Troubleshooting

### "Tasker Service not available"
- Make sure Python service is running
- Check if port 8765 is free: `netstat -an | findstr 8765`

### "OAGI not available"
- Reinstall: `pip install oagi --upgrade`
- Check: `python -c "from oagi import Actor; print('OK')"`

### Task not executing
- Check Tasker Service terminal for errors
- Verify API key is correct
- Make sure no other automation is running (pyautogui conflicts)
