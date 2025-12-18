"""
Tasker Service - FastAPI wrapper for OAGI
Supports all three Lux modes: Actor, Thinker, and Tasker
Runs locally and receives requests from Architect's Hand Bridge
v4.1 - KB-Pure with Debug Logging for Booking.com analysis
"""

import asyncio
import os
import io
import sys
import webbrowser
import subprocess
import time
from typing import Optional, List
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# PyAutoGUI for screenshots and actions
import pyautogui

# Import Windows Unicode handler (KB official)
WINDOWS_UNICODE_AVAILABLE = False
typewrite_exact = None

if sys.platform == "win32":
    try:
        from _windows import typewrite_exact
        WINDOWS_UNICODE_AVAILABLE = True
        print("✅ Windows Unicode handler loaded (KB official)")
    except ImportError as e:
        print(f"⚠️ Windows Unicode handler not available: {e}")
else:
    print(f"ℹ️ Platform: {sys.platform} - Windows Unicode not applicable")

# === DEBUG LOGGING SYSTEM ===
DEBUG_LOGS_DIR = Path("debug_logs")
DEBUG_LOGS_DIR.mkdir(exist_ok=True)

def get_debug_log_path() -> Path:
    """Generate timestamped debug log file path"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEBUG_LOGS_DIR / f"debug_{timestamp}.log"

# Initialize current debug log file
current_debug_log = get_debug_log_path()
print(f"📁 Debug logs directory: {DEBUG_LOGS_DIR.absolute()}")

def debug_log(message: str, level: str = "INFO"):
    """Write debug message to both console and file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line)
    try:
        with open(current_debug_log, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    except Exception as e:
        print(f"[ERROR] Failed to write debug log: {e}")

def debug_screenshot(label: str) -> str:
    """Take screenshot for debug analysis."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"screenshot_{label}_{timestamp}.png"
        filepath = DEBUG_LOGS_DIR / filename
        screenshot = pyautogui.screenshot()
        screenshot.save(str(filepath))
        debug_log(f"Screenshot saved: {filename}", "DEBUG")
        return str(filepath)
    except Exception as e:
        debug_log(f"Screenshot failed: {e}", "ERROR")
        return ""

def debug_mouse_position() -> tuple:
    """Get current mouse position for coordinate verification"""
    try:
        x, y = pyautogui.position()
        return (x, y)
    except Exception as e:
        debug_log(f"Failed to get mouse position: {e}", "ERROR")
        return (0, 0)

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
    version: str = "4.1.0"


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
    version="4.1.0",
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
    """Execute a single action using pyautogui with proper delays for web forms"""
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
            
            debug_log(f"=== CLICK ACTION START ===", "INFO")
            debug_log(f"Target coordinates: ({x}, {y})", "INFO")
            
            # Screenshot BEFORE click
            screenshot_before = debug_screenshot("before_click")
            
            # Get mouse position before
            mouse_before = debug_mouse_position()
            debug_log(f"Mouse position before: {mouse_before}", "DEBUG")
            
            # Execute CLICK (KB Pure: single click)
            start_time = time.time()
            pyautogui.click(x, y)
            click_duration = time.time() - start_time
            
            debug_log(f"Click executed in {click_duration*1000:.2f}ms", "INFO")
            
            # Get mouse position after
            mouse_after = debug_mouse_position()
            debug_log(f"Mouse position after: {mouse_after}", "DEBUG")
            
            # Verify mouse moved to target
            if mouse_after == (x, y):
                debug_log(f"✅ Mouse position verified at target", "INFO")
            else:
                debug_log(f"⚠️ Mouse position mismatch: expected ({x},{y}), got {mouse_after}", "WARNING")
            
            # Small delay for UI response
            time.sleep(0.1)
            
            # Screenshot AFTER click
            screenshot_after = debug_screenshot("after_click")
            
            debug_log(f"=== CLICK ACTION END ===", "INFO")
            
        except Exception as e:
            debug_log(f"Click FAILED: {e}", "ERROR")
            print(f"  -> Click parse error: {e}")
    
    elif action_type == 'type':
        # Argument is the text to type
        if argument:
            # Remove quotes if present (KB standard)
            text = argument.strip("\"'")
            
            debug_log(f"=== TYPE ACTION START ===", "INFO")
            debug_log(f"Text to type: '{text}'", "INFO")
            debug_log(f"Text length: {len(text)} characters", "INFO")
            debug_log(f"Windows Unicode available: {WINDOWS_UNICODE_AVAILABLE}", "INFO")
            
            # Screenshot BEFORE typing
            screenshot_before = debug_screenshot("before_type")
            
            # Get mouse position
            mouse_pos = debug_mouse_position()
            debug_log(f"Mouse position: {mouse_pos}", "DEBUG")
            
            # Execute TYPE (KB Pure: platform-specific handler)
            typing_success = False
            typing_method = "unknown"
            
            try:
                start_time = time.time()
                
                if sys.platform == "win32" and WINDOWS_UNICODE_AVAILABLE:
                    # KB Official: Windows Unicode handler
                    typing_method = "Windows Unicode (KB official)"
                    debug_log(f"Using: {typing_method}", "INFO")
                    
                    # Type each character with logging
                    for i, char in enumerate(text):
                        debug_log(f"Char {i+1}/{len(text)}: '{char}' (U+{ord(char):04X})", "DEBUG")
                        typewrite_exact(char, interval=0.01)
                    
                    typing_success = True
                else:
                    # KB Fallback: pyautogui
                    typing_method = "PyAutoGUI (KB fallback)"
                    debug_log(f"Using: {typing_method}", "INFO")
                    pyautogui.typewrite(text, interval=0.01)
                    typing_success = True
                
                typing_duration = time.time() - start_time
                debug_log(f"Typing completed in {typing_duration*1000:.2f}ms", "INFO")
                
            except Exception as e:
                debug_log(f"Typing FAILED: {e}", "ERROR")
                import traceback
                debug_log(f"Traceback:\n{traceback.format_exc()}", "ERROR")
            
            # Small delay for rendering
            time.sleep(0.2)
            
            # Screenshot AFTER typing
            screenshot_after = debug_screenshot("after_type")
            
            # Attempt to verify text presence
            try:
                import pyperclip
                
                # Select all and copy
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.05)
                pyautogui.hotkey('ctrl', 'c')
                time.sleep(0.05)
                
                clipboard_content = pyperclip.paste()
                debug_log(f"Clipboard content: '{clipboard_content}'", "DEBUG")
                
                if text.lower() in clipboard_content.lower():
                    debug_log(f"✅ TEXT VERIFIED: Found in field", "INFO")
                else:
                    debug_log(f"⚠️ TEXT NOT FOUND: Expected '{text}', got '{clipboard_content}'", "WARNING")
                    debug_log(f"Possible causes:", "WARNING")
                    debug_log(f"  1. Wrong element focused", "WARNING")
                    debug_log(f"  2. Field cleared by JavaScript", "WARNING")
                    debug_log(f"  3. Field inside iFrame", "WARNING")
                    
            except Exception as e:
                debug_log(f"Text verification failed: {e}", "WARNING")
            
            debug_log(f"=== TYPE ACTION END ===", "INFO")
            
            if typing_success:
                print(f'  -> Typed "{text}" via {typing_method}')
    
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
    
    elif action_type == 'wait':
        # Wait/pause action
        try:
            wait_time = float(argument) if argument else 1.0
        except:
            wait_time = 1.0
        print(f"  -> Waiting {wait_time} seconds")
        time.sleep(wait_time)
    
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
        "version": "4.1.0",
        "oagi_available": OAGI_AVAILABLE,
        "supported_modes": ["actor", "thinker", "tasker", "direct"],
        "features": ["kb_compliant", "windows_unicode_input", "debug_logging", "screenshots"],
        "endpoints": [
            "GET /status - Check service status",
            "POST /execute - Execute a task",
            "POST /stop - Stop current task"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "=" * 50)
    print("  TASKER SERVICE v4.1 (KB-Pure + Debug)")
    print("  Supports: Actor | Thinker | Tasker modes")
    print("  + Windows Unicode + Debug Logging")
    print("=" * 50 + "\n")
    
    uvicorn.run(
        app, 
        host="127.0.0.1", 
        port=8765,
        log_level="info"
    )
