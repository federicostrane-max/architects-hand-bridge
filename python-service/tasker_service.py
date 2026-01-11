#!/usr/bin/env python3
"""
tasker_service.py v7.0 - Unified Multi-Provider Computer Use
=============================================================

SUPPORTED PROVIDERS:

1. LUX (Vision + PyAutoGUI - controlla il TUO PC)
   - actor   : AsyncActor per task single-goal
   - thinker : AsyncActor con lux-thinker-1 (più ragionamento)
   - tasker  : TaskerAgent con todos strutturati

2. GEMINI CUA (Vision pura - browser dedicato)
   - Usa Playwright con Edge + persistent context
   - Tool computer_use simulato

3. GEMINI HYBRID (DOM + Vision - browser dedicato) [NUOVO]
   - Combina Accessibility Tree + Screenshot
   - Self-healing automatico

Versioni:
- v6.0.7: Switch a Edge per evitare conflitti
- v7.0.0: Unified con Hybrid Mode + Lux completo
"""

import asyncio
import base64
import json
import logging
import os
import sys
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Literal, List

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ============================================================================
# CONFIGURATION
# ============================================================================

SERVICE_VERSION = "7.1.5"
SERVICE_PORT = 8765

# Lux reference resolution (il modello è stato trainato su questa risoluzione)
LUX_REF_WIDTH = 1920
LUX_REF_HEIGHT = 1200

# Viewport per Gemini (ottimizzato per Computer Use)
VIEWPORT_WIDTH = 1288
VIEWPORT_HEIGHT = 711

# Profile directories
GEMINI_PROFILE_DIR = Path.home() / ".gemini-browser-profile"
HYBRID_PROFILE_DIR = Path.home() / ".hybrid-browser-profile"

# Models (aggiornati da Stagehand repo ufficiale)
GEMINI_HYBRID_MODEL = "gemini-3-flash-preview"                    # Per Hybrid (DOM + Vision)
GEMINI_CUA_MODEL = "gemini-2.5-computer-use-preview-10-2025"      # Per CUA (solo Vision)

# Analysis directory for reports
ANALYSIS_DIR = Path.home() / ".architect-hand" / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# LOGGING
# ============================================================================

class TaskLogger:
    """Logger personalizzato con timestamp e colori"""
    
    def __init__(self):
        self.logs: List[str] = []
        
    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] [{level}] {message}"
        self.logs.append(formatted)
        print(formatted)
        
    def get_logs(self) -> List[str]:
        return self.logs.copy()
    
    def clear(self):
        self.logs = []

logger = TaskLogger()

# Standard logging per uvicorn
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s.%(msecs)03d] %(message)s',
    datefmt='%H:%M:%S'
)

# ============================================================================
# DEPENDENCY CHECKS
# ============================================================================

# PyAutoGUI
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
    logger.log("✅ PyAutoGUI disponibile")
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    logger.log("⚠️ PyAutoGUI non disponibile", "WARNING")

# Pyperclip (per clipboard typing)
try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
    logger.log("✅ Pyperclip disponibile")
except ImportError:
    PYPERCLIP_AVAILABLE = False
    logger.log("⚠️ Pyperclip non disponibile", "WARNING")

# OpenAGI Lux SDK (oagi)
OAGI_AVAILABLE = False
ASYNC_ACTOR_AVAILABLE = False
TASKER_AGENT_AVAILABLE = False
ASYNC_AGENT_OBSERVER_AVAILABLE = False

try:
    from oagi import (
        AsyncActor,
        TaskerAgent,
        AsyncAgentObserver,
        AsyncScreenshotMaker,
        AsyncPyautoguiActionHandler,
        PyautoguiConfig
    )
    ASYNC_ACTOR_AVAILABLE = True
    TASKER_AGENT_AVAILABLE = True
    ASYNC_AGENT_OBSERVER_AVAILABLE = True
    OAGI_AVAILABLE = True
    logger.log("✅ OAGI SDK completo (AsyncActor, TaskerAgent, handlers)")
except ImportError as e:
    logger.log(f"⚠️ OAGI SDK non disponibile: {e}", "WARNING")

# Google GenAI (google-genai, NOT google-generativeai)
try:
    from google import genai
    from google.genai import types
    from google.genai.types import Content, Part, GenerateContentConfig
    GEMINI_AVAILABLE = True
    logger.log("✅ Google GenAI SDK disponibile")
except ImportError:
    GEMINI_AVAILABLE = False
    logger.log("⚠️ Google GenAI SDK non disponibile", "WARNING")

# Playwright
try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
    logger.log("✅ Playwright disponibile")
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.log("⚠️ Playwright non disponibile", "WARNING")

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class TaskRequest(BaseModel):
    """Request per esecuzione task"""
    task_description: str
    start_url: Optional[str] = None
    mode: Literal["actor", "thinker", "tasker", "gemini", "gemini_cua", "gemini_hybrid"] = "actor"
    
    # API Keys (passate dalla web app)
    api_key: Optional[str] = None  # OAGI API key per Lux, oppure Gemini API key se mode=gemini
    gemini_api_key: Optional[str] = None  # Gemini API key (alternativa)
    
    # Lux settings
    model: str = "lux-actor-1"
    max_steps: int = 30
    max_steps_per_todo: int = 24
    temperature: float = 0.0
    todos: Optional[List[str]] = None
    
    # PyAutoGUI settings
    drag_duration: float = 0.5
    scroll_amount: int = 3
    wait_duration: float = 1.0
    action_pause: float = 0.1
    
    # Screenshot settings
    enable_screenshot_resize: bool = True
    
    # Gemini settings
    headless: bool = False
    highlight_mouse: bool = False


class TaskResponse(BaseModel):
    """Response dall'esecuzione task"""
    success: bool
    message: str = ""
    result: Optional[str] = None
    error: Optional[str] = None
    steps_executed: int = 0
    completed_todos: int = 0
    total_todos: int = 0
    mode_used: str = ""
    actions_log: List[dict] = []
    logs: List[str] = []


class StatusResponse(BaseModel):
    status: str
    version: str
    providers: dict
    modes: List[str]


# ============================================================================
# EXECUTION HISTORY TRACKER
# ============================================================================

class ExecutionHistory:
    """Traccia la storia dell'esecuzione per analisi"""
    
    def __init__(self, task: str, todos: List[str] = None):
        self.task = task
        self.todos = todos or []
        self.steps: List[dict] = []
        self.start_time = datetime.now()
        self.end_time: Optional[datetime] = None
        
    def add_step(self, step_num: int, action_type: str, details: dict = None):
        self.steps.append({
            "step": step_num,
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "details": details or {}
        })
        
    def finish(self, success: bool):
        self.end_time = datetime.now()
        self.success = success
        
    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "todos": self.todos,
            "steps": self.steps,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "success": getattr(self, 'success', None)
        }


# ============================================================================
# LUX: RESIZED SCREENSHOT MAKER
# ============================================================================

class ResizedScreenshotMaker:
    """
    Screenshot maker che ridimensiona alla risoluzione di riferimento Lux.
    Lux è stato trainato su 1920x1200, quindi le coordinate funzionano meglio
    se gli screenshot sono in quella risoluzione.
    """
    
    def __init__(self, target_width: int = LUX_REF_WIDTH, target_height: int = LUX_REF_HEIGHT):
        self.target_width = target_width
        self.target_height = target_height
        
    async def __call__(self) -> str:
        """Cattura screenshot, ridimensiona e restituisce base64"""
        try:
            from PIL import Image
            import io
            
            # Cattura screenshot
            screenshot = pyautogui.screenshot()
            
            # Ridimensiona alla risoluzione target
            resized = screenshot.resize(
                (self.target_width, self.target_height),
                Image.Resampling.LANCZOS
            )
            
            # Converti in base64
            buffer = io.BytesIO()
            resized.save(buffer, format='PNG')
            buffer.seek(0)
            
            return base64.b64encode(buffer.read()).decode('utf-8')
            
        except Exception as e:
            logger.log(f"❌ Errore screenshot: {e}", "ERROR")
            raise


# ============================================================================
# LUX: COORDINATE SCALING
# ============================================================================

def scale_coordinates(x: int, y: int) -> tuple:
    """
    Scala le coordinate dalla risoluzione Lux a quella reale dello schermo.
    
    Lux restituisce coordinate basate su 1920x1200.
    Se il tuo schermo è diverso, le coordinate vanno scalate.
    """
    if not PYAUTOGUI_AVAILABLE:
        return x, y
        
    screen_width, screen_height = pyautogui.size()
    
    x_scaled = int(x * screen_width / LUX_REF_WIDTH)
    y_scaled = int(y * screen_height / LUX_REF_HEIGHT)
    
    return x_scaled, y_scaled


# ============================================================================
# LUX: CLIPBOARD TYPING (per tastiere non-US)
# ============================================================================

def type_via_clipboard(text: str):
    """
    Digita testo usando clipboard (Ctrl+V) invece di typewrite().
    Necessario per tastiere non-US (es. italiana) dove i caratteri
    speciali non vengono digitati correttamente.
    """
    if not PYPERCLIP_AVAILABLE:
        logger.log("⚠️ Pyperclip non disponibile, uso typewrite", "WARNING")
        pyautogui.typewrite(text, interval=0.05)
        return
        
    try:
        # Salva clipboard attuale
        old_clipboard = pyperclip.paste()
        
        # Copia testo in clipboard
        pyperclip.copy(text)
        
        # Incolla con Ctrl+V
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        
        # Ripristina clipboard
        pyperclip.copy(old_clipboard)
        
    except Exception as e:
        logger.log(f"⚠️ Clipboard typing fallito: {e}, uso typewrite", "WARNING")
        pyautogui.typewrite(text, interval=0.05)


# ============================================================================
# LUX: ACTOR/THINKER MODE EXECUTION
# ============================================================================

async def execute_with_actor(request: TaskRequest) -> TaskResponse:
    """
    Esegue task usando AsyncActor (per mode actor/thinker).
    
    - actor: usa lux-actor-1 (veloce, meno ragionamento)
    - thinker: usa lux-thinker-1 (più lento, più ragionamento)
    """
    logger.clear()
    logger.log("=" * 60)
    logger.log(f"LUX {request.mode.upper()} MODE - v7.0")
    logger.log("=" * 60)
    logger.log(f"Task: {request.task_description[:80]}...")
    
    if not ASYNC_ACTOR_AVAILABLE:
        return TaskResponse(
            success=False,
            error="AsyncActor non disponibile. Installa: pip install openagi",
            mode_used=request.mode
        )
    
    # Seleziona modello
    if request.mode == "thinker":
        model = "lux-thinker-1"
    else:
        model = "lux-actor-1"
    
    logger.log(f"Model: {model}")
    logger.log(f"Max steps: {request.max_steps}")
    
    # Screen info
    if PYAUTOGUI_AVAILABLE:
        screen_width, screen_height = pyautogui.size()
        logger.log(f"Screen: {screen_width}x{screen_height}")
        logger.log(f"Lux reference: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
    
    history = ExecutionHistory(request.task_description)
    
    try:
        # API key
        api_key = request.api_key or os.getenv("OAGI_API_KEY")
        if not api_key:
            raise ValueError("OAGI_API_KEY non configurata")
        
        # Crea Actor
        actor = AsyncActor(
            api_key=api_key,
            model=model
        )
        
        # Inizializza task
        actor.init_task(
            task_desc=request.task_description,
            max_steps=request.max_steps
        )
        
        # Crea handlers
        pyautogui_config = PyautoguiConfig(
            drag_duration=request.drag_duration,
            scroll_amount=request.scroll_amount,
            wait_duration=request.wait_duration,
            action_pause=request.action_pause
        )
        
        if request.enable_screenshot_resize:
            image_provider = ResizedScreenshotMaker()
            logger.log(f"📸 Screenshot resize: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
        else:
            image_provider = AsyncScreenshotMaker()
            logger.log("📸 Screenshot: risoluzione nativa")
        
        action_handler = AsyncPyautoguiActionHandler(config=pyautogui_config)
        logger.log("🎮 Action handler: PyAutoGUI")
        
        # Execution loop
        step = 0
        done = False
        
        while not done and step < request.max_steps:
            step += 1
            logger.log(f"\n--- Step {step}/{request.max_steps} ---")
            
            # Cattura screenshot
            screenshot_b64 = await image_provider()
            
            # Chiedi azione a Lux
            actions, is_done = await actor.act(
                image=screenshot_b64,
                action_handler=action_handler
            )
            
            if is_done:
                logger.log("✅ Task completato!")
                done = True
                break
            
            # Esegui azioni
            for action in actions:
                action_type = str(action.type.value) if hasattr(action.type, "value") else str(action.type)
                argument = str(action.argument) if hasattr(action, "argument") else ""
                
                logger.log(f"🎯 Action: {action_type}")
                
                # Intercetta type per clipboard
                if action_type.lower() == "type" and argument:
                    logger.log(f"⌨️ Typing via clipboard: '{argument[:50]}...'")
                    type_via_clipboard(argument)
                    history.add_step(step, "type", {"text": argument[:100]})
                else:
                    # Esegui via SDK
                    await action_handler([action])
                    history.add_step(step, action_type, {"argument": argument[:100] if argument else ""})
                
                time.sleep(0.1)
        
        history.finish(done)
        
        return TaskResponse(
            success=done,
            message="Task completato" if done else f"Max steps ({request.max_steps}) raggiunto",
            steps_executed=step,
            mode_used=request.mode,
            actions_log=history.steps,
            logs=logger.get_logs()
        )
        
    except Exception as e:
        logger.log(f"❌ Errore: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        
        return TaskResponse(
            success=False,
            error=str(e),
            mode_used=request.mode,
            logs=logger.get_logs()
        )


# ============================================================================
# LUX: TASKER MODE EXECUTION (con Todos)
# ============================================================================

async def execute_with_tasker(request: TaskRequest) -> TaskResponse:
    """
    Esegue task usando TaskerAgent con lista di todos.
    
    Ogni todo viene eseguito in sequenza con max_steps_per_todo step.
    Il TaskerAgent traccia quali todos sono completati.
    """
    logger.clear()
    logger.log("=" * 60)
    logger.log("LUX TASKER MODE - v7.0")
    logger.log("=" * 60)
    
    if not TASKER_AGENT_AVAILABLE:
        return TaskResponse(
            success=False,
            error="TaskerAgent non disponibile. Installa: pip install openagi",
            mode_used="tasker"
        )
    
    todos = request.todos or []
    if not todos:
        return TaskResponse(
            success=False,
            error="Tasker mode richiede una lista di todos",
            mode_used="tasker"
        )
    
    logger.log(f"Task: {request.task_description[:80]}...")
    logger.log(f"Todos: {len(todos)}")
    for i, todo in enumerate(todos):
        logger.log(f"  [{i+1}] {todo[:60]}...")
    
    # Screen info
    if PYAUTOGUI_AVAILABLE:
        screen_width, screen_height = pyautogui.size()
        logger.log(f"Screen: {screen_width}x{screen_height}")
    
    history = ExecutionHistory(request.task_description, todos)
    
    try:
        # API key
        api_key = request.api_key or os.getenv("OAGI_API_KEY")
        if not api_key:
            raise ValueError("OAGI_API_KEY non configurata")
        
        # Crea PyAutoGUI config
        pyautogui_config = PyautoguiConfig(
            drag_duration=request.drag_duration,
            scroll_amount=request.scroll_amount,
            wait_duration=request.wait_duration,
            action_pause=request.action_pause
        )
        
        # Crea observer (opzionale)
        observer = None
        if ASYNC_AGENT_OBSERVER_AVAILABLE:
            observer = AsyncAgentObserver()
            logger.log("📊 Observer abilitato")
        
        # Crea image provider
        if request.enable_screenshot_resize:
            image_provider = ResizedScreenshotMaker()
            logger.log(f"📸 Screenshot resize: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT}")
        else:
            image_provider = AsyncScreenshotMaker()
            logger.log("📸 Screenshot: risoluzione nativa")
        
        # Crea action handler
        action_handler = AsyncPyautoguiActionHandler(config=pyautogui_config)
        logger.log("🎮 Action handler: PyAutoGUI")
        
        # Crea TaskerAgent
        tasker_kwargs = {
            "api_key": api_key,
            "base_url": "https://api.agiopen.org",
            "model": "lux-actor-1",  # Tasker usa sempre actor
            "max_steps": request.max_steps_per_todo,
            "temperature": 0.0,  # Forzato a 0 per evitare loop
        }
        
        if observer:
            tasker_kwargs["step_observer"] = observer
        
        logger.log(f"Creating TaskerAgent:")
        logger.log(f"  model: lux-actor-1")
        logger.log(f"  max_steps_per_todo: {request.max_steps_per_todo}")
        logger.log(f"  temperature: 0.0")
        
        tasker = TaskerAgent(**tasker_kwargs)
        
        # Set task e todos
        tasker.set_task(
            task=request.task_description,
            todos=todos
        )
        
        logger.log("🚀 Avvio esecuzione TaskerAgent...")
        
        # Esegui
        success = await tasker.execute(
            instruction="",  # Task già impostato via set_task
            action_handler=action_handler,
            image_provider=image_provider
        )
        
        # Ottieni risultati da memory
        completed_todos = 0
        todo_statuses = []
        
        try:
            memory = tasker.get_memory()
            if memory:
                logger.log(f"📋 Summary: {memory.task_execution_summary}")
                
                for i, todo_mem in enumerate(memory.todos):
                    status = todo_mem.status.value if hasattr(todo_mem.status, 'value') else str(todo_mem.status)
                    todo_statuses.append({
                        "index": i,
                        "description": todo_mem.description,
                        "status": status
                    })
                    if status == "completed":
                        completed_todos += 1
                    logger.log(f"  [{i+1}] {status}: {todo_mem.description[:50]}...")
        except Exception as mem_err:
            logger.log(f"⚠️ Memory non disponibile: {mem_err}", "WARNING")
            completed_todos = len(todos) if success else 0
        
        # Esporta report observer
        if observer:
            try:
                report_dir = ANALYSIS_DIR / f"tasker_{int(time.time())}"
                report_dir.mkdir(parents=True, exist_ok=True)
                observer_file = report_dir / "observer_history.html"
                observer.export("html", str(observer_file))
                logger.log(f"📊 Report: {observer_file}")
            except Exception as obs_err:
                logger.log(f"⚠️ Export observer fallito: {obs_err}", "WARNING")
        
        history.finish(success)
        
        return TaskResponse(
            success=success,
            message=f"Completati {completed_todos}/{len(todos)} todos",
            steps_executed=request.max_steps_per_todo * len(todos),
            completed_todos=completed_todos,
            total_todos=len(todos),
            mode_used="tasker",
            actions_log=todo_statuses,
            logs=logger.get_logs()
        )
        
    except Exception as e:
        logger.log(f"❌ Errore: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        
        return TaskResponse(
            success=False,
            error=str(e),
            total_todos=len(todos),
            mode_used="tasker",
            logs=logger.get_logs()
        )


# ============================================================================
# GEMINI HYBRID MODE (DOM + Vision)
# ============================================================================

class ActionType(Enum):
    """Tipi di azione per Hybrid Mode"""
    ACT_DOM = "act_dom"
    CLICK_VISION = "click_vision"
    TYPE = "type"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    WAIT = "wait"
    DONE = "done"
    FAIL = "fail"


@dataclass
class HybridAction:
    """Azione risultante dall'analisi Gemini"""
    action_type: ActionType
    selector: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    direction: Optional[str] = None
    reasoning: str = ""


class HybridModeExecutor:
    """Esecutore Hybrid Mode che combina DOM e Vision"""
    
    def __init__(self, headless: bool = False, api_key: Optional[str] = None):
        self.headless = headless
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.actions_log: list = []
        
        if GEMINI_AVAILABLE:
            # Usa api_key passata o fallback a env var
            key = api_key or os.getenv("GEMINI_API_KEY")
            if key:
                self.client = genai.Client(api_key=key)
                logger.log(f"✅ Gemini Client configurato per: {GEMINI_HYBRID_MODEL}")
            else:
                raise ValueError("Gemini API key non configurata")
    
    async def start_browser(self, start_url: Optional[str] = None):
        """Avvia browser Edge con profilo persistente"""
        self.playwright = await async_playwright().start()
        HYBRID_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.log(f"🌐 Avvio Edge: {HYBRID_PROFILE_DIR}")
        
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(HYBRID_PROFILE_DIR),
            channel="msedge",
            headless=self.headless,
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
            ]
        )
        
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        
        if start_url:
            logger.log(f"📍 Navigazione: {start_url}")
            await self.page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)
    
    async def close_browser(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def capture_screenshot(self) -> str:
        screenshot_bytes = await self.page.screenshot(type="png")
        return base64.b64encode(screenshot_bytes).decode("utf-8")
    
    async def get_accessibility_tree(self) -> str:
        """Estrae accessibility tree semplificato"""
        try:
            snapshot = await self.page.accessibility.snapshot()
            if not snapshot:
                return "Accessibility tree non disponibile"
            return self._format_a11y_tree(snapshot)
        except Exception as e:
            return f"Errore: {e}"
    
    def _format_a11y_tree(self, node: dict, indent: int = 0) -> str:
        lines = []
        prefix = "  " * indent
        role = node.get("role", "unknown")
        name = node.get("name", "")
        
        if name:
            lines.append(f'{prefix}[{role}] "{name}"')
        else:
            lines.append(f'{prefix}[{role}]')
        
        for child in node.get("children", []):
            lines.append(self._format_a11y_tree(child, indent + 1))
        
        return "\n".join(lines)
    
    def _build_prompt(self, task: str, a11y_tree: str, current_url: str, step: int) -> str:
        return f"""Sei un agente di automazione web Hybrid (DOM + Vision).

TASK: {task}

URL: {current_url}
Step: {step}

ACCESSIBILITY TREE:
```
{a11y_tree[:6000]}
```

STRUMENTI:
1. act_dom - Click via selettore: {{"action": "act_dom", "selector": "...", "reasoning": "..."}}
2. click_vision - Click via coordinate: {{"action": "click_vision", "x": 640, "y": 380, "reasoning": "..."}}
3. type - Digita testo: {{"action": "type", "text": "...", "reasoning": "..."}}
4. scroll - Scrolla: {{"action": "scroll", "direction": "down", "reasoning": "..."}}
5. navigate - Vai a URL: {{"action": "navigate", "url": "...", "reasoning": "..."}}
6. wait - Attendi: {{"action": "wait", "reasoning": "..."}}
7. done - Completato: {{"action": "done", "reasoning": "..."}}
8. fail - Fallito: {{"action": "fail", "reasoning": "..."}}

Preferisci act_dom quando possibile. Coordinate: viewport {VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}.
Rispondi SOLO con il JSON:"""
    
    async def analyze_and_decide(self, task: str, step: int) -> HybridAction:
        screenshot_b64 = await self.capture_screenshot()
        a11y_tree = await self.get_accessibility_tree()
        current_url = self.page.url
        
        prompt = self._build_prompt(task, a11y_tree, current_url, step)
        
        try:
            # Prepara contenuto per google-genai SDK
            contents = [
                Content(
                    role="user",
                    parts=[
                        Part(text=prompt),
                        Part(inline_data=types.Blob(
                            mime_type="image/png",
                            data=base64.b64decode(screenshot_b64)
                        ))
                    ]
                )
            ]
            
            response = self.client.models.generate_content(
                model=GEMINI_HYBRID_MODEL,
                contents=contents,
                config=GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=1024,
                )
            )
            
            response_text = response.text.strip()
            
            if "```" in response_text:
                response_text = response_text.split("```")[1].replace("json", "").strip()
            
            action_data = json.loads(response_text)
            return self._parse_action(action_data)
            
        except Exception as e:
            logger.log(f"❌ Errore Gemini: {e}", "ERROR")
            return HybridAction(action_type=ActionType.FAIL, reasoning=str(e))
    
    def _parse_action(self, data: dict) -> HybridAction:
        action_map = {
            "act_dom": ActionType.ACT_DOM,
            "click_vision": ActionType.CLICK_VISION,
            "type": ActionType.TYPE,
            "scroll": ActionType.SCROLL,
            "navigate": ActionType.NAVIGATE,
            "wait": ActionType.WAIT,
            "done": ActionType.DONE,
            "fail": ActionType.FAIL,
        }
        
        return HybridAction(
            action_type=action_map.get(data.get("action", "fail"), ActionType.FAIL),
            selector=data.get("selector"),
            x=data.get("x"),
            y=data.get("y"),
            text=data.get("text") or data.get("url"),
            direction=data.get("direction"),
            reasoning=data.get("reasoning", "")
        )
    
    async def execute_action(self, action: HybridAction) -> bool:
        """
        Esegue l'azione con SELF-HEALING BIDIREZIONALE:
        
        1. Se DOM fallisce → prova Vision (trova coordinate elemento)
        2. Se Vision fallisce → prova DOM (trova elemento a quelle coordinate)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action.action_type.value,
            "reasoning": action.reasoning,
            "success": False
        }
        
        try:
            if action.action_type == ActionType.ACT_DOM:
                # === AZIONE DOM-BASED ===
                logger.log(f"[DOM] Click: {action.selector}")
                try:
                    await self.page.click(action.selector, timeout=5000)
                    log_entry["success"] = True
                except Exception as dom_error:
                    # SELF-HEALING: DOM → Vision
                    logger.log(f"[DOM] Fallito: {dom_error}")
                    logger.log(f"[SELF-HEAL] Provo a trovare coordinate dell'elemento...")
                    
                    try:
                        # Prova a ottenere bounding box dell'elemento
                        element = await self.page.query_selector(action.selector)
                        if element:
                            box = await element.bounding_box()
                            if box:
                                x = int(box["x"] + box["width"] / 2)
                                y = int(box["y"] + box["height"] / 2)
                                await self.page.mouse.click(x, y)
                                log_entry["fallback"] = "dom_to_vision"
                                log_entry["coordinates"] = {"x": x, "y": y}
                                log_entry["success"] = True
                                logger.log(f"[SELF-HEAL] ✅ Click via coordinate ({x}, {y})")
                            else:
                                raise Exception("Bounding box non disponibile")
                        else:
                            raise Exception("Elemento non trovato nel DOM")
                    except Exception as heal_error:
                        logger.log(f"[SELF-HEAL] ❌ Fallito: {heal_error}", "ERROR")
                        log_entry["error"] = str(heal_error)
            
            elif action.action_type == ActionType.CLICK_VISION:
                # === AZIONE VISION-BASED ===
                x, y = action.x, action.y
                logger.log(f"[VISION] Click: ({x}, {y})")
                
                try:
                    await self.page.mouse.click(x, y)
                    log_entry["success"] = True
                    log_entry["coordinates"] = {"x": x, "y": y}
                except Exception as vision_error:
                    logger.log(f"[VISION] Fallito: {vision_error}")
                    logger.log(f"[SELF-HEAL] Provo a trovare elemento DOM a ({x}, {y})...")
                    
                    # SELF-HEALING: Vision → DOM
                    try:
                        element_info = await self.page.evaluate('''(coords) => {
                            const el = document.elementFromPoint(coords.x, coords.y);
                            if (el) {
                                const rect = el.getBoundingClientRect();
                                return {
                                    found: true,
                                    x: rect.x + rect.width / 2,
                                    y: rect.y + rect.height / 2,
                                    tag: el.tagName,
                                    id: el.id || null,
                                    className: el.className || null
                                };
                            }
                            return { found: false };
                        }''', {"x": x, "y": y})
                        
                        if element_info.get("found"):
                            new_x = int(element_info["x"])
                            new_y = int(element_info["y"])
                            await self.page.mouse.click(new_x, new_y)
                            log_entry["fallback"] = "vision_to_dom"
                            log_entry["original_coordinates"] = {"x": x, "y": y}
                            log_entry["corrected_coordinates"] = {"x": new_x, "y": new_y}
                            log_entry["element"] = {
                                "tag": element_info.get("tag"),
                                "id": element_info.get("id")
                            }
                            log_entry["success"] = True
                            logger.log(f"[SELF-HEAL] ✅ Trovato {element_info['tag']} a ({new_x}, {new_y})")
                        else:
                            raise Exception("Nessun elemento a quelle coordinate")
                    except Exception as heal_error:
                        logger.log(f"[SELF-HEAL] ❌ Fallito: {heal_error}", "ERROR")
                        log_entry["error"] = str(heal_error)
            
            elif action.action_type == ActionType.TYPE:
                logger.log(f"[TYPE] {action.text[:30]}...")
                await self.page.keyboard.type(action.text, delay=50)
                log_entry["success"] = True
            
            elif action.action_type == ActionType.SCROLL:
                logger.log(f"[SCROLL] {action.direction}")
                delta = -500 if action.direction == "up" else 500
                await self.page.mouse.wheel(0, delta)
                log_entry["success"] = True
            
            elif action.action_type == ActionType.NAVIGATE:
                logger.log(f"[NAVIGATE] {action.text}")
                await self.page.goto(action.text, wait_until="domcontentloaded", timeout=30000)
                log_entry["success"] = True
            
            elif action.action_type == ActionType.WAIT:
                logger.log("[WAIT] 2s...")
                await asyncio.sleep(2)
                log_entry["success"] = True
            
            elif action.action_type == ActionType.DONE:
                logger.log(f"✅ [DONE] {action.reasoning}")
                log_entry["success"] = True
                self.actions_log.append(log_entry)
                return True
            
            elif action.action_type == ActionType.FAIL:
                logger.log(f"❌ [FAIL] {action.reasoning}")
                self.actions_log.append(log_entry)
                return False
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            log_entry["error"] = str(e)
            logger.log(f"❌ Errore: {e}", "ERROR")
        
        self.actions_log.append(log_entry)
        return log_entry["success"]
    
    async def run(self, task: str, start_url: Optional[str], max_steps: int = 30) -> TaskResponse:
        self.actions_log = []
        logger.clear()
        logger.log("=" * 60)
        logger.log("GEMINI HYBRID MODE - v7.0")
        logger.log("=" * 60)
        logger.log(f"Task: {task[:80]}...")
        
        try:
            await self.start_browser(start_url)
            
            for step in range(1, max_steps + 1):
                logger.log(f"\n--- Step {step}/{max_steps} ---")
                
                action = await self.analyze_and_decide(task, step)
                logger.log(f"🎯 {action.action_type.value}: {action.reasoning[:60]}...")
                
                success = await self.execute_action(action)
                
                if action.action_type == ActionType.DONE:
                    return TaskResponse(
                        success=True,
                        result=action.reasoning,
                        steps_executed=step,
                        mode_used="gemini_hybrid",
                        actions_log=self.actions_log,
                        logs=logger.get_logs()
                    )
                
                if action.action_type == ActionType.FAIL:
                    return TaskResponse(
                        success=False,
                        error=action.reasoning,
                        steps_executed=step,
                        mode_used="gemini_hybrid",
                        actions_log=self.actions_log,
                        logs=logger.get_logs()
                    )
            
            return TaskResponse(
                success=False,
                error=f"Max steps ({max_steps}) raggiunto",
                steps_executed=max_steps,
                mode_used="gemini_hybrid",
                actions_log=self.actions_log,
                logs=logger.get_logs()
            )
            
        finally:
            await self.close_browser()


# ============================================================================
# GEMINI CUA MODE (Vision Only)
# ============================================================================

async def execute_with_gemini_cua(request: TaskRequest) -> TaskResponse:
    """Esegue task con Gemini CUA (solo vision)"""
    logger.clear()
    logger.log("=" * 60)
    logger.log("GEMINI CUA MODE - v7.1.4")
    logger.log("=" * 60)
    
    if not GEMINI_AVAILABLE or not PLAYWRIGHT_AVAILABLE:
        return TaskResponse(
            success=False,
            error="Gemini o Playwright non disponibili",
            mode_used="gemini_cua"
        )
    
    # Usa gemini_api_key o api_key come fallback (retrocompatibilità)
    api_key = request.gemini_api_key or request.api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return TaskResponse(
            success=False,
            error="Gemini API key non configurata",
            mode_used="gemini_cua"
        )
    
    # Usa max_steps_per_todo come fallback per max_steps
    max_steps = request.max_steps if request.max_steps != 30 else request.max_steps_per_todo
    
    client = genai.Client(api_key=api_key)
    actions_log = []
    
    try:
        pw = await async_playwright().start()
        GEMINI_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(GEMINI_PROFILE_DIR),
            channel="msedge",
            headless=request.headless,
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        if request.start_url:
            await page.goto(request.start_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)
        
        for step in range(1, max_steps + 1):
            logger.log(f"\n--- Step {step}/{max_steps} ---")
            
            screenshot_bytes = await page.screenshot(type="png")
            
            prompt = f"""Task: {request.task_description}
URL: {page.url}
Step: {step}

Analizza lo screenshot. Rispondi con JSON:
{{"action": "click|type|scroll|done|fail", "x": num, "y": num, "text": "...", "reasoning": "..."}}

Viewport: {VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}"""
            
            try:
                contents = [
                    Content(
                        role="user",
                        parts=[
                            Part(text=prompt),
                            Part(inline_data=types.Blob(
                                mime_type="image/png",
                                data=screenshot_bytes
                            ))
                        ]
                    )
                ]
                
                response = client.models.generate_content(
                    model=GEMINI_CUA_MODEL,
                    contents=contents,
                    config=GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=1024,
                    )
                )
                
                response_text = response.text.strip()
                
                if "```" in response_text:
                    response_text = response_text.split("```")[1].replace("json", "").strip()
                
                action_data = json.loads(response_text)
                action_type = action_data.get("action", "fail")
                
                logger.log(f"🎯 {action_type}: {action_data.get('reasoning', '')[:50]}...")
                
                if action_type == "click":
                    x, y = action_data.get("x", 0), action_data.get("y", 0)
                    await page.mouse.click(x, y)
                    actions_log.append({"step": step, "action": "click", "x": x, "y": y})
                    
                elif action_type == "type":
                    text = action_data.get("text", "")
                    await page.keyboard.type(text, delay=50)
                    actions_log.append({"step": step, "action": "type", "text": text[:50]})
                    
                elif action_type == "scroll":
                    await page.mouse.wheel(0, 500)
                    actions_log.append({"step": step, "action": "scroll"})
                    
                elif action_type == "done":
                    await context.close()
                    await pw.stop()
                    return TaskResponse(
                        success=True,
                        result=action_data.get("reasoning", "Task completato"),
                        steps_executed=step,
                        mode_used="gemini_cua",
                        actions_log=actions_log,
                        logs=logger.get_logs()
                    )
                    
                elif action_type == "fail":
                    await context.close()
                    await pw.stop()
                    return TaskResponse(
                        success=False,
                        error=action_data.get("reasoning", "Task fallito"),
                        steps_executed=step,
                        mode_used="gemini_cua",
                        actions_log=actions_log,
                        logs=logger.get_logs()
                    )
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.log(f"⚠️ Errore step {step}: {e}", "WARNING")
                continue
        
        await context.close()
        await pw.stop()
        
        return TaskResponse(
            success=False,
            error=f"Max steps ({max_steps}) raggiunto",
            steps_executed=max_steps,
            mode_used="gemini_cua",
            actions_log=actions_log,
            logs=logger.get_logs()
        )
        
    except Exception as e:
        logger.log(f"❌ Errore: {e}", "ERROR")
        return TaskResponse(
            success=False,
            error=str(e),
            mode_used="gemini_cua",
            logs=logger.get_logs()
        )


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_screen_info() -> dict:
    """Info sullo schermo per debug"""
    info = {
        "lux_reference": {"width": LUX_REF_WIDTH, "height": LUX_REF_HEIGHT},
        "gemini_viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
    }
    
    if PYAUTOGUI_AVAILABLE:
        size = pyautogui.size()
        info["screen"] = {"width": size.width, "height": size.height}
        info["scale_x"] = size.width / LUX_REF_WIDTH
        info["scale_y"] = size.height / LUX_REF_HEIGHT
    
    return info


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Architect's Hand - Tasker Service",
    description="Unified Multi-Provider Computer Use (Lux + Gemini)",
    version=SERVICE_VERSION
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

is_running = False


@app.get("/")
async def root():
    return {"service": "Architect's Hand Tasker", "version": SERVICE_VERSION}


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Stato del servizio"""
    modes = []
    
    if ASYNC_ACTOR_AVAILABLE:
        modes.extend(["actor", "thinker"])
    if TASKER_AGENT_AVAILABLE:
        modes.append("tasker")
    if GEMINI_AVAILABLE and PLAYWRIGHT_AVAILABLE:
        modes.extend(["gemini_cua", "gemini_hybrid"])
    
    return StatusResponse(
        status="running" if not is_running else "busy",
        version=SERVICE_VERSION,
        providers={
            "lux": {
                "available": OAGI_AVAILABLE,
                "async_actor": ASYNC_ACTOR_AVAILABLE,
                "tasker_agent": TASKER_AGENT_AVAILABLE,
                "observer": ASYNC_AGENT_OBSERVER_AVAILABLE,
            },
            "gemini": {
                "available": GEMINI_AVAILABLE,
                "playwright": PLAYWRIGHT_AVAILABLE,
            },
            "system": {
                "pyautogui": PYAUTOGUI_AVAILABLE,
                "pyperclip": PYPERCLIP_AVAILABLE,
            }
        },
        modes=modes
    )


@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    """Esegue un task"""
    global is_running
    
    # Debug: log full request
    logger.log("=" * 60)
    logger.log(f"[REQUEST] mode: {request.mode}")
    logger.log(f"[REQUEST] task: {request.task_description[:50]}...")
    logger.log(f"[REQUEST] api_key: {'***' + request.api_key[-4:] if request.api_key else 'None'}")
    logger.log(f"[REQUEST] gemini_api_key: {'***' + request.gemini_api_key[-4:] if request.gemini_api_key else 'None'}")
    logger.log(f"[REQUEST] max_steps: {request.max_steps}")
    logger.log(f"[REQUEST] max_steps_per_todo: {request.max_steps_per_todo}")
    logger.log("=" * 60)
    
    if is_running:
        raise HTTPException(status_code=409, detail="Un task è già in esecuzione")
    
    is_running = True
    
    try:
        # Lux modes
        if request.mode in ["actor", "thinker"]:
            return await execute_with_actor(request)
        
        elif request.mode == "tasker":
            return await execute_with_tasker(request)
        
        # Gemini modes
        elif request.mode == "gemini_cua":
            return await execute_with_gemini_cua(request)
        
        elif request.mode in ["gemini", "gemini_hybrid"]:
            # 'gemini' è alias per 'gemini_hybrid' (retrocompatibilità)
            # Usa api_key come fallback per gemini_api_key (il client passa api_key)
            gemini_key = request.gemini_api_key or request.api_key
            
            # Debug: log what we received
            logger.log(f"[DEBUG] mode: {request.mode}")
            logger.log(f"[DEBUG] gemini_api_key presente: {bool(request.gemini_api_key)}")
            logger.log(f"[DEBUG] api_key presente: {bool(request.api_key)}")
            logger.log(f"[DEBUG] gemini_key finale: {bool(gemini_key)}")
            
            # Usa max_steps_per_todo come fallback per max_steps (il client passa max_steps_per_todo)
            max_steps = request.max_steps if request.max_steps != 30 else request.max_steps_per_todo
            
            if not gemini_key:
                return TaskResponse(
                    success=False,
                    error="Gemini API key non configurata. Verifica che sia salvata nelle impostazioni della app.",
                    mode_used="gemini_hybrid"
                )
            
            executor = HybridModeExecutor(headless=request.headless, api_key=gemini_key)
            return await executor.run(request.task_description, request.start_url, max_steps)
        
        else:
            raise HTTPException(status_code=400, detail=f"Mode sconosciuto: {request.mode}")
    
    finally:
        is_running = False


@app.post("/stop")
async def stop_execution():
    global is_running
    is_running = False
    return {"status": "stop richiesto"}


@app.get("/screen")
async def get_screen():
    return get_screen_info()


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║     ARCHITECT'S HAND - TASKER SERVICE v{SERVICE_VERSION}               ║
╠══════════════════════════════════════════════════════════════╣
║  Unified Multi-Provider Computer Use                         ║
║                                                              ║
║  LUX (OpenAGI) - Controlla il tuo PC:                       ║
║    {'✅' if ASYNC_ACTOR_AVAILABLE else '❌'} actor   - AsyncActor, task single-goal             ║
║    {'✅' if ASYNC_ACTOR_AVAILABLE else '❌'} thinker - AsyncActor, più ragionamento            ║
║    {'✅' if TASKER_AGENT_AVAILABLE else '❌'} tasker  - TaskerAgent con todos                   ║
║                                                              ║
║  GEMINI - Browser dedicato:                                  ║
║    {'✅' if GEMINI_AVAILABLE and PLAYWRIGHT_AVAILABLE else '❌'} gemini_cua    - Solo Vision                       ║
║    {'✅' if GEMINI_AVAILABLE and PLAYWRIGHT_AVAILABLE else '❌'} gemini_hybrid - DOM + Vision (Stagehand-like)     ║
║                                                              ║
║  Endpoint: http://127.0.0.1:{SERVICE_PORT}                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT, log_level="info")
