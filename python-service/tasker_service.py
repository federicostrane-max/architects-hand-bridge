#!/usr/bin/env python3
"""
tasker_service.py v7.0 - Hybrid Mode (DOM + Vision)
====================================================

Implementazione ispirata a Stagehand che combina:
- DOM-based actions (selettori CSS/XPath via Accessibility Tree)
- Vision-based actions (coordinate pixel via screenshot)

Il modello Gemini 3 Flash decide autonomamente quale approccio usare
per ogni singola azione, con self-healing automatico.

Autore: The Architect's Hand
Versione: 7.0.0
"""

import os
import sys
import json
import base64
import asyncio
import time
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum

# FastAPI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Playwright
try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️ Playwright not available")

# Google Gemini
try:
    from google import genai
    from google.genai import types
    from google.genai.types import Content, Part, FunctionDeclaration, Tool, Schema
    GEMINI_AVAILABLE = True
    GEMINI_IMPORT_ERROR = None
except ImportError as e:
    GEMINI_AVAILABLE = False
    GEMINI_IMPORT_ERROR = str(e)
    print(f"⚠️ Gemini SDK not available: {e}")

# ============================================================================
# CONFIGURATION
# ============================================================================

# Modello per Hybrid Mode (DOM + Vision)
GEMINI_HYBRID_MODEL = "gemini-3-flash-preview"

# Modello per CUA puro (solo Vision) - mantenuto per retrocompatibilità
GEMINI_CUA_MODEL = "gemini-2.5-computer-use-preview-10-2025"

# Viewport ottimale per Computer Use (come da Stagehand docs)
VIEWPORT_WIDTH = 1288
VIEWPORT_HEIGHT = 711

# Profile directory per persistent context
HYBRID_PROFILE_DIR = Path.home() / ".hybrid-browser-profile"

# ============================================================================
# DATA CLASSES
# ============================================================================

class ActionType(Enum):
    """Tipi di azione supportati"""
    # DOM-based
    ACT = "act"           # Azione su selettore (click, type, etc.)
    OBSERVE = "observe"   # Osserva elementi nella pagina
    EXTRACT = "extract"   # Estrai dati strutturati
    
    # Vision-based
    CLICK = "click"       # Click su coordinate
    TYPE = "type"         # Digita testo
    SCROLL = "scroll"     # Scroll
    DRAG = "drag"         # Drag and drop
    
    # Control
    WAIT = "wait"         # Attendi
    NAVIGATE = "navigate" # Naviga a URL
    DONE = "done"         # Task completato


@dataclass
class HybridAction:
    """Rappresenta un'azione hybrid (DOM o Vision)"""
    action_type: ActionType
    
    # Per DOM actions
    selector: Optional[str] = None
    instruction: Optional[str] = None
    
    # Per Vision actions
    x: Optional[int] = None
    y: Optional[int] = None
    
    # Parametri comuni
    text: Optional[str] = None
    url: Optional[str] = None
    duration: Optional[int] = None
    
    # Metadata
    reasoning: Optional[str] = None
    confidence: float = 1.0
    fallback_available: bool = True


@dataclass
class ExecutionResult:
    """Risultato di un'esecuzione"""
    success: bool
    action: HybridAction
    screenshot_after: Optional[str] = None
    error: Optional[str] = None
    fallback_used: bool = False
    duration_ms: int = 0


@dataclass
class StepRecord:
    """Record di uno step di esecuzione"""
    turn: int
    action: Optional[HybridAction] = None
    result: Optional[ExecutionResult] = None
    accessibility_tree: Optional[str] = None
    screenshot_before: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


# ============================================================================
# LOGGING
# ============================================================================

class HybridLogger:
    """Logger per Hybrid Mode"""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.logs: List[str] = []
        
    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] [{level}] {message}"
        self.logs.append(formatted)
        if self.verbose:
            print(formatted)
    
    def debug(self, message: str):
        self.log(message, "DEBUG")
    
    def info(self, message: str):
        self.log(message, "INFO")
    
    def warning(self, message: str):
        self.log(message, "WARN")
    
    def error(self, message: str):
        self.log(message, "ERROR")
    
    def action(self, action_type: str, details: str):
        self.log(f"🎯 {action_type}: {details}", "ACTION")
    
    def dom(self, message: str):
        self.log(f"📄 DOM: {message}", "DOM")
    
    def vision(self, message: str):
        self.log(f"👁️ VISION: {message}", "VISION")


logger = HybridLogger()

# ============================================================================
# ACCESSIBILITY TREE EXTRACTOR
# ============================================================================

class AccessibilityTreeExtractor:
    """
    Estrae l'Accessibility Tree dalla pagina.
    Questo è il componente chiave che permette le azioni DOM-based.
    
    L'accessibility tree fornisce una rappresentazione semantica della pagina
    che è più stabile del raw DOM e contiene informazioni su ruoli, label, stati.
    """
    
    @staticmethod
    async def extract(page: Page, max_depth: int = 10) -> Dict[str, Any]:
        """
        Estrae l'accessibility tree completo dalla pagina.
        
        Returns:
            Dict con la struttura dell'accessibility tree
        """
        try:
            # Usa l'API di Playwright per ottenere l'accessibility tree
            snapshot = await page.accessibility.snapshot()
            return snapshot if snapshot else {}
        except Exception as e:
            logger.error(f"Failed to extract accessibility tree: {e}")
            return {}
    
    @staticmethod
    def serialize_tree(tree: Dict[str, Any], max_tokens: int = 8000) -> str:
        """
        Serializza l'accessibility tree in formato testo ottimizzato per LLM.
        Filtra elementi non interattivi e riduce la dimensione.
        
        Args:
            tree: Accessibility tree dict
            max_tokens: Limite approssimativo di token
            
        Returns:
            Stringa formattata dell'accessibility tree
        """
        if not tree:
            return "No accessibility tree available"
        
        lines = []
        AccessibilityTreeExtractor._serialize_node(tree, lines, depth=0)
        
        result = "\n".join(lines)
        
        # Troncamento approssimativo (4 chars ≈ 1 token)
        max_chars = max_tokens * 4
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... [truncated]"
        
        return result
    
    @staticmethod
    def _serialize_node(node: Dict[str, Any], lines: List[str], depth: int):
        """Serializza ricorsivamente un nodo dell'accessibility tree"""
        if depth > 10:  # Limite profondità
            return
        
        indent = "  " * depth
        role = node.get("role", "unknown")
        name = node.get("name", "")
        
        # Filtra ruoli non interattivi comuni
        skip_roles = {"generic", "none", "presentation", "paragraph", "StaticText"}
        if role in skip_roles and not name:
            # Processa comunque i figli
            for child in node.get("children", []):
                AccessibilityTreeExtractor._serialize_node(child, lines, depth)
            return
        
        # Costruisci la linea
        parts = [f"{indent}[{role}]"]
        
        if name:
            # Tronca nomi lunghi
            display_name = name[:100] + "..." if len(name) > 100 else name
            parts.append(f'"{display_name}"')
        
        # Aggiungi attributi rilevanti
        attrs = []
        if node.get("focused"):
            attrs.append("focused")
        if node.get("disabled"):
            attrs.append("disabled")
        if node.get("checked") is not None:
            attrs.append(f"checked={node['checked']}")
        if node.get("selected"):
            attrs.append("selected")
        if node.get("expanded") is not None:
            attrs.append(f"expanded={node['expanded']}")
        if node.get("value"):
            val = str(node["value"])[:50]
            attrs.append(f"value='{val}'")
        
        if attrs:
            parts.append(f"({', '.join(attrs)})")
        
        lines.append(" ".join(parts))
        
        # Processa figli
        for child in node.get("children", []):
            AccessibilityTreeExtractor._serialize_node(child, lines, depth + 1)
    
    @staticmethod
    def find_interactive_elements(tree: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Trova tutti gli elementi interattivi nell'accessibility tree.
        Utile per debugging e per trovare selettori.
        """
        interactive_roles = {
            "button", "link", "textbox", "checkbox", "radio", "combobox",
            "listbox", "option", "menuitem", "tab", "searchbox", "spinbutton",
            "slider", "switch", "menuitemcheckbox", "menuitemradio"
        }
        
        elements = []
        
        def _find(node: Dict[str, Any], path: str = ""):
            role = node.get("role", "")
            name = node.get("name", "")
            
            if role in interactive_roles:
                elements.append({
                    "role": role,
                    "name": name,
                    "path": path,
                    "focused": node.get("focused", False),
                    "disabled": node.get("disabled", False)
                })
            
            for i, child in enumerate(node.get("children", [])):
                child_path = f"{path}/{role}[{i}]" if path else f"{role}[{i}]"
                _find(child, child_path)
        
        _find(tree)
        return elements


# ============================================================================
# SCREENSHOT MANAGER
# ============================================================================

class ScreenshotManager:
    """Gestisce la cattura degli screenshot"""
    
    def __init__(self, page: Page):
        self.page = page
    
    async def capture(self) -> Tuple[bytes, str]:
        """
        Cattura uno screenshot della pagina.
        
        Returns:
            Tuple di (bytes, base64_string)
        """
        try:
            png_bytes = await self.page.screenshot(type="png", full_page=False)
            b64_string = base64.b64encode(png_bytes).decode("utf-8")
            return png_bytes, b64_string
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            raise
    
    async def capture_element(self, selector: str) -> Optional[Tuple[bytes, str]]:
        """Cattura screenshot di un elemento specifico"""
        try:
            element = await self.page.query_selector(selector)
            if element:
                png_bytes = await element.screenshot(type="png")
                b64_string = base64.b64encode(png_bytes).decode("utf-8")
                return png_bytes, b64_string
        except Exception as e:
            logger.error(f"Element screenshot failed: {e}")
        return None


# ============================================================================
# HYBRID ACTION EXECUTOR
# ============================================================================

class HybridActionExecutor:
    """
    Esegue le azioni hybrid (DOM e Vision).
    Implementa anche il self-healing automatico.
    """
    
    def __init__(self, page: Page):
        self.page = page
        self.last_action_time = 0
        self.min_action_delay = 100  # ms tra azioni
    
    async def execute(self, action: HybridAction) -> ExecutionResult:
        """
        Esegue un'azione hybrid.
        Se l'azione DOM fallisce e c'è un fallback Vision disponibile,
        prova automaticamente con le coordinate.
        """
        start_time = time.time()
        
        # Rate limiting
        elapsed = (time.time() - self.last_action_time) * 1000
        if elapsed < self.min_action_delay:
            await asyncio.sleep((self.min_action_delay - elapsed) / 1000)
        
        try:
            if action.action_type == ActionType.ACT:
                result = await self._execute_act(action)
            elif action.action_type == ActionType.CLICK:
                result = await self._execute_click(action)
            elif action.action_type == ActionType.TYPE:
                result = await self._execute_type(action)
            elif action.action_type == ActionType.SCROLL:
                result = await self._execute_scroll(action)
            elif action.action_type == ActionType.NAVIGATE:
                result = await self._execute_navigate(action)
            elif action.action_type == ActionType.WAIT:
                result = await self._execute_wait(action)
            elif action.action_type == ActionType.DONE:
                result = ExecutionResult(success=True, action=action)
            else:
                result = ExecutionResult(
                    success=False,
                    action=action,
                    error=f"Unknown action type: {action.action_type}"
                )
            
            self.last_action_time = time.time()
            result.duration_ms = int((time.time() - start_time) * 1000)
            return result
            
        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            return ExecutionResult(
                success=False,
                action=action,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000)
            )
    
    async def _execute_act(self, action: HybridAction) -> ExecutionResult:
        """
        Esegue un'azione DOM-based.
        Usa il selettore per trovare l'elemento e eseguire l'azione.
        """
        if not action.selector:
            return ExecutionResult(
                success=False,
                action=action,
                error="No selector provided for act action"
            )
        
        logger.dom(f"Executing act with selector: {action.selector}")
        
        try:
            # Trova l'elemento
            element = await self.page.query_selector(action.selector)
            
            if not element:
                # Self-healing: prova con selettori alternativi
                element = await self._try_alternative_selectors(action.selector)
            
            if not element:
                # Fallback a Vision se disponibile
                if action.fallback_available and action.x is not None and action.y is not None:
                    logger.warning(f"DOM selector failed, falling back to coordinates ({action.x}, {action.y})")
                    click_action = HybridAction(
                        action_type=ActionType.CLICK,
                        x=action.x,
                        y=action.y,
                        text=action.text
                    )
                    result = await self._execute_click(click_action)
                    result.fallback_used = True
                    return result
                
                return ExecutionResult(
                    success=False,
                    action=action,
                    error=f"Element not found: {action.selector}"
                )
            
            # Determina l'azione da eseguire basandosi sull'istruzione
            instruction = (action.instruction or "").lower()
            
            if action.text and ("type" in instruction or "enter" in instruction or "fill" in instruction):
                await element.fill(action.text)
                logger.dom(f"Filled '{action.text}' into {action.selector}")
            elif "check" in instruction:
                await element.check()
                logger.dom(f"Checked {action.selector}")
            elif "uncheck" in instruction:
                await element.uncheck()
                logger.dom(f"Unchecked {action.selector}")
            elif "select" in instruction and action.text:
                await element.select_option(action.text)
                logger.dom(f"Selected '{action.text}' in {action.selector}")
            elif "hover" in instruction:
                await element.hover()
                logger.dom(f"Hovered over {action.selector}")
            elif "focus" in instruction:
                await element.focus()
                logger.dom(f"Focused {action.selector}")
            else:
                # Default: click
                await element.click()
                logger.dom(f"Clicked {action.selector}")
            
            return ExecutionResult(success=True, action=action)
            
        except Exception as e:
            logger.error(f"Act execution failed: {e}")
            
            # Fallback a Vision
            if action.fallback_available and action.x is not None and action.y is not None:
                logger.warning(f"DOM action failed, falling back to coordinates ({action.x}, {action.y})")
                click_action = HybridAction(
                    action_type=ActionType.CLICK,
                    x=action.x,
                    y=action.y,
                    text=action.text
                )
                result = await self._execute_click(click_action)
                result.fallback_used = True
                return result
            
            return ExecutionResult(success=False, action=action, error=str(e))
    
    async def _try_alternative_selectors(self, original_selector: str) -> Optional[Any]:
        """
        Prova selettori alternativi quando il primo fallisce.
        Implementa parte del self-healing.
        """
        # Strategie di fallback per selettori comuni
        alternatives = []
        
        # Se è un selettore con attributo, prova varianti
        if "[" in original_selector:
            # Prova senza il valore specifico
            base = original_selector.split("[")[0]
            if base:
                alternatives.append(base)
        
        # Se contiene testo, prova text selector
        if "text=" not in original_selector.lower():
            # Estrai possibile testo dal selettore
            match = re.search(r'"([^"]+)"', original_selector)
            if match:
                alternatives.append(f'text="{match.group(1)}"')
        
        for alt_selector in alternatives:
            try:
                element = await self.page.query_selector(alt_selector)
                if element:
                    logger.dom(f"Found element with alternative selector: {alt_selector}")
                    return element
            except:
                continue
        
        return None
    
    async def _execute_click(self, action: HybridAction) -> ExecutionResult:
        """Esegue un click su coordinate specifiche"""
        if action.x is None or action.y is None:
            return ExecutionResult(
                success=False,
                action=action,
                error="No coordinates provided for click action"
            )
        
        logger.vision(f"Clicking at ({action.x}, {action.y})")
        
        try:
            await self.page.mouse.click(action.x, action.y)
            return ExecutionResult(success=True, action=action)
        except Exception as e:
            return ExecutionResult(success=False, action=action, error=str(e))
    
    async def _execute_type(self, action: HybridAction) -> ExecutionResult:
        """Digita testo, opzionalmente su coordinate specifiche"""
        if not action.text:
            return ExecutionResult(
                success=False,
                action=action,
                error="No text provided for type action"
            )
        
        try:
            # Se ci sono coordinate, prima clicca lì
            if action.x is not None and action.y is not None:
                logger.vision(f"Clicking at ({action.x}, {action.y}) before typing")
                await self.page.mouse.click(action.x, action.y)
                await asyncio.sleep(0.1)
            
            logger.vision(f"Typing: {action.text[:50]}...")
            await self.page.keyboard.type(action.text, delay=50)
            return ExecutionResult(success=True, action=action)
        except Exception as e:
            return ExecutionResult(success=False, action=action, error=str(e))
    
    async def _execute_scroll(self, action: HybridAction) -> ExecutionResult:
        """Esegue scroll"""
        try:
            # Default: scroll di 300px verso il basso
            delta_y = action.y if action.y else 300
            
            if action.x is not None and action.y is not None:
                # Scroll su posizione specifica
                await self.page.mouse.move(action.x, action.y)
            
            await self.page.mouse.wheel(0, delta_y)
            logger.vision(f"Scrolled by {delta_y}px")
            return ExecutionResult(success=True, action=action)
        except Exception as e:
            return ExecutionResult(success=False, action=action, error=str(e))
    
    async def _execute_navigate(self, action: HybridAction) -> ExecutionResult:
        """Naviga a un URL"""
        if not action.url:
            return ExecutionResult(
                success=False,
                action=action,
                error="No URL provided for navigate action"
            )
        
        try:
            logger.info(f"Navigating to: {action.url}")
            await self.page.goto(action.url, wait_until="domcontentloaded")
            return ExecutionResult(success=True, action=action)
        except Exception as e:
            return ExecutionResult(success=False, action=action, error=str(e))
    
    async def _execute_wait(self, action: HybridAction) -> ExecutionResult:
        """Attende per un periodo specificato"""
        duration = action.duration if action.duration else 1000
        logger.info(f"Waiting for {duration}ms")
        await asyncio.sleep(duration / 1000)
        return ExecutionResult(success=True, action=action)


# ============================================================================
# GEMINI HYBRID CLIENT
# ============================================================================

class GeminiHybridClient:
    """
    Client per Gemini 3 Flash in modalità Hybrid.
    
    Definisce i tool disponibili (DOM e Vision) e gestisce
    la comunicazione con il modello.
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)
        self.conversation_history: List[Content] = []
    
    def _build_tools(self) -> List[Tool]:
        """
        Costruisce la lista dei tool disponibili per il modello.
        Include sia tool DOM-based che Vision-based.
        """
        tools = []
        
        # Tool DOM-based: act
        act_tool = FunctionDeclaration(
            name="act",
            description="""Execute a DOM-based action using a CSS/XPath selector.
            Use this when you can identify a clear, reliable selector for the target element.
            Preferred for: buttons, links, form inputs, elements with clear identifiers.
            The selector should be as specific as possible.""",
            parameters=Schema(
                type="object",
                properties={
                    "selector": Schema(
                        type="string",
                        description="CSS selector or XPath to find the element. Examples: 'button[type=submit]', '#login-btn', '[data-testid=\"search\"]', 'text=\"Sign In\"'"
                    ),
                    "instruction": Schema(
                        type="string",
                        description="What to do with the element: 'click', 'type', 'check', 'uncheck', 'select', 'hover', 'focus'"
                    ),
                    "text": Schema(
                        type="string",
                        description="Text to type or option to select (if applicable)"
                    ),
                    "fallback_x": Schema(
                        type="integer",
                        description="Fallback X coordinate if selector fails"
                    ),
                    "fallback_y": Schema(
                        type="integer",
                        description="Fallback Y coordinate if selector fails"
                    )
                },
                required=["selector", "instruction"]
            )
        )
        
        # Tool Vision-based: click
        click_tool = FunctionDeclaration(
            name="click",
            description="""Click at specific pixel coordinates on the screen.
            Use this when: no reliable DOM selector exists, element is in canvas/SVG,
            dealing with dynamic content, or DOM approach failed.
            Coordinates are relative to the viewport (0,0 = top-left).""",
            parameters=Schema(
                type="object",
                properties={
                    "x": Schema(
                        type="integer",
                        description="X coordinate (pixels from left edge)"
                    ),
                    "y": Schema(
                        type="integer",
                        description="Y coordinate (pixels from top edge)"
                    ),
                    "reasoning": Schema(
                        type="string",
                        description="Brief explanation of why you're clicking here"
                    )
                },
                required=["x", "y"]
            )
        )
        
        # Tool Vision-based: type
        type_tool = FunctionDeclaration(
            name="type",
            description="""Type text, optionally clicking at coordinates first.
            Use for text input when DOM selector is unreliable.""",
            parameters=Schema(
                type="object",
                properties={
                    "text": Schema(
                        type="string",
                        description="Text to type"
                    ),
                    "x": Schema(
                        type="integer",
                        description="Optional: X coordinate to click before typing"
                    ),
                    "y": Schema(
                        type="integer",
                        description="Optional: Y coordinate to click before typing"
                    )
                },
                required=["text"]
            )
        )
        
        # Tool: scroll
        scroll_tool = FunctionDeclaration(
            name="scroll",
            description="""Scroll the page. Positive y = scroll down, negative = scroll up.""",
            parameters=Schema(
                type="object",
                properties={
                    "delta_y": Schema(
                        type="integer",
                        description="Pixels to scroll (positive=down, negative=up). Default 300."
                    ),
                    "x": Schema(
                        type="integer",
                        description="Optional: X position to scroll at"
                    ),
                    "y": Schema(
                        type="integer",
                        description="Optional: Y position to scroll at"
                    )
                },
                required=[]
            )
        )
        
        # Tool: navigate
        navigate_tool = FunctionDeclaration(
            name="navigate",
            description="""Navigate to a URL.""",
            parameters=Schema(
                type="object",
                properties={
                    "url": Schema(
                        type="string",
                        description="Full URL to navigate to"
                    )
                },
                required=["url"]
            )
        )
        
        # Tool: wait
        wait_tool = FunctionDeclaration(
            name="wait",
            description="""Wait for a specified duration. Use when page needs time to load or update.""",
            parameters=Schema(
                type="object",
                properties={
                    "duration_ms": Schema(
                        type="integer",
                        description="Duration to wait in milliseconds"
                    )
                },
                required=[]
            )
        )
        
        # Tool: done
        done_tool = FunctionDeclaration(
            name="done",
            description="""Mark the task as complete. Call this when the task has been successfully completed.""",
            parameters=Schema(
                type="object",
                properties={
                    "summary": Schema(
                        type="string",
                        description="Brief summary of what was accomplished"
                    )
                },
                required=["summary"]
            )
        )
        
        # Combina tutti i tool
        tools.append(Tool(function_declarations=[
            act_tool, click_tool, type_tool, scroll_tool, navigate_tool, wait_tool, done_tool
        ]))
        
        return tools
    
    def _build_system_prompt(self, task: str) -> str:
        """Costruisce il system prompt per il modello"""
        return f"""You are an AI browser automation agent operating in HYBRID MODE.

You have access to both DOM-based and Vision-based tools:

DOM-BASED TOOLS (preferred when reliable selectors exist):
- act(selector, instruction, text?): Execute action on element via CSS/XPath selector
  - Use for: buttons, links, form inputs, elements with clear identifiers
  - Selectors can be: CSS ('#id', '.class', '[attr=val]'), XPath, or text ('text="Click me"')

VISION-BASED TOOLS (use when DOM approach is unreliable):
- click(x, y): Click at specific pixel coordinates
- type(text, x?, y?): Type text, optionally clicking at coordinates first
- scroll(delta_y): Scroll the page
  - Use for: canvas elements, SVGs, dynamic content, when selectors fail

CONTROL TOOLS:
- navigate(url): Go to a URL
- wait(duration_ms): Wait for page to load
- done(summary): Mark task as complete

DECISION FRAMEWORK for each action:
1. Can I identify a reliable DOM selector for this element?
   - YES → Use act() with the selector
   - NO → Use click() with coordinates

2. For form inputs:
   - If input has clear selector → act(selector, "type", text)
   - If input is hard to select → type(text, x, y)

3. For buttons/links:
   - Standard HTML with id/class/text → act(selector, "click")
   - Icon buttons, SVG, canvas → click(x, y)

4. Always provide fallback coordinates in act() when possible

CURRENT TASK: {task}

Analyze the screenshot and accessibility tree carefully.
Choose the most reliable approach for each action.
If an action fails, the system will automatically try the fallback."""
    
    async def get_next_action(
        self,
        task: str,
        screenshot_bytes: bytes,
        accessibility_tree: str,
        current_url: str,
        previous_actions: List[str] = None
    ) -> HybridAction:
        """
        Chiede al modello la prossima azione da eseguire.
        
        Args:
            task: Descrizione del task
            screenshot_bytes: Screenshot PNG
            accessibility_tree: Accessibility tree serializzato
            current_url: URL corrente
            previous_actions: Lista delle azioni precedenti
            
        Returns:
            HybridAction da eseguire
        """
        # Costruisci il contesto
        context_parts = [
            f"CURRENT URL: {current_url}\n",
            f"ACCESSIBILITY TREE:\n{accessibility_tree}\n"
        ]
        
        if previous_actions:
            context_parts.append(f"PREVIOUS ACTIONS:\n" + "\n".join(previous_actions[-5:]))
        
        context_parts.append(f"\nWhat is the next action to complete the task?")
        
        # Costruisci il messaggio
        user_content = Content(
            role="user",
            parts=[
                Part(text="\n".join(context_parts)),
                Part.from_bytes(data=screenshot_bytes, mime_type="image/png")
            ]
        )
        
        # Prima chiamata: includi system prompt
        if not self.conversation_history:
            system_content = Content(
                role="user",
                parts=[Part(text=self._build_system_prompt(task))]
            )
            self.conversation_history.append(system_content)
            
            # Risposta fittizia del modello per il system prompt
            self.conversation_history.append(Content(
                role="model",
                parts=[Part(text="I understand. I'll analyze the page and choose the best approach for each action.")]
            ))
        
        self.conversation_history.append(user_content)
        
        # Config con tools
        config = types.GenerateContentConfig(
            tools=self._build_tools(),
            temperature=0.1,  # Bassa temperatura per azioni deterministiche
        )
        
        # Chiama il modello
        response = self.client.models.generate_content(
            model=GEMINI_HYBRID_MODEL,
            contents=self.conversation_history,
            config=config
        )
        
        # Aggiungi risposta alla history
        if response.candidates:
            self.conversation_history.append(response.candidates[0].content)
        
        # Parsa la risposta
        return self._parse_response(response)
    
    def _parse_response(self, response) -> HybridAction:
        """Parsa la risposta del modello in un HybridAction"""
        if not response.candidates:
            return HybridAction(
                action_type=ActionType.DONE,
                reasoning="No response from model"
            )
        
        candidate = response.candidates[0]
        
        # Cerca function calls
        for part in candidate.content.parts:
            if part.function_call:
                fc = part.function_call
                args = dict(fc.args) if fc.args else {}
                
                logger.info(f"Model chose: {fc.name}({args})")
                
                if fc.name == "act":
                    return HybridAction(
                        action_type=ActionType.ACT,
                        selector=args.get("selector"),
                        instruction=args.get("instruction", "click"),
                        text=args.get("text"),
                        x=args.get("fallback_x"),
                        y=args.get("fallback_y"),
                        fallback_available=bool(args.get("fallback_x") and args.get("fallback_y"))
                    )
                
                elif fc.name == "click":
                    return HybridAction(
                        action_type=ActionType.CLICK,
                        x=args.get("x"),
                        y=args.get("y"),
                        reasoning=args.get("reasoning")
                    )
                
                elif fc.name == "type":
                    return HybridAction(
                        action_type=ActionType.TYPE,
                        text=args.get("text"),
                        x=args.get("x"),
                        y=args.get("y")
                    )
                
                elif fc.name == "scroll":
                    return HybridAction(
                        action_type=ActionType.SCROLL,
                        y=args.get("delta_y", 300),
                        x=args.get("x"),
                    )
                
                elif fc.name == "navigate":
                    return HybridAction(
                        action_type=ActionType.NAVIGATE,
                        url=args.get("url")
                    )
                
                elif fc.name == "wait":
                    return HybridAction(
                        action_type=ActionType.WAIT,
                        duration=args.get("duration_ms", 1000)
                    )
                
                elif fc.name == "done":
                    return HybridAction(
                        action_type=ActionType.DONE,
                        reasoning=args.get("summary")
                    )
        
        # Se non c'è function call, considera il task completato
        text_response = ""
        for part in candidate.content.parts:
            if part.text:
                text_response += part.text
        
        logger.info(f"Model text response (no tool): {text_response[:200]}")
        return HybridAction(
            action_type=ActionType.DONE,
            reasoning=text_response
        )
    
    def add_action_result(self, action: HybridAction, result: ExecutionResult):
        """Aggiunge il risultato di un'azione alla conversation history"""
        result_text = f"Action result: {'SUCCESS' if result.success else 'FAILED'}"
        if result.error:
            result_text += f" - Error: {result.error}"
        if result.fallback_used:
            result_text += " (fallback coordinates used)"
        
        self.conversation_history.append(Content(
            role="user",
            parts=[Part(text=result_text)]
        ))
    
    def reset(self):
        """Reset della conversation history"""
        self.conversation_history = []


# ============================================================================
# HYBRID BROWSER AGENT
# ============================================================================

class HybridBrowserAgent:
    """
    Agente browser che opera in modalità Hybrid.
    Coordina il browser, il modello Gemini, e l'esecuzione delle azioni.
    """
    
    def __init__(
        self,
        api_key: str,
        headless: bool = False,
        profile_dir: Optional[Path] = None
    ):
        self.api_key = api_key
        self.headless = headless
        self.profile_dir = profile_dir or HYBRID_PROFILE_DIR
        
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        
        self.gemini_client = None
        self.executor = None
        self.screenshot_manager = None
        self.is_running = False
    
    async def start(self, initial_url: Optional[str] = None):
        """Avvia il browser e inizializza i componenti"""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not available")
        if not GEMINI_AVAILABLE:
            raise RuntimeError(f"Gemini SDK not available: {GEMINI_IMPORT_ERROR}")
        
        logger.info("Starting Hybrid Browser Agent...")
        logger.info(f"Profile directory: {self.profile_dir}")
        
        # Crea profile directory se non esiste
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        
        # Avvia Playwright
        self.playwright = await async_playwright().start()
        
        # Usa Edge con persistent context per evitare conflitti con Chrome
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel="msedge",
            headless=self.headless,
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-web-security",
            ],
            ignore_default_args=["--enable-automation"],
        )
        
        # Usa la prima pagina o creane una nuova
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        
        # Anti-detection
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)
        
        # Inizializza componenti
        self.gemini_client = GeminiHybridClient(self.api_key)
        self.executor = HybridActionExecutor(self.page)
        self.screenshot_manager = ScreenshotManager(self.page)
        
        # Naviga all'URL iniziale se specificato
        if initial_url:
            await self.page.goto(initial_url, wait_until="domcontentloaded")
            logger.info(f"Navigated to: {initial_url}")
        
        self.is_running = True
        logger.info("Hybrid Browser Agent started successfully")
    
    async def execute_task(
        self,
        task: str,
        max_steps: int = 20,
        step_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Esegue un task completo.
        
        Args:
            task: Descrizione del task da eseguire
            max_steps: Numero massimo di step
            step_callback: Callback opzionale chiamata ad ogni step
            
        Returns:
            Dict con risultati dell'esecuzione
        """
        if not self.is_running:
            raise RuntimeError("Agent not started")
        
        logger.info("=" * 60)
        logger.info(f"HYBRID MODE EXECUTION")
        logger.info(f"Task: {task}")
        logger.info(f"Max steps: {max_steps}")
        logger.info("=" * 60)
        
        self.gemini_client.reset()
        
        steps: List[StepRecord] = []
        previous_actions: List[str] = []
        completed = False
        
        for turn in range(1, max_steps + 1):
            if not self.is_running:
                logger.warning("Execution stopped by user")
                break
            
            logger.info(f"\n{'='*40}")
            logger.info(f"STEP {turn}/{max_steps}")
            logger.info(f"{'='*40}")
            
            step = StepRecord(turn=turn)
            
            try:
                # 1. Cattura screenshot
                screenshot_bytes, screenshot_b64 = await self.screenshot_manager.capture()
                step.screenshot_before = screenshot_b64
                
                # 2. Estrai accessibility tree
                a11y_tree = await AccessibilityTreeExtractor.extract(self.page)
                a11y_serialized = AccessibilityTreeExtractor.serialize_tree(a11y_tree)
                step.accessibility_tree = a11y_serialized
                
                logger.debug(f"Accessibility tree extracted: {len(a11y_serialized)} chars")
                
                # 3. Ottieni la prossima azione dal modello
                current_url = self.page.url
                action = await self.gemini_client.get_next_action(
                    task=task,
                    screenshot_bytes=screenshot_bytes,
                    accessibility_tree=a11y_serialized,
                    current_url=current_url,
                    previous_actions=previous_actions
                )
                
                step.action = action
                
                # Log dell'azione scelta
                if action.action_type == ActionType.ACT:
                    logger.action("DOM", f"selector='{action.selector}' instruction='{action.instruction}'")
                elif action.action_type == ActionType.CLICK:
                    logger.action("VISION", f"click at ({action.x}, {action.y})")
                elif action.action_type == ActionType.TYPE:
                    logger.action("TYPE", f"text='{action.text[:30]}...' at ({action.x}, {action.y})")
                elif action.action_type == ActionType.DONE:
                    logger.info(f"✅ Task completed: {action.reasoning}")
                    completed = True
                else:
                    logger.action(action.action_type.value.upper(), str(action))
                
                # 4. Esegui l'azione
                if action.action_type == ActionType.DONE:
                    step.result = ExecutionResult(success=True, action=action)
                    steps.append(step)
                    break
                
                result = await self.executor.execute(action)
                step.result = result
                
                # 5. Aggiungi risultato alla history
                action_desc = f"{action.action_type.value}"
                if action.selector:
                    action_desc += f"(selector='{action.selector}')"
                elif action.x is not None:
                    action_desc += f"(x={action.x}, y={action.y})"
                action_desc += f" -> {'OK' if result.success else 'FAILED'}"
                if result.fallback_used:
                    action_desc += " [fallback]"
                previous_actions.append(action_desc)
                
                self.gemini_client.add_action_result(action, result)
                
                # Log risultato
                if result.success:
                    logger.info(f"✓ Action succeeded" + (" (fallback used)" if result.fallback_used else ""))
                else:
                    logger.error(f"✗ Action failed: {result.error}")
                
                # Breve pausa tra le azioni
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.error(f"Step {turn} failed with exception: {e}")
                step.result = ExecutionResult(
                    success=False,
                    action=step.action or HybridAction(action_type=ActionType.WAIT),
                    error=str(e)
                )
            
            steps.append(step)
            
            if step_callback:
                await step_callback(step)
        
        # Compila risultati
        successful_steps = sum(1 for s in steps if s.result and s.result.success)
        failed_steps = sum(1 for s in steps if s.result and not s.result.success)
        fallback_used = sum(1 for s in steps if s.result and s.result.fallback_used)
        
        dom_actions = sum(1 for s in steps if s.action and s.action.action_type == ActionType.ACT)
        vision_actions = sum(1 for s in steps if s.action and s.action.action_type in [ActionType.CLICK, ActionType.TYPE])
        
        return {
            "success": completed,
            "task": task,
            "total_steps": len(steps),
            "successful_steps": successful_steps,
            "failed_steps": failed_steps,
            "fallback_used": fallback_used,
            "dom_actions": dom_actions,
            "vision_actions": vision_actions,
            "final_url": self.page.url,
            "steps": [
                {
                    "turn": s.turn,
                    "action_type": s.action.action_type.value if s.action else None,
                    "success": s.result.success if s.result else None,
                    "fallback": s.result.fallback_used if s.result else False,
                    "error": s.result.error if s.result else None
                }
                for s in steps
            ]
        }
    
    async def stop(self):
        """Ferma l'agente e chiude il browser"""
        self.is_running = False
        
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        
        logger.info("Hybrid Browser Agent stopped")
    
    def request_stop(self):
        """Richiede lo stop dell'esecuzione corrente"""
        self.is_running = False


# ============================================================================
# FASTAPI SERVICE
# ============================================================================

app = FastAPI(
    title="Hybrid Browser Agent Service",
    description="Browser automation with Hybrid Mode (DOM + Vision)",
    version="7.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent instance
agent: Optional[HybridBrowserAgent] = None


class ExecuteRequest(BaseModel):
    """Request per esecuzione task"""
    api_key: str
    task_description: str
    initial_url: Optional[str] = None
    max_steps: int = 20
    headless: bool = False
    mode: str = "hybrid"  # "hybrid" o "cua" per retrocompatibilità


class ExecuteResponse(BaseModel):
    """Response dell'esecuzione"""
    success: bool
    task: str
    total_steps: int
    successful_steps: int
    failed_steps: int
    fallback_used: int
    dom_actions: int
    vision_actions: int
    final_url: str
    steps: List[Dict[str, Any]]
    message: Optional[str] = None


@app.get("/")
async def root():
    """Health check"""
    return {
        "service": "Hybrid Browser Agent",
        "version": "7.0.0",
        "status": "running",
        "mode": "hybrid",
        "models": {
            "hybrid": GEMINI_HYBRID_MODEL,
            "cua": GEMINI_CUA_MODEL
        },
        "features": {
            "dom_actions": True,
            "vision_actions": True,
            "self_healing": True,
            "persistent_context": True
        }
    }


@app.get("/status")
async def status():
    """Stato dell'agente"""
    return {
        "agent_active": agent is not None and agent.is_running,
        "playwright_available": PLAYWRIGHT_AVAILABLE,
        "gemini_available": GEMINI_AVAILABLE,
        "profile_dir": str(HYBRID_PROFILE_DIR)
    }


@app.post("/execute", response_model=ExecuteResponse)
async def execute_task(request: ExecuteRequest):
    """
    Esegue un task in modalità Hybrid.
    
    Il modello Gemini 3 Flash analizzerà la pagina e sceglierà
    automaticamente tra azioni DOM-based e Vision-based.
    """
    global agent
    
    if not PLAYWRIGHT_AVAILABLE:
        raise HTTPException(status_code=500, detail="Playwright not available")
    if not GEMINI_AVAILABLE:
        raise HTTPException(status_code=500, detail=f"Gemini SDK not available: {GEMINI_IMPORT_ERROR}")
    
    try:
        # Crea nuovo agente
        agent = HybridBrowserAgent(
            api_key=request.api_key,
            headless=request.headless
        )
        
        # Avvia
        await agent.start(initial_url=request.initial_url)
        
        # Esegui task
        result = await agent.execute_task(
            task=request.task_description,
            max_steps=request.max_steps
        )
        
        return ExecuteResponse(
            success=result["success"],
            task=result["task"],
            total_steps=result["total_steps"],
            successful_steps=result["successful_steps"],
            failed_steps=result["failed_steps"],
            fallback_used=result["fallback_used"],
            dom_actions=result["dom_actions"],
            vision_actions=result["vision_actions"],
            final_url=result["final_url"],
            steps=result["steps"],
            message="Task completed successfully" if result["success"] else "Task did not complete"
        )
        
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if agent:
            await agent.stop()
            agent = None


@app.post("/stop")
async def stop_execution():
    """Ferma l'esecuzione corrente"""
    global agent
    
    if agent:
        agent.request_stop()
        return {"status": "stop requested"}
    
    return {"status": "no active agent"}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("HYBRID BROWSER AGENT SERVICE v7.0")
    print("=" * 60)
    print(f"Playwright available: {PLAYWRIGHT_AVAILABLE}")
    print(f"Gemini SDK available: {GEMINI_AVAILABLE}")
    print(f"Hybrid model: {GEMINI_HYBRID_MODEL}")
    print(f"CUA model: {GEMINI_CUA_MODEL}")
    print(f"Profile directory: {HYBRID_PROFILE_DIR}")
    print("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=8765)
