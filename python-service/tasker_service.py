"""
Tasker Service v5.2 - Official OAGI SDK + Reasoning Capture
============================================================

Key Features:
- Manual step control with REASONING capture for each step
- ResizedScreenshotMaker - resizes screenshots to 1920x1080
- Coordinate scaling from Lux 1080p to actual screen resolution
- HTML execution report with full reasoning chain

Based on: https://github.com/agiopen-org/oagi-python
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
        AsyncPyautoguiActionHandler, PyautoguiConfig,
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

# Configuration
SERVICE_VERSION = "5.2"
SERVICE_PORT = 8765
DEBUG_LOGS_DIR = Path("debug_logs")
ANALYSIS_DIR = Path("lux_analysis")
DEBUG_LOGS_DIR.mkdir(exist_ok=True)
ANALYSIS_DIR.mkdir(exist_ok=True)

# LUX Resolution (from KB/README.md)
LUX_REF_WIDTH = 1920
LUX_REF_HEIGHT = 1080

# ============================================================
# STEP HISTORY - Stores reasoning and actions
# ============================================================
class StepRecord:
    def __init__(self, step_num: int):
        self.step_num = step_num
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
            "step_num": self.step_num, "timestamp": self.timestamp,
            "reasoning": self.reasoning, "actions": self.actions,
            "screenshot_before": self.screenshot_before,
            "screenshot_after": self.screenshot_after,
            "success": self.success, "error": self.error, "stop": self.stop
        }

class ExecutionHistory:
    def __init__(self, task_description: str):
        self.task_description = task_description
        self.start_time = datetime.now()
        self.end_time: Optional[datetime] = None
        self.steps: List[StepRecord] = []
        self.completed: bool = False
        self.final_error: Optional[str] = None
    
    def add_step(self, step: StepRecord):
        self.steps.append(step)
    
    def finish(self, completed: bool, error: Optional[str] = None):
        self.end_time = datetime.now()
        self.completed = completed
        self.final_error = error
    
    def to_dict(self) -> Dict:
        return {
            "task_description": self.task_description,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (self.end_time - self.start_time).total_seconds() if self.end_time else None,
            "total_steps": len(self.steps),
            "completed": self.completed,
            "final_error": self.final_error,
            "steps": [s.to_dict() for s in self.steps]
        }
    
    def generate_report(self, output_dir: Path) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if PYAUTOGUI_AVAILABLE:
            screen_width, screen_height = pyautogui.size()
            scale_y = screen_height / LUX_REF_HEIGHT
        else:
            screen_width, screen_height = LUX_REF_WIDTH, LUX_REF_HEIGHT
            scale_y = 1.0
        
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time else 0
        
        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>LUX Report - {self.task_description[:50]}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #f5f5f5; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 20px; }}
        .header h1 {{ margin: 0 0 10px 0; }}
        .step {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .step-num {{ background: #667eea; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold; }}
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
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 LUX Execution Report</h1>
        <div><strong>Task:</strong> {self.task_description}</div>
        <div><strong>Duration:</strong> {duration:.1f}s | <strong>Status:</strong> {"✅ Completed" if self.completed else "❌ Not Completed"}</div>
    </div>
    <div class="screen-info">
        📐 <strong>Screen:</strong> {screen_width}x{screen_height} | <strong>Lux:</strong> {LUX_REF_WIDTH}x{LUX_REF_HEIGHT} | <strong>Y Scale:</strong> {scale_y:.3f}
    </div>
'''
        
        for step in self.steps:
            step_class = "success" if step.success else "error"
            html += f'''
    <div class="step {step_class}">
        <span class="step-num">Step {step.step_num}</span>
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
                        coords_html = f'LUX: <span class="original">({lux_coords["x"]}, {lux_coords["y"]})</span> → Scaled: <span class="scaled">({scaled_coords["x"]}, {scaled_coords["y"]})</span>'
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
            "needs_resize": (w != LUX_REF_WIDTH or h != LUX_REF_HEIGHT),
            "source": "pyautogui"
        }
    except:
        return {"width": 1920, "height": 1080, "source": "error"}

# ============================================================
# PYDANTIC MODELS
# ============================================================
class TaskRequest(BaseModel):
    api_key: str
    task_description: str
    mode: str = "actor"
    model: str = "lux-actor-1"
    max_steps: int = 20
    start_url: Optional[str] = None
    todos: Optional[List[str]] = None
    drag_duration: float = 0.5
    scroll_amount: int = 30
    wait_duration: float = 1.0
    action_pause: float = 0.1
    step_delay: float = 0.3
    enable_analysis: bool = True
    enable_scaling: bool = True
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
        "is_running": is_running,
        "current_task": current_task,
        "screen": screen_info
    }

@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    """Main execution endpoint"""
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
        logger.log(f"Max Steps: {request.max_steps}")
        logger.log(f"Start URL: {request.start_url}")
        logger.log(f"Screenshot Resize: {request.enable_screenshot_resize}")
        logger.log(f"Coordinate Scaling: {request.enable_scaling}")
        
        os.environ["OAGI_API_KEY"] = request.api_key
        
        if request.start_url:
            open_browser_with_url(request.start_url)
        
        result, execution_report = await execute_with_manual_control(request)
        result.execution_report = execution_report
        
        logger.log(f"Task completed: success={result.success}")
        return result
        
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
# RESIZED SCREENSHOT MAKER
# ============================================================
class ResizedScreenshotMaker:
    def __init__(self):
        self.base_maker = AsyncScreenshotMaker()
        if PYAUTOGUI_AVAILABLE:
            self.screen_width, self.screen_height = pyautogui.size()
        else:
            self.screen_width, self.screen_height = LUX_REF_WIDTH, LUX_REF_HEIGHT
        self.needs_resize = (self.screen_width != LUX_REF_WIDTH or self.screen_height != LUX_REF_HEIGHT)
        if self.needs_resize:
            debug_log(f"📸 ResizedScreenshotMaker: {self.screen_width}x{self.screen_height} → {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
    
    async def __call__(self):
        screenshot = await self.base_maker()
        if not self.needs_resize or not PIL_AVAILABLE:
            return screenshot
        try:
            pil_image = screenshot.to_pil()
            resized = pil_image.resize((LUX_REF_WIDTH, LUX_REF_HEIGHT), Image.LANCZOS)
            debug_log(f"📸 Resized: {pil_image.size} → {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
            return PILImage(resized)
        except Exception as e:
            debug_log(f"Resize failed: {e}", "ERROR")
            return screenshot

def scale_coordinates(x: int, y: int, screen_width: int, screen_height: int) -> tuple:
    """Scale coordinates from LUX reference (1920x1080) to actual screen"""
    return int(x * screen_width / LUX_REF_WIDTH), int(y * screen_height / LUX_REF_HEIGHT)

# ============================================================
# MANUAL CONTROL EXECUTION - Captures Reasoning
# ============================================================
async def execute_with_manual_control(request: TaskRequest) -> tuple[TaskResponse, Optional[str]]:
    """Execute with manual step control to capture reasoning"""
    logger.log("Manual Control execution with reasoning capture")
    
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
        screen_width, screen_height = LUX_REF_WIDTH, LUX_REF_HEIGHT
    
    logger.log(f"Screen: {screen_width}x{screen_height}, Scale Y: {screen_height/LUX_REF_HEIGHT:.3f}")
    
    # Create components
    screenshot_maker = ResizedScreenshotMaker() if request.enable_screenshot_resize else AsyncScreenshotMaker()
    pyautogui_config = PyautoguiConfig(
        drag_duration=request.drag_duration, 
        scroll_amount=request.scroll_amount, 
        wait_duration=request.wait_duration, 
        action_pause=request.action_pause
    )
    base_action_handler = AsyncPyautoguiActionHandler(config=pyautogui_config)
    
    history = ExecutionHistory(request.task_description)
    completed = False
    
    try:
        async with AsyncActor(api_key=request.api_key, model=model) as actor:
            await actor.init_task(request.task_description)
            logger.log(f"Task initialized")
            
            for step_num in range(1, request.max_steps + 1):
                step_record = StepRecord(step_num)
                logger.log(f"{'='*50}")
                logger.log(f"STEP {step_num}/{request.max_steps}")
                logger.log(f"{'='*50}")
                
                # Screenshot before
                step_record.screenshot_before = debug_screenshot(f"step_{step_num}_before")
                
                # Get image for Lux
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
                            
                            if request.enable_scaling:
                                x_scaled, y_scaled = scale_coordinates(x_lux, y_lux, screen_width, screen_height)
                                action_data["scaled_coords"] = {"x": x_scaled, "y": y_scaled}
                                logger.log(f"   🎯 Click: LUX ({x_lux}, {y_lux}) → Scaled ({x_scaled}, {y_scaled})")
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
                
                # Execute actions
                try:
                    if request.enable_scaling and PYAUTOGUI_AVAILABLE:
                        for action in actions:
                            action_type = str(action.type.value) if hasattr(action.type, "value") else str(action.type)
                            argument = str(action.argument) if hasattr(action, "argument") else ""
                            
                            if action_type == "click":
                                coords = argument.replace(" ", "").split(",")
                                x_lux, y_lux = int(coords[0]), int(coords[1])
                                x_scaled, y_scaled = scale_coordinates(x_lux, y_lux, screen_width, screen_height)
                                logger.log(f"   🖱️ Click at ({x_scaled}, {y_scaled})")
                                pyautogui.click(x_scaled, y_scaled)
                                time.sleep(0.1)
                            elif action_type == "drag":
                                parts = argument.replace(" ", "").split(",")
                                if len(parts) >= 4:
                                    x1, y1 = int(parts[0]), int(parts[1])
                                    x2, y2 = int(parts[2]), int(parts[3])
                                    x1_s, y1_s = scale_coordinates(x1, y1, screen_width, screen_height)
                                    x2_s, y2_s = scale_coordinates(x2, y2, screen_width, screen_height)
                                    pyautogui.moveTo(x1_s, y1_s)
                                    pyautogui.drag(x2_s - x1_s, y2_s - y1_s, duration=0.5)
                                else:
                                    await base_action_handler([action])
                            else:
                                await base_action_handler([action])
                    else:
                        await base_action_handler(actions)
                    
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
                logger.log(f"⚠️ Max steps ({request.max_steps}) reached")
        
        # Generate report
        history.finish(completed)
        report_dir = ANALYSIS_DIR / f"execution_{int(time.time())}"
        execution_report = history.generate_report(report_dir)
        logger.log(f"📊 Report: {execution_report}")
        
        return TaskResponse(
            success=completed,
            message="Completed" if completed else "Max steps reached",
            completed_todos=1 if completed else 0,
            total_todos=1,
            execution_summary={"model": model, "steps": len(history.steps), "completed": completed}
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
    
    async with AsyncActor(api_key=api_key, model=request.get("model", "lux-actor-1")) as actor:
        await actor.init_task(instruction)
        screenshot_maker = ResizedScreenshotMaker()
        image = await screenshot_maker()
        step = await actor.step(image)
        
        reasoning = getattr(step, "reason", None) or getattr(step, "reasoning", None)
        actions_data = [
            {"type": str(a.type.value) if hasattr(a.type, "value") else str(a.type), "argument": str(getattr(a, "argument", ""))} 
            for a in (step.actions or [])
        ]
        
        return {"stop": getattr(step, "stop", False), "reasoning": reasoning, "actions": actions_data}

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
    """Get screen info"""
    return debug_screen_info()

@app.post("/debug/screenshot")
async def capture_debug_screenshot(label: str = "manual"):
    """Capture debug screenshot"""
    path = debug_screenshot(f"manual_{label}")
    return {"success": path is not None, "path": path}

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    import uvicorn
    
    screen_info = debug_screen_info()
    print(f"\n{'='*60}")
    print(f"  TASKER SERVICE v{SERVICE_VERSION}")
    print(f"  Manual Control + Reasoning Capture")
    print(f"{'='*60}")
    print(f"  OAGI: {'✅' if OAGI_AVAILABLE else '❌'}  PIL: {'✅' if PIL_AVAILABLE else '❌'}  PyAutoGUI: {'✅' if PYAUTOGUI_AVAILABLE else '❌'}")
    print(f"  Screen: {screen_info['width']}x{screen_info['height']} | Lux: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
    if screen_info.get("needs_resize"):
        print(f"  ⚠️  Screenshot resize REQUIRED | Scale Y: {screen_info['scale_y']:.3f}")
    print(f"{'='*60}")
    print(f"  http://127.0.0.1:{SERVICE_PORT}")
    print(f"  Reports: {ANALYSIS_DIR}/execution_<timestamp>/")
    print(f"{'='*60}\n")
    
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT, log_level="info")
