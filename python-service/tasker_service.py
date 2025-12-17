"""
Tasker Service - FastAPI wrapper for OAGI
Supports all three Lux modes: Actor, Thinker, and Tasker
Runs locally and receives requests from Architect's Hand Bridge
v3.0 - Uses DEDICATED Chrome profile (separate from user's browser)
"""

import asyncio
import os
import io
import webbrowser
import subprocess
import time
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# PyAutoGUI for screenshots and actions
import pyautogui

# OAGI imports - all from main module
try:
    from oagi import Actor, TaskerAgent, AsyncPyautoguiActionHandler, AsyncScreenshotMaker
    OAGI_AVAILABLE = True
except ImportError as e:
    print(f"Warning: OAGI import failed: {e}")
    OAGI_AVAILABLE = False


# Request/Response models
class TaskRequest(BaseModel):
    api_key: str
    task_description: str
    todos: List[str]
    start_url: Optional[str] = None
    max_steps: int = 60
    reflection_interval: int = 20
    model: str = "lux-actor-1"
    temperature: float = 0.1
    mode: str = "tasker"  # 'direct', 'tasker', 'actor', 'thinker'


class TaskResponse(BaseModel):
    success: bool
    message: str
    completed_todos: int
    total_todos: int
    error: Optional[str] = None
    execution_summary: Optional[dict] = None


class StatusResponse(BaseModel):
    status: str
    oagi_available: bool
    version: str = "3.0.0"


# Global state
current_task = None
is_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    print("=" * 50)
    print("Tasker Service Starting...")
    print(f"OAGI Available: {OAGI_AVAILABLE}")
    print("Supported modes: actor, thinker, tasker, direct")
    print("=" * 50)
    yield
    print("Tasker Service Shutting Down...")


# Create FastAPI app
app = FastAPI(
    title="Tasker Service",
    description="Local service for OAGI execution (Actor/Thinker/Tasker modes)",
    version="3.0.0",
    lifespan=lifespan
)

# Enable CORS for Electron app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def open_browser_with_url(url: str):
    """Open Chrome with DEDICATED PROFILE for Lux (separate from user's browser)"""
    print(f"\n>>> Opening browser with URL: {url}")
    
    import platform
    system = platform.system()
    
    if system == "Windows":
        # Use dedicated profile so Lux Chrome is SEPARATE from user's Chrome
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        
        # Alternative paths
        if not os.path.exists(chrome_path):
            chrome_path = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        if not os.path.exists(chrome_path):
            chrome_path = os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
        
        # Lux dedicated profile path
        lux_profile_path = os.path.join(
            os.path.expanduser("~"),
            "AppData", "Local", "Google", "Chrome", "User Data", "LuxProfile"
        )
        
        try:
            # Launch Chrome with:
            # --user-data-dir: Dedicated profile (SEPARATE instance from user's Chrome)
            # --remote-debugging-port: For potential CDP connection
            # --start-maximized: Full screen
            # --new-window: New window
            # --no-first-run: Skip first run dialogs
            # --no-default-browser-check: Skip default browser prompt
            process = subprocess.Popen([
                chrome_path,
                f"--user-data-dir={lux_profile_path}",
                "--remote-debugging-port=9222",
                "--start-maximized",
                "--new-window",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                url
            ], 
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
            )
            print(f">>> Chrome launched with DEDICATED Lux profile")
            print(f">>> Profile: {lux_profile_path}")
            print(f">>> PID: {process.pid}")
        except Exception as e:
            print(f">>> Chrome launch failed: {e}, trying webbrowser")
            webbrowser.open(url)
    else:
        # macOS/Linux
        chrome_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
        ]
        
        # Lux profile for non-Windows
        lux_profile_path = os.path.expanduser("~/.config/google-chrome-lux")
        
        chrome_opened = False
        for chrome_path in chrome_paths:
            if os.path.exists(chrome_path):
                try:
                    subprocess.Popen([
                        chrome_path,
                        f"--user-data-dir={lux_profile_path}",
                        "--remote-debugging-port=9222",
                        "--start-maximized",
                        "--new-window",
                        url
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                    )
                    chrome_opened = True
                    print(f">>> Chrome opened with Lux profile from: {chrome_path}")
                    break
                except Exception as e:
                    print(f">>> Failed: {e}")
        
        if not chrome_opened:
            print(">>> Using default browser")
            webbrowser.open(url)
    
    # Wait for browser to open and load
    print(">>> Waiting 4 seconds for browser to load...")
    time.sleep(4)
    
    print(">>> Browser ready - Lux can now see ONLY this page\n")


def take_screenshot_bytes():
    """Take screenshot and return as bytes"""
    screenshot = pyautogui.screenshot()
    img_bytes = io.BytesIO()
    screenshot.save(img_bytes, format='PNG')
    return img_bytes.getvalue()


def execute_action(action):
    """Execute a single action using pyautogui"""
    # Get action type - handle both enum and string
    action_type = None
    if hasattr(action, 'type'):
        if hasattr(action.type, 'value'):
            action_type = action.type.value  # Enum like ActionType.CLICK
        else:
            action_type = str(action.type)
    
    # Get argument
    argument = getattr(action, 'argument', '') or ''
    
    print(f"  Executing: {action_type} | Argument: {argument}")
    
    if action_type == 'click':
        # Parse coordinates from argument like "516, 977"
        try:
            coords = argument.replace(' ', '').split(',')
            x = int(coords[0])
            y = int(coords[1])
            print(f"  -> Clicking at ({x}, {y})")
            pyautogui.click(x, y)
        except Exception as e:
            print(f"  -> Click parse error: {e}")
    
    elif action_type == 'type':
        # Argument is the text to type
        if argument:
            print(f"  -> Typing: {argument}")
            pyautogui.write(argument, interval=0.02)
    
    elif action_type == 'key' or action_type == 'press':
        # Argument is the key to press
        if argument:
            print(f"  -> Pressing key: {argument}")
            pyautogui.press(argument.lower())
    
    elif action_type == 'scroll':
        # Handle multiple scroll formats:
        # Format 1: "421,476,up" or "421,476,down" (x, y, direction)
        # Format 2: "-3" or "3" (scroll amount)
        try:
            parts = argument.replace(' ', '').split(',')
            if len(parts) >= 3:
                # Format: x, y, direction
                x = int(parts[0])
                y = int(parts[1])
                direction = parts[2].lower()
                amount = 3 if direction == 'up' else -3
                print(f"  -> Scrolling {direction} at ({x}, {y})")
                pyautogui.moveTo(x, y)
                pyautogui.scroll(amount)
            elif len(parts) == 1:
                # Format: just amount
                amount = int(argument) if argument else 0
                print(f"  -> Scrolling: {amount}")
                pyautogui.scroll(amount)
            else:
                print(f"  -> Unknown scroll format: {argument}")
        except Exception as e:
            print(f"  -> Scroll error: {e}")
    
    elif action_type == 'drag':
        # Format: "startX, startY, endX, endY"
        try:
            parts = argument.replace(' ', '').split(',')
            if len(parts) >= 4:
                start_x = int(parts[0])
                start_y = int(parts[1])
                end_x = int(parts[2])
                end_y = int(parts[3])
                print(f"  -> Dragging from ({start_x}, {start_y}) to ({end_x}, {end_y})")
                pyautogui.moveTo(start_x, start_y)
                pyautogui.drag(end_x - start_x, end_y - start_y, duration=0.5)
            else:
                print(f"  -> Drag requires 4 coordinates")
        except Exception as e:
            print(f"  -> Drag error: {e}")
    
    elif action_type == 'hotkey':
        # Argument is keys separated by +
        if argument:
            keys = [k.strip().lower() for k in argument.split('+')]
            print(f"  -> Hotkey: {keys}")
            pyautogui.hotkey(*keys)
    
    elif action_type == 'finish':
        print(f"  -> Finish action received")
        return 'finish'
    
    else:
        print(f"  -> Unknown action type: {action_type}")
    
    return None


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Check if service is running and OAGI is available"""
    return StatusResponse(
        status="running" if not is_running else "busy",
        oagi_available=OAGI_AVAILABLE
    )


@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    """Execute a task using the appropriate OAGI agent based on mode"""
    global is_running, current_task
    
    if not OAGI_AVAILABLE:
        raise HTTPException(
            status_code=500, 
            detail="OAGI library not available. Please install with: pip install oagi"
        )
    
    if is_running:
        raise HTTPException(
            status_code=409,
            detail="Another task is currently running"
        )
    
    is_running = True
    current_task = request.task_description
    
    try:
        # Set API key
        os.environ["OAGI_API_KEY"] = request.api_key
        
        # ========================================
        # AUTO-OPEN BROWSER IF start_url PROVIDED
        # ========================================
        if request.start_url:
            open_browser_with_url(request.start_url)
        
        # Route based on mode
        mode = request.mode.lower()
        
        if mode in ['direct', 'actor', 'thinker']:
            # Direct execution - use Actor with step loop
            return await execute_direct_mode(request)
        else:
            # Tasker mode - use TaskerAgent.execute()
            return await execute_tasker_mode(request)
        
    except Exception as e:
        print(f"Error executing task: {e}")
        import traceback
        traceback.print_exc()
        return TaskResponse(
            success=False,
            message="Task failed with error",
            completed_todos=0,
            total_todos=len(request.todos),
            error=str(e)
        )
        
    finally:
        is_running = False
        current_task = None


async def execute_direct_mode(request: TaskRequest) -> TaskResponse:
    """Execute using Actor with step loop (for Actor/Thinker modes)"""
    
    print(f"\n{'='*50}")
    print(f"[Direct Mode] Executing: {request.task_description}")
    print(f"Model: {request.model}")
    print(f"Max Steps: {request.max_steps}")
    print(f"{'='*50}\n")
    
    try:
        # Determine model based on mode
        model = request.model
        if request.mode == 'thinker' and 'thinker' not in model:
            model = 'lux-thinker-1'
        elif request.mode == 'actor' and 'actor' not in model:
            model = 'lux-actor-1'
        
        # Create Actor
        actor = Actor(
            api_key=request.api_key,
            model=model
        )
        
        # Initialize task with max_steps
        actor.init_task(
            task_desc=request.task_description,
            max_steps=request.max_steps
        )
        
        # Execute using step loop with pyautogui
        print("Starting Actor step loop...")
        steps_executed = 0
        success = False
        
        for step_num in range(request.max_steps):
            # Take screenshot using pyautogui
            screenshot_bytes = take_screenshot_bytes()
            
            # Get next step from Actor
            step_result = actor.step(screenshot_bytes)
            
            print(f"\nStep {step_num + 1}:")
            if hasattr(step_result, 'reason'):
                # Print first 100 chars of reason
                reason_short = step_result.reason[:100] + "..." if len(step_result.reason) > 100 else step_result.reason
                print(f"  Reason: {reason_short}")
            
            # Check if done via stop flag
            if hasattr(step_result, 'stop') and step_result.stop:
                print("  -> Task signaled STOP")
                success = True
                break
            
            # Execute actions if present
            if hasattr(step_result, 'actions') and step_result.actions:
                for action in step_result.actions:
                    result = execute_action(action)
                    if result == 'finish':
                        success = True
                        break
                
                if success:
                    break
            
            steps_executed += 1
            
            # Small delay between steps
            await asyncio.sleep(0.3)
        
        # Cleanup
        actor.close()
        
        print(f"\n{'='*50}")
        print(f"Direct task {'COMPLETED' if success else 'reached max steps'}")
        print(f"Steps executed: {steps_executed}")
        print(f"{'='*50}\n")
        
        return TaskResponse(
            success=success,
            message=f"Task {'completed' if success else 'reached max steps'} after {steps_executed} steps",
            completed_todos=1 if success else 0,
            total_todos=1,
            execution_summary={"steps_executed": steps_executed}
        )
        
    except Exception as e:
        print(f"Direct mode error: {e}")
        raise


async def execute_tasker_mode(request: TaskRequest) -> TaskResponse:
    """Execute using TaskerAgent.execute() with todos"""
    
    print(f"\n{'='*50}")
    print(f"[Tasker Mode] Executing: {request.task_description}")
    print(f"Todos: {len(request.todos)}")
    for i, todo in enumerate(request.todos):
        print(f"  {i+1}. {todo}")
    print(f"Model: {request.model}")
    print(f"Max Steps: {request.max_steps}")
    print(f"Reflection Interval: {request.reflection_interval}")
    print(f"{'='*50}\n")
    
    try:
        # Create TaskerAgent
        tasker = TaskerAgent(
            api_key=request.api_key,
            model=request.model,
            max_steps=request.max_steps,
            reflection_interval=request.reflection_interval
        )
        
        # Set task with todos
        tasker.set_task(
            task=request.task_description,
            todos=request.todos
        )
        
        # Create handlers (these are used internally by execute())
        action_handler = AsyncPyautoguiActionHandler()
        image_provider = AsyncScreenshotMaker()
        
        # Execute using TaskerAgent's built-in execute method
        print("Starting TaskerAgent execution...")
        success = await tasker.execute(
            instruction=request.task_description,
            action_handler=action_handler,
            image_provider=image_provider
        )
        
        # Get results
        completed = len(request.todos) if success else 0
        
        # Try to get actual completion from memory
        try:
            memory = tasker.get_memory()
            if memory and hasattr(memory, 'todos'):
                completed = sum(1 for t in memory.todos if getattr(t, 'status', '').lower() == 'completed')
        except:
            pass
        
        print(f"\n{'='*50}")
        print(f"Task {'COMPLETED' if success else 'FAILED'}")
        print(f"Completed {completed}/{len(request.todos)} todos")
        print(f"{'='*50}\n")
        
        return TaskResponse(
            success=success,
            message="Task completed successfully" if success else "Task failed",
            completed_todos=completed,
            total_todos=len(request.todos)
        )
        
    except Exception as e:
        print(f"Tasker mode error: {e}")
        raise


@app.post("/stop")
async def stop_task():
    """Stop the currently running task"""
    global is_running, current_task
    
    if not is_running:
        return {"message": "No task running"}
    
    # TODO: Implement graceful stop
    is_running = False
    current_task = None
    
    return {"message": "Task stop requested"}


@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "Tasker Service",
        "version": "3.0.0",
        "oagi_available": OAGI_AVAILABLE,
        "supported_modes": ["actor", "thinker", "tasker", "direct"],
        "features": ["dedicated_chrome_profile", "scroll_drag_support", "remote_debugging"],
        "endpoints": [
            "GET /status - Check service status",
            "POST /execute - Execute a task",
            "POST /stop - Stop current task"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "=" * 50)
    print("  TASKER SERVICE v3.0")
    print("  Supports: Actor | Thinker | Tasker modes")
    print("  + Dedicated Chrome profile (LuxProfile)")
    print("=" * 50 + "\n")
    
    uvicorn.run(
        app, 
        host="127.0.0.1", 
        port=8765,
        log_level="info"
    )
