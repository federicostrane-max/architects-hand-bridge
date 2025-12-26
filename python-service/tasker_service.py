"""
Tasker Service v5.6.1 - Fixed TaskerAgent API
=========================================================

CHANGES from v5.6.0:
- FIX: TaskerAgent uses .run() not .step() (API correction)
- FIX: TaskerAgent requires action_handler and screenshot_maker in constructor
- ADD: Custom ClipboardActionHandler for Italian keyboard support
- ADD: SyncScreenshotMaker wrapper for TaskerAgent (sync, not async)

From oagi-python SDK README:
    config = ImageConfig(
        format="JPEG",
        quality=85,
        width=1260,
        height=700
    )

This is the resolution Lux API expects for optimal coordinate detection.
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

# OAGI SDK
OAGI_AVAILABLE = False
OAGI_IMPORT_ERROR = None

try:
    from oagi import (
        AsyncDefaultAgent, AsyncActor, TaskerAgent,
        AsyncPyautoguiActionHandler, PyautoguiActionHandler, PyautoguiConfig,
        AsyncScreenshotMaker, PILImage, ImageConfig,
    )
    OAGI_AVAILABLE = True
    print("✅ OAGI SDK loaded")
except ImportError as e:
    OAGI_IMPORT_ERROR = str(e)
    print(f"❌ OAGI SDK failed: {e}")

# PIL
PIL_AVAILABLE = False
try:
    from PIL import Image
    PIL_AVAILABLE = True
    print("✅ PIL loaded")
except ImportError:
    print("⚠️ PIL not available")

# LUX Analyzer
ANALYZER_AVAILABLE = False
try:
    from lux_analyzer import LuxAnalyzer
    ANALYZER_AVAILABLE = True
    print("✅ LUX Analyzer loaded")
except ImportError:
    print("ℹ️ LUX Analyzer not available")

# PyAutoGUI
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("⚠️ PyAutoGUI not available")

# Pyperclip for clipboard operations
PYPERCLIP_AVAILABLE = False
try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
    print("✅ Pyperclip loaded")
except ImportError:
    print("⚠️ Pyperclip not available - typing may not work with special chars")

# Configuration
SERVICE_VERSION = "5.6.1"
SERVICE_PORT = 8765
DEBUG_LOGS_DIR = Path("debug_logs")
ANALYSIS_DIR = Path("lux_analysis")
DEBUG_LOGS_DIR.mkdir(exist_ok=True)
ANALYSIS_DIR.mkdir(exist_ok=True)

# ============================================================
# LUX RESOLUTION - FROM SDK ImageConfig EXAMPLE
# ============================================================
LUX_REF_WIDTH = 1260
LUX_REF_HEIGHT = 700

# ============================================================
# STEP HISTORY - Stores reasoning and actions
# ============================================================
class StepRecord:
    def __init__(self, step_num: int, todo_index: Optional[int] = None):
        self.step_num = step_num
        self.todo_index = todo_index
        self.timestamp = datetime.now().isoformat()
        self.reasoning: Optional[str] = None
        self.actions: List[Dict] = []
        self.screenshot_before: Optional[str] = None
        self.screenshot_after: Optional[str] = None
        self.success: bool = False
        self.error: Optional[str] = None
        self.stop: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "step_num": self.step_num, 
            "todo_index": self.todo_index,
            "timestamp": self.timestamp,
            "reasoning": self.reasoning, "actions": self.actions,
            "screenshot_before": self.screenshot_before,
            "screenshot_after": self.screenshot_after,
            "success": self.success, "error": self.error, "stop": self.stop
        }

class ExecutionHistory:
    def __init__(self, task_description: str, todos: Optional[List[str]] = None):
        self.task_description = task_description
        self.todos = todos or []
        self.start_time = datetime.now()
        self.end_time: Optional[datetime] = None
        self.steps: List[StepRecord] = []
        self.completed: bool = False
        self.final_error: Optional[str] = None
        self.completed_todos: int = 0
    
    def add_step(self, step: StepRecord):
        self.steps.append(step)
    
    def finish(self, completed: bool, error: Optional[str] = None, completed_todos: int = 0):
        self.end_time = datetime.now()
        self.completed = completed
        self.final_error = error
        self.completed_todos = completed_todos
    
    def to_dict(self) -> Dict:
        return {
            "task_description": self.task_description,
            "todos": self.todos,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (self.end_time - self.start_time).total_seconds() if self.end_time else None,
            "total_steps": len(self.steps),
            "completed": self.completed,
            "completed_todos": self.completed_todos,
            "total_todos": len(self.todos),
            "final_error": self.final_error,
            "steps": [s.to_dict() for s in self.steps]
        }
    
    def generate_report(self, output_dir: Path) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if PYAUTOGUI_AVAILABLE:
            screen_width, screen_height = pyautogui.size()
            scale_x = screen_width / LUX_REF_WIDTH
            scale_y = screen_height / LUX_REF_HEIGHT
        else:
            screen_width, screen_height = 1920, 1080
            scale_x = scale_y = 1.0
        
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time else 0
        
        # Todos section
        todos_html = ""
        if self.todos:
            todos_html = "<div class='todos-section'><h3>📋 Todos</h3><ol>"
            for i, todo in enumerate(self.todos):
                status = "✅" if i < self.completed_todos else "❌"
                todos_html += f"<li>{status} {todo}</li>"
            todos_html += "</ol></div>"
        
        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>LUX Report - {self.task_description[:50]}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #f5f5f5; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 20px; }}
        .header h1 {{ margin: 0 0 10px 0; }}
        .todos-section {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .todos-section ol {{ margin: 10px 0; padding-left: 20px; }}
        .todos-section li {{ margin: 8px 0; padding: 8px; background: #f8f9fa; border-radius: 4px; }}
        .step {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .step-num {{ background: #667eea; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold; }}
        .todo-badge {{ background: #28a745; color: white; padding: 3px 10px; border-radius: 10px; font-size: 12px; margin-left: 10px; }}
        .reasoning {{ background: #e8f4f8; padding: 15px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #667eea; }}
        .reasoning-label {{ font-weight: bold; color: #667eea; }}
        .action {{ background: #f8f9fa; padding: 12px; border-radius: 6px; margin-bottom: 8px; font-family: monospace; }}
        .action-type {{ color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 10px; }}
        .action-type.click {{ background: #007bff; }}
        .action-type.type {{ background: #28a745; }}
        .action-type.scroll {{ background: #ffc107; color: black; }}
        .coords .original {{ color: #dc3545; }}
        .coords .scaled {{ color: #28a745; font-weight: bold; }}
        .success {{ border-left: 4px solid #28a745; }}
        .error {{ border-left: 4px solid #dc3545; }}
        .summary {{ background: white; border-radius: 10px; padding: 20px; margin-top: 20px; }}
        .stat {{ display: inline-block; margin-right: 30px; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #667eea; }}
        .stat-label {{ font-size: 12px; color: #888; }}
        .screen-info {{ background: #fff3cd; padding: 10px 15px; border-radius: 6px; margin-bottom: 20px; }}
        .sdk-note {{ background: #d4edda; padding: 10px 15px; border-radius: 6px; margin-bottom: 20px; border-left: 4px solid #28a745; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 LUX Execution Report v{SERVICE_VERSION}</h1>
        <div><strong>Task:</strong> {self.task_description}</div>
        <div><strong>Duration:</strong> {duration:.1f}s | <strong>Status:</strong> {"✅ Completed" if self.completed else "❌ Not Completed"}</div>
        {"<div><strong>Todos:</strong> " + str(self.completed_todos) + "/" + str(len(self.todos)) + " completed</div>" if self.todos else ""}
    </div>
    <div class="sdk-note">
        📐 <strong>SDK Resolution:</strong> Using <strong>{LUX_REF_WIDTH}×{LUX_REF_HEIGHT}</strong> as per SDK ImageConfig recommendation
    </div>
    <div class="screen-info">
        🖥️ <strong>Screen:</strong> {screen_width}×{screen_height} | 
        <strong>Scale:</strong> X={scale_x:.3f}, Y={scale_y:.3f}
    </div>
    {todos_html}
'''
        
        for step in self.steps:
            step_class = "success" if step.success else "error"
            todo_badge = f'<span class="todo-badge">Todo {step.todo_index + 1}</span>' if step.todo_index is not None else ""
            html += f'''
    <div class="step {step_class}">
        <span class="step-num">Step {step.step_num}</span>{todo_badge}
        <div class="reasoning">
            <div class="reasoning-label">🧠 LUX Reasoning:</div>
            {step.reasoning or "<em>No reasoning</em>"}
        </div>
        <div><strong>Actions ({len(step.actions)}):</strong></div>
'''
            for action in step.actions:
                action_type = action.get("type", "unknown")
                lux_coords = action.get("lux_coords")
                scaled_coords = action.get("scaled_coords")
                
                if action_type == "click" and lux_coords:
                    if scaled_coords:
                        coords_html = f'LUX ({LUX_REF_WIDTH}×{LUX_REF_HEIGHT}): <span class="original">({lux_coords["x"]}, {lux_coords["y"]})</span> → Screen: <span class="scaled">({scaled_coords["x"]}, {scaled_coords["y"]})</span>'
                    else:
                        coords_html = f'({lux_coords["x"]}, {lux_coords["y"]})'
                else:
                    arg = str(action.get("argument", ""))[:80]
                    coords_html = arg.replace("<", "&lt;").replace(">", "&gt;")
                
                html += f'''
        <div class="action">
            <span class="action-type {action_type}">{action_type.upper()}</span>
            <span class="coords">{coords_html}</span>
        </div>
'''
            html += "    </div>\n"
        
        html += f'''
    <div class="summary">
        <h2>📊 Summary</h2>
        <div class="stat"><div class="stat-value">{len(self.steps)}</div><div class="stat-label">Steps</div></div>
        <div class="stat"><div class="stat-value">{sum(len(s.actions) for s in self.steps)}</div><div class="stat-label">Actions</div></div>
        <div class="stat"><div class="stat-value">{duration:.1f}s</div><div class="stat-label">Duration</div></div>
        {"<div class='stat'><div class='stat-value'>" + str(self.completed_todos) + "/" + str(len(self.todos)) + "</div><div class='stat-label'>Todos</div></div>" if self.todos else ""}
        <div class="stat"><div class="stat-value">{"✅" if self.completed else "❌"}</div><div class="stat-label">Completed</div></div>
    </div>
</body>
</html>
'''
        
        report_path = output_dir / "execution_report.html"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html)
        
        json_path = output_dir / "execution_history.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        
        return str(report_path)

# ============================================================
# LOGGING
# ============================================================
class Logger:
    def __init__(self):
        self.log_file = DEBUG_LOGS_DIR / f"service_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.analyzer = None
    
    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except: pass

logger = Logger()

DEBUG_SCREENSHOTS_DIR = DEBUG_LOGS_DIR / "screenshots"
DEBUG_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
_debug_step_counter = 0

def debug_log(message: str, level: str = "INFO"):
    logger.log(message, level)

def debug_screenshot(prefix: str = "screenshot") -> Optional[str]:
    global _debug_step_counter
    _debug_step_counter += 1
    if not PYAUTOGUI_AVAILABLE: return None
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{_debug_step_counter:03d}_{prefix}_{timestamp}.png"
        filepath = DEBUG_SCREENSHOTS_DIR / filename
        pyautogui.screenshot().save(filepath)
        return str(filepath)
    except: return None

def debug_screen_info() -> dict:
    if not PYAUTOGUI_AVAILABLE:
        return {"width": 1920, "height": 1080, "source": "default"}
    try:
        w, h = pyautogui.size()
        return {
            "width": w, "height": h,
            "lux_ref_width": LUX_REF_WIDTH, "lux_ref_height": LUX_REF_HEIGHT,
            "scale_x": w / LUX_REF_WIDTH, "scale_y": h / LUX_REF_HEIGHT,
            "needs_resize": True,
            "source": "pyautogui"
        }
    except:
        return {"width": 1920, "height": 1080, "source": "error"}

# ============================================================
# CLIPBOARD TYPING - For Italian keyboard support
# ============================================================
def type_via_clipboard(text: str):
    """
    Type text using clipboard (Ctrl+V) instead of typewrite().
    This supports special characters like @ on Italian keyboards.
    """
    if PYPERCLIP_AVAILABLE:
        # Save current clipboard
        try:
            old_clipboard = pyperclip.paste()
        except:
            old_clipboard = ""
        
        try:
            # Copy text to clipboard and paste
            pyperclip.copy(text)
            time.sleep(0.1)  # Increased from 0.05
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.15)  # Increased from 0.1
        finally:
            # Restore old clipboard (optional, comment out if not needed)
            try:
                pyperclip.copy(old_clipboard)
            except:
                pass
    else:
        # Fallback to typewrite if pyperclip not available
        # This won't work well with special chars on non-US keyboards
        pyautogui.typewrite(text, interval=0.05)

# ============================================================
# PYDANTIC MODELS
# ============================================================
class TaskRequest(BaseModel):
    api_key: str
    task_description: str
    mode: str = "actor"  # "actor", "thinker", or "tasker"
    model: str = "lux-actor-1"
    max_steps_per_todo: int = 24
    temperature: float = 0.0
    start_url: Optional[str] = None
    todos: Optional[List[str]] = None  # Required for tasker mode
    drag_duration: float = 0.5
    scroll_amount: int = 30
    wait_duration: float = 1.0
    action_pause: float = 0.1
    step_delay: float = 0.3
    enable_analysis: bool = True
    enable_scaling: bool = False
    enable_screenshot_resize: bool = True

class TaskResponse(BaseModel):
    success: bool
    message: str
    completed_todos: int = 0
    total_todos: int = 0
    error: Optional[str] = None
    execution_summary: Optional[Dict[str, Any]] = None
    analysis_report: Optional[str] = None
    execution_report: Optional[str] = None

class StatusResponse(BaseModel):
    status: str
    oagi_available: bool
    analyzer_available: bool
    version: str = SERVICE_VERSION

# ============================================================
# FASTAPI APP
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.log(f"Tasker Service v{SERVICE_VERSION} starting...")
    screen_info = debug_screen_info()
    logger.log(f"Screen: {screen_info['width']}x{screen_info['height']}")
    logger.log(f"SDK Resolution: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
    logger.log(f"Clipboard typing: {'✅ Enabled' if PYPERCLIP_AVAILABLE else '❌ Disabled'}")
    logger.log(f"Supported modes: actor, thinker, tasker")
    yield
    logger.log("Shutting down...")

app = FastAPI(title="Tasker Service", version=SERVICE_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

is_running = False
current_task = None

# ============================================================
# BROWSER
# ============================================================
def open_browser_with_url(url: str):
    logger.log(f"Opening browser: {url}")
    import platform
    system = platform.system()
    
    if system == "Windows":
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        chrome_path = next((p for p in chrome_paths if os.path.exists(p)), None)
        if chrome_path:
            lux_profile = os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\User Data\\LuxProfile")
            try:
                subprocess.Popen([chrome_path, f"--user-data-dir={lux_profile}", "--remote-debugging-port=9222", "--start-maximized", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                webbrowser.open(url)
        else:
            webbrowser.open(url)
    else:
        webbrowser.open(url)
    
    time.sleep(4)

# ============================================================
# ENDPOINTS
# ============================================================
@app.get("/")
async def root():
    """Root endpoint"""
    return await get_status()

@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Status endpoint - required by bridge"""
    return StatusResponse(
        status="busy" if is_running else "ready", 
        oagi_available=OAGI_AVAILABLE, 
        analyzer_available=ANALYZER_AVAILABLE,
        version=SERVICE_VERSION
    )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    screen_info = debug_screen_info()
    return {
        "status": "healthy", 
        "version": SERVICE_VERSION, 
        "oagi_available": OAGI_AVAILABLE,
        "pil_available": PIL_AVAILABLE,
        "analyzer_available": ANALYZER_AVAILABLE,
        "pyautogui_available": PYAUTOGUI_AVAILABLE,
        "pyperclip_available": PYPERCLIP_AVAILABLE,
        "is_running": is_running,
        "current_task": current_task,
        "screen": screen_info,
        "lux_resolution": f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}",
        "supported_modes": ["actor", "thinker", "tasker"]
    }

@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    """Main execution endpoint - routes to appropriate executor based on mode"""
    global is_running, current_task
    
    if not OAGI_AVAILABLE:
        raise HTTPException(status_code=500, detail=f"OAGI SDK not available: {OAGI_IMPORT_ERROR}")
    if is_running:
        raise HTTPException(status_code=409, detail=f"Task running: {current_task}")
    
    is_running = True
    current_task = request.task_description
    
    try:
        logger.log(f"{'='*60}")
        logger.log(f"EXECUTING TASK")
        logger.log(f"{'='*60}")
        logger.log(f"Task: {request.task_description}")
        logger.log(f"Mode: {request.mode}")
        logger.log(f"Model: {request.model}")
        logger.log(f"Max Steps Per Todo: {request.max_steps_per_todo}")
        logger.log(f"Temperature: {request.temperature}")
        logger.log(f"Start URL: {request.start_url}")
        logger.log(f"Todos: {len(request.todos) if request.todos else 0}")
        logger.log(f"SDK Resolution: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
        logger.log(f"Screenshot Resize: {request.enable_screenshot_resize}")
        logger.log(f"Coordinate Scaling: {request.enable_scaling}")
        logger.log(f"Clipboard Typing: {PYPERCLIP_AVAILABLE}")
        
        os.environ["OAGI_API_KEY"] = request.api_key
        
        if request.start_url:
            open_browser_with_url(request.start_url)
        
        # Route to appropriate executor based on mode
        if request.mode == "tasker":
            # Tasker mode - requires todos
            if not request.todos or len(request.todos) == 0:
                raise HTTPException(
                    status_code=400, 
                    detail="Tasker mode requires todos list. Got empty or null todos."
                )
            logger.log(f"🎯 Using TASKER mode with {len(request.todos)} todos")
            result, execution_report = await execute_with_tasker(request)
        else:
            # Actor or Thinker mode - uses AsyncActor
            logger.log(f"🎯 Using {'THINKER' if request.mode == 'thinker' else 'ACTOR'} mode")
            result, execution_report = await execute_with_actor(request)
        
        result.execution_report = execution_report
        
        logger.log(f"Task completed: success={result.success}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.log(f"Error: {e}", "ERROR")
        import traceback
        logger.log(traceback.format_exc(), "ERROR")
        return TaskResponse(success=False, message="Failed", error=str(e))
    finally:
        is_running = False
        current_task = None

@app.post("/stop")
async def stop_task():
    """Stop current task"""
    global is_running, current_task
    if not is_running:
        return {"status": "no task running"}
    is_running = False
    stopped = current_task
    current_task = None
    return {"status": "stopped", "task": stopped}

# ============================================================
# RESIZED SCREENSHOT MAKER - SDK RESOLUTION (1260x700)
# ============================================================
class ResizedScreenshotMaker:
    """
    Screenshot maker that resizes to 1260x700 for Lux API.
    ASYNC version for AsyncActor.
    """
    
    def __init__(self):
        if PYAUTOGUI_AVAILABLE:
            self.screen_width, self.screen_height = pyautogui.size()
        else:
            self.screen_width, self.screen_height = 1920, 1080
        
        self.needs_resize = True
        
        debug_log(f"📸 ResizedScreenshotMaker (SDK v{SERVICE_VERSION}):")
        debug_log(f"   Screen: {self.screen_width}x{self.screen_height}")
        debug_log(f"   Lux SDK expects: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
        debug_log(f"   Scale factors: X={self.screen_width/LUX_REF_WIDTH:.3f}, Y={self.screen_height/LUX_REF_HEIGHT:.3f}")
    
    async def __call__(self):
        """Capture screenshot and resize to 1260x700 for Lux"""
        
        if not PIL_AVAILABLE or not PYAUTOGUI_AVAILABLE:
            debug_log("⚠️ PIL or PyAutoGUI not available - using SDK default", "WARNING")
            base_maker = AsyncScreenshotMaker()
            return await base_maker()
        
        try:
            pil_screenshot = pyautogui.screenshot()
            original_size = pil_screenshot.size
            
            resized = pil_screenshot.resize((LUX_REF_WIDTH, LUX_REF_HEIGHT), Image.LANCZOS)
            
            debug_log(f"📸 Screenshot: {original_size[0]}x{original_size[1]} → {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
            
            return PILImage(resized)
            
        except Exception as e:
            debug_log(f"⚠️ Screenshot resize failed: {e}", "ERROR")
            base_maker = AsyncScreenshotMaker()
            return await base_maker()


class SyncResizedScreenshotMaker:
    """
    Screenshot maker that resizes to 1260x700 for Lux API.
    SYNC version for TaskerAgent.
    """
    
    def __init__(self):
        if PYAUTOGUI_AVAILABLE:
            self.screen_width, self.screen_height = pyautogui.size()
        else:
            self.screen_width, self.screen_height = 1920, 1080
        
        debug_log(f"📸 SyncResizedScreenshotMaker (SDK v{SERVICE_VERSION}):")
        debug_log(f"   Screen: {self.screen_width}x{self.screen_height}")
        debug_log(f"   Lux SDK expects: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
    
    def __call__(self):
        """Capture screenshot and resize to 1260x700 for Lux (SYNC)"""
        
        if not PIL_AVAILABLE or not PYAUTOGUI_AVAILABLE:
            debug_log("⚠️ PIL or PyAutoGUI not available", "WARNING")
            return None
        
        try:
            pil_screenshot = pyautogui.screenshot()
            original_size = pil_screenshot.size
            
            resized = pil_screenshot.resize((LUX_REF_WIDTH, LUX_REF_HEIGHT), Image.LANCZOS)
            
            debug_log(f"📸 Screenshot: {original_size[0]}x{original_size[1]} → {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
            
            return PILImage(resized)
            
        except Exception as e:
            debug_log(f"⚠️ Screenshot resize failed: {e}", "ERROR")
            return None


def scale_coordinates(x: int, y: int, screen_width: int, screen_height: int) -> tuple:
    """
    Scale coordinates from Lux SDK reference (1260x700) to actual screen.
    """
    x_scaled = int(x * screen_width / LUX_REF_WIDTH)
    y_scaled = int(y * screen_height / LUX_REF_HEIGHT)
    return x_scaled, y_scaled

# ============================================================
# CLIPBOARD ACTION HANDLER - For Italian keyboard support
# ============================================================
class ClipboardActionHandler:
    """
    Custom action handler that uses clipboard for typing.
    SYNC version for TaskerAgent.
    Wraps PyautoguiActionHandler but intercepts 'type' actions.
    """
    
    def __init__(self, config: PyautoguiConfig = None):
        self.config = config or PyautoguiConfig()
        self.base_handler = PyautoguiActionHandler(config=self.config)
    
    def __call__(self, actions):
        """Execute actions, using clipboard for type actions"""
        for action in actions:
            action_type = str(action.type.value) if hasattr(action.type, "value") else str(action.type)
            argument = str(action.argument) if hasattr(action, "argument") else ""
            
            if action_type.lower() == "type":
                # Intercept type actions - use clipboard
                debug_log(f"⌨️ Typing via clipboard: '{argument[:50]}...'")
                type_via_clipboard(argument)
                time.sleep(0.1)
            else:
                # All other actions - use base handler
                self.base_handler([action])


# ============================================================
# CLIPBOARD TYPING WRAPPER - Intercepts type actions (ASYNC)
# ============================================================
async def execute_actions_with_clipboard_typing(actions, sdk_handler):
    """
    Execute actions using SDK handler, but intercept 'type' actions
    to use clipboard (Ctrl+V) instead of typewrite() for Italian keyboard support.
    """
    for action in actions:
        action_type = str(action.type.value) if hasattr(action.type, "value") else str(action.type)
        argument = str(action.argument) if hasattr(action, "argument") else ""
        
        if action_type.lower() == "type":
            # Intercept type actions - use clipboard instead of SDK
            debug_log(f"⌨️ Typing via clipboard: '{argument[:50]}...'")
            type_via_clipboard(argument)
            time.sleep(0.1)
        else:
            # All other actions - use SDK handler
            await sdk_handler([action])

# ============================================================
# TASKER MODE EXECUTION - Uses TaskerAgent with .run()
# ============================================================
async def execute_with_tasker(request: TaskRequest) -> tuple[TaskResponse, Optional[str]]:
    """Execute using TaskerAgent with todos list"""
    logger.log("=" * 50)
    logger.log("TASKER MODE EXECUTION")
    logger.log("=" * 50)
    
    todos = request.todos or []
    logger.log(f"Task: {request.task_description}")
    logger.log(f"Todos: {len(todos)}")
    for i, todo in enumerate(todos):
        logger.log(f"  [{i}] {todo[:80]}...")
    
    # Screen info
    if PYAUTOGUI_AVAILABLE:
        screen_width, screen_height = pyautogui.size()
    else:
        screen_width, screen_height = 1920, 1080
    
    scale_x = screen_width / LUX_REF_WIDTH
    scale_y = screen_height / LUX_REF_HEIGHT
    
    history = ExecutionHistory(request.task_description, todos)
    
    try:
        # Create custom components for TaskerAgent
        pyautogui_config = PyautoguiConfig(
            drag_duration=request.drag_duration,
            scroll_amount=request.scroll_amount,
            wait_duration=request.wait_duration,
            action_pause=request.action_pause
        )
        
        # Create screenshot maker (SYNC for TaskerAgent)
        screenshot_maker = SyncResizedScreenshotMaker() if request.enable_screenshot_resize else None
        
        # Create action handler with clipboard support (SYNC for TaskerAgent)
        action_handler = ClipboardActionHandler(config=pyautogui_config)
        
        logger.log(f"Creating TaskerAgent with model=lux-actor-1, max_steps={request.max_steps_per_todo}")
        
        # Create TaskerAgent with custom handlers
        tasker = TaskerAgent(
            api_key=request.api_key,
            model="lux-actor-1",  # Tasker always uses actor model
            max_steps=request.max_steps_per_todo,
            temperature=request.temperature,
            action_handler=action_handler,
            screenshot_maker=screenshot_maker
        )
        
        # Set task and todos
        tasker.set_task(
            task=request.task_description,
            todos=todos
        )
        
        logger.log("TaskerAgent configured, starting execution with .run()...")
        
        # Run TaskerAgent - this is SYNCHRONOUS, so run in executor
        loop = asyncio.get_event_loop()
        
        def run_tasker():
            """Run tasker in sync context"""
            try:
                tasker.run()
                return True, None
            except Exception as e:
                return False, str(e)
        
        # Execute in thread pool to not block event loop
        success, error = await loop.run_in_executor(None, run_tasker)
        
        if error:
            logger.log(f"TaskerAgent error: {error}", "ERROR")
            history.finish(False, error, completed_todos=0)
        else:
            logger.log("TaskerAgent completed successfully")
            # TaskerAgent doesn't expose which todos completed, assume all if success
            history.finish(True, completed_todos=len(todos))
        
        # Generate report
        report_dir = ANALYSIS_DIR / f"tasker_{int(time.time())}"
        execution_report = history.generate_report(report_dir)
        logger.log(f"📊 Report: {execution_report}")
        
        completed_todos = len(todos) if success else 0
        
        if success:
            message = f"All {len(todos)} todos completed"
        else:
            message = f"Failed: {error}"
        
        return TaskResponse(
            success=success,
            message=message,
            completed_todos=completed_todos,
            total_todos=len(todos),
            error=error,
            execution_summary={
                "mode": "tasker",
                "model": "lux-actor-1",
                "todos": todos,
                "completed_todos": completed_todos,
                "total_todos": len(todos),
                "max_steps_per_todo": request.max_steps_per_todo,
                "lux_resolution": f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}",
                "screen_resolution": f"{screen_width}x{screen_height}",
                "scale_factors": {"x": scale_x, "y": scale_y},
                "clipboard_typing": PYPERCLIP_AVAILABLE
            }
        ), execution_report
        
    except Exception as e:
        logger.log(f"Tasker execution error: {e}", "ERROR")
        import traceback
        logger.log(traceback.format_exc(), "ERROR")
        
        history.finish(False, str(e), completed_todos=0)
        try:
            report_dir = ANALYSIS_DIR / f"tasker_{int(time.time())}"
            execution_report = history.generate_report(report_dir)
        except:
            execution_report = None
        
        return TaskResponse(
            success=False,
            message=f"Error: {str(e)}",
            completed_todos=0,
            total_todos=len(todos),
            error=str(e)
        ), execution_report

# ============================================================
# ACTOR/THINKER MODE EXECUTION - Uses AsyncActor
# ============================================================
async def execute_with_actor(request: TaskRequest) -> tuple[TaskResponse, Optional[str]]:
    """Execute with AsyncActor for actor/thinker modes"""
    logger.log("Actor/Thinker mode execution with reasoning capture")
    
    # Determine model
    model = request.model
    if request.mode == "thinker" and "thinker" not in model:
        model = "lux-thinker-1"
    elif request.mode == "actor" and "actor" not in model:
        model = "lux-actor-1"
    
    logger.log(f"Model: {model}")
    
    # Screen info
    if PYAUTOGUI_AVAILABLE:
        screen_width, screen_height = pyautogui.size()
    else:
        screen_width, screen_height = 1920, 1080
    
    scale_x = screen_width / LUX_REF_WIDTH
    scale_y = screen_height / LUX_REF_HEIGHT
    logger.log(f"Screen: {screen_width}x{screen_height}")
    logger.log(f"SDK Resolution: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
    logger.log(f"Scale factors: X={scale_x:.3f}, Y={scale_y:.3f}")
    
    # Create components
    screenshot_maker = ResizedScreenshotMaker() if request.enable_screenshot_resize else AsyncScreenshotMaker()
    pyautogui_config = PyautoguiConfig(
        drag_duration=request.drag_duration, 
        scroll_amount=request.scroll_amount, 
        wait_duration=request.wait_duration, 
        action_pause=request.action_pause
    )
    
    # Use SDK's action handler (handles coordinates correctly)
    action_handler = AsyncPyautoguiActionHandler(config=pyautogui_config)
    
    history = ExecutionHistory(request.task_description)
    completed = False
    stopped = False
    
    try:
        # Pass max_steps_per_todo to init_task()
        async with AsyncActor(api_key=request.api_key, model=model) as actor:
            await actor.init_task(request.task_description, max_steps=request.max_steps_per_todo)
            logger.log(f"Task initialized with max_steps={request.max_steps_per_todo}")
            
            for step_num in range(1, request.max_steps_per_todo + 1):
                # Check if stop requested
                if not is_running:
                    logger.log("🛑 Stop requested - aborting execution")
                    stopped = True
                    break
                
                step_record = StepRecord(step_num)
                logger.log(f"{'='*50}")
                logger.log(f"STEP {step_num}/{request.max_steps_per_todo}")
                logger.log(f"{'='*50}")
                
                # Screenshot before
                step_record.screenshot_before = debug_screenshot(f"step_{step_num}_before")
                
                # Get image for Lux (resized to 1260x700)
                image = await screenshot_maker()
                
                # Get step from Lux
                step = await actor.step(image)
                
                # 🎯 CAPTURE REASONING
                reasoning = getattr(step, "reason", None) or getattr(step, "reasoning", None)
                step_record.reasoning = reasoning
                logger.log(f"🧠 REASONING: {reasoning}")
                
                # Check if done
                if step.stop:
                    logger.log("✅ Task complete")
                    step_record.stop = True
                    step_record.success = True
                    history.add_step(step_record)
                    completed = True
                    break
                
                # Process actions
                actions = step.actions or []
                logger.log(f"📋 Actions: {len(actions)}")
                
                for action in actions:
                    action_type = str(action.type.value) if hasattr(action.type, "value") else str(action.type)
                    argument = str(action.argument) if hasattr(action, "argument") else ""
                    
                    action_data = {"type": action_type, "argument": argument, "lux_coords": None, "scaled_coords": None}
                    
                    if action_type == "click" and argument:
                        try:
                            coords = argument.replace(" ", "").split(",")
                            x_lux, y_lux = int(coords[0]), int(coords[1])
                            action_data["lux_coords"] = {"x": x_lux, "y": y_lux}
                        except Exception as e:
                            logger.log(f"   ⚠️ Parse error: {e}", "WARNING")
                    elif action_type == "type":
                        logger.log(f"   ⌨️ Type: '{argument[:50]}'")
                    elif action_type == "scroll":
                        logger.log(f"   🖱️ Scroll: {argument}")
                    elif action_type == "hotkey":
                        logger.log(f"   ⌨️ Hotkey: {argument}")
                    else:
                        logger.log(f"   ❓ {action_type}: {argument}")
                    
                    step_record.actions.append(action_data)
                
                # Execute actions using SDK handler with clipboard typing intercept
                try:
                    await execute_actions_with_clipboard_typing(actions, action_handler)
                    step_record.success = True
                    logger.log(f"✅ Step {step_num} executed")
                    
                except Exception as e:
                    step_record.error = str(e)
                    logger.log(f"❌ Step error: {e}", "ERROR")
                
                # Screenshot after
                step_record.screenshot_after = debug_screenshot(f"step_{step_num}_after")
                history.add_step(step_record)
                
                # Delay
                if request.step_delay > 0:
                    await asyncio.sleep(request.step_delay)
            
            else:
                logger.log(f"⚠️ Max steps ({request.max_steps_per_todo}) reached")
        
        # Generate report
        history.finish(completed)
        report_dir = ANALYSIS_DIR / f"execution_{int(time.time())}"
        execution_report = history.generate_report(report_dir)
        logger.log(f"📊 Report: {execution_report}")
        
        if stopped:
            message = "Stopped by user"
        elif completed:
            message = "Completed"
        else:
            message = "Max steps reached"
        
        return TaskResponse(
            success=completed,
            message=message,
            completed_todos=1 if completed else 0,
            total_todos=1,
            execution_summary={
                "mode": request.mode,
                "model": model, 
                "steps": len(history.steps), 
                "completed": completed,
                "stopped": stopped,
                "max_steps_per_todo": request.max_steps_per_todo,
                "lux_resolution": f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}",
                "screen_resolution": f"{screen_width}x{screen_height}",
                "scale_factors": {"x": scale_x, "y": scale_y},
                "clipboard_typing": PYPERCLIP_AVAILABLE
            }
        ), execution_report
        
    except Exception as e:
        history.finish(False, str(e))
        try:
            report_dir = ANALYSIS_DIR / f"execution_{int(time.time())}"
            execution_report = history.generate_report(report_dir)
        except:
            execution_report = None
        raise

# ============================================================
# DEBUG ENDPOINTS
# ============================================================
@app.post("/execute_step")
async def execute_single_step(request: dict):
    """Execute single step for debugging"""
    if not OAGI_AVAILABLE:
        raise HTTPException(status_code=500, detail="OAGI not available")
    
    api_key = request.get("api_key")
    instruction = request.get("instruction")
    if not api_key or not instruction:
        raise HTTPException(status_code=400, detail="api_key and instruction required")
    
    max_steps = request.get("max_steps_per_todo", 24)
    
    async with AsyncActor(api_key=api_key, model=request.get("model", "lux-actor-1")) as actor:
        await actor.init_task(instruction, max_steps=max_steps)
        screenshot_maker = ResizedScreenshotMaker()
        image = await screenshot_maker()
        step = await actor.step(image)
        
        reasoning = getattr(step, "reason", None) or getattr(step, "reasoning", None)
        actions_data = [
            {"type": str(a.type.value) if hasattr(a.type, "value") else str(a.type), "argument": str(getattr(a, "argument", ""))} 
            for a in (step.actions or [])
        ]
        
        return {
            "stop": getattr(step, "stop", False), 
            "reasoning": reasoning, 
            "actions": actions_data,
            "lux_resolution": f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}"
        }

@app.get("/analysis/sessions")
async def list_analysis_sessions():
    """List all analysis sessions"""
    sessions = []
    if ANALYSIS_DIR.exists():
        for session_dir in ANALYSIS_DIR.iterdir():
            if session_dir.is_dir():
                report_path = session_dir / "execution_report.html"
                sessions.append({
                    "name": session_dir.name,
                    "path": str(session_dir),
                    "has_report": report_path.exists(),
                    "report_path": str(report_path) if report_path.exists() else None
                })
    return {"sessions": sorted(sessions, key=lambda x: x['name'], reverse=True)}

@app.get("/analysis/latest")
async def get_latest_analysis():
    """Get latest analysis session"""
    if not ANALYSIS_DIR.exists():
        return {"error": "No sessions"}
    sessions = sorted([d for d in ANALYSIS_DIR.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
    if not sessions:
        return {"error": "No sessions"}
    latest = sessions[0]
    report_path = latest / "execution_report.html"
    return {"session": latest.name, "report_path": str(report_path) if report_path.exists() else None}

@app.get("/debug/screen")
async def get_screen_debug_info():
    """Get screen info with SDK resolution"""
    info = debug_screen_info()
    info["lux_resolution"] = f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}"
    info["clipboard_typing"] = PYPERCLIP_AVAILABLE
    return info

@app.post("/debug/screenshot")
async def capture_debug_screenshot(label: str = "manual"):
    """Capture debug screenshot"""
    path = debug_screenshot(f"manual_{label}")
    return {"success": path is not None, "path": path}

@app.post("/debug/test_resize")
async def test_screenshot_resize():
    """Test screenshot resize functionality with SDK resolution"""
    if not PIL_AVAILABLE or not PYAUTOGUI_AVAILABLE:
        return {"error": "PIL or PyAutoGUI not available"}
    
    try:
        original = pyautogui.screenshot()
        original_path = DEBUG_SCREENSHOTS_DIR / "test_original.png"
        original.save(original_path)
        
        resized = original.resize((LUX_REF_WIDTH, LUX_REF_HEIGHT), Image.LANCZOS)
        resized_path = DEBUG_SCREENSHOTS_DIR / "test_resized_sdk.png"
        resized.save(resized_path)
        
        return {
            "success": True,
            "original": {"path": str(original_path), "size": original.size},
            "resized": {"path": str(resized_path), "size": resized.size},
            "sdk_resolution": f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}",
            "scale_factors": {
                "x": original.size[0] / LUX_REF_WIDTH,
                "y": original.size[1] / LUX_REF_HEIGHT
            }
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/debug/test_coordinate_scaling")
async def test_coordinate_scaling(lux_x: int = 290, lux_y: int = 272):
    """Test coordinate scaling from SDK resolution to screen"""
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "PyAutoGUI not available"}
    
    screen_width, screen_height = pyautogui.size()
    x_scaled, y_scaled = scale_coordinates(lux_x, lux_y, screen_width, screen_height)
    
    return {
        "lux_coords": {"x": lux_x, "y": lux_y},
        "lux_resolution": f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}",
        "screen_resolution": f"{screen_width}x{screen_height}",
        "scaled_coords": {"x": x_scaled, "y": y_scaled},
        "scale_factors": {
            "x": screen_width / LUX_REF_WIDTH,
            "y": screen_height / LUX_REF_HEIGHT
        },
        "explanation": f"LUX ({lux_x}, {lux_y}) on {LUX_REF_WIDTH}x{LUX_REF_HEIGHT} → ({x_scaled}, {y_scaled}) on {screen_width}x{screen_height}"
    }

@app.post("/debug/test_mouse")
async def test_mouse_movement():
    """Test if PyAutoGUI can move the mouse from within the service"""
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "PyAutoGUI not available"}
    
    start_pos = pyautogui.position()
    logger.log(f"🖱️ TEST MOUSE - Start position: {start_pos}")
    
    logger.log(f"🖱️ Moving to (500, 500)...")
    pyautogui.moveTo(500, 500)
    time.sleep(0.3)
    
    after_move = pyautogui.position()
    logger.log(f"🖱️ After moveTo: {after_move}")
    
    logger.log(f"🖱️ Clicking at (500, 500)...")
    pyautogui.click(500, 500)
    time.sleep(0.2)
    
    logger.log(f"🖱️ Moving to (800, 400)...")
    pyautogui.moveTo(800, 400)
    time.sleep(0.3)
    
    final_pos = pyautogui.position()
    logger.log(f"🖱️ Final position: {final_pos}")
    
    mouse_moved = (start_pos[0] != after_move[0]) or (start_pos[1] != after_move[1])
    logger.log(f"🖱️ Mouse moved: {mouse_moved}")
    
    return {
        "start": {"x": start_pos[0], "y": start_pos[1]},
        "after_move_to_500_500": {"x": after_move[0], "y": after_move[1]},
        "final_800_400": {"x": final_pos[0], "y": final_pos[1]},
        "mouse_moved": mouse_moved,
        "success": mouse_moved
    }

@app.post("/debug/test_click_at")
async def test_click_at_coordinates(lux_x: int = 500, lux_y: int = 350):
    """Test click at scaled coordinates"""
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "PyAutoGUI not available"}
    
    screen_width, screen_height = pyautogui.size()
    x_scaled, y_scaled = scale_coordinates(lux_x, lux_y, screen_width, screen_height)
    
    logger.log(f"🎯 TEST CLICK - LUX coords: ({lux_x}, {lux_y})")
    logger.log(f"📐 Scaled to: ({x_scaled}, {y_scaled}) on {screen_width}x{screen_height}")
    logger.log(f"🖱️ Clicking...")
    
    pyautogui.moveTo(x_scaled, y_scaled)
    time.sleep(0.3)
    
    pyautogui.click(x_scaled, y_scaled)
    time.sleep(0.2)
    
    return {
        "lux_coords": {"x": lux_x, "y": lux_y},
        "lux_resolution": f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}",
        "screen_resolution": f"{screen_width}x{screen_height}",
        "scaled_coords": {"x": x_scaled, "y": y_scaled},
        "clicked": True
    }

@app.post("/debug/test_type")
async def test_type_text(text: str = "test@example.com"):
    """Test typing text via clipboard (supports @ and special chars)"""
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "PyAutoGUI not available"}
    
    logger.log(f"⌨️ TEST TYPE - Typing via clipboard: '{text}'")
    
    type_via_clipboard(text)
    
    return {
        "typed": text,
        "method": "clipboard" if PYPERCLIP_AVAILABLE else "typewrite",
        "success": True
    }

@app.post("/debug/test_click_and_type")
async def test_click_and_type(lux_x: int = 630, lux_y: int = 350, text: str = "test@example.com"):
    """Click and type in one action using clipboard"""
    if not PYAUTOGUI_AVAILABLE:
        return {"error": "PyAutoGUI not available"}
    
    screen_width, screen_height = pyautogui.size()
    x_scaled, y_scaled = scale_coordinates(lux_x, lux_y, screen_width, screen_height)
    
    logger.log(f"🎯 CLICK+TYPE - LUX ({lux_x}, {lux_y}) → Screen ({x_scaled}, {y_scaled})")
    logger.log(f"⌨️ Will type via clipboard: '{text}'")
    
    pyautogui.click(x_scaled, y_scaled)
    time.sleep(0.3)
    
    type_via_clipboard(text)
    
    logger.log(f"✅ Click+Type completed")
    
    return {
        "lux_coords": {"x": lux_x, "y": lux_y},
        "clicked_at": {"x": x_scaled, "y": y_scaled},
        "typed": text,
        "method": "clipboard" if PYPERCLIP_AVAILABLE else "typewrite",
        "success": True
    }

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    import uvicorn
    
    screen_info = debug_screen_info()
    print(f"\n{'='*60}")
    print(f"  TASKER SERVICE v{SERVICE_VERSION}")
    print(f"  SDK Resolution: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
    print(f"  Default max_steps_per_todo: 24")
    print(f"{'='*60}")
    print(f"  OAGI: {'✅' if OAGI_AVAILABLE else '❌'}  PIL: {'✅' if PIL_AVAILABLE else '❌'}  PyAutoGUI: {'✅' if PYAUTOGUI_AVAILABLE else '❌'}  Pyperclip: {'✅' if PYPERCLIP_AVAILABLE else '❌'}")
    print(f"  Screen: {screen_info['width']}x{screen_info['height']}")
    print(f"  Scale: X={screen_info['scale_x']:.3f}, Y={screen_info['scale_y']:.3f}")
    print(f"  Clipboard Typing: {'✅ Enabled' if PYPERCLIP_AVAILABLE else '❌ Disabled (install pyperclip)'}")
    print(f"{'='*60}")
    print(f"  SUPPORTED MODES:")
    print(f"    • actor   - AsyncActor with manual step control")
    print(f"    • thinker - AsyncActor with lux-thinker-1 model")
    print(f"    • tasker  - TaskerAgent with .run() (automatic)")
    print(f"{'='*60}")
    print(f"  http://127.0.0.1:{SERVICE_PORT}")
    print(f"  Reports: {ANALYSIS_DIR}/")
    print(f"{'='*60}\n")
    
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT, log_level="info")
