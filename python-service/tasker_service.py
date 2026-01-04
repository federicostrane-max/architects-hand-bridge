"""
Tasker Service v6.0.1 - Multi-provider Computer Use
====================================================
Supports:
- Lux (actor/thinker/tasker) via OAGI SDK + PyAutoGUI
- Gemini Computer Use via Playwright (official Google implementation)

Based on:
- Original v5.7.2 Lux implementation
- Official Google repo: github.com/google-gemini/computer-use-preview
"""

import asyncio
import io
import os
import sys
import subprocess
import time
import webbrowser
import json
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ============================================================================
# OAGI SDK (for Lux)
# ============================================================================
OAGI_AVAILABLE = False
OAGI_IMPORT_ERROR = None
ASYNC_AGENT_OBSERVER_AVAILABLE = False

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
    print(f"⚠️ OAGI SDK failed: {e}")

# Try to import AsyncAgentObserver (may be in different location)
try:
    from oagi.agent.observer import AsyncAgentObserver
    ASYNC_AGENT_OBSERVER_AVAILABLE = True
    print("✅ AsyncAgentObserver loaded")
except ImportError:
    print("ℹ️ AsyncAgentObserver not available (optional)")

# ============================================================================
# GEMINI SDK
# ============================================================================
GEMINI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    from google.genai.types import (
        Part,
        GenerateContentConfig,
        Content,
        Candidate,
        FunctionResponse,
        FinishReason,
    )
    GEMINI_AVAILABLE = True
    print("✅ Gemini SDK loaded")
except ImportError as e:
    print(f"⚠️ Gemini SDK not available: {e}")

# ============================================================================
# PLAYWRIGHT (for Gemini)
# ============================================================================
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, Page
    import playwright.sync_api
    PLAYWRIGHT_AVAILABLE = True
    print("✅ Playwright loaded")
except ImportError as e:
    print(f"⚠️ Playwright not available: {e}")

# ============================================================================
# PIL
# ============================================================================
PIL_AVAILABLE = False
try:
    from PIL import Image
    PIL_AVAILABLE = True
    print("✅ PIL loaded")
except ImportError:
    print("⚠️ PIL not available")

# ============================================================================
# PYAUTOGUI (for Lux)
# ============================================================================
PYAUTOGUI_AVAILABLE = False
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
    PYAUTOGUI_AVAILABLE = True
    print("✅ PyAutoGUI loaded")
except ImportError:
    print("⚠️ PyAutoGUI not available")

# ============================================================================
# PYPERCLIP
# ============================================================================
PYPERCLIP_AVAILABLE = False
try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
    print("✅ Pyperclip loaded")
except ImportError:
    print("⚠️ Pyperclip not available")

# ============================================================================
# CONFIGURATION
# ============================================================================
SERVICE_VERSION = "6.0.1"
SERVICE_PORT = 8765
DEBUG_LOGS_DIR = Path("debug_logs")
ANALYSIS_DIR = Path("lux_analysis")
DEBUG_LOGS_DIR.mkdir(exist_ok=True)
ANALYSIS_DIR.mkdir(exist_ok=True)

# Lux resolution (from SDK ImageConfig)
LUX_REF_WIDTH = 1260
LUX_REF_HEIGHT = 700

# Gemini resolution (from official Google repo)
GEMINI_REF_WIDTH = 1440
GEMINI_REF_HEIGHT = 900
GEMINI_MODEL = "gemini-2.5-computer-use-preview-10-2025"
MAX_RECENT_TURNS_WITH_SCREENSHOTS = 3

# Predefined Computer Use functions (from official Google repo)
PREDEFINED_COMPUTER_USE_FUNCTIONS = [
    "open_web_browser", "click_at", "hover_at", "type_text_at",
    "scroll_document", "scroll_at", "wait_5_seconds", "go_back",
    "go_forward", "search", "navigate", "key_combination", "drag_and_drop",
]

# Playwright key mapping (from official Google repo)
PLAYWRIGHT_KEY_MAP = {
    "backspace": "Backspace", "tab": "Tab", "return": "Enter", "enter": "Enter",
    "shift": "Shift", "control": "ControlOrMeta", "alt": "Alt", "escape": "Escape",
    "space": "Space", "pageup": "PageUp", "pagedown": "PageDown", "end": "End",
    "home": "Home", "left": "ArrowLeft", "up": "ArrowUp", "right": "ArrowRight",
    "down": "ArrowDown", "insert": "Insert", "delete": "Delete", "semicolon": ";",
    "equals": "=", "multiply": "Multiply", "add": "Add", "separator": "Separator",
    "subtract": "Subtract", "decimal": "Decimal", "divide": "Divide",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6",
    "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
    "command": "Meta", "meta": "Meta", "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight", "arrowup": "ArrowUp", "arrowdown": "ArrowDown",
}

# Thread pool for Playwright
executor = ThreadPoolExecutor(max_workers=2)

# ============================================================================
# MODELS
# ============================================================================
class ExecuteRequest(BaseModel):
    api_key: str
    task_description: str
    mode: str = "actor"  # actor, thinker, tasker, gemini
    max_steps_per_todo: int = 15
    start_url: Optional[str] = None
    todos: Optional[List[str]] = None  # For Lux tasker mode
    headless: bool = False  # For Gemini
    highlight_mouse: bool = False  # For Gemini

class StatusResponse(BaseModel):
    status: str
    version: str
    oagi_available: bool
    gemini_available: bool
    playwright_available: bool
    modes: List[str]

class ExecuteResponse(BaseModel):
    success: bool
    message: str
    steps_executed: int = 0
    final_url: Optional[str] = None
    report_path: Optional[str] = None
    error: Optional[str] = None

@dataclass
class EnvState:
    """Environment state for Gemini (from Google repo)"""
    screenshot: bytes
    url: str

# ============================================================================
# LOGGING
# ============================================================================
DEBUG_SCREENSHOTS_DIR = DEBUG_LOGS_DIR / "screenshots"
DEBUG_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
_debug_step_counter = 0

def debug_log(message: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{level}] {message}")

def debug_screenshot(prefix: str = "screenshot") -> Optional[str]:
    global _debug_step_counter
    _debug_step_counter += 1
    if not PYAUTOGUI_AVAILABLE:
        return None
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{_debug_step_counter:03d}_{prefix}_{timestamp}.png"
        filepath = DEBUG_SCREENSHOTS_DIR / filename
        pyautogui.screenshot().save(filepath)
        return str(filepath)
    except:
        return None

# ============================================================================
# EXECUTION HISTORY (shared)
# ============================================================================
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
            "reasoning": self.reasoning,
            "actions": self.actions,
            "screenshot_before": self.screenshot_before,
            "screenshot_after": self.screenshot_after,
            "success": self.success,
            "error": self.error,
            "stop": self.stop
        }

class ExecutionHistory:
    def __init__(self, task_description: str, mode: str, todos: Optional[List[str]] = None):
        self.task_description = task_description
        self.mode = mode
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
            "mode": self.mode,
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
        
        if self.mode == "gemini":
            ref_width, ref_height = GEMINI_REF_WIDTH, GEMINI_REF_HEIGHT
            control_method = "Playwright (browser-level)"
        else:
            ref_width, ref_height = LUX_REF_WIDTH, LUX_REF_HEIGHT
            control_method = "PyAutoGUI (OS-level)"

        if PYAUTOGUI_AVAILABLE:
            screen_width, screen_height = pyautogui.size()
            scale_x = screen_width / ref_width
            scale_y = screen_height / ref_height
        else:
            screen_width, screen_height = 1920, 1080
            scale_x = scale_y = 1.0

        duration = (self.end_time - self.start_time).total_seconds() if self.end_time else 0

        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Execution Report - {self.mode.upper()}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .header h1 {{ margin: 0; color: white; }}
        .mode-badge {{ display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; margin-left: 10px; }}
        .mode-gemini {{ background: #4285f4; }}
        .mode-lux {{ background: #00d4aa; }}
        .info-box {{ background: #16213e; padding: 15px; border-radius: 8px; margin-bottom: 15px; }}
        .step {{ background: #16213e; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #667eea; }}
        .step.success {{ border-left-color: #00d4aa; }}
        .step.error {{ border-left-color: #ff6b6b; }}
        .reasoning {{ background: #0f0f23; padding: 10px; border-radius: 5px; margin: 10px 0; font-style: italic; color: #a0a0a0; }}
        .action {{ background: #0f0f23; padding: 8px; border-radius: 4px; margin: 5px 0; font-family: monospace; }}
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
        .stat {{ background: #16213e; padding: 15px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 24px; color: #667eea; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Execution Report 
            <span class="mode-badge mode-{self.mode}">{self.mode.upper()}</span>
        </h1>
        <p><strong>Task:</strong> {self.task_description}</p>
    </div>
    
    <div class="info-box">
        <p><strong>Control Method:</strong> {control_method}</p>
        <p><strong>Reference Resolution:</strong> {ref_width}×{ref_height}</p>
        <p><strong>Screen:</strong> {screen_width}×{screen_height} | Scale: {scale_x:.2f}x, {scale_y:.2f}x</p>
    </div>
    
    <div class="stats">
        <div class="stat"><div class="stat-value">{len(self.steps)}</div><div>Steps</div></div>
        <div class="stat"><div class="stat-value">{duration:.1f}s</div><div>Duration</div></div>
        <div class="stat"><div class="stat-value">{"✓" if self.completed else "✗"}</div><div>Status</div></div>
        <div class="stat"><div class="stat-value">{self.mode}</div><div>Provider</div></div>
    </div>
    
    <h2>Execution Timeline</h2>
'''
        for step in self.steps:
            step_class = "success" if step.success else "error"
            reasoning_html = f'<div class="reasoning">{step.reasoning}</div>' if step.reasoning else ""
            actions_html = "".join([f'<div class="action">{json.dumps(a)}</div>' for a in step.actions])
            
            html += f'''
    <div class="step {step_class}">
        <strong>Step {step.step_num}</strong> - {step.timestamp}
        {reasoning_html}
        {actions_html}
    </div>
'''
        
        html += f'''
    <div class="info-box">
        <strong>Final:</strong> {"Completed" if self.completed else self.final_error or "Unknown"}
    </div>
</body>
</html>'''

        report_path = output_dir / "execution_report.html"
        report_path.write_text(html, encoding="utf-8")

        json_path = output_dir / "execution_history.json"
        json_path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

        return str(report_path)

# ============================================================================
# LUX UTILITIES
# ============================================================================
def type_via_clipboard(text: str):
    """Type text via clipboard (handles Unicode)"""
    if not PYPERCLIP_AVAILABLE or not PYAUTOGUI_AVAILABLE:
        return
    original = pyperclip.paste()
    try:
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
    finally:
        try:
            pyperclip.copy(original)
        except:
            pass

# ============================================================================
# PLAYWRIGHT COMPUTER (from official Google repo)
# ============================================================================
class PlaywrightComputer:
    """Playwright-based browser control for Gemini Computer Use"""
    
    def __init__(
        self,
        screen_size: tuple = (GEMINI_REF_WIDTH, GEMINI_REF_HEIGHT),
        initial_url: str = "https://www.google.com",
        search_engine_url: str = "https://www.google.com",
        headless: bool = False,
        highlight_mouse: bool = False,
    ):
        self._initial_url = initial_url
        self._screen_size = screen_size
        self._search_engine_url = search_engine_url
        self._headless = headless
        self._highlight_mouse = highlight_mouse
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _handle_new_page(self, new_page):
        """Handle new tabs - redirect to current page"""
        new_url = new_page.url
        new_page.close()
        self._page.goto(new_url)

    def __enter__(self):
        print("🌐 Creating Playwright browser session...")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            args=[
                "--disable-extensions", "--disable-file-system", "--disable-plugins",
                "--disable-dev-shm-usage", "--disable-background-networking",
                "--disable-default-apps", "--disable-sync",
            ],
            headless=self._headless,
        )
        self._context = self._browser.new_context(
            viewport={"width": self._screen_size[0], "height": self._screen_size[1]}
        )
        self._page = self._context.new_page()
        self._page.goto(self._initial_url)
        self._context.on("page", self._handle_new_page)
        print(f"✅ Playwright browser started at {self._initial_url}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        try:
            if self._browser:
                self._browser.close()
        except Exception as e:
            if "Connection closed" not in str(e):
                raise
        if self._playwright:
            self._playwright.stop()
        print("🔴 Playwright browser closed")

    def screen_size(self) -> tuple:
        viewport = self._page.viewport_size
        return (viewport["width"], viewport["height"]) if viewport else self._screen_size

    def current_state(self) -> EnvState:
        self._page.wait_for_load_state()
        time.sleep(0.5)
        screenshot_bytes = self._page.screenshot(type="png", full_page=False)
        return EnvState(screenshot=screenshot_bytes, url=self._page.url)

    def open_web_browser(self) -> EnvState:
        return self.current_state()

    def click_at(self, x: int, y: int) -> EnvState:
        self._highlight_position(x, y)
        self._page.mouse.click(x, y)
        self._page.wait_for_load_state()
        return self.current_state()

    def hover_at(self, x: int, y: int) -> EnvState:
        self._highlight_position(x, y)
        self._page.mouse.move(x, y)
        self._page.wait_for_load_state()
        return self.current_state()

    def type_text_at(self, x: int, y: int, text: str, press_enter: bool = False, clear_before_typing: bool = True) -> EnvState:
        self._highlight_position(x, y)
        self._page.mouse.click(x, y)
        self._page.wait_for_load_state()
        if clear_before_typing:
            self.key_combination(["Control", "A"] if sys.platform != "darwin" else ["Command", "A"])
            self.key_combination(["Delete"])
        self._page.keyboard.type(text)
        self._page.wait_for_load_state()
        if press_enter:
            self.key_combination(["Enter"])
        self._page.wait_for_load_state()
        return self.current_state()

    def scroll_document(self, direction: str) -> EnvState:
        if direction == "down":
            return self.key_combination(["PageDown"])
        elif direction == "up":
            return self.key_combination(["PageUp"])
        elif direction in ("left", "right"):
            amount = self.screen_size()[0] // 2
            sign = "-" if direction == "left" else ""
            self._page.evaluate(f"window.scrollBy({sign}{amount}, 0);")
            self._page.wait_for_load_state()
            return self.current_state()
        raise ValueError(f"Unsupported direction: {direction}")

    def scroll_at(self, x: int, y: int, direction: str, magnitude: int = 800) -> EnvState:
        self._highlight_position(x, y)
        self._page.mouse.move(x, y)
        self._page.wait_for_load_state()
        dx, dy = 0, 0
        if direction == "up": dy = -magnitude
        elif direction == "down": dy = magnitude
        elif direction == "left": dx = -magnitude
        elif direction == "right": dx = magnitude
        self._page.mouse.wheel(dx, dy)
        self._page.wait_for_load_state()
        return self.current_state()

    def wait_5_seconds(self) -> EnvState:
        time.sleep(5)
        return self.current_state()

    def go_back(self) -> EnvState:
        self._page.go_back()
        self._page.wait_for_load_state()
        return self.current_state()

    def go_forward(self) -> EnvState:
        self._page.go_forward()
        self._page.wait_for_load_state()
        return self.current_state()

    def search(self) -> EnvState:
        return self.navigate(self._search_engine_url)

    def navigate(self, url: str) -> EnvState:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._page.goto(url)
        self._page.wait_for_load_state()
        return self.current_state()

    def key_combination(self, keys: list) -> EnvState:
        keys = [PLAYWRIGHT_KEY_MAP.get(k.lower(), k) for k in keys]
        for key in keys[:-1]:
            self._page.keyboard.down(key)
        self._page.keyboard.press(keys[-1])
        for key in reversed(keys[:-1]):
            self._page.keyboard.up(key)
        return self.current_state()

    def drag_and_drop(self, x: int, y: int, destination_x: int, destination_y: int) -> EnvState:
        self._highlight_position(x, y)
        self._page.mouse.move(x, y)
        self._page.wait_for_load_state()
        self._page.mouse.down()
        self._page.wait_for_load_state()
        self._highlight_position(destination_x, destination_y)
        self._page.mouse.move(destination_x, destination_y)
        self._page.wait_for_load_state()
        self._page.mouse.up()
        return self.current_state()

    def _highlight_position(self, x: int, y: int):
        if not self._highlight_mouse:
            return
        self._page.evaluate(f"""
        () => {{
            const div = document.createElement('div');
            div.style.pointerEvents = 'none';
            div.style.border = '4px solid red';
            div.style.borderRadius = '50%';
            div.style.width = '20px';
            div.style.height = '20px';
            div.style.position = 'fixed';
            div.style.zIndex = '9999';
            div.style.left = {x} - 10 + 'px';
            div.style.top = {y} - 10 + 'px';
            document.body.appendChild(div);
            setTimeout(() => div.remove(), 2000);
        }}
        """)
        time.sleep(0.5)

# ============================================================================
# GEMINI BROWSER AGENT (from official Google repo)
# ============================================================================
class GeminiBrowserAgent:
    """Gemini Computer Use Agent using Playwright"""
    
    def __init__(self, browser_computer: PlaywrightComputer, api_key: str, task: str, max_steps: int = 15):
        self._browser = browser_computer
        self._api_key = api_key
        self._task = task
        self._max_steps = max_steps
        self.final_reasoning: Optional[str] = None
        self.history = ExecutionHistory(task, "gemini")
        
        self.screenshot_dir = DEBUG_SCREENSHOTS_DIR
        self._client = genai.Client(api_key=api_key)
        self._contents: List[Content] = [Content(role="user", parts=[Part(text=self._task)])]
        self._config = GenerateContentConfig(
            temperature=1, top_p=0.95, top_k=40, max_output_tokens=8192,
            tools=[types.Tool(computer_use=types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER))]
        )

    def denormalize_x(self, x: int) -> int:
        return int(x / 1000 * self._browser.screen_size()[0])

    def denormalize_y(self, y: int) -> int:
        return int(y / 1000 * self._browser.screen_size()[1])

    def _save_screenshot(self, screenshot_bytes: bytes) -> str:
        timestamp = datetime.now().strftime("%H%M%S_%f")
        path = self.screenshot_dir / f"gemini_{timestamp}.png"
        path.write_bytes(screenshot_bytes)
        return str(path)

    def handle_action(self, action: types.FunctionCall) -> EnvState:
        name = action.name
        args = dict(action.args) if action.args else {}
        print(f"  → Executing: {name}")

        if name == "open_web_browser":
            return self._browser.open_web_browser()
        elif name == "click_at":
            return self._browser.click_at(self.denormalize_x(args["x"]), self.denormalize_y(args["y"]))
        elif name == "hover_at":
            return self._browser.hover_at(self.denormalize_x(args["x"]), self.denormalize_y(args["y"]))
        elif name == "type_text_at":
            return self._browser.type_text_at(
                self.denormalize_x(args["x"]), self.denormalize_y(args["y"]),
                args["text"], args.get("press_enter", False), args.get("clear_before_typing", True)
            )
        elif name == "scroll_document":
            return self._browser.scroll_document(args["direction"])
        elif name == "scroll_at":
            magnitude = args.get("magnitude", 800)
            direction = args["direction"]
            if direction in ("up", "down"):
                magnitude = self.denormalize_y(magnitude)
            else:
                magnitude = self.denormalize_x(magnitude)
            return self._browser.scroll_at(
                self.denormalize_x(args["x"]), self.denormalize_y(args["y"]), direction, magnitude
            )
        elif name == "wait_5_seconds":
            return self._browser.wait_5_seconds()
        elif name == "go_back":
            return self._browser.go_back()
        elif name == "go_forward":
            return self._browser.go_forward()
        elif name == "search":
            return self._browser.search()
        elif name == "navigate":
            return self._browser.navigate(args["url"])
        elif name == "key_combination":
            return self._browser.key_combination(args["keys"].split("+"))
        elif name == "drag_and_drop":
            return self._browser.drag_and_drop(
                self.denormalize_x(args["x"]), self.denormalize_y(args["y"]),
                self.denormalize_x(args["destination_x"]), self.denormalize_y(args["destination_y"])
            )
        else:
            print(f"  ⚠️ Unknown action: {name}")
            return self._browser.current_state()

    def get_text(self, candidate: Candidate) -> Optional[str]:
        if not candidate.content or not candidate.content.parts:
            return None
        texts = [p.text for p in candidate.content.parts if p.text]
        return " ".join(texts) or None

    def extract_function_calls(self, candidate: Candidate) -> List[types.FunctionCall]:
        if not candidate.content or not candidate.content.parts:
            return []
        return [p.function_call for p in candidate.content.parts if p.function_call]

    def run_one_iteration(self) -> Literal["COMPLETE", "CONTINUE"]:
        try:
            response = self._client.models.generate_content(
                model=GEMINI_MODEL, contents=self._contents, config=self._config
            )
        except Exception as e:
            print(f"  ❌ Gemini API error: {e}")
            return "COMPLETE"

        if not response.candidates:
            print("  ❌ No candidates")
            return "COMPLETE"

        candidate = response.candidates[0]
        if candidate.content:
            self._contents.append(candidate.content)

        reasoning = self.get_text(candidate)
        function_calls = self.extract_function_calls(candidate)

        if reasoning:
            print(f"  💭 {reasoning[:150]}...")

        if not function_calls and not reasoning and candidate.finish_reason == FinishReason.MALFORMED_FUNCTION_CALL:
            return "CONTINUE"

        if not function_calls:
            print(f"  ✅ Task complete: {reasoning}")
            self.final_reasoning = reasoning
            return "COMPLETE"

        function_responses = []
        for fc in function_calls:
            extra_fields = {}
            if fc.args and (safety := fc.args.get("safety_decision")):
                if safety.get("decision") == "require_confirmation":
                    print(f"  ⚠️ Safety check: {safety.get('explanation', 'N/A')}")
                extra_fields["safety_acknowledgement"] = "true"

            env_state = self.handle_action(fc)
            screenshot_path = self._save_screenshot(env_state.screenshot)

            step = StepRecord(len(self.history.steps) + 1)
            step.reasoning = reasoning
            step.actions = [{"type": fc.name, "args": dict(fc.args) if fc.args else {}}]
            step.screenshot_after = screenshot_path
            step.success = True
            self.history.add_step(step)

            function_responses.append(
                FunctionResponse(
                    name=fc.name,
                    response={"url": env_state.url, **extra_fields},
                    parts=[types.FunctionResponsePart(
                        inline_data=types.FunctionResponseBlob(mime_type="image/png", data=env_state.screenshot)
                    )]
                )
            )

        self._contents.append(Content(role="user", parts=[Part(function_response=fr) for fr in function_responses]))
        self._cleanup_old_screenshots()
        return "CONTINUE"

    def _cleanup_old_screenshots(self):
        turns_found = 0
        for content in reversed(self._contents):
            if content.role == "user" and content.parts:
                has_screenshot = any(
                    p.function_response and p.function_response.parts and
                    p.function_response.name in PREDEFINED_COMPUTER_USE_FUNCTIONS
                    for p in content.parts
                )
                if has_screenshot:
                    turns_found += 1
                    if turns_found > MAX_RECENT_TURNS_WITH_SCREENSHOTS:
                        for p in content.parts:
                            if (p.function_response and p.function_response.parts and
                                p.function_response.name in PREDEFINED_COMPUTER_USE_FUNCTIONS):
                                p.function_response.parts = None

    def run(self) -> tuple:
        print(f"\n🤖 Starting Gemini Browser Agent")
        print(f"   Task: {self._task}")
        print(f"   Max steps: {self._max_steps}")

        initial_state = self._browser.current_state()
        self._contents[0].parts.append(
            Part(inline_data=types.Blob(mime_type="image/png", data=initial_state.screenshot))
        )

        steps = 0
        status = "CONTINUE"
        while status == "CONTINUE" and steps < self._max_steps:
            steps += 1
            print(f"\n📍 Step {steps}/{self._max_steps}")
            status = self.run_one_iteration()

        success = self.final_reasoning is not None
        message = self.final_reasoning or f"Reached max steps ({steps})"
        return success, message, steps

# ============================================================================
# LUX EXECUTION (OAGI SDK)
# ============================================================================
async def execute_with_lux(
    api_key: str, task: str, mode: str, max_steps: int,
    start_url: Optional[str], todos: Optional[List[str]] = None
) -> ExecuteResponse:
    """Execute task using OAGI Lux SDK"""
    
    if not OAGI_AVAILABLE:
        return ExecuteResponse(
            success=False, message="OAGI SDK not available",
            error=OAGI_IMPORT_ERROR or "oagi package not installed"
        )

    history = ExecutionHistory(task, mode, todos)

    try:
        if start_url:
            webbrowser.open(start_url)
            await asyncio.sleep(2)

        # Image config for Lux
        image_config = ImageConfig(format="JPEG", quality=85, width=LUX_REF_WIDTH, height=LUX_REF_HEIGHT)
        image_provider = AsyncScreenshotMaker(config=image_config)
        action_handler = AsyncPyautoguiActionHandler()

        if mode == "tasker" and todos:
            # TaskerAgent mode with todos
            observer = AsyncAgentObserver() if ASYNC_AGENT_OBSERVER_AVAILABLE else None
            
            tasker = TaskerAgent(
                api_key=api_key,
                base_url="https://api.agiopen.org",
                model="lux-actor-1",
                max_steps=max_steps,
                temperature=0.0,
                step_observer=observer,
            )
            tasker.set_task(task=task, todos=todos)
            
            success = await tasker.execute(
                instruction="",
                action_handler=action_handler,
                image_provider=image_provider,
            )
            
            history.finish(success, completed_todos=len(todos) if success else 0)

        else:
            # AsyncActor mode
            model = "lux-thinker-1" if mode == "thinker" else "lux-actor-1"
            
            actor = AsyncActor(
                api_key=api_key,
                base_url="https://api.agiopen.org",
                model=model,
                max_steps=max_steps,
            )
            
            step_count = 0
            async for step in actor.run(
                instruction=task,
                action_handler=action_handler,
                image_provider=image_provider,
            ):
                step_count += 1
                record = StepRecord(step_count)
                record.reasoning = getattr(step, 'reasoning', None)
                record.success = True
                history.add_step(record)
            
            history.finish(True)

        report_dir = ANALYSIS_DIR / f"{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        report_path = history.generate_report(report_dir)

        return ExecuteResponse(
            success=True,
            message=f"Task completed with {mode}",
            steps_executed=len(history.steps),
            report_path=report_path
        )

    except Exception as e:
        history.finish(False, str(e))
        debug_log(f"Lux execution error: {e}", "ERROR")
        return ExecuteResponse(success=False, message="Execution failed", error=str(e))

# ============================================================================
# GEMINI EXECUTION (Playwright)
# ============================================================================
def _run_gemini_sync(api_key: str, task: str, max_steps: int, start_url: str, headless: bool, highlight_mouse: bool) -> ExecuteResponse:
    """Run Gemini agent synchronously"""
    computer = PlaywrightComputer(
        screen_size=(GEMINI_REF_WIDTH, GEMINI_REF_HEIGHT),
        initial_url=start_url,
        headless=headless,
        highlight_mouse=highlight_mouse,
    )
    
    with computer as browser:
        agent = GeminiBrowserAgent(browser_computer=browser, api_key=api_key, task=task, max_steps=max_steps)
        success, message, steps = agent.run()
        
        agent.history.finish(success, None if success else message)
        report_dir = ANALYSIS_DIR / f"gemini_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        report_path = agent.history.generate_report(report_dir)
        
        return ExecuteResponse(
            success=success, message=message, steps_executed=steps,
            final_url=browser._page.url if browser._page else None,
            report_path=report_path
        )

async def execute_with_gemini(api_key: str, task: str, max_steps: int, start_url: Optional[str], headless: bool = False, highlight_mouse: bool = False) -> ExecuteResponse:
    """Execute task using Gemini + Playwright"""
    if not GEMINI_AVAILABLE:
        return ExecuteResponse(success=False, message="Gemini SDK not available", error="google-genai not installed")
    if not PLAYWRIGHT_AVAILABLE:
        return ExecuteResponse(success=False, message="Playwright not available", error="Run: pip install playwright && playwright install chromium")
    
    url = start_url or "https://www.google.com"
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _run_gemini_sync, api_key, task, max_steps, url, headless, highlight_mouse)

# ============================================================================
# FASTAPI APPLICATION
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "="*60)
    print(f"🚀 TASKER SERVICE v{SERVICE_VERSION}")
    print("="*60)
    print(f"OAGI SDK:    {'✅ Available' if OAGI_AVAILABLE else '❌ Not available'}")
    print(f"Gemini SDK:  {'✅ Available' if GEMINI_AVAILABLE else '❌ Not available'}")
    print(f"Playwright:  {'✅ Available' if PLAYWRIGHT_AVAILABLE else '❌ Not available'}")
    print("\nSUPPORTED MODES:")
    if OAGI_AVAILABLE:
        print("  • actor   - Lux AsyncActor (PyAutoGUI)")
        print("  • thinker - Lux AsyncActor (PyAutoGUI)")
        print("  • tasker  - Lux TaskerAgent (PyAutoGUI)")
    if GEMINI_AVAILABLE and PLAYWRIGHT_AVAILABLE:
        print("  • gemini  - Google Gemini Computer Use (Playwright)")
    print("="*60 + "\n")
    yield
    executor.shutdown(wait=False)
    print("Shutting down...")

app = FastAPI(title="Tasker Service", version=SERVICE_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/status", response_model=StatusResponse)
async def get_status():
    modes = []
    if OAGI_AVAILABLE:
        modes.extend(["actor", "thinker", "tasker"])
    if GEMINI_AVAILABLE and PLAYWRIGHT_AVAILABLE:
        modes.append("gemini")
    return StatusResponse(
        status="running", version=SERVICE_VERSION,
        oagi_available=OAGI_AVAILABLE, gemini_available=GEMINI_AVAILABLE,
        playwright_available=PLAYWRIGHT_AVAILABLE, modes=modes
    )

@app.post("/execute", response_model=ExecuteResponse)
async def execute_task(request: ExecuteRequest):
    debug_log(f"Received task: {request.task_description[:100]}...")
    debug_log(f"Mode: {request.mode}")
    
    if request.mode == "gemini":
        if not GEMINI_AVAILABLE:
            raise HTTPException(status_code=400, detail="Gemini SDK not available")
        if not PLAYWRIGHT_AVAILABLE:
            raise HTTPException(status_code=400, detail="Playwright not available")
        return await execute_with_gemini(
            request.api_key, request.task_description, request.max_steps_per_todo,
            request.start_url, request.headless, request.highlight_mouse
        )
    elif request.mode in ["actor", "thinker", "tasker"]:
        if not OAGI_AVAILABLE:
            raise HTTPException(status_code=400, detail="OAGI SDK not available")
        return await execute_with_lux(
            request.api_key, request.task_description, request.mode,
            request.max_steps_per_todo, request.start_url, request.todos
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown mode: {request.mode}")

@app.post("/debug/test_gemini")
async def test_gemini(api_key: str = Query(...)):
    if not GEMINI_AVAILABLE:
        return {"success": False, "error": "Gemini SDK not installed"}
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", contents="Say 'Gemini ready!'")
        return {"success": True, "response": response.text, "computer_use_model": GEMINI_MODEL, "playwright_available": PLAYWRIGHT_AVAILABLE}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/debug/test_playwright")
async def test_playwright():
    if not PLAYWRIGHT_AVAILABLE:
        return {"success": False, "error": "Playwright not installed"}
    try:
        def _test():
            with PlaywrightComputer(headless=True) as browser:
                state = browser.current_state()
                return {"url": state.url, "screenshot_size": len(state.screenshot)}
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, _test)
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT)
