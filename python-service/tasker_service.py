"""
Tasker Service v5.0 - Official OAGI SDK + LUX Analyzer
======================================================

A FastAPI service that bridges the Lovable web app with local LUX execution.

Key Features:
- Uses official OAGI SDK patterns (AsyncDefaultAgent, AsyncPyautoguiActionHandler)
- Integrated LUX behavior analyzer for debugging coordinate issues
- Supports Actor, Thinker, and Tasker modes
- Automatic browser launch with dedicated Chrome profile
- Comprehensive logging and screenshot capture

Based on: https://github.com/agiopen-org/oagi-python

Usage:
    python tasker_service.py
    
    # Service runs on http://127.0.0.1:8765
    # Lovable web app sends POST requests to /execute
"""

import asyncio
import os
import sys
import subprocess
import time
import webbrowser
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ============================================================
# OAGI SDK IMPORTS - Official Pattern
# ============================================================
OAGI_AVAILABLE = False
OAGI_IMPORT_ERROR = None

try:
    from oagi import (
        # Agents
        AsyncDefaultAgent,
        AsyncActor,
        TaskerAgent,
        
        # Action Handlers
        AsyncPyautoguiActionHandler,
        PyautoguiConfig,
        
        # Screenshot
        AsyncScreenshotMaker,
        
        # Image processing
        PILImage,
        ImageConfig,
    )
    OAGI_AVAILABLE = True
    print("✅ OAGI SDK loaded successfully")
except ImportError as e:
    OAGI_IMPORT_ERROR = str(e)
    print(f"❌ OAGI SDK import failed: {e}")
    print("   Install with: pip install oagi")

# ============================================================
# LUX ANALYZER - For debugging coordinate issues
# ============================================================
ANALYZER_AVAILABLE = False

try:
    from lux_analyzer import LuxAnalyzer
    ANALYZER_AVAILABLE = True
    print("✅ LUX Analyzer loaded")
except ImportError:
    print("ℹ️ LUX Analyzer not available (optional - copy lux_analyzer.py to use)")

# ============================================================
# PYAUTOGUI - Fallback for when SDK not available
# ============================================================
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("⚠️ PyAutoGUI not available")

# ============================================================
# CONFIGURATION
# ============================================================
SERVICE_VERSION = "5.0"
SERVICE_PORT = 8765
DEBUG_LOGS_DIR = Path("debug_logs")
ANALYSIS_DIR = Path("lux_analysis")

# Create directories
DEBUG_LOGS_DIR.mkdir(exist_ok=True)
ANALYSIS_DIR.mkdir(exist_ok=True)

# ============================================================
# LOGGING SYSTEM
# ============================================================
class Logger:
    """Centralized logging with file output"""
    
    def __init__(self):
        self.log_file = DEBUG_LOGS_DIR / f"service_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.analyzer: Optional[LuxAnalyzer] = None
    
    def log(self, message: str, level: str = "INFO"):
        """Log message to console and file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_line + '\n')
        except Exception:
            pass
    
    def start_analysis_session(self, session_name: str = None):
        """Start LUX behavior analysis session"""
        if ANALYZER_AVAILABLE:
            name = session_name or f"session_{int(time.time())}"
            self.analyzer = LuxAnalyzer(session_name=name, output_dir=str(ANALYSIS_DIR))
            self.log(f"Analysis session started: {name}")
            return self.analyzer
        return None
    
    def end_analysis_session(self) -> Optional[str]:
        """End analysis session and generate report"""
        if self.analyzer:
            report_path = self.analyzer.generate_report()
            self.log(f"Analysis report: {report_path}")
            self.analyzer = None
            return report_path
        return None

# Global logger
logger = Logger()

# ============================================================
# DETAILED DEBUG FUNCTIONS (from v4.x)
# ============================================================
DEBUG_SCREENSHOTS_DIR = DEBUG_LOGS_DIR / "screenshots"
DEBUG_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

_debug_step_counter = 0

def debug_log(message: str, level: str = "INFO"):
    """Detailed debug logging with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line)
    
    # Also write to logger file
    logger.log(message, level)

def debug_screenshot(prefix: str = "screenshot") -> Optional[str]:
    """
    Capture screenshot for debugging.
    Returns path to saved screenshot.
    """
    global _debug_step_counter
    _debug_step_counter += 1
    
    if not PYAUTOGUI_AVAILABLE:
        debug_log("Screenshot skipped - PyAutoGUI not available", "WARNING")
        return None
    
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{_debug_step_counter:03d}_{prefix}_{timestamp}.png"
        filepath = DEBUG_SCREENSHOTS_DIR / filename
        
        screenshot = pyautogui.screenshot()
        screenshot.save(filepath)
        
        debug_log(f"Screenshot saved: {filepath}", "DEBUG")
        return str(filepath)
    except Exception as e:
        debug_log(f"Screenshot failed: {e}", "ERROR")
        return None

def debug_mouse_position() -> tuple:
    """Get current mouse position for debugging"""
    if not PYAUTOGUI_AVAILABLE:
        return (0, 0)
    try:
        return pyautogui.position()
    except Exception:
        return (0, 0)

def debug_screen_info() -> dict:
    """Get screen resolution info for debugging"""
    if not PYAUTOGUI_AVAILABLE:
        return {"width": 1920, "height": 1080, "source": "default"}
    try:
        w, h = pyautogui.size()
        return {
            "width": w,
            "height": h,
            "lux_ref_width": 1920,
            "lux_ref_height": 1080,
            "scale_x": w / 1920,
            "scale_y": h / 1080,
            "source": "pyautogui"
        }
    except Exception:
        return {"width": 1920, "height": 1080, "source": "error"}

# ============================================================
# PYDANTIC MODELS
# ============================================================
class TaskRequest(BaseModel):
    """Request model for task execution"""
    api_key: str
    task_description: str
    mode: str = "actor"  # actor, thinker, tasker
    model: str = "lux-actor-1"
    max_steps: int = 20
    start_url: Optional[str] = None
    todos: Optional[List[str]] = None
    
    # PyAutoGUI configuration
    drag_duration: float = 0.5
    scroll_amount: int = 30
    wait_duration: float = 1.0
    action_pause: float = 0.1
    step_delay: float = 0.3
    
    # Analysis options
    enable_analysis: bool = True
    
    # Resolution scaling (IMPORTANT for non-1080p screens!)
    # LUX is trained on 1920x1080. If your screen is different (e.g., 1920x1200),
    # coordinates need to be scaled. Set to True to auto-scale.
    enable_scaling: bool = True
    
    class Config:
        json_schema_extra = {
            "example": {
                "api_key": "your-oagi-api-key",
                "task_description": "Search for hotels in Bergamo on booking.com",
                "mode": "actor",
                "model": "lux-actor-1",
                "max_steps": 20,
                "start_url": "https://www.booking.com",
                "enable_analysis": True,
                "enable_scaling": True
            }
        }

class TaskResponse(BaseModel):
    """Response model for task execution"""
    success: bool
    message: str
    completed_todos: int = 0
    total_todos: int = 0
    error: Optional[str] = None
    execution_summary: Optional[Dict[str, Any]] = None
    analysis_report: Optional[str] = None

class StatusResponse(BaseModel):
    """Response model for status check"""
    status: str
    oagi_available: bool
    analyzer_available: bool
    version: str = SERVICE_VERSION

# ============================================================
# FASTAPI APP
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    logger.log(f"Tasker Service v{SERVICE_VERSION} starting...")
    logger.log(f"OAGI SDK: {'Available' if OAGI_AVAILABLE else 'Not available'}")
    logger.log(f"Analyzer: {'Available' if ANALYZER_AVAILABLE else 'Not available'}")
    yield
    logger.log("Tasker Service shutting down...")

app = FastAPI(
    title="Tasker Service",
    description="OAGI SDK-based task automation service for Architect's Hand",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
is_running = False
current_task = None

# ============================================================
# BROWSER MANAGEMENT
# ============================================================
def open_browser_with_url(url: str):
    """
    Open Chrome with dedicated Lux profile.
    
    Uses a separate Chrome profile so Lux browser doesn't interfere
    with user's regular Chrome sessions.
    """
    logger.log(f"Opening browser: {url}")
    
    import platform
    system = platform.system()
    
    if system == "Windows":
        # Find Chrome
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
        
        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break
        
        if not chrome_path:
            logger.log("Chrome not found, using default browser", "WARNING")
            webbrowser.open(url)
            time.sleep(4)
            return
        
        # Dedicated Lux profile
        lux_profile = os.path.join(
            os.path.expanduser("~"),
            "AppData", "Local", "Google", "Chrome", "User Data", "LuxProfile"
        )
        
        try:
            subprocess.Popen([
                chrome_path,
                f"--user-data-dir={lux_profile}",
                "--remote-debugging-port=9222",
                "--start-maximized",
                "--new-window",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                url
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            logger.log(f"Chrome launched with Lux profile: {lux_profile}")
            
        except Exception as e:
            logger.log(f"Chrome launch failed: {e}", "ERROR")
            webbrowser.open(url)
    
    elif system == "Darwin":  # macOS
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        lux_profile = os.path.expanduser("~/Library/Application Support/Google/Chrome/LuxProfile")
        
        if os.path.exists(chrome_path):
            try:
                subprocess.Popen([
                    chrome_path,
                    f"--user-data-dir={lux_profile}",
                    "--remote-debugging-port=9222",
                    "--start-maximized",
                    url
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.log("Chrome launched on macOS")
            except Exception as e:
                logger.log(f"Chrome launch failed: {e}", "ERROR")
                webbrowser.open(url)
        else:
            webbrowser.open(url)
    
    else:  # Linux
        chrome_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]
        
        lux_profile = os.path.expanduser("~/.config/google-chrome-lux")
        
        for chrome_path in chrome_paths:
            if os.path.exists(chrome_path):
                try:
                    subprocess.Popen([
                        chrome_path,
                        f"--user-data-dir={lux_profile}",
                        "--remote-debugging-port=9222",
                        "--start-maximized",
                        url
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    logger.log("Chrome launched on Linux")
                    break
                except Exception:
                    continue
        else:
            webbrowser.open(url)
    
    # Wait for browser to load
    logger.log("Waiting for browser to load...")
    time.sleep(4)
    logger.log("Browser ready")

# ============================================================
# API ENDPOINTS
# ============================================================
@app.get("/", response_model=StatusResponse)
async def root():
    """Root endpoint - returns service status"""
    return await get_status()

@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Check service status and availability"""
    return StatusResponse(
        status="busy" if is_running else "ready",
        oagi_available=OAGI_AVAILABLE,
        analyzer_available=ANALYZER_AVAILABLE,
        version=SERVICE_VERSION
    )

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "version": SERVICE_VERSION,
        "oagi_available": OAGI_AVAILABLE,
        "oagi_error": OAGI_IMPORT_ERROR if not OAGI_AVAILABLE else None,
        "analyzer_available": ANALYZER_AVAILABLE,
        "pyautogui_available": PYAUTOGUI_AVAILABLE,
        "is_running": is_running,
        "current_task": current_task[:50] + "..." if current_task and len(current_task) > 50 else current_task
    }

@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    """
    Main execution endpoint.
    
    Receives task requests from Lovable web app and executes them
    using the OAGI SDK.
    """
    global is_running, current_task
    
    # Check OAGI availability
    if not OAGI_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail=f"OAGI SDK not available: {OAGI_IMPORT_ERROR}. Install with: pip install oagi"
        )
    
    # Check if already running
    if is_running:
        raise HTTPException(
            status_code=409,
            detail=f"Another task is running: {current_task}"
        )
    
    is_running = True
    current_task = request.task_description
    analysis_report = None
    
    # Start analysis session if enabled
    analyzer = None
    if request.enable_analysis and ANALYZER_AVAILABLE:
        analyzer = logger.start_analysis_session(f"task_{int(time.time())}")
    
    try:
        logger.log(f"{'='*60}")
        logger.log(f"EXECUTING TASK")
        logger.log(f"{'='*60}")
        logger.log(f"Task: {request.task_description}")
        logger.log(f"Mode: {request.mode}")
        logger.log(f"Model: {request.model}")
        logger.log(f"Max Steps: {request.max_steps}")
        logger.log(f"Start URL: {request.start_url}")
        
        # Set API key
        os.environ["OAGI_API_KEY"] = request.api_key
        
        # Open browser if URL provided
        if request.start_url:
            open_browser_with_url(request.start_url)
        
        # Route based on mode
        mode = request.mode.lower()
        
        if mode in ['actor', 'thinker', 'direct']:
            result = await execute_with_default_agent(request, analyzer)
        elif mode == 'tasker' and request.todos:
            result = await execute_with_tasker_agent(request, analyzer)
        else:
            # Default to actor mode
            result = await execute_with_default_agent(request, analyzer)
        
        # Add analysis report path if available
        if analyzer:
            analysis_report = logger.end_analysis_session()
            result.analysis_report = analysis_report
        
        logger.log(f"Task completed: success={result.success}")
        return result
        
    except Exception as e:
        logger.log(f"Task failed with error: {e}", "ERROR")
        import traceback
        logger.log(traceback.format_exc(), "ERROR")
        
        # End analysis session on error
        if analyzer:
            analysis_report = logger.end_analysis_session()
        
        return TaskResponse(
            success=False,
            message="Task failed with error",
            error=str(e),
            analysis_report=analysis_report
        )
    
    finally:
        is_running = False
        current_task = None

@app.post("/stop")
async def stop_task():
    """Stop the currently running task"""
    global is_running, current_task
    
    if not is_running:
        return {"status": "no task running"}
    
    # Note: This doesn't actually interrupt the SDK execution
    # It just marks the task as stopped for the next check
    is_running = False
    stopped_task = current_task
    current_task = None
    
    logger.log(f"Task stop requested: {stopped_task}")
    
    return {"status": "stop requested", "task": stopped_task}

# ============================================================
# EXECUTION METHODS - Using Official SDK Patterns
# ============================================================

async def execute_with_default_agent(
    request: TaskRequest, 
    analyzer: Optional[LuxAnalyzer] = None
) -> TaskResponse:
    """
    Execute using AsyncDefaultAgent.
    
    This is the recommended approach from the official OAGI SDK.
    The SDK internally handles:
    - Screenshot capture
    - API communication
    - Action parsing and execution
    - Step loop management
    - Error handling
    """
    
    logger.log("Using AsyncDefaultAgent execution")
    
    # Configure PyAutoGUI behavior
    pyautogui_config = PyautoguiConfig(
        drag_duration=request.drag_duration,
        scroll_amount=request.scroll_amount,
        wait_duration=request.wait_duration,
        action_pause=request.action_pause,
    )
    
    # Determine model
    model = request.model
    if request.mode == 'thinker' and 'thinker' not in model:
        model = 'lux-thinker-1'
    elif request.mode == 'actor' and 'actor' not in model:
        model = 'lux-actor-1'
    
    logger.log(f"Model: {model}")
    logger.log(f"Config: pause={pyautogui_config.action_pause}s, scroll={pyautogui_config.scroll_amount}")
    logger.log(f"Scaling: {'ENABLED' if request.enable_scaling else 'disabled'}")
    
    try:
        # Create agent
        agent = AsyncDefaultAgent(
            api_key=request.api_key,
            max_steps=request.max_steps,
            model=model,
            step_delay=request.step_delay
        )
        
        # Create handlers
        action_handler = AsyncPyautoguiActionHandler(config=pyautogui_config)
        screenshot_maker = AsyncScreenshotMaker()
        
        # Wrap handler based on options:
        # - If analysis enabled: use AnalyzingActionHandler (includes scaling)
        # - If only scaling enabled: use ScalingActionHandler
        # - If both disabled: use raw SDK handler
        if analyzer:
            action_handler = AnalyzingActionHandler(
                action_handler, 
                analyzer, 
                enable_scaling=request.enable_scaling
            )
        elif request.enable_scaling:
            # Scaling without analysis
            action_handler = ScalingActionHandler(action_handler)
        
        logger.log("Starting agent.execute()...")
        
        # Execute using SDK - This is the key simplification!
        # The SDK handles the entire loop internally
        completed = await agent.execute(
            instruction=request.task_description,
            action_handler=action_handler,
            image_provider=screenshot_maker,
        )
        
        logger.log(f"Agent execution finished: completed={completed}")
        
        return TaskResponse(
            success=completed,
            message="Task completed successfully" if completed else "Task reached max steps without completion",
            completed_todos=1 if completed else 0,
            total_todos=1,
            execution_summary={
                "model": model,
                "max_steps": request.max_steps,
                "step_delay": request.step_delay,
                "completed": completed
            }
        )
        
    except Exception as e:
        logger.log(f"Agent execution error: {e}", "ERROR")
        raise


async def execute_with_tasker_agent(
    request: TaskRequest,
    analyzer: Optional[LuxAnalyzer] = None
) -> TaskResponse:
    """
    Execute using TaskerAgent for structured workflows.
    
    TaskerAgent is designed for when you have a list of specific
    steps (todos) that need to be executed in order.
    """
    
    logger.log("Using TaskerAgent execution")
    logger.log(f"Todos: {len(request.todos)} items")
    
    if not request.todos:
        return TaskResponse(
            success=False,
            message="Tasker mode requires 'todos' list",
            error="No todos provided"
        )
    
    # Configure PyAutoGUI
    pyautogui_config = PyautoguiConfig(
        drag_duration=request.drag_duration,
        scroll_amount=request.scroll_amount,
        wait_duration=request.wait_duration,
        action_pause=request.action_pause,
    )
    
    try:
        # Create TaskerAgent
        tasker = TaskerAgent(
            api_key=request.api_key,
            base_url=os.getenv("OAGI_BASE_URL", "https://api.agiopen.org"),
        )
        
        # Set task with todos
        tasker.set_task(
            task=request.task_description,
            todos=request.todos
        )
        
        # Create handlers
        action_handler = AsyncPyautoguiActionHandler(config=pyautogui_config)
        screenshot_maker = AsyncScreenshotMaker()
        
        # Wrap handler based on options:
        if analyzer:
            action_handler = AnalyzingActionHandler(
                action_handler, 
                analyzer,
                enable_scaling=request.enable_scaling
            )
        elif request.enable_scaling:
            # Scaling without analysis
            action_handler = ScalingActionHandler(action_handler)
        
        # Execute todos
        completed_count = 0
        
        for i, todo in enumerate(request.todos):
            logger.log(f"Executing todo {i+1}/{len(request.todos)}: {todo[:50]}...")
            
            try:
                success = await tasker.execute_todo(
                    todo_index=i,
                    action_handler=action_handler,
                    image_provider=screenshot_maker,
                    max_steps=request.max_steps
                )
                
                if success:
                    completed_count += 1
                    logger.log(f"Todo {i+1} completed")
                else:
                    logger.log(f"Todo {i+1} incomplete", "WARNING")
                    
            except Exception as e:
                logger.log(f"Todo {i+1} error: {e}", "ERROR")
        
        all_completed = completed_count == len(request.todos)
        
        return TaskResponse(
            success=all_completed,
            message=f"Completed {completed_count}/{len(request.todos)} todos",
            completed_todos=completed_count,
            total_todos=len(request.todos),
            execution_summary={
                "completed_todos": completed_count,
                "total_todos": len(request.todos),
                "todos": request.todos
            }
        )
        
    except Exception as e:
        logger.log(f"Tasker execution error: {e}", "ERROR")
        raise

# ============================================================
# RESOLUTION SCALING CONFIGURATION
# ============================================================
# LUX models are trained on 1920x1080 resolution.
# If your screen is different, coordinates need to be scaled.

LUX_REF_WIDTH = 1920
LUX_REF_HEIGHT = 1080

def scale_coordinates(x: int, y: int, screen_width: int, screen_height: int) -> tuple:
    """
    Scale coordinates from LUX reference (1920x1080) to actual screen resolution.
    
    Args:
        x, y: Original coordinates from LUX (in 1920x1080 space)
        screen_width, screen_height: Actual screen resolution
        
    Returns:
        (x_scaled, y_scaled): Coordinates adjusted for actual screen
    """
    # Scale X (usually 1.0 if width is 1920)
    x_scaled = int(x * screen_width / LUX_REF_WIDTH)
    
    # Scale Y (important for 1920x1200 screens: 1200/1080 = 1.111)
    y_scaled = int(y * screen_height / LUX_REF_HEIGHT)
    
    return x_scaled, y_scaled

# ============================================================
# SCALING ACTION HANDLER (lightweight, no logging)
# ============================================================

class ScalingActionHandler:
    """
    Lightweight wrapper that ONLY scales coordinates.
    Use this when enable_scaling=True but enable_analysis=False.
    
    For full logging with scaling, use AnalyzingActionHandler instead.
    """
    
    def __init__(self, handler: AsyncPyautoguiActionHandler):
        self.handler = handler
        
        # Get screen info
        if PYAUTOGUI_AVAILABLE:
            self.screen_width, self.screen_height = pyautogui.size()
        else:
            self.screen_width, self.screen_height = 1920, 1080
        
        self.scale_x = self.screen_width / LUX_REF_WIDTH
        self.scale_y = self.screen_height / LUX_REF_HEIGHT
        
        if self.scale_y != 1.0:
            print(f"📐 ScalingActionHandler: Y coords will be scaled by {self.scale_y:.3f}")
    
    async def __call__(self, actions):
        """Execute actions with scaled coordinates"""
        for action in actions:
            action_type = str(action.type.value) if hasattr(action.type, 'value') else str(action.type)
            argument = str(action.argument) if hasattr(action, 'argument') else ""
            
            if action_type == 'click' and PYAUTOGUI_AVAILABLE:
                coords = argument.replace(' ', '').split(',')
                x_lux, y_lux = int(coords[0]), int(coords[1])
                x_scaled, y_scaled = scale_coordinates(
                    x_lux, y_lux,
                    self.screen_width, self.screen_height
                )
                print(f"🖱️ Click: ({x_lux},{y_lux}) → ({x_scaled},{y_scaled})")
                pyautogui.click(x_scaled, y_scaled)
                time.sleep(0.1)
                
            elif action_type == 'drag' and PYAUTOGUI_AVAILABLE:
                parts = argument.replace(' ', '').split(',')
                if len(parts) >= 4:
                    x1_lux, y1_lux = int(parts[0]), int(parts[1])
                    x2_lux, y2_lux = int(parts[2]), int(parts[3])
                    x1_s, y1_s = scale_coordinates(x1_lux, y1_lux, self.screen_width, self.screen_height)
                    x2_s, y2_s = scale_coordinates(x2_lux, y2_lux, self.screen_width, self.screen_height)
                    pyautogui.moveTo(x1_s, y1_s)
                    pyautogui.drag(x2_s - x1_s, y2_s - y1_s, duration=0.5)
                else:
                    await self.handler([action])
            else:
                # Non-coordinate actions: use SDK
                await self.handler([action])

# ============================================================
# ANALYZING ACTION HANDLER WRAPPER (with full logging + SCALING)
# ============================================================

class AnalyzingActionHandler:
    """
    Wrapper around AsyncPyautoguiActionHandler that:
    1. SCALES coordinates from LUX reference (1920x1080) to actual screen
    2. Logs actions to LuxAnalyzer with screenshots
    3. Provides detailed debug logging
    
    This fixes the coordinate mismatch on non-1080p screens!
    """
    
    def __init__(self, handler: AsyncPyautoguiActionHandler, analyzer: LuxAnalyzer, enable_scaling: bool = True):
        self.handler = handler
        self.analyzer = analyzer
        self.action_counter = 0
        self.enable_scaling = enable_scaling
        
        # Get screen info once at init
        if PYAUTOGUI_AVAILABLE:
            self.screen_width, self.screen_height = pyautogui.size()
        else:
            self.screen_width, self.screen_height = 1920, 1080
        
        # Calculate scale factors
        self.scale_x = self.screen_width / LUX_REF_WIDTH
        self.scale_y = self.screen_height / LUX_REF_HEIGHT
        
        debug_log(f"📐 Resolution Scaling initialized:", "INFO")
        debug_log(f"   LUX reference: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}", "INFO")
        debug_log(f"   Your screen:   {self.screen_width}x{self.screen_height}", "INFO")
        debug_log(f"   Scale factors: X={self.scale_x:.3f}, Y={self.scale_y:.3f}", "INFO")
        
        if self.scale_y != 1.0:
            debug_log(f"   ⚠️  Y-scaling active! LUX Y coords will be multiplied by {self.scale_y:.3f}", "WARNING")
    
    async def __call__(self, actions):
        """Execute actions with coordinate scaling and logging"""
        
        for action in actions:
            self.action_counter += 1
            
            # Extract action details
            action_type = str(action.type.value) if hasattr(action.type, 'value') else str(action.type)
            argument = str(action.argument) if hasattr(action, 'argument') else ""
            
            debug_log(f"{'='*60}", "INFO")
            debug_log(f"ACTION #{self.action_counter}: {action_type.upper()}", "INFO")
            debug_log(f"{'='*60}", "INFO")
            debug_log(f"Raw argument from LUX: {argument}", "INFO")
            
            # Get screen info
            screen_info = debug_screen_info()
            
            # Screenshot BEFORE action
            screenshot_before = debug_screenshot(f"action_{self.action_counter}_before")
            
            # Get mouse position BEFORE
            mouse_before = debug_mouse_position()
            debug_log(f"Mouse position before: {mouse_before}", "DEBUG")
            
            # Log to analyzer based on action type
            logged_action = None
            
            if action_type == 'click':
                try:
                    coords = argument.replace(' ', '').split(',')
                    x_lux, y_lux = int(coords[0]), int(coords[1])
                    
                    # SCALE COORDINATES!
                    if self.enable_scaling:
                        x_scaled, y_scaled = scale_coordinates(
                            x_lux, y_lux, 
                            self.screen_width, self.screen_height
                        )
                        debug_log(f"🎯 LUX coords:    ({x_lux}, {y_lux})", "INFO")
                        debug_log(f"📐 Scaled coords: ({x_scaled}, {y_scaled})", "INFO")
                        debug_log(f"   Y adjustment: {y_lux} → {y_scaled} (×{self.scale_y:.3f})", "INFO")
                    else:
                        x_scaled, y_scaled = x_lux, y_lux
                        debug_log(f"Target coords (no scaling): ({x_scaled}, {y_scaled})", "INFO")
                    
                    # Calculate percentages for analysis
                    x_pct = (x_scaled / self.screen_width) * 100
                    y_pct = (y_scaled / self.screen_height) * 100
                    debug_log(f"   Screen position: {x_pct:.1f}%, {y_pct:.1f}%", "INFO")
                    
                    # Log to analyzer with screenshot
                    logged_action = self.analyzer.log_action(
                        action_type='click',
                        x=x_scaled,  # Log SCALED coordinates
                        y=y_scaled,
                        metadata={
                            'raw_argument': argument,
                            'lux_x': x_lux,
                            'lux_y': y_lux,
                            'scaled_x': x_scaled,
                            'scaled_y': y_scaled,
                            'scale_factor_y': self.scale_y,
                            'x_percent': x_pct,
                            'y_percent': y_pct,
                            'mouse_before': mouse_before,
                            'screenshot_before': screenshot_before,
                            'screen_info': screen_info
                        },
                        capture_screenshots=True
                    )
                except Exception as e:
                    debug_log(f"Click parse error: {e}", "ERROR")
            
            elif action_type == 'type':
                debug_log(f"Text to type: '{argument}'", "INFO")
                debug_log(f"Text length: {len(argument)} characters", "INFO")
                
                logged_action = self.analyzer.log_action(
                    action_type='type',
                    text=argument,
                    metadata={
                        'raw_argument': argument,
                        'text_length': len(argument),
                        'mouse_position': mouse_before,
                        'screenshot_before': screenshot_before
                    },
                    capture_screenshots=True
                )
            
            elif action_type == 'scroll':
                debug_log(f"Scroll amount: {argument}", "INFO")
                
                logged_action = self.analyzer.log_action(
                    action_type='scroll',
                    scroll_amount=argument,
                    metadata={
                        'raw_argument': argument,
                        'mouse_position': mouse_before
                    },
                    capture_screenshots=True
                )
            
            elif action_type == 'hotkey':
                debug_log(f"Hotkey: {argument}", "INFO")
                
                logged_action = self.analyzer.log_action(
                    action_type='hotkey',
                    keys=argument.split('+') if '+' in argument else [argument],
                    metadata={'raw_argument': argument},
                    capture_screenshots=True
                )
            
            else:
                debug_log(f"Other action type: {action_type} with arg: {argument}", "INFO")
        
        # ============================================================
        # EXECUTE ACTIONS WITH SCALING
        # ============================================================
        # For clicks with scaling enabled, we execute manually with pyautogui
        # to apply the coordinate transformation. Other actions use SDK.
        
        debug_log(f"Executing {len(actions)} action(s)...", "INFO")
        start_time = time.time()
        
        try:
            for action in actions:
                action_type = str(action.type.value) if hasattr(action.type, 'value') else str(action.type)
                argument = str(action.argument) if hasattr(action, 'argument') else ""
                
                if action_type == 'click' and self.enable_scaling and PYAUTOGUI_AVAILABLE:
                    # EXECUTE CLICK WITH SCALED COORDINATES
                    coords = argument.replace(' ', '').split(',')
                    x_lux, y_lux = int(coords[0]), int(coords[1])
                    x_scaled, y_scaled = scale_coordinates(
                        x_lux, y_lux,
                        self.screen_width, self.screen_height
                    )
                    
                    debug_log(f"🖱️ Executing click at SCALED ({x_scaled}, {y_scaled})", "INFO")
                    pyautogui.click(x_scaled, y_scaled)
                    time.sleep(0.1)  # Small pause after click
                    
                elif action_type == 'drag' and self.enable_scaling and PYAUTOGUI_AVAILABLE:
                    # EXECUTE DRAG WITH SCALED COORDINATES
                    # Format: "x1,y1,x2,y2"
                    parts = argument.replace(' ', '').split(',')
                    if len(parts) >= 4:
                        x1_lux, y1_lux = int(parts[0]), int(parts[1])
                        x2_lux, y2_lux = int(parts[2]), int(parts[3])
                        
                        x1_scaled, y1_scaled = scale_coordinates(x1_lux, y1_lux, self.screen_width, self.screen_height)
                        x2_scaled, y2_scaled = scale_coordinates(x2_lux, y2_lux, self.screen_width, self.screen_height)
                        
                        debug_log(f"🖱️ Executing drag from ({x1_scaled}, {y1_scaled}) to ({x2_scaled}, {y2_scaled})", "INFO")
                        pyautogui.moveTo(x1_scaled, y1_scaled)
                        pyautogui.drag(x2_scaled - x1_scaled, y2_scaled - y1_scaled, duration=0.5)
                    else:
                        # Fallback to SDK
                        await self.handler([action])
                
                else:
                    # For non-coordinate actions (type, scroll, hotkey), use SDK handler
                    await self.handler([action])
            
            execution_time = (time.time() - start_time) * 1000
            debug_log(f"✅ Actions executed in {execution_time:.2f}ms", "INFO")
            
            # Screenshot AFTER all actions
            screenshot_after = debug_screenshot(f"action_batch_after")
            
            # Get mouse position AFTER
            mouse_after = debug_mouse_position()
            debug_log(f"Mouse position after: {mouse_after}", "DEBUG")
            
            # Mark last logged action as complete
            if logged_action:
                self.analyzer.mark_action_complete(logged_action, success=True)
            
            return None
            
        except Exception as e:
            debug_log(f"❌ Action execution failed: {e}", "ERROR")
            
            # Capture error screenshot
            debug_screenshot(f"action_error")
            
            if logged_action:
                self.analyzer.mark_action_complete(logged_action, success=False, error_message=str(e))
            
            raise

# ============================================================
# MANUAL CONTROL ENDPOINT (for debugging)
# ============================================================

@app.post("/execute_step")
async def execute_single_step(request: dict):
    """
    Execute a single step for debugging purposes.
    
    Allows step-by-step execution to inspect LUX responses.
    """
    if not OAGI_AVAILABLE:
        raise HTTPException(status_code=500, detail="OAGI SDK not available")
    
    api_key = request.get("api_key")
    instruction = request.get("instruction")
    model = request.get("model", "lux-actor-1")
    
    if not api_key or not instruction:
        raise HTTPException(status_code=400, detail="api_key and instruction required")
    
    try:
        async with AsyncActor(api_key=api_key, model=model) as actor:
            await actor.init_task(instruction)
            
            screenshot_maker = AsyncScreenshotMaker()
            image = await screenshot_maker()
            
            step = await actor.step(image)
            
            # Parse actions for response
            actions_data = []
            for action in (step.actions or []):
                action_type = str(action.type.value) if hasattr(action.type, 'value') else str(action.type)
                actions_data.append({
                    "type": action_type,
                    "argument": str(action.argument) if hasattr(action, 'argument') else None
                })
            
            return {
                "stop": step.stop if hasattr(step, 'stop') else False,
                "reason": step.reason if hasattr(step, 'reason') else None,
                "actions": actions_data,
                "action_count": len(actions_data)
            }
            
    except Exception as e:
        logger.log(f"Single step error: {e}", "ERROR")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# ANALYSIS ENDPOINTS
# ============================================================

@app.get("/analysis/sessions")
async def list_analysis_sessions():
    """List available analysis sessions"""
    sessions = []
    
    if ANALYSIS_DIR.exists():
        for session_dir in ANALYSIS_DIR.iterdir():
            if session_dir.is_dir():
                report_path = session_dir / "report.html"
                sessions.append({
                    "name": session_dir.name,
                    "path": str(session_dir),
                    "has_report": report_path.exists(),
                    "report_path": str(report_path) if report_path.exists() else None
                })
    
    return {"sessions": sessions}

@app.get("/analysis/latest")
async def get_latest_analysis():
    """Get the latest analysis session"""
    if not ANALYSIS_DIR.exists():
        return {"error": "No analysis sessions found"}
    
    sessions = sorted(ANALYSIS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not sessions:
        return {"error": "No analysis sessions found"}
    
    latest = sessions[0]
    report_path = latest / "report.html"
    
    return {
        "session": latest.name,
        "path": str(latest),
        "has_report": report_path.exists(),
        "report_path": str(report_path) if report_path.exists() else None
    }

@app.get("/debug/screen")
async def get_screen_debug_info():
    """
    Get screen and mouse debug information.
    Useful for debugging coordinate issues.
    """
    screen_info = debug_screen_info()
    mouse_pos = debug_mouse_position()
    
    # Calculate where LUX reference coords would map to
    lux_ref_x = int(mouse_pos[0] * 1920 / screen_info['width'])
    lux_ref_y = int(mouse_pos[1] * 1080 / screen_info['height'])
    
    return {
        "screen": screen_info,
        "current_mouse": {
            "x": mouse_pos[0],
            "y": mouse_pos[1],
            "x_percent": (mouse_pos[0] / screen_info['width']) * 100,
            "y_percent": (mouse_pos[1] / screen_info['height']) * 100
        },
        "lux_reference": {
            "width": 1920,
            "height": 1080,
            "current_mouse_in_lux_ref": {"x": lux_ref_x, "y": lux_ref_y}
        },
        "debug_dirs": {
            "logs": str(DEBUG_LOGS_DIR),
            "screenshots": str(DEBUG_SCREENSHOTS_DIR),
            "analysis": str(ANALYSIS_DIR)
        }
    }

@app.post("/debug/screenshot")
async def capture_debug_screenshot(label: str = "manual"):
    """
    Capture a debug screenshot manually.
    Useful for testing screenshot capture.
    """
    path = debug_screenshot(f"manual_{label}")
    
    if path:
        return {"success": True, "path": path}
    else:
        return {"success": False, "error": "Screenshot failed"}

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*60)
    print(f"  TASKER SERVICE v{SERVICE_VERSION}")
    print("  Official OAGI SDK + LUX Analyzer")
    print("="*60)
    print(f"  OAGI SDK:  {'✅ Available' if OAGI_AVAILABLE else '❌ Not available'}")
    print(f"  Analyzer:  {'✅ Available' if ANALYZER_AVAILABLE else '➖ Optional'}")
    print(f"  PyAutoGUI: {'✅ Available' if PYAUTOGUI_AVAILABLE else '❌ Not available'}")
    print("="*60)
    print(f"  Endpoint: http://127.0.0.1:{SERVICE_PORT}")
    print(f"  Docs:     http://127.0.0.1:{SERVICE_PORT}/docs")
    print("="*60 + "\n")
    
    if not OAGI_AVAILABLE:
        print("⚠️  WARNING: OAGI SDK not available!")
        print("   Install with: pip install oagi")
        print("")
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=SERVICE_PORT,
        log_level="info"
    )
