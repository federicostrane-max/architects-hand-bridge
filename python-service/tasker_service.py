#!/usr/bin/env python3
"""
tasker_service.py v7.4.0 - Unified Multi-Provider Computer Use
=============================================================

SUPPORTED PROVIDERS:

1. LUX (Vision + PyAutoGUI - controlla il TUO PC)
   - actor   : AsyncActor per task single-goal
   - thinker : AsyncActor con lux-thinker-1 (più ragionamento)
   - tasker  : TaskerAgent con todos strutturati

2. GEMINI CUA (Vision pura - browser dedicato)
   - Usa Playwright con Edge + persistent context
   - Tool computer_use simulato

3. GEMINI HYBRID (DOM + Vision - browser dedicato)
   - Combina Accessibility Tree + Screenshot
   - Self-healing automatico

Versioni:
- v6.0.7: Switch a Edge per evitare conflitti
- v7.0.0: Unified con Hybrid Mode + Lux completo
- v7.2.2: FIX CRITICO - Risoluzione Lux corretta a 1260x700 (da repo ufficiale oagi)
- v7.2.3: FIX - Usa ImageConfig ufficiale SDK invece di custom ResizedScreenshotMaker
- v7.3.0: ALLINEAMENTO SDK - Fix parametri default (temperature=0.5, max_steps=20/60),
          aggiunto reset_handler(), reflection_interval=20, step_delay=0.3,
          rimossa intercettazione type_via_clipboard (usa handler SDK nativo)
- v7.4.0: FILE LOGGING - Ogni esecuzione crea un file .log in execution_logs/
          con tutti i dettagli per debug facile
- v7.5.0: ENHANCED LOGGING - Sistema isolato per esecuzione (fix race condition),
          log reasoning di Lux, screenshot per step, report HTML automatico
- v7.5.1: EDGE PERSISTENT - Tutti i modi usano Edge con profilo persistente unificato
          (~/.architect-hand-browser) per mantenere i login tra sessioni
- v7.5.2: FIX SCREENSHOT - Gestisce correttamente PILImage dall'SDK oagi
- v7.5.3: FOREGROUND - Porta Edge in primo piano dopo apertura (necessario per Lux vision)
- v7.5.4: FIX FOREGROUND - Usa AttachThreadInput + keybd_event per bypassare
          restrizioni Windows su SetForegroundWindow, fallback Alt+Tab
- v7.5.5: FIX WINDOW DETECT - Cerca Edge per processo (msedge.exe) via psutil,
          non per titolo (che non contiene "edge")
- v7.5.6: MAXIMIZE - Massimizza Edge a schermo intero dopo averlo portato in primo piano
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

SERVICE_VERSION = "7.5.6"
SERVICE_PORT = 8765

# ==========================================================================
# RISOLUZIONE LUX - CORRETTA DA DOCUMENTAZIONE UFFICIALE SDK OAGI
# ==========================================================================
# Fonte: https://github.com/agiopen-org/oagi-python
# 
# from oagi import PILImage, ImageConfig
# config = ImageConfig(
#     format="JPEG",
#     quality=85,
#     width=1260,   # ← RISOLUZIONE UFFICIALE
#     height=700    # ← RISOLUZIONE UFFICIALE
# )
#
# NOTA: La versione precedente usava 1920x1200 che causava imprecisione
# nelle coordinate dei click. Il modello Lux è trainato su 1260x700.
# ==========================================================================
LUX_REF_WIDTH = 1260
LUX_REF_HEIGHT = 700

# Viewport per Gemini (ottimizzato per Computer Use)
VIEWPORT_WIDTH = 1288
VIEWPORT_HEIGHT = 711

# Profile directories - UNIFIED per sessioni persistenti
# Tutti i modi usano lo stesso profilo per mantenere i login
BROWSER_PROFILE_DIR = Path.home() / ".architect-hand-browser"
GEMINI_PROFILE_DIR = BROWSER_PROFILE_DIR  # Alias per retrocompatibilità
HYBRID_PROFILE_DIR = BROWSER_PROFILE_DIR  # Alias per retrocompatibilità

# Models (aggiornati da Stagehand repo ufficiale)
GEMINI_HYBRID_MODEL = "gemini-3-flash-preview"                    # Per Hybrid (DOM + Vision)
GEMINI_CUA_MODEL = "gemini-2.5-computer-use-preview-10-2025"      # Per CUA (solo Vision)

# Analysis directory for reports
ANALYSIS_DIR = Path.home() / ".architect-hand" / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

# Execution logs directory (per debug facile)
EXECUTION_LOGS_DIR = Path(__file__).parent / "execution_logs"
EXECUTION_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# LOGGING - Sistema Isolato per Esecuzione (v7.5.0)
# ============================================================================

class ExecutionContext:
    """
    Contesto di esecuzione isolato per ogni task.
    Risolve race condition: ogni task ha il suo logger/directory.
    """

    def __init__(self, mode: str, task_description: str):
        self.mode = mode
        self.task_description = task_description
        self.start_time = datetime.now()
        self.execution_id = f"{mode}_{self.start_time.strftime('%Y%m%d_%H%M%S%f')}"

        # Directory dedicata per questa esecuzione
        self.execution_dir = EXECUTION_LOGS_DIR / self.execution_id
        self.execution_dir.mkdir(parents=True, exist_ok=True)

        # Files
        self.log_file = self.execution_dir / "execution.log"
        self.report_file = self.execution_dir / "report.html"
        self.screenshots_dir = self.execution_dir / "screenshots"
        self.screenshots_dir.mkdir(exist_ok=True)

        # Data
        self.logs: List[str] = []
        self.steps: List[dict] = []
        self.current_step = 0
        self.success = False
        self.error: Optional[str] = None

        # Scrivi header
        self._write_header()

    def _write_header(self):
        header = [
            "=" * 80,
            f"EXECUTION LOG - {self.execution_id}",
            "=" * 80,
            f"Start Time: {self.start_time.isoformat()}",
            f"Mode: {self.mode}",
            f"Task: {self.task_description}",
            f"Directory: {self.execution_dir}",
            "=" * 80,
            ""
        ]
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(header))
        self.log(f"📁 Execution directory: {self.execution_dir}")

    def log(self, message: str, level: str = "INFO"):
        """Log con timestamp - scrive su file E console"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] [{level}] {message}"
        self.logs.append(formatted)
        print(formatted)

        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(formatted + '\n')
        except Exception as e:
            print(f"[WARN] Failed to write log: {e}")

    def start_step(self, step_num: int, max_steps: int):
        """Inizia un nuovo step"""
        self.current_step = step_num
        self.log(f"\n{'='*60}")
        self.log(f"STEP {step_num}/{max_steps}")
        self.log(f"{'='*60}")

    def log_reasoning(self, reasoning: str):
        """Log del reasoning di Lux"""
        if reasoning:
            self.log(f"🧠 REASONING: {reasoning}")
            if self.steps and self.current_step > 0:
                # Aggiungi reasoning all'ultimo step
                for step in reversed(self.steps):
                    if step.get("step") == self.current_step:
                        step["reasoning"] = reasoning
                        break

    def log_action(self, action_type: str, argument: str = "", coordinates: tuple = None):
        """Log di un'azione"""
        self.log(f"🎯 ACTION: {action_type}")
        if argument:
            self.log(f"   Argument: {argument}")
        if coordinates:
            self.log(f"   Coordinates: ({coordinates[0]}, {coordinates[1]})")

        # Salva nei steps
        step_data = {
            "step": self.current_step,
            "action_type": action_type,
            "argument": argument,
            "coordinates": coordinates,
            "timestamp": datetime.now().isoformat()
        }
        self.steps.append(step_data)

    def save_screenshot(self, screenshot_data, label: str = "") -> Optional[str]:
        """
        Salva screenshot per questo step.

        Args:
            screenshot_data: può essere:
                - str: base64 encoded PNG
                - bytes: raw PNG data
                - PILImage: oggetto PIL Image (dall'SDK oagi)
            label: etichetta opzionale (es. "before", "after")
        """
        try:
            filename = f"step_{self.current_step:03d}"
            if label:
                filename += f"_{label}"
            filename += ".png"

            filepath = self.screenshots_dir / filename

            # Gestisci diversi tipi di input
            if isinstance(screenshot_data, str):
                # Base64 string
                img_data = base64.b64decode(screenshot_data)
                with open(filepath, 'wb') as f:
                    f.write(img_data)
            elif isinstance(screenshot_data, bytes):
                # Raw bytes
                with open(filepath, 'wb') as f:
                    f.write(screenshot_data)
            elif hasattr(screenshot_data, 'save'):
                # PIL Image object (ha metodo save)
                screenshot_data.save(str(filepath), format='PNG')
            elif hasattr(screenshot_data, 'image') and hasattr(screenshot_data.image, 'save'):
                # PILImage wrapper dall'SDK oagi (ha attributo .image che è PIL Image)
                screenshot_data.image.save(str(filepath), format='PNG')
            else:
                # Prova a convertire a bytes
                self.log(f"⚠️ Tipo screenshot sconosciuto: {type(screenshot_data)}", "WARNING")
                return None

            self.log(f"📸 Screenshot: {filename}")

            # Aggiungi path allo step corrente
            for step in reversed(self.steps):
                if step.get("step") == self.current_step:
                    step["screenshot"] = str(filepath)
                    break

            return str(filepath)
        except Exception as e:
            self.log(f"⚠️ Screenshot save failed: {e}", "WARNING")
            import traceback
            traceback.print_exc()
            return None

    def finish(self, success: bool, error: Optional[str] = None):
        """Finalizza esecuzione e genera report"""
        self.success = success
        self.error = error
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        # Log footer
        self.log("")
        self.log("=" * 80)
        self.log(f"EXECUTION {'COMPLETED' if success else 'FAILED'}")
        self.log(f"End Time: {end_time.isoformat()}")
        self.log(f"Duration: {duration:.1f}s")
        self.log(f"Steps: {len(self.steps)}")
        if error:
            self.log(f"Error: {error}")
        self.log("=" * 80)

        # Genera report HTML
        self._generate_html_report(duration)

        print(f"\n📄 Log: {self.log_file}")
        print(f"📊 Report: {self.report_file}\n")

    def _generate_html_report(self, duration: float):
        """Genera report HTML dettagliato"""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>LUX Report - {self.execution_id}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #f5f5f5; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; margin-bottom: 20px; }}
        .header h1 {{ margin: 0 0 10px 0; }}
        .header .task {{ font-size: 14px; opacity: 0.9; white-space: pre-wrap; }}
        .stats {{ display: flex; gap: 20px; margin-top: 15px; }}
        .stat {{ background: rgba(255,255,255,0.2); padding: 10px 20px; border-radius: 8px; }}
        .stat-value {{ font-size: 24px; font-weight: bold; }}
        .stat-label {{ font-size: 12px; opacity: 0.8; }}
        .step {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .step-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 15px; }}
        .step-num {{ background: #667eea; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold; }}
        .reasoning {{ background: #e8f4f8; padding: 15px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #667eea; }}
        .reasoning-label {{ font-weight: bold; color: #667eea; margin-bottom: 5px; }}
        .action {{ background: #f8f9fa; padding: 12px; border-radius: 6px; margin-bottom: 8px; }}
        .action-type {{ display: inline-block; background: #007bff; color: white; padding: 2px 10px; border-radius: 4px; font-size: 12px; margin-right: 10px; }}
        .action-type.click {{ background: #007bff; }}
        .action-type.type {{ background: #28a745; }}
        .action-type.scroll {{ background: #ffc107; color: black; }}
        .action-type.wait {{ background: #6c757d; }}
        .action-type.hotkey {{ background: #17a2b8; }}
        .action-type.drag {{ background: #fd7e14; }}
        .action-type.left_double {{ background: #dc3545; }}
        .screenshot {{ max-width: 100%; border-radius: 8px; margin-top: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }}
        .success {{ border-left: 4px solid #28a745; }}
        .failed {{ border-left: 4px solid #dc3545; }}
        .status-badge {{ display: inline-block; padding: 5px 15px; border-radius: 20px; font-weight: bold; }}
        .status-success {{ background: #28a745; color: white; }}
        .status-failed {{ background: #dc3545; color: white; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 LUX Execution Report</h1>
        <div class="task">{self.task_description}</div>
        <div class="stats">
            <div class="stat">
                <div class="stat-value">{len(self.steps)}</div>
                <div class="stat-label">Steps</div>
            </div>
            <div class="stat">
                <div class="stat-value">{duration:.1f}s</div>
                <div class="stat-label">Duration</div>
            </div>
            <div class="stat">
                <div class="stat-value">
                    <span class="status-badge {'status-success' if self.success else 'status-failed'}">
                        {'✓ Success' if self.success else '✗ Failed'}
                    </span>
                </div>
                <div class="stat-label">Status</div>
            </div>
        </div>
    </div>
"""

        # Raggruppa steps per numero
        steps_by_num = {}
        for step in self.steps:
            num = step.get("step", 0)
            if num not in steps_by_num:
                steps_by_num[num] = {"actions": [], "reasoning": None, "screenshot": None}
            steps_by_num[num]["actions"].append(step)
            if step.get("reasoning"):
                steps_by_num[num]["reasoning"] = step["reasoning"]
            if step.get("screenshot"):
                steps_by_num[num]["screenshot"] = step["screenshot"]

        # Genera HTML per ogni step
        for step_num in sorted(steps_by_num.keys()):
            step_data = steps_by_num[step_num]
            html += f"""
    <div class="step {'success' if self.success else ''}">
        <div class="step-header">
            <span class="step-num">Step {step_num}</span>
        </div>
"""
            if step_data["reasoning"]:
                html += f"""
        <div class="reasoning">
            <div class="reasoning-label">🧠 LUX Reasoning:</div>
            {step_data["reasoning"]}
        </div>
"""

            html += "        <div><strong>Actions:</strong></div>\n"

            for action in step_data["actions"]:
                action_type = action.get("action_type", "unknown")
                argument = action.get("argument", "")
                coords = action.get("coordinates")

                html += f"""
        <div class="action">
            <span class="action-type {action_type.lower()}">{action_type.upper()}</span>
"""
                if coords:
                    html += f"            <span>({coords[0]}, {coords[1]})</span>\n"
                if argument:
                    html += f"            <span>{argument[:100]}</span>\n"
                html += "        </div>\n"

            # Screenshot (usa path relativo)
            if step_data["screenshot"]:
                screenshot_path = Path(step_data["screenshot"])
                relative_path = f"screenshots/{screenshot_path.name}"
                html += f"""
        <img class="screenshot" src="{relative_path}" alt="Step {step_num} screenshot">
"""

            html += "    </div>\n"

        # Footer
        html += f"""
    <div class="step">
        <h3>📋 Execution Summary</h3>
        <p><strong>Execution ID:</strong> {self.execution_id}</p>
        <p><strong>Mode:</strong> {self.mode}</p>
        <p><strong>Duration:</strong> {duration:.1f} seconds</p>
        <p><strong>Total Steps:</strong> {len(steps_by_num)}</p>
        <p><strong>Total Actions:</strong> {len(self.steps)}</p>
        {"<p><strong>Error:</strong> " + self.error + "</p>" if self.error else ""}
    </div>
</body>
</html>
"""

        with open(self.report_file, 'w', encoding='utf-8') as f:
            f.write(html)

    def get_logs(self) -> List[str]:
        return self.logs.copy()

    def get_log_path(self) -> str:
        return str(self.log_file)

    def get_report_path(self) -> str:
        return str(self.report_file)


class TaskLogger:
    """
    Logger globale per messaggi di sistema (startup, dependency checks).
    Per le esecuzioni task, usa ExecutionContext.
    """

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


# Logger globale solo per startup/system messages
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
RESET_HANDLER_AVAILABLE = False

try:
    from oagi import (
        AsyncActor,
        TaskerAgent,
        AsyncAgentObserver,
        AsyncScreenshotMaker,
        AsyncPyautoguiActionHandler,
        PyautoguiConfig,
        ImageConfig  # Per configurare resize screenshot a 1260x700
    )
    from oagi.handler.utils import reset_handler  # Per reset stato handler a inizio/fine task
    ASYNC_ACTOR_AVAILABLE = True
    TASKER_AGENT_AVAILABLE = True
    ASYNC_AGENT_OBSERVER_AVAILABLE = True
    OAGI_AVAILABLE = True
    RESET_HANDLER_AVAILABLE = True
    logger.log("✅ OAGI SDK completo (AsyncActor, TaskerAgent, handlers, reset_handler)")
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
    
    # Lux settings (default da SDK ufficiale oagi/constants.py)
    model: str = "lux-actor-1"
    max_steps: int = 20              # DEFAULT_MAX_STEPS = 20 (Actor)
    max_steps_per_todo: int = 60     # DEFAULT_MAX_STEPS_TASKER = 60
    temperature: float = 0.5         # DEFAULT_TEMPERATURE = 0.5
    step_delay: float = 0.3          # DEFAULT_STEP_DELAY = 0.3
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
    
    # Browser reuse settings
    reuse_browser: bool = True  # True = riusa pagina esistente, False = nuova pagina
    new_tab: bool = False  # True = apre nuova tab nello stesso browser (mantiene login)


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
    log_file: Optional[str] = None      # Path del file di log completo
    report_file: Optional[str] = None   # Path del report HTML (v7.5.0)


class StatusResponse(BaseModel):
    status: str
    version: str
    providers: dict
    modes: List[str]
    # Campi flat per retrocompatibilità con bridge
    oagi_available: bool = False
    gemini_available: bool = False
    playwright_available: bool = False


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
# BROWSER: Open Edge with Persistent Profile (for Lux modes)
# ============================================================================

def bring_edge_to_foreground() -> bool:
    """
    Porta la finestra di Edge in primo piano.

    Windows ha restrizioni su SetForegroundWindow - non funziona se il processo
    chiamante non è in primo piano. Usiamo diversi workaround:
    1. AttachThreadInput per "rubare" il focus
    2. Simula Alt key per bypassare le restrizioni
    3. Fallback con click sulla taskbar
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Trova la finestra di Edge cercando per CLASSE della finestra
        # Edge usa la classe "Chrome_WidgetWin_1" (come Chrome, è basato su Chromium)
        # Ma possiamo anche cercare per processo
        edge_hwnd = None
        edge_windows = []

        def enum_windows_callback(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                # Ottieni nome della classe
                class_name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_name, 256)

                # Ottieni titolo
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value

                # Edge usa classe "Chrome_WidgetWin_1" e il processo è msedge.exe
                # Controlliamo il processo
                if class_name.value == "Chrome_WidgetWin_1" and title:
                    # Ottieni PID del processo
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                    # Controlla se è Edge verificando il nome del processo
                    try:
                        import psutil
                        proc = psutil.Process(pid.value)
                        if "msedge" in proc.name().lower():
                            edge_windows.append((hwnd, title))
                            logger.log(f"🔍 Trovata finestra Edge: '{title[:50]}...' (hwnd: {hwnd})")
                    except:
                        # psutil non disponibile, usa euristica sul titolo
                        # Edge aggiunge "- Microsoft Edge" o "- Microsoft​ Edge" al titolo
                        # Ma a volte no! Quindi controlliamo altri pattern
                        title_lower = title.lower()
                        # Escludi finestre Chrome esplicite
                        if "chrome" not in title_lower and "google" not in title_lower:
                            # Potrebbe essere Edge
                            edge_windows.append((hwnd, title))
                            logger.log(f"🔍 Possibile finestra Edge: '{title[:50]}...' (hwnd: {hwnd})")
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

        if not edge_windows:
            logger.log("⚠️ Nessuna finestra Edge trovata", "WARNING")
            return _click_edge_taskbar()

        # Prendi la prima (più recente)
        edge_hwnd, edge_title = edge_windows[0]
        logger.log(f"✅ Selezionata finestra Edge: '{edge_title[:50]}...' (hwnd: {edge_hwnd})")

        # Metodo 1: AttachThreadInput + SetForegroundWindow
        # Questo "attacca" il nostro thread al thread della finestra foreground
        foreground_hwnd = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()

        # Attach al thread foreground
        user32.AttachThreadInput(current_thread, foreground_thread, True)

        try:
            # Costanti ShowWindow
            SW_RESTORE = 9
            SW_MAXIMIZE = 3
            SW_SHOWMAXIMIZED = 3

            # Prima ripristina se minimizzata
            user32.ShowWindow(edge_hwnd, SW_RESTORE)

            # Simula pressione Alt per bypassare restrizioni Windows
            # (Windows permette SetForegroundWindow dopo un input event)
            VK_MENU = 0x12  # Alt key
            KEYEVENTF_EXTENDEDKEY = 0x0001
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

            # Ora SetForegroundWindow dovrebbe funzionare
            user32.SetForegroundWindow(edge_hwnd)
            user32.BringWindowToTop(edge_hwnd)

            # MASSIMIZZA la finestra a schermo intero
            user32.ShowWindow(edge_hwnd, SW_MAXIMIZE)
            logger.log("📐 Finestra Edge massimizzata")

            # Imposta focus
            user32.SetFocus(edge_hwnd)

        finally:
            # Detach dal thread
            user32.AttachThreadInput(current_thread, foreground_thread, False)

        # Verifica se ha funzionato
        time.sleep(0.3)
        new_foreground = user32.GetForegroundWindow()

        if new_foreground == edge_hwnd:
            logger.log(f"✅ Edge in primo piano e massimizzato")
            return True
        else:
            logger.log("⚠️ SetForegroundWindow non ha funzionato, provo click taskbar", "WARNING")
            # Fallback: click sulla taskbar
            return _click_edge_taskbar()

    except Exception as e:
        logger.log(f"⚠️ Errore bring_edge_to_foreground: {e}", "WARNING")
        import traceback
        traceback.print_exc()
        return _click_edge_taskbar()


def _click_edge_taskbar() -> bool:
    """
    Fallback: trova e clicca sull'icona Edge nella taskbar.
    """
    try:
        if not PYAUTOGUI_AVAILABLE:
            return False

        logger.log("🖱️ Tentativo click su taskbar Edge...")

        # La taskbar è tipicamente in basso, cerca l'icona Edge
        # Ottieni dimensioni schermo
        screen_width, screen_height = pyautogui.size()

        # La taskbar è alta circa 40-48 pixel in basso
        taskbar_y = screen_height - 24  # Centro della taskbar

        # Cerca l'icona Edge nella taskbar usando pyautogui.locateOnScreen
        # Ma questo richiede un'immagine di riferimento, quindi usiamo un approccio diverso:
        # Prova Win+1, Win+2, etc. per attivare le app nella taskbar

        # Metodo più semplice: usa Alt+Tab ripetutamente per trovare Edge
        # O meglio: usa Win+Tab e poi click

        # Prova con pyautogui.hotkey per simulare Win+numero
        # Prima proviamo Alt+Tab
        pyautogui.keyDown('alt')
        time.sleep(0.1)
        pyautogui.press('tab')
        time.sleep(0.3)

        # Cerca "Edge" nel task switcher (potrebbe non funzionare sempre)
        # Rilascia Alt per selezionare
        pyautogui.keyUp('alt')

        logger.log("🔄 Usato Alt+Tab")
        return True

    except Exception as e:
        logger.log(f"⚠️ Click taskbar fallito: {e}", "WARNING")
        return False


async def open_edge_persistent(url: Optional[str] = None, wait_seconds: float = 3.0) -> bool:
    """
    Apre Microsoft Edge con profilo persistente per Lux modes.

    - Usa lo stesso profilo di Gemini modes per mantenere i login
    - Se url è fornito, naviga a quell'URL
    - Porta Edge in primo piano per Lux
    - Aspetta che il browser sia pronto prima di ritornare

    Returns: True se browser aperto con successo
    """
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # Trova il path di Edge
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]

    edge_exe = None
    for path in edge_paths:
        if Path(path).exists():
            edge_exe = path
            break

    if not edge_exe:
        logger.log("⚠️ Microsoft Edge non trovato", "WARNING")
        return False

    # Costruisci comando
    cmd = [
        edge_exe,
        f"--user-data-dir={BROWSER_PROFILE_DIR}",
        "--no-first-run",
        "--disable-features=msEdgeEnhancedSecurityMode",
        "--start-maximized",
    ]

    if url:
        cmd.append(url)

    try:
        logger.log(f"🌐 Apertura Edge con profilo persistente: {BROWSER_PROFILE_DIR}")
        if url:
            logger.log(f"📍 URL: {url}")

        # Avvia Edge
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Aspetta che il browser si apra
        await asyncio.sleep(wait_seconds)

        # Porta Edge in primo piano
        bring_edge_to_foreground()

        # Aspetta un attimo per il focus
        await asyncio.sleep(0.5)

        logger.log("✅ Edge aperto e in primo piano")
        return True

    except Exception as e:
        logger.log(f"❌ Errore apertura Edge: {e}", "ERROR")
        return False


# ============================================================================
# LUX: COORDINATE SCALING
# ============================================================================
# NOTA: ResizedScreenshotMaker rimossa - ora usiamo AsyncScreenshotMaker con
# ImageConfig ufficiale dell'SDK (width=1260, height=700)
# ============================================================================

def scale_coordinates(x: int, y: int) -> tuple:
    """
    Scala le coordinate dalla risoluzione Lux a quella reale dello schermo.
    
    RISOLUZIONE LUX: 1260x700 (documentazione ufficiale SDK oagi)
    
    Lux restituisce coordinate basate su 1260x700.
    Se il tuo schermo è diverso (es. 1920x1080, 2560x1440), 
    le coordinate vanno scalate proporzionalmente.
    
    Esempio:
        Lux click: (630, 350)  # Centro in 1260x700
        Schermo: 2560x1440
        Risultato: (1280, 720)  # Centro scalato
    """
    if not PYAUTOGUI_AVAILABLE:
        return x, y
        
    screen_width, screen_height = pyautogui.size()
    
    x_scaled = int(x * screen_width / LUX_REF_WIDTH)
    y_scaled = int(y * screen_height / LUX_REF_HEIGHT)
    
    logger.log(f"🎯 Coordinate: Lux({x}, {y}) → Screen({x_scaled}, {y_scaled})")
    
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

    v7.5.0: Usa ExecutionContext per logging isolato con:
    - Screenshot salvati per ogni step
    - Reasoning di Lux catturato
    - Report HTML automatico

    v7.5.1: Apre automaticamente Edge con profilo persistente se start_url è fornito
    """
    # Crea contesto isolato per questa esecuzione
    ctx = ExecutionContext(request.mode, request.task_description)

    if not ASYNC_ACTOR_AVAILABLE:
        ctx.finish(False, "AsyncActor non disponibile. Installa: pip install openagi")
        return TaskResponse(
            success=False,
            error="AsyncActor non disponibile. Installa: pip install openagi",
            mode_used=request.mode,
            log_file=ctx.get_log_path()
        )

    # Se c'è un start_url, apri Edge con profilo persistente
    if request.start_url:
        ctx.log(f"🌐 Apertura Edge per URL: {request.start_url}")
        browser_opened = await open_edge_persistent(request.start_url, wait_seconds=3.0)
        if not browser_opened:
            ctx.log("⚠️ Impossibile aprire Edge, Lux procederà comunque", "WARNING")

    # Seleziona modello
    model = "lux-thinker-1" if request.mode == "thinker" else "lux-actor-1"

    ctx.log(f"LUX {request.mode.upper()} MODE - v{SERVICE_VERSION}")
    ctx.log(f"Model: {model}")
    ctx.log(f"Max steps: {request.max_steps}")

    # Screen info
    if PYAUTOGUI_AVAILABLE:
        screen_width, screen_height = pyautogui.size()
        ctx.log(f"Screen reale: {screen_width}x{screen_height}")
        ctx.log(f"Lux reference: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT} (ufficiale)")
        ctx.log(f"Scale factor: {screen_width/LUX_REF_WIDTH:.2f}x, {screen_height/LUX_REF_HEIGHT:.2f}y")

    step_count = 0
    done = False

    try:
        # API key
        api_key = request.api_key or os.getenv("OAGI_API_KEY")
        if not api_key:
            raise ValueError("OAGI_API_KEY non configurata")

        # Crea handlers
        pyautogui_config = PyautoguiConfig(
            drag_duration=request.drag_duration,
            scroll_amount=request.scroll_amount,
            wait_duration=request.wait_duration,
            action_pause=request.action_pause
        )

        if request.enable_screenshot_resize:
            image_config = ImageConfig(
                format="JPEG",
                quality=85,
                width=LUX_REF_WIDTH,
                height=LUX_REF_HEIGHT
            )
            image_provider = AsyncScreenshotMaker(config=image_config)
            ctx.log(f"📸 Screenshot resize: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT} (SDK ufficiale)")
        else:
            image_provider = AsyncScreenshotMaker()
            ctx.log("📸 Screenshot: risoluzione nativa (⚠️ potrebbe causare imprecisione)")

        action_handler = AsyncPyautoguiActionHandler(config=pyautogui_config)
        ctx.log("🎮 Action handler: PyAutoGUI")

        # Reset handler state
        if RESET_HANDLER_AVAILABLE:
            reset_handler(action_handler)
            ctx.log("🔄 Handler state reset")

        # Execution loop
        async with AsyncActor(api_key=api_key, model=model) as actor:
            await actor.init_task(
                task_desc=request.task_description,
                max_steps=request.max_steps
            )

            while not done and step_count < request.max_steps:
                step_count += 1
                ctx.start_step(step_count, request.max_steps)

                # Cattura screenshot
                screenshot_b64 = await image_provider()

                # Salva screenshot PRIMA dell'azione
                ctx.save_screenshot(screenshot_b64, "before")

                # Chiedi azione a Lux
                step_result = await actor.step(screenshot_b64)

                # Log reasoning (se disponibile)
                if hasattr(step_result, 'reasoning') and step_result.reasoning:
                    ctx.log_reasoning(step_result.reasoning)
                elif hasattr(step_result, 'thought') and step_result.thought:
                    ctx.log_reasoning(step_result.thought)

                # Controlla se task completato
                if step_result.stop:
                    ctx.log("✅ Task completato!")
                    done = True
                    break

                # Esegui azioni
                for action in step_result.actions:
                    action_type = str(action.type.value) if hasattr(action.type, "value") else str(action.type)
                    argument = str(action.argument) if hasattr(action, "argument") else ""

                    # Estrai coordinate se presenti
                    coordinates = None
                    if hasattr(action, 'x') and hasattr(action, 'y'):
                        coordinates = (action.x, action.y)
                    elif hasattr(action, 'coordinate') and action.coordinate:
                        coordinates = (action.coordinate.x, action.coordinate.y)

                    ctx.log_action(action_type, argument, coordinates)

                    # Esegui via SDK handler
                    await action_handler([action])

                    # Delay tra azioni
                    await asyncio.sleep(request.step_delay)

                # Salva screenshot DOPO le azioni
                screenshot_after = await image_provider()
                ctx.save_screenshot(screenshot_after, "after")

        # Reset handler state a fine
        if RESET_HANDLER_AVAILABLE:
            reset_handler(action_handler)
            ctx.log("🔄 Handler state reset (fine)")

        # Finalizza e genera report
        ctx.finish(done)

        return TaskResponse(
            success=done,
            message="Task completato" if done else f"Max steps ({request.max_steps}) raggiunto",
            steps_executed=step_count,
            mode_used=request.mode,
            actions_log=ctx.steps,
            logs=ctx.get_logs(),
            log_file=ctx.get_log_path(),
            report_file=ctx.get_report_path()
        )

    except Exception as e:
        ctx.log(f"❌ Errore: {e}", "ERROR")
        import traceback
        traceback.print_exc()

        # Finalizza anche in caso di errore
        ctx.finish(False, str(e))

        return TaskResponse(
            success=False,
            error=str(e),
            steps_executed=step_count,
            mode_used=request.mode,
            logs=ctx.get_logs(),
            log_file=ctx.get_log_path(),
            report_file=ctx.get_report_path()
        )


# ============================================================================
# LUX: TASKER MODE EXECUTION (con Todos)
# ============================================================================

async def execute_with_tasker(request: TaskRequest) -> TaskResponse:
    """
    Esegue task usando TaskerAgent con lista di todos.

    Ogni todo viene eseguito in sequenza con max_steps_per_todo step.
    Il TaskerAgent traccia quali todos sono completati.

    v7.5.0: Usa ExecutionContext per logging isolato.
    v7.5.1: Apre automaticamente Edge con profilo persistente se start_url è fornito.
    """
    todos = request.todos or []

    # Crea contesto isolato per questa esecuzione
    ctx = ExecutionContext("tasker", request.task_description)

    # Se c'è un start_url, apri Edge con profilo persistente
    if request.start_url:
        ctx.log(f"🌐 Apertura Edge per URL: {request.start_url}")
        browser_opened = await open_edge_persistent(request.start_url, wait_seconds=3.0)
        if not browser_opened:
            ctx.log("⚠️ Impossibile aprire Edge, Lux procederà comunque", "WARNING")

    if not TASKER_AGENT_AVAILABLE:
        ctx.finish(False, "TaskerAgent non disponibile. Installa: pip install openagi")
        return TaskResponse(
            success=False,
            error="TaskerAgent non disponibile. Installa: pip install openagi",
            mode_used="tasker",
            log_file=ctx.get_log_path(),
            report_file=ctx.get_report_path()
        )

    if not todos:
        ctx.finish(False, "Tasker mode richiede una lista di todos")
        return TaskResponse(
            success=False,
            error="Tasker mode richiede una lista di todos",
            mode_used="tasker",
            log_file=ctx.get_log_path(),
            report_file=ctx.get_report_path()
        )

    ctx.log(f"LUX TASKER MODE - v{SERVICE_VERSION}")
    ctx.log(f"Todos: {len(todos)}")
    for i, todo in enumerate(todos):
        ctx.log(f"  [{i+1}] {todo[:60]}...")

    # Screen info
    if PYAUTOGUI_AVAILABLE:
        screen_width, screen_height = pyautogui.size()
        ctx.log(f"Screen reale: {screen_width}x{screen_height}")
        ctx.log(f"Lux reference: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT} (ufficiale)")

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
            ctx.log("📊 Observer abilitato")

        # Crea image provider
        if request.enable_screenshot_resize:
            # Usa ImageConfig ufficiale dell'SDK per resize a 1260x700
            image_config = ImageConfig(
                format="JPEG",
                quality=85,
                width=LUX_REF_WIDTH,   # 1260
                height=LUX_REF_HEIGHT  # 700
            )
            image_provider = AsyncScreenshotMaker(config=image_config)
            ctx.log(f"📸 Screenshot resize: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT} (SDK ufficiale)")
        else:
            image_provider = AsyncScreenshotMaker()
            ctx.log("📸 Screenshot: risoluzione nativa (⚠️ potrebbe causare imprecisione)")

        # Crea action handler
        action_handler = AsyncPyautoguiActionHandler(config=pyautogui_config)
        ctx.log("🎮 Action handler: PyAutoGUI")

        # Reset handler state a inizio automazione (best practice SDK)
        if RESET_HANDLER_AVAILABLE:
            reset_handler(action_handler)
            ctx.log("🔄 Handler state reset")

        # Crea TaskerAgent con parametri da SDK (constants.py)
        tasker_kwargs = {
            "api_key": api_key,
            "base_url": "https://api.agiopen.org",
            "model": "lux-actor-1",  # Tasker usa sempre actor
            "max_steps": request.max_steps_per_todo,         # DEFAULT_MAX_STEPS_TASKER = 60
            "temperature": request.temperature,              # DEFAULT_TEMPERATURE = 0.5
            "reflection_interval": 20,                       # DEFAULT_REFLECTION_INTERVAL_TASKER = 20
        }

        if observer:
            tasker_kwargs["step_observer"] = observer

        ctx.log(f"Creating TaskerAgent:")
        ctx.log(f"  model: lux-actor-1")
        ctx.log(f"  max_steps_per_todo: {request.max_steps_per_todo}")
        ctx.log(f"  temperature: {request.temperature}")
        ctx.log(f"  reflection_interval: 20")

        tasker = TaskerAgent(**tasker_kwargs)

        # Set task e todos
        tasker.set_task(
            task=request.task_description,
            todos=todos
        )

        ctx.log("🚀 Avvio esecuzione TaskerAgent...")

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
                ctx.log(f"📋 Summary: {memory.task_execution_summary}")

                for i, todo_mem in enumerate(memory.todos):
                    status = todo_mem.status.value if hasattr(todo_mem.status, 'value') else str(todo_mem.status)
                    todo_statuses.append({
                        "index": i,
                        "description": todo_mem.description,
                        "status": status
                    })
                    if status == "completed":
                        completed_todos += 1
                    ctx.log(f"  [{i+1}] {status}: {todo_mem.description[:50]}...")
        except Exception as mem_err:
            ctx.log(f"⚠️ Memory non disponibile: {mem_err}", "WARNING")
            completed_todos = len(todos) if success else 0

        # Esporta report observer (oltre al nostro report HTML)
        if observer:
            try:
                observer_file = ctx.execution_dir / "observer_history.html"
                observer.export("html", str(observer_file))
                ctx.log(f"📊 Observer report: {observer_file}")
            except Exception as obs_err:
                ctx.log(f"⚠️ Export observer fallito: {obs_err}", "WARNING")

        # Reset handler state a fine automazione (best practice SDK)
        if RESET_HANDLER_AVAILABLE:
            reset_handler(action_handler)
            ctx.log("🔄 Handler state reset (fine)")

        # Finalizza e genera report
        ctx.finish(success)

        return TaskResponse(
            success=success,
            message=f"Completati {completed_todos}/{len(todos)} todos",
            steps_executed=request.max_steps_per_todo * len(todos),
            completed_todos=completed_todos,
            total_todos=len(todos),
            mode_used="tasker",
            actions_log=todo_statuses,
            logs=ctx.get_logs(),
            log_file=ctx.get_log_path(),
            report_file=ctx.get_report_path()
        )

    except Exception as e:
        ctx.log(f"❌ Errore: {e}", "ERROR")
        import traceback
        traceback.print_exc()

        # Finalizza anche in caso di errore
        ctx.finish(False, str(e))

        return TaskResponse(
            success=False,
            error=str(e),
            total_todos=len(todos),
            mode_used="tasker",
            logs=ctx.get_logs(),
            log_file=ctx.get_log_path(),
            report_file=ctx.get_report_path()
        )


# ============================================================================
# GEMINI HYBRID MODE (DOM + Vision)
# ============================================================================

class ActionType(Enum):
    """Tipi di azione per Hybrid Mode"""
    ACT_DOM = "act_dom"
    CLICK_VISION = "click_vision"
    DOUBLE_CLICK = "double_click"  # Nuovo per loop handling
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
        self.api_key = api_key
        self.action_history: List[dict] = []  # History per loop detection
        
        if GEMINI_AVAILABLE:
            # Usa api_key passata o fallback a env var
            key = api_key or os.getenv("GEMINI_API_KEY")
            if key:
                self.client = genai.Client(api_key=key)
                logger.log(f"✅ Gemini Client configurato per: {GEMINI_HYBRID_MODEL}")
            else:
                raise ValueError("Gemini API key non configurata")
    
    def is_browser_open(self) -> bool:
        """Verifica se il browser è ancora aperto e funzionante"""
        try:
            return self.context is not None and self.page is not None and not self.page.is_closed()
        except:
            return False
    
    async def start_browser(self, start_url: Optional[str] = None, new_tab: bool = False):
        """Avvia browser Edge con profilo persistente o riusa esistente"""
        
        # Se il browser è già aperto
        if self.is_browser_open():
            if new_tab:
                # Apri nuova tab (mantiene login perché stesso context)
                logger.log("📑 Apertura nuova tab (login mantenuto)")
                self.page = await self.context.new_page()
                if start_url:
                    logger.log(f"📍 Navigazione: {start_url}")
                    await self.page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(1)
            else:
                # Riusa la pagina esistente
                logger.log(f"♻️ Riuso pagina esistente: {self.page.url}")
                if start_url:
                    logger.log(f"📍 Navigazione: {start_url}")
                    await self.page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(1)
            return
        
        # Avvia nuovo browser
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
        self.context = None
        self.page = None
        self.playwright = None
    
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
    
    def _detect_loop(self) -> bool:
        """Rileva se siamo in un loop (3+ azioni simili consecutive)"""
        if len(self.action_history) < 3:
            return False
        
        last_3 = self.action_history[-3:]
        
        # Verifica se le ultime 3 azioni sono dello stesso tipo
        action_types = [a.get("action") for a in last_3]
        if len(set(action_types)) == 1 and action_types[0] in ["click_vision", "act_dom"]:
            # Verifica se le coordinate sono simili (entro 50px)
            if action_types[0] == "click_vision":
                coords = [(a.get("x", 0), a.get("y", 0)) for a in last_3]
                x_range = max(c[0] for c in coords) - min(c[0] for c in coords)
                y_range = max(c[1] for c in coords) - min(c[1] for c in coords)
                if x_range < 50 and y_range < 50:
                    logger.log("🔄 LOOP RILEVATO: 3+ click simili sulle stesse coordinate", "WARNING")
                    return True
            elif action_types[0] == "act_dom":
                selectors = [a.get("selector", "") for a in last_3]
                if len(set(selectors)) == 1:
                    logger.log("🔄 LOOP RILEVATO: 3+ click sullo stesso selettore", "WARNING")
                    return True
        
        return False
    
    def _get_history_for_prompt(self) -> str:
        """Genera stringa delle ultime azioni per il prompt"""
        if not self.action_history:
            return "Nessuna azione precedente."
        
        lines = []
        for i, action in enumerate(self.action_history[-5:], 1):  # Ultime 5 azioni
            action_type = action.get("action", "unknown")
            if action_type == "click_vision":
                lines.append(f"  {i}. click_vision ({action.get('x')}, {action.get('y')})")
            elif action_type == "act_dom":
                lines.append(f"  {i}. act_dom selector='{action.get('selector', '')[:50]}'")
            elif action_type == "type":
                lines.append(f"  {i}. type '{action.get('text', '')[:30]}...'")
            elif action_type == "navigate":
                lines.append(f"  {i}. navigate to {action.get('url', '')[:50]}")
            else:
                lines.append(f"  {i}. {action_type}")
        
        return "\n".join(lines)
    
    def _build_prompt(self, task: str, a11y_tree: str, current_url: str, step: int, loop_detected: bool = False) -> str:
        history_text = self._get_history_for_prompt()
        
        loop_warning = ""
        if loop_detected:
            loop_warning = """
⚠️ ATTENZIONE: HAI RIPETUTO LA STESSA AZIONE 3+ VOLTE SENZA SUCCESSO!
DEVI provare una strategia DIVERSA:
- Se stai cliccando un elemento senza effetto, prova DOPPIO CLICK (double_click)
- Se non riesci a cliccare, prova a SCROLLARE per rendere visibile l'elemento
- Se l'elemento non risponde, prova a usare un selettore diverso
- Se niente funziona, riporta FAIL con spiegazione

"""

        return f"""Sei un agente di automazione web Hybrid (DOM + Vision).

TASK: {task}

URL: {current_url}
Step: {step}

AZIONI PRECEDENTI (ultime 5):
{history_text}
{loop_warning}
ACCESSIBILITY TREE:
```
{a11y_tree[:6000]}
```

STRUMENTI:
1. act_dom - Click via selettore: {{"action": "act_dom", "selector": "...", "reasoning": "..."}}
2. click_vision - Click via coordinate: {{"action": "click_vision", "x": 640, "y": 380, "reasoning": "..."}}
3. double_click - Doppio click via coordinate: {{"action": "double_click", "x": 640, "y": 380, "reasoning": "..."}}
4. type - Digita testo: {{"action": "type", "text": "...", "reasoning": "..."}}
5. scroll - Scrolla: {{"action": "scroll", "direction": "down", "reasoning": "..."}}
6. navigate - Vai a URL: {{"action": "navigate", "url": "...", "reasoning": "..."}}
7. wait - Attendi: {{"action": "wait", "reasoning": "..."}}
8. done - Completato: {{"action": "done", "reasoning": "..."}}
9. fail - Fallito: {{"action": "fail", "reasoning": "..."}}

Preferisci act_dom quando possibile. Coordinate: viewport {VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}.
NON ripetere azioni che non hanno funzionato. Se un click non funziona, prova double_click o scroll.
Rispondi SOLO con il JSON:"""
    
    async def analyze_and_decide(self, task: str, step: int, retry_count: int = 0) -> HybridAction:
        screenshot_b64 = await self.capture_screenshot()
        a11y_tree = await self.get_accessibility_tree()
        current_url = self.page.url
        
        # Rileva loop
        loop_detected = self._detect_loop()
        
        prompt = self._build_prompt(task, a11y_tree, current_url, step, loop_detected)
        
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
            
            # Estrai JSON dalla risposta
            if "```" in response_text:
                # Trova il blocco di codice
                parts = response_text.split("```")
                for part in parts:
                    part = part.replace("json", "").strip()
                    if part.startswith("{"):
                        response_text = part
                        break
            
            # Prova a riparare JSON comuni errori
            response_text = self._try_fix_json(response_text)
            
            try:
                action_data = json.loads(response_text)
                return self._parse_action(action_data)
            except json.JSONDecodeError as json_err:
                logger.log(f"⚠️ JSON malformato: {json_err}", "WARNING")
                logger.log(f"⚠️ Risposta: {response_text[:200]}...", "WARNING")
                
                # Retry fino a 2 volte
                if retry_count < 2:
                    logger.log(f"🔄 Retry {retry_count + 1}/2...", "INFO")
                    await asyncio.sleep(0.5)
                    return await self.analyze_and_decide(task, step, retry_count + 1)
                
                # Dopo 2 retry, ritorna WAIT invece di FAIL
                logger.log("⏳ Troppi errori JSON, aspetto e continuo...", "WARNING")
                return HybridAction(action_type=ActionType.WAIT, reasoning="Errore parsing, attendo")
            
        except Exception as e:
            logger.log(f"❌ Errore Gemini: {e}", "ERROR")
            
            # Retry per errori di rete
            if retry_count < 2:
                logger.log(f"🔄 Retry {retry_count + 1}/2...", "INFO")
                await asyncio.sleep(1)
                return await self.analyze_and_decide(task, step, retry_count + 1)
            
            return HybridAction(action_type=ActionType.FAIL, reasoning=str(e))
    
    def _try_fix_json(self, text: str) -> str:
        """Prova a riparare JSON comuni errori"""
        text = text.strip()
        
        # Rimuovi caratteri prima di {
        if "{" in text:
            text = text[text.index("{"):]
        
        # Rimuovi caratteri dopo l'ultima }
        if "}" in text:
            text = text[:text.rindex("}") + 1]
        
        # Fix virgolette non chiuse alla fine
        # Count quotes
        quote_count = text.count('"')
        if quote_count % 2 != 0:
            # Aggiungi virgoletta mancante prima dell'ultima }
            text = text[:-1] + '"}'
        
        return text
    
    def _parse_action(self, data: dict) -> HybridAction:
        action_map = {
            "act_dom": ActionType.ACT_DOM,
            "click_vision": ActionType.CLICK_VISION,
            "double_click": ActionType.DOUBLE_CLICK,
            "type": ActionType.TYPE,
            "scroll": ActionType.SCROLL,
            "navigate": ActionType.NAVIGATE,
            "wait": ActionType.WAIT,
            "done": ActionType.DONE,
            "fail": ActionType.FAIL,
        }
        
        # Salva l'azione nella history per loop detection
        self.action_history.append({
            "action": data.get("action", "unknown"),
            "selector": data.get("selector"),
            "x": data.get("x"),
            "y": data.get("y"),
            "text": data.get("text"),
            "url": data.get("url"),
        })
        
        # Mantieni solo le ultime 10 azioni
        if len(self.action_history) > 10:
            self.action_history = self.action_history[-10:]
        
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
            
            elif action.action_type == ActionType.DOUBLE_CLICK:
                # === DOPPIO CLICK (per webmail, elementi che richiedono dblclick) ===
                x, y = action.x, action.y
                logger.log(f"[DOUBLE_CLICK] ({x}, {y})")
                
                try:
                    await self.page.mouse.dblclick(x, y)
                    log_entry["success"] = True
                    log_entry["coordinates"] = {"x": x, "y": y}
                except Exception as e:
                    logger.log(f"[DOUBLE_CLICK] Fallito: {e}", "ERROR")
                    log_entry["error"] = str(e)
            
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
    
    async def run(self, task: str, start_url: Optional[str], max_steps: int = 30, new_tab: bool = False) -> TaskResponse:
        self.actions_log = []
        logger.clear()
        logger.log("=" * 60)
        logger.log(f"GEMINI HYBRID MODE - v{SERVICE_VERSION}")
        logger.log("=" * 60)
        logger.log(f"Task: {task[:80]}...")
        logger.log(f"Reuse browser: {self.is_browser_open()} | New tab: {new_tab}")
        
        try:
            await self.start_browser(start_url, new_tab=new_tab)
            
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
            # NON chiudere il browser - lascialo aperto per l'utente
            # await self.close_browser()
            logger.log("🌐 Browser lasciato aperto")


# ============================================================================
# GEMINI CUA MODE (Vision Only)
# ============================================================================

async def execute_with_gemini_cua(request: TaskRequest) -> TaskResponse:
    """Esegue task con Gemini CUA (solo vision)"""
    logger.clear()
    logger.log("=" * 60)
    logger.log(f"GEMINI CUA MODE - v{SERVICE_VERSION}")
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
                    # NON chiudere il browser - lascialo aperto
                    # await context.close()
                    # await pw.stop()
                    logger.log("🌐 Browser lasciato aperto")
                    return TaskResponse(
                        success=True,
                        result=action_data.get("reasoning", "Task completato"),
                        steps_executed=step,
                        mode_used="gemini_cua",
                        actions_log=actions_log,
                        logs=logger.get_logs()
                    )
                    
                elif action_type == "fail":
                    # NON chiudere il browser - lascialo aperto
                    # await context.close()
                    # await pw.stop()
                    logger.log("🌐 Browser lasciato aperto")
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
        
        # NON chiudere il browser - lascialo aperto
        # await context.close()
        # await pw.stop()
        logger.log("🌐 Browser lasciato aperto")
        
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
# Executor globale per mantenere il browser aperto tra i task
global_hybrid_executor: Optional[HybridModeExecutor] = None


def detect_browser_behavior(task_description: str) -> dict:
    """
    Analizza la descrizione del task per determinare il comportamento del browser.
    
    Returns:
        {"new_tab": bool, "close_current": bool}
    """
    task_lower = task_description.lower()
    
    # Pattern per NUOVA TAB/PAGINA
    new_tab_patterns = [
        "nuova pagina", "nuova tab", "nuovo tab", "nuova scheda",
        "apri una nuova", "in una nuova", "apri nuova",
        "new tab", "new page", "open new", "in a new",
        "altra pagina", "altra tab", "altra scheda",
    ]
    
    # Pattern per CHIUDERE e riaprire
    close_patterns = [
        "chiudi e apri", "riavvia browser", "nuovo browser",
        "close and open", "restart browser", "fresh browser",
        "ricomincia", "da zero", "from scratch",
    ]
    
    # Pattern per USARE PAGINA CORRENTE (esplicito)
    same_page_patterns = [
        "stessa pagina", "questa pagina", "pagina corrente",
        "same page", "current page", "this page",
        "continua", "prosegui", "vai avanti",
    ]
    
    result = {"new_tab": False, "close_current": False}
    
    for pattern in new_tab_patterns:
        if pattern in task_lower:
            result["new_tab"] = True
            logger.log(f"🔍 Rilevato pattern nuova tab: '{pattern}'")
            break
    
    for pattern in close_patterns:
        if pattern in task_lower:
            result["close_current"] = True
            logger.log(f"🔍 Rilevato pattern chiudi browser: '{pattern}'")
            break
    
    for pattern in same_page_patterns:
        if pattern in task_lower:
            result["new_tab"] = False
            result["close_current"] = False
            logger.log(f"🔍 Rilevato pattern stessa pagina: '{pattern}'")
            break
    
    return result


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
        modes.extend(["gemini", "gemini_cua", "gemini_hybrid"])
    
    return StatusResponse(
        status="running" if not is_running else "busy",
        version=SERVICE_VERSION,
        providers={
            "lux": {
                "available": OAGI_AVAILABLE,
                "async_actor": ASYNC_ACTOR_AVAILABLE,
                "tasker_agent": TASKER_AGENT_AVAILABLE,
                "observer": ASYNC_AGENT_OBSERVER_AVAILABLE,
                "reference_resolution": f"{LUX_REF_WIDTH}x{LUX_REF_HEIGHT}",  # Aggiunto per debug
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
        modes=modes,
        # Campi flat per retrocompatibilità con bridge
        oagi_available=OAGI_AVAILABLE,
        gemini_available=GEMINI_AVAILABLE,
        playwright_available=PLAYWRIGHT_AVAILABLE
    )


@app.post("/execute", response_model=TaskResponse)
async def execute_task(request: TaskRequest):
    """
    Esegue un task.

    v7.5.0: Ogni modo crea il proprio ExecutionContext isolato.
    Non c'è più un logger globale per le esecuzioni - ogni modo
    gestisce il proprio logging internamente.
    """
    global is_running

    # Log request info (sistema, non esecuzione)
    logger.log(f"[REQUEST] mode={request.mode} task={request.task_description[:50]}...")

    if is_running:
        logger.log("[REJECTED] Un task è già in esecuzione", "WARNING")
        raise HTTPException(status_code=409, detail="Un task è già in esecuzione")

    is_running = True

    try:
        result = None

        # Lux modes (usano ExecutionContext per logging isolato)
        if request.mode in ["actor", "thinker"]:
            result = await execute_with_actor(request)

        elif request.mode == "tasker":
            result = await execute_with_tasker(request)

        # Gemini modes
        elif request.mode == "gemini_cua":
            result = await execute_with_gemini_cua(request)

        elif request.mode in ["gemini", "gemini_hybrid"]:
            global global_hybrid_executor

            # 'gemini' è alias per 'gemini_hybrid' (retrocompatibilità)
            # Usa api_key come fallback per gemini_api_key (il client passa api_key)
            gemini_key = request.gemini_api_key or request.api_key

            # Rileva comportamento browser dalla descrizione del task
            behavior = detect_browser_behavior(request.task_description)

            # I parametri espliciti nella request hanno priorità
            new_tab = request.new_tab or behavior["new_tab"]
            close_current = behavior["close_current"]

            # Debug: log what we received
            logger.log(f"[DEBUG] mode: {request.mode}")
            logger.log(f"[DEBUG] gemini_api_key presente: {bool(request.gemini_api_key)}")
            logger.log(f"[DEBUG] api_key presente: {bool(request.api_key)}")
            logger.log(f"[DEBUG] gemini_key finale: {bool(gemini_key)}")
            logger.log(f"[DEBUG] reuse_browser: {request.reuse_browser}")
            logger.log(f"[DEBUG] new_tab (rilevato): {new_tab}")
            logger.log(f"[DEBUG] close_current (rilevato): {close_current}")

            # Usa max_steps_per_todo come fallback per max_steps (il client passa max_steps_per_todo)
            max_steps = request.max_steps if request.max_steps != 30 else request.max_steps_per_todo

            if not gemini_key:
                return TaskResponse(
                    success=False,
                    error="Gemini API key non configurata. Verifica che sia salvata nelle impostazioni della app.",
                    mode_used="gemini_hybrid"
                )

            # Se richiesto di chiudere il browser corrente
            if close_current and global_hybrid_executor and global_hybrid_executor.is_browser_open():
                logger.log("🚫 Chiusura browser esistente come richiesto")
                await global_hybrid_executor.close_browser()
                global_hybrid_executor = None

            # Logica per riuso browser
            if request.reuse_browser and global_hybrid_executor and global_hybrid_executor.is_browser_open():
                # Riusa l'executor esistente (browser già aperto)
                logger.log("♻️ Riuso executor esistente")
                executor = global_hybrid_executor
            else:
                # Crea nuovo executor
                logger.log("🆕 Creazione nuovo executor")
                executor = HybridModeExecutor(headless=request.headless, api_key=gemini_key)
                global_hybrid_executor = executor

            result = await executor.run(
                request.task_description,
                request.start_url,
                max_steps,
                new_tab=new_tab
            )

        else:
            raise HTTPException(status_code=400, detail=f"Mode sconosciuto: {request.mode}")

        return result

    except Exception as e:
        logger.log(f"❌ EXCEPTION: {str(e)}", "ERROR")
        raise

    finally:
        is_running = False


@app.post("/stop")
async def stop_execution():
    global is_running
    is_running = False
    return {"status": "stop richiesto"}


@app.post("/close_browser")
async def close_browser():
    """Chiude il browser Gemini se aperto"""
    global global_hybrid_executor
    if global_hybrid_executor and global_hybrid_executor.is_browser_open():
        await global_hybrid_executor.close_browser()
        logger.log("🚫 Browser chiuso")
        return {"status": "browser chiuso"}
    return {"status": "nessun browser aperto"}


@app.get("/browser_status")
async def browser_status():
    """Stato del browser Gemini"""
    global global_hybrid_executor
    if global_hybrid_executor and global_hybrid_executor.is_browser_open():
        return {
            "browser_open": True,
            "current_url": global_hybrid_executor.page.url if global_hybrid_executor.page else None
        }
    return {"browser_open": False, "current_url": None}


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
║    📐 Risoluzione: {LUX_REF_WIDTH}x{LUX_REF_HEIGHT} (ufficiale SDK)                  ║
║                                                              ║
║  GEMINI - Browser dedicato:                                  ║
║    {'✅' if GEMINI_AVAILABLE and PLAYWRIGHT_AVAILABLE else '❌'} gemini_cua    - Solo Vision                       ║
║    {'✅' if GEMINI_AVAILABLE and PLAYWRIGHT_AVAILABLE else '❌'} gemini_hybrid - DOM + Vision (Stagehand-like)     ║
║                                                              ║
║  Endpoint: http://127.0.0.1:{SERVICE_PORT}                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT, log_level="info")
