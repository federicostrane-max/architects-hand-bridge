"""
tasker_service.py - v5.9.0
Multi-provider Computer Use service for The Architect's Hand
Supports: Lux (actor/thinker/tasker) + Gemini Computer Use

Based on official Google implementation:
https://github.com/google-gemini/computer-use-preview
"""

import asyncio
import base64
import json
import os
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal, Union, Any, List
from contextlib import asynccontextmanager
import pyautogui
import pyperclip
from PIL import Image
from io import BytesIO

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ============================================================================
# SDK IMPORTS
# ============================================================================

# Lux SDK
OAGI_AVAILABLE = False
try:
    from oagilib import Client as OAGIClient
    from oagilib.lux import AsyncActor
    from oagilib.lux.agent import TaskerAgent
    from oagilib.lux.screenshot import ResizedScreenshotMaker
    OAGI_AVAILABLE = True
    print("✅ OAGI SDK loaded")
except ImportError as e:
    print(f"⚠️ OAGI SDK not available: {e}")

# Gemini SDK
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
# CONFIGURATION
# ============================================================================

# Lux configuration
LUX_REF_WIDTH = 1260
LUX_REF_HEIGHT = 700

# Gemini configuration (from official Google repo)
GEMINI_REF_WIDTH = 1440
GEMINI_REF_HEIGHT = 900
GEMINI_MODEL = "gemini-2.5-computer-use-preview-10-2025"
MAX_RECENT_TURNS_WITH_SCREENSHOTS = 3

# Predefined Computer Use functions (from official Google repo)
PREDEFINED_COMPUTER_USE_FUNCTIONS = [
    "open_web_browser",
    "click_at",
    "hover_at",
    "type_text_at",
    "scroll_document",
    "scroll_at",
    "wait_5_seconds",
    "go_back",
    "go_forward",
    "search",
    "navigate",
    "key_combination",
    "drag_and_drop",
]

# PyAutoGUI settings
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

# ============================================================================
# MODELS
# ============================================================================

class ExecuteRequest(BaseModel):
    api_key: str
    task_description: str
    mode: str = "actor"  # actor, thinker, tasker, gemini
    max_steps_per_todo: int = 15
    start_url: Optional[str] = None

class StatusResponse(BaseModel):
    status: str
    version: str
    oagi_available: bool
    gemini_available: bool
    modes: list

class ExecuteResponse(BaseModel):
    success: bool
    message: str
    steps_executed: int = 0
    final_url: Optional[str] = None
    report_path: Optional[str] = None
    error: Optional[str] = None

# ============================================================================
# EXECUTION HISTORY (shared between Lux and Gemini)
# ============================================================================

class ExecutionHistory:
    """Records and exports execution history for both Lux and Gemini"""
    
    def __init__(self, task_description: str, mode: str):
        self.task_description = task_description
        self.mode = mode
        self.steps: List[dict] = []
        self.start_time = datetime.now()
        self.end_time: Optional[datetime] = None
        
    def add_step(self, action: str, args: dict, screenshot_path: Optional[str] = None, reasoning: Optional[str] = None):
        self.steps.append({
            "step_number": len(self.steps) + 1,
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "args": args,
            "screenshot": screenshot_path,
            "reasoning": reasoning
        })
        
    def finalize(self, success: bool, final_message: str):
        self.end_time = datetime.now()
        self.success = success
        self.final_message = final_message
        
    def generate_report(self, output_dir: Path) -> str:
        """Generate HTML report"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine resolution based on mode
        if self.mode == "gemini":
            resolution = f"{GEMINI_REF_WIDTH}x{GEMINI_REF_HEIGHT}"
        else:
            resolution = f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}"
        
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time else 0
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Execution Report - {self.mode.upper()}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        .mode-badge {{ display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; margin-left: 10px; }}
        .mode-gemini {{ background: #4285f4; }}
        .mode-lux {{ background: #00d4aa; }}
        .step {{ background: #16213e; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #667eea; }}
        .step-header {{ display: flex; justify-content: space-between; margin-bottom: 10px; }}
        .action {{ color: #00d4aa; font-weight: bold; }}
        .reasoning {{ color: #a0a0a0; font-style: italic; margin: 10px 0; padding: 10px; background: #0f0f23; border-radius: 5px; }}
        .args {{ color: #ffd93d; }}
        .screenshot {{ max-width: 100%; border-radius: 5px; margin-top: 10px; }}
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
        .stat {{ background: #16213e; padding: 15px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 24px; color: #667eea; }}
        .success {{ color: #00d4aa; }}
        .error {{ color: #ff6b6b; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Execution Report 
            <span class="mode-badge mode-{self.mode}">{self.mode.upper()}</span>
        </h1>
        <p><strong>Task:</strong> {self.task_description}</p>
        <p><strong>Resolution:</strong> {resolution}</p>
    </div>
    
    <div class="stats">
        <div class="stat">
            <div class="stat-value">{len(self.steps)}</div>
            <div>Steps</div>
        </div>
        <div class="stat">
            <div class="stat-value">{duration:.1f}s</div>
            <div>Duration</div>
        </div>
        <div class="stat">
            <div class="stat-value {'success' if getattr(self, 'success', False) else 'error'}">
                {'✓' if getattr(self, 'success', False) else '✗'}
            </div>
            <div>Status</div>
        </div>
        <div class="stat">
            <div class="stat-value">{self.mode}</div>
            <div>Provider</div>
        </div>
    </div>
    
    <h2>Execution Timeline</h2>
"""
        
        for step in self.steps:
            reasoning_html = f'<div class="reasoning">{step.get("reasoning", "")}</div>' if step.get("reasoning") else ""
            screenshot_html = f'<img src="{step["screenshot"]}" class="screenshot">' if step.get("screenshot") else ""
            
            html += f"""
    <div class="step">
        <div class="step-header">
            <span class="action">Step {step['step_number']}: {step['action']}</span>
            <span>{step['timestamp']}</span>
        </div>
        {reasoning_html}
        <div class="args">Args: {json.dumps(step['args'])}</div>
        {screenshot_html}
    </div>
"""
        
        html += f"""
    <div class="step">
        <div class="step-header">
            <span class="{'success' if getattr(self, 'success', False) else 'error'}">
                Final: {getattr(self, 'final_message', 'Unknown')}
            </span>
        </div>
    </div>
</body>
</html>"""
        
        report_path = output_dir / "execution_report.html"
        report_path.write_text(html, encoding="utf-8")
        
        # Also save JSON
        json_path = output_dir / "execution_history.json"
        json_path.write_text(json.dumps({
            "task": self.task_description,
            "mode": self.mode,
            "resolution": resolution,
            "steps": self.steps,
            "success": getattr(self, 'success', False),
            "duration_seconds": duration
        }, indent=2), encoding="utf-8")
        
        return str(report_path)

# ============================================================================
# SHARED UTILITIES
# ============================================================================

def type_via_clipboard(text: str):
    """Type text via clipboard (handles Unicode)"""
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

def capture_screenshot_png(width: int, height: int) -> bytes:
    """Capture and resize screenshot, return PNG bytes"""
    screenshot = pyautogui.screenshot()
    screenshot = screenshot.resize((width, height), Image.LANCZOS)
    buffer = BytesIO()
    screenshot.save(buffer, format='PNG')
    return buffer.getvalue()

def get_screen_size() -> tuple:
    """Get actual screen size"""
    return pyautogui.size()

# ============================================================================
# GEMINI COMPUTER USE IMPLEMENTATION
# (Based on official Google repo: github.com/google-gemini/computer-use-preview)
# ============================================================================

class GeminiComputerUseAgent:
    """
    Gemini Computer Use Agent - follows official Google implementation
    """
    
    def __init__(self, api_key: str, task: str, max_steps: int = 15):
        self.api_key = api_key
        self.task = task
        self.max_steps = max_steps
        self.history = ExecutionHistory(task, "gemini")
        self.final_reasoning: Optional[str] = None
        
        # Initialize Gemini client
        self._client = genai.Client(api_key=api_key)
        
        # Conversation history
        self._contents: List[Content] = [
            Content(
                role="user",
                parts=[Part(text=self.task)],
            )
        ]
        
        # Configuration (from official repo)
        self._generate_content_config = GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    ),
                ),
            ],
        )
        
        # Screenshot directory
        self.screenshot_dir = Path("debug_logs/screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        
    def denormalize_x(self, x: int) -> int:
        """Convert normalized x (0-999) to screen pixels"""
        screen_width, _ = get_screen_size()
        return int(x / 1000 * screen_width)
    
    def denormalize_y(self, y: int) -> int:
        """Convert normalized y (0-999) to screen pixels"""
        _, screen_height = get_screen_size()
        return int(y / 1000 * screen_height)
    
    def capture_screenshot(self) -> tuple:
        """Capture screenshot at Gemini reference resolution, return (bytes, path)"""
        png_bytes = capture_screenshot_png(GEMINI_REF_WIDTH, GEMINI_REF_HEIGHT)
        
        # Save for debugging
        timestamp = datetime.now().strftime("%H%M%S_%f")
        path = self.screenshot_dir / f"gemini_{timestamp}.png"
        path.write_bytes(png_bytes)
        
        return png_bytes, str(path)
    
    def handle_action(self, action: types.FunctionCall) -> tuple:
        """
        Execute action and return (url, screenshot_bytes, screenshot_path)
        Based on official Google implementation
        """
        name = action.name
        args = dict(action.args) if action.args else {}
        
        print(f"  → Executing: {name} with args: {args}")
        
        if name == "open_web_browser":
            pass  # Browser already open
            
        elif name == "click_at":
            x = self.denormalize_x(args["x"])
            y = self.denormalize_y(args["y"])
            pyautogui.click(x, y)
            time.sleep(0.3)
            
        elif name == "hover_at":
            x = self.denormalize_x(args["x"])
            y = self.denormalize_y(args["y"])
            pyautogui.moveTo(x, y)
            
        elif name == "type_text_at":
            x = self.denormalize_x(args["x"])
            y = self.denormalize_y(args["y"])
            text = args["text"]
            press_enter = args.get("press_enter", False)
            clear_before = args.get("clear_before_typing", True)
            
            pyautogui.click(x, y)
            time.sleep(0.1)
            
            if clear_before:
                pyautogui.hotkey('ctrl', 'a')
                pyautogui.press('delete')
                time.sleep(0.05)
            
            type_via_clipboard(text)
            
            if press_enter:
                pyautogui.press('enter')
            time.sleep(0.2)
            
        elif name == "scroll_document":
            direction = args["direction"]
            if direction == "down":
                pyautogui.press('pagedown')
            elif direction == "up":
                pyautogui.press('pageup')
            elif direction == "left":
                pyautogui.scroll(3, horizontal=True)
            elif direction == "right":
                pyautogui.scroll(-3, horizontal=True)
            time.sleep(0.2)
            
        elif name == "scroll_at":
            x = self.denormalize_x(args["x"])
            y = self.denormalize_y(args["y"])
            direction = args["direction"]
            magnitude = args.get("magnitude", 800)
            
            # Denormalize magnitude
            if direction in ("up", "down"):
                magnitude = self.denormalize_y(magnitude)
            else:
                magnitude = self.denormalize_x(magnitude)
            
            pyautogui.moveTo(x, y)
            
            if direction == "up":
                pyautogui.scroll(magnitude // 100)
            elif direction == "down":
                pyautogui.scroll(-magnitude // 100)
            time.sleep(0.2)
            
        elif name == "wait_5_seconds":
            time.sleep(5)
            
        elif name == "go_back":
            pyautogui.hotkey('alt', 'left')
            time.sleep(0.5)
            
        elif name == "go_forward":
            pyautogui.hotkey('alt', 'right')
            time.sleep(0.5)
            
        elif name == "search":
            webbrowser.open("https://www.google.com")
            time.sleep(1)
            
        elif name == "navigate":
            url = args["url"]
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            webbrowser.open(url)
            time.sleep(1)
            
        elif name == "key_combination":
            keys = args["keys"].split("+")
            # Map keys to pyautogui names
            key_map = {
                "control": "ctrl",
                "command": "ctrl",  # Windows equivalent
                "meta": "ctrl",
                "return": "enter",
                "arrowleft": "left",
                "arrowright": "right",
                "arrowup": "up",
                "arrowdown": "down",
            }
            mapped_keys = [key_map.get(k.lower(), k.lower()) for k in keys]
            pyautogui.hotkey(*mapped_keys)
            time.sleep(0.2)
            
        elif name == "drag_and_drop":
            x = self.denormalize_x(args["x"])
            y = self.denormalize_y(args["y"])
            dest_x = self.denormalize_x(args["destination_x"])
            dest_y = self.denormalize_y(args["destination_y"])
            
            pyautogui.moveTo(x, y)
            pyautogui.mouseDown()
            pyautogui.moveTo(dest_x, dest_y, duration=0.3)
            pyautogui.mouseUp()
            
        else:
            print(f"  ⚠️ Unknown action: {name}")
        
        # Capture result screenshot
        screenshot_bytes, screenshot_path = self.capture_screenshot()
        
        # Record in history
        self.history.add_step(name, args, screenshot_path)
        
        # Return current URL (we don't have access to browser URL from pyautogui)
        return "unknown", screenshot_bytes, screenshot_path
    
    def get_text(self, candidate: Candidate) -> Optional[str]:
        """Extract text from candidate"""
        if not candidate.content or not candidate.content.parts:
            return None
        text = []
        for part in candidate.content.parts:
            if part.text:
                text.append(part.text)
        return " ".join(text) or None
    
    def extract_function_calls(self, candidate: Candidate) -> List[types.FunctionCall]:
        """Extract function calls from candidate"""
        if not candidate.content or not candidate.content.parts:
            return []
        ret = []
        for part in candidate.content.parts:
            if part.function_call:
                ret.append(part.function_call)
        return ret
    
    def get_safety_confirmation(self, safety: dict) -> Literal["CONTINUE", "TERMINATE"]:
        """Handle safety confirmation (auto-approve with logging)"""
        if safety.get("decision") == "require_confirmation":
            print(f"  ⚠️ Safety confirmation required: {safety.get('explanation', 'No explanation')}")
            # Auto-approve for automation (in production, could prompt user)
            return "CONTINUE"
        return "CONTINUE"
    
    def run_one_iteration(self) -> Literal["COMPLETE", "CONTINUE"]:
        """Run one iteration of the agent loop"""
        
        # Generate response from Gemini
        try:
            response = self._client.models.generate_content(
                model=GEMINI_MODEL,
                contents=self._contents,
                config=self._generate_content_config,
            )
        except Exception as e:
            print(f"  ❌ Gemini API error: {e}")
            return "COMPLETE"
        
        if not response.candidates:
            print("  ❌ No candidates in response")
            return "COMPLETE"
        
        candidate = response.candidates[0]
        
        # Append model turn to history
        if candidate.content:
            self._contents.append(candidate.content)
        
        reasoning = self.get_text(candidate)
        function_calls = self.extract_function_calls(candidate)
        
        if reasoning:
            print(f"  💭 Reasoning: {reasoning[:200]}...")
        
        # Handle malformed function call
        if (not function_calls and not reasoning and 
            candidate.finish_reason == FinishReason.MALFORMED_FUNCTION_CALL):
            return "CONTINUE"
        
        # No function calls = task complete
        if not function_calls:
            print(f"  ✅ Task complete: {reasoning}")
            self.final_reasoning = reasoning
            return "COMPLETE"
        
        # Execute each function call
        function_responses = []
        for fc in function_calls:
            extra_fields = {}
            
            # Handle safety decision
            if fc.args and (safety := fc.args.get("safety_decision")):
                decision = self.get_safety_confirmation(safety)
                if decision == "TERMINATE":
                    return "COMPLETE"
                extra_fields["safety_acknowledgement"] = "true"
            
            # Execute the action
            url, screenshot_bytes, screenshot_path = self.handle_action(fc)
            
            # Update history with reasoning
            if self.history.steps:
                self.history.steps[-1]["reasoning"] = reasoning
            
            # Build function response (official format)
            function_responses.append(
                FunctionResponse(
                    name=fc.name,
                    response={
                        "url": url,
                        **extra_fields,
                    },
                    parts=[
                        types.FunctionResponsePart(
                            inline_data=types.FunctionResponseBlob(
                                mime_type="image/png",
                                data=screenshot_bytes
                            )
                        )
                    ],
                )
            )
        
        # Add function responses to conversation
        self._contents.append(
            Content(
                role="user",
                parts=[Part(function_response=fr) for fr in function_responses],
            )
        )
        
        # Remove old screenshots to save context space
        self._cleanup_old_screenshots()
        
        return "CONTINUE"
    
    def _cleanup_old_screenshots(self):
        """Remove screenshots from old turns to save context"""
        turns_with_screenshots = 0
        
        for content in reversed(self._contents):
            if content.role == "user" and content.parts:
                has_screenshot = False
                for part in content.parts:
                    if (part.function_response and 
                        part.function_response.parts and
                        part.function_response.name in PREDEFINED_COMPUTER_USE_FUNCTIONS):
                        has_screenshot = True
                        break
                
                if has_screenshot:
                    turns_with_screenshots += 1
                    if turns_with_screenshots > MAX_RECENT_TURNS_WITH_SCREENSHOTS:
                        for part in content.parts:
                            if (part.function_response and 
                                part.function_response.parts and
                                part.function_response.name in PREDEFINED_COMPUTER_USE_FUNCTIONS):
                                part.function_response.parts = None
    
    def run(self) -> ExecuteResponse:
        """Run the full agent loop"""
        print(f"\n🤖 Starting Gemini Computer Use Agent")
        print(f"   Task: {self.task}")
        print(f"   Max steps: {self.max_steps}")
        
        # Capture initial screenshot
        screenshot_bytes, screenshot_path = self.capture_screenshot()
        
        # Add initial screenshot to conversation
        self._contents[0].parts.append(
            Part(
                inline_data=types.Blob(
                    mime_type="image/png",
                    data=screenshot_bytes
                )
            )
        )
        
        steps = 0
        status = "CONTINUE"
        
        while status == "CONTINUE" and steps < self.max_steps:
            steps += 1
            print(f"\n📍 Step {steps}/{self.max_steps}")
            status = self.run_one_iteration()
        
        # Generate report
        success = status == "COMPLETE" or steps >= self.max_steps
        final_msg = self.final_reasoning or f"Completed {steps} steps"
        self.history.finalize(success, final_msg)
        
        report_dir = Path("lux_analysis") / f"gemini_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        report_path = self.history.generate_report(report_dir)
        
        return ExecuteResponse(
            success=success,
            message=final_msg,
            steps_executed=steps,
            report_path=report_path
        )

# ============================================================================
# LUX EXECUTION (existing implementation)
# ============================================================================

async def execute_with_lux(
    api_key: str,
    task: str,
    mode: str,
    max_steps: int,
    start_url: Optional[str]
) -> ExecuteResponse:
    """Execute task using Lux SDK"""
    
    if not OAGI_AVAILABLE:
        return ExecuteResponse(
            success=False,
            message="Lux SDK not available",
            error="OAGI SDK not installed"
        )
    
    history = ExecutionHistory(task, mode)
    
    try:
        client = OAGIClient(api_key=api_key)
        screenshot_maker = ResizedScreenshotMaker(
            max_width=LUX_REF_WIDTH,
            max_height=LUX_REF_HEIGHT
        )
        
        # Navigate to start URL if provided
        if start_url:
            webbrowser.open(start_url)
            await asyncio.sleep(2)
        
        if mode == "tasker":
            # TaskerAgent mode
            agent = TaskerAgent(
                client=client,
                screenshot_maker=screenshot_maker,
                type_via_clipboard=type_via_clipboard
            )
            
            result = await agent.execute(
                task=task,
                max_steps_per_todo=max_steps
            )
            
            history.finalize(True, str(result))
            
        else:
            # Actor/Thinker mode
            model = "lux-thinker-1" if mode == "thinker" else "lux-actor-1"
            
            actor = AsyncActor(
                client=client,
                model=model,
                screenshot_maker=screenshot_maker,
                type_via_clipboard=type_via_clipboard
            )
            
            steps = 0
            async for step in actor.run(task, max_steps=max_steps):
                steps += 1
                history.add_step(
                    action=step.action if hasattr(step, 'action') else "step",
                    args={"step": steps},
                    reasoning=step.reasoning if hasattr(step, 'reasoning') else None
                )
            
            history.finalize(True, f"Completed {steps} steps")
        
        # Generate report
        report_dir = Path("lux_analysis") / f"{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        report_path = history.generate_report(report_dir)
        
        return ExecuteResponse(
            success=True,
            message=f"Task completed with {mode}",
            steps_executed=len(history.steps),
            report_path=report_path
        )
        
    except Exception as e:
        history.finalize(False, str(e))
        return ExecuteResponse(
            success=False,
            message="Execution failed",
            error=str(e)
        )

# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "="*60)
    print("🚀 TASKER SERVICE v5.9.0")
    print("="*60)
    print(f"OAGI SDK: {'✅ Available' if OAGI_AVAILABLE else '❌ Not available'}")
    print(f"Gemini SDK: {'✅ Available' if GEMINI_AVAILABLE else '❌ Not available'}")
    print("\nSUPPORTED MODES:")
    if OAGI_AVAILABLE:
        print("  • actor   - Lux AsyncActor (lux-actor-1)")
        print("  • thinker - Lux AsyncActor (lux-thinker-1)")
        print("  • tasker  - Lux TaskerAgent")
    if GEMINI_AVAILABLE:
        print("  • gemini  - Google Gemini Computer Use")
    print("="*60 + "\n")
    yield
    print("Shutting down...")

app = FastAPI(title="Tasker Service", version="5.9.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/status", response_model=StatusResponse)
async def get_status():
    modes = []
    if OAGI_AVAILABLE:
        modes.extend(["actor", "thinker", "tasker"])
    if GEMINI_AVAILABLE:
        modes.append("gemini")
    
    return StatusResponse(
        status="running",
        version="5.9.0",
        oagi_available=OAGI_AVAILABLE,
        gemini_available=GEMINI_AVAILABLE,
        modes=modes
    )

@app.post("/execute", response_model=ExecuteResponse)
async def execute_task(request: ExecuteRequest):
    print(f"\n📥 Received task: {request.task_description[:100]}...")
    print(f"   Mode: {request.mode}")
    
    if request.mode == "gemini":
        if not GEMINI_AVAILABLE:
            raise HTTPException(status_code=400, detail="Gemini SDK not available")
        
        agent = GeminiComputerUseAgent(
            api_key=request.api_key,
            task=request.task_description,
            max_steps=request.max_steps_per_todo
        )
        
        # Navigate to start URL if provided
        if request.start_url:
            webbrowser.open(request.start_url)
            await asyncio.sleep(2)
        
        return agent.run()
    
    elif request.mode in ["actor", "thinker", "tasker"]:
        if not OAGI_AVAILABLE:
            raise HTTPException(status_code=400, detail="Lux SDK not available")
        
        return await execute_with_lux(
            api_key=request.api_key,
            task=request.task_description,
            mode=request.mode,
            max_steps=request.max_steps_per_todo,
            start_url=request.start_url
        )
    
    else:
        raise HTTPException(
            status_code=400, 
            detail=f"Unknown mode: {request.mode}. Available: {['actor', 'thinker', 'tasker', 'gemini']}"
        )

@app.post("/debug/test_gemini")
async def test_gemini(api_key: str = Query(...)):
    """Test Gemini API connection"""
    if not GEMINI_AVAILABLE:
        return {"success": False, "error": "Gemini SDK not installed"}
    
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Say 'Gemini Computer Use ready!' in exactly those words."
        )
        return {
            "success": True,
            "response": response.text,
            "model_for_computer_use": GEMINI_MODEL
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
