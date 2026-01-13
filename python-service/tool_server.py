#!/usr/bin/env python3
"""
tool_server.py v8.4.2 - Desktop App "Hands Only" Server
======================================================

PRINCIPIO ARCHITETTURALE: HANDS ONLY
====================================
Questo server fornisce SOLO capacità di esecuzione ("mani").
TUTTA l'intelligenza (decisioni, verifiche, confidence) sta nella Web App.

Il Tool Server:
✅ Cattura screenshot
✅ Legge coordinate DOM
✅ Legge struttura DOM (Accessibility Tree)
✅ Esegue click/type/scroll
✅ Converte coordinate (utility)
❌ NON decide se procedere o meno
❌ NON calcola confidence
❌ NON confronta coordinate tra sorgenti

VIEWPORT: 1260×700 (Lux SDK native)
===================================
- Allineato con Lux SDK reference resolution
- Coordinate Lux usabili direttamente (1:1 mapping)
- Coordinate Gemini (0-999) richiedono denormalizzazione nella Web App

CHANGELOG:
- v8.0.1: Fixed accessibility tree with JavaScript fallback
- v8.1.0: Added /browser/dom/element_rect
- v8.2.0: Added 'normalized' coordinate_origin for Gemini 2.5
- v8.3.0: Viewport aligned to Lux SDK (1260×700)
- v8.4.0: Added Triple Verification (ERRORE ARCHITETTURALE)
- v8.4.1: RIMOSSA Triple Verification (spostata in Web App)
         - Rimosso /coordinates/triple_verify endpoint
         - Rimossa classe TripleVerifier
         - Server torna a essere "Hands Only"
- v8.4.2: Aggiunto /browser/dom/tree endpoint
         - Restituisce Accessibility Tree della pagina
         - Usato dall'agente DOM Analyzer per analizzare struttura siti
"""

import asyncio
import base64
import io
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Literal, List, Dict, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ============================================================================
# CONFIGURATION
# ============================================================================

SERVICE_VERSION = "8.4.2"
SERVICE_PORT = 8766

# ============================================================================
# MODEL REFERENCE RESOLUTIONS
# ============================================================================

# Lux SDK reference (model trained on this)
LUX_SDK_WIDTH = 1260
LUX_SDK_HEIGHT = 700

# Gemini 2.5 Computer Use recommended resolution (for reference only)
GEMINI_RECOMMENDED_WIDTH = 1440
GEMINI_RECOMMENDED_HEIGHT = 900

# Lux full screen reference (for desktop scope)
LUX_SCREEN_REF_WIDTH = 1920
LUX_SCREEN_REF_HEIGHT = 1200

# ============================================================================
# VIEWPORT CONFIGURATION
# ============================================================================
# Viewport = Lux SDK native resolution
# Questo significa:
# - Screenshot catturati a 1260×700
# - Coordinate Lux usabili direttamente (no scaling)
# - Coordinate DOM già in viewport space
# - Solo Gemini (normalized) richiede conversione
# ============================================================================
VIEWPORT_WIDTH = LUX_SDK_WIDTH   # 1260
VIEWPORT_HEIGHT = LUX_SDK_HEIGHT  # 700

# Gemini normalized coordinate range (0-999)
NORMALIZED_COORD_MAX = 999

# Browser profile directory
BROWSER_PROFILE_DIR = Path.home() / ".edge-automation-profile"

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DEPENDENCY CHECKS
# ============================================================================

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
    logger.info("✅ PyAutoGUI available")
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    logger.warning("⚠️ PyAutoGUI not available")

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
    logger.info("✅ Pyperclip available")
except ImportError:
    PYPERCLIP_AVAILABLE = False
    logger.warning("⚠️ Pyperclip not available")

try:
    from PIL import Image
    PIL_AVAILABLE = True
    logger.info("✅ PIL available")
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("⚠️ PIL not available")

try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
    logger.info("✅ Playwright available")
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("⚠️ Playwright not available")


# ============================================================================
# PYDANTIC MODELS - Requests
# ============================================================================

class ScreenshotRequest(BaseModel):
    """Request for screenshot"""
    scope: Literal["browser", "desktop"] = "browser"
    session_id: Optional[str] = None
    # Quale formato restituire
    include_lux_metadata: bool = True
    include_gemini_resize: bool = False  # Se true, include anche resize a 1440×900


class ClickRequest(BaseModel):
    """Request for click action"""
    scope: Literal["browser", "desktop"] = "browser"
    x: int
    y: int
    coordinate_origin: Literal["viewport", "screen", "lux_sdk", "normalized"] = "viewport"
    click_type: Literal["single", "double", "right"] = "single"
    session_id: Optional[str] = None


class TypeRequest(BaseModel):
    """Request for type action"""
    scope: Literal["browser", "desktop"] = "browser"
    text: str
    method: Literal["clipboard", "keystrokes"] = "clipboard"
    session_id: Optional[str] = None
    selector: Optional[str] = None


class ScrollRequest(BaseModel):
    """Request for scroll action"""
    scope: Literal["browser", "desktop"] = "browser"
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = 300
    x: Optional[int] = None
    y: Optional[int] = None
    coordinate_origin: Literal["viewport", "screen", "lux_sdk", "normalized"] = "viewport"
    session_id: Optional[str] = None


class KeypressRequest(BaseModel):
    """Request for keypress action"""
    scope: Literal["browser", "desktop"] = "browser"
    key: str
    session_id: Optional[str] = None


class BrowserStartRequest(BaseModel):
    """Request to start browser session"""
    start_url: Optional[str] = None
    headless: bool = False


class NavigateRequest(BaseModel):
    """Request to navigate to URL"""
    session_id: str
    url: str


class TabRequest(BaseModel):
    """Request for tab operations"""
    session_id: str
    tab_id: Optional[int] = None
    url: Optional[str] = None


class ElementRectRequest(BaseModel):
    """
    Request to get element bounding rectangle.
    Restituisce dati grezzi - la Web App decide cosa farne.
    """
    session_id: str
    selector: Optional[str] = None
    text: Optional[str] = None
    text_exact: Optional[bool] = False
    role: Optional[str] = None
    role_name: Optional[str] = None
    test_id: Optional[str] = None
    placeholder: Optional[str] = None
    label: Optional[str] = None
    index: Optional[int] = 0
    must_be_visible: Optional[bool] = True


class CoordinateConvertRequest(BaseModel):
    """Request to convert coordinates between spaces (utility)"""
    x: int
    y: int
    from_space: Literal["viewport", "screen", "lux_sdk", "normalized"]
    to_space: Literal["viewport", "screen", "lux_sdk", "normalized"]


# ============================================================================
# PYDANTIC MODELS - Responses
# ============================================================================

class ActionResponse(BaseModel):
    """Generic response for actions"""
    success: bool
    error: Optional[str] = None
    executed_with: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ScreenshotResponse(BaseModel):
    """
    Response containing screenshot data.
    Dati grezzi - la Web App decide come usarli.
    """
    success: bool
    error: Optional[str] = None
    
    # Screenshot principale (viewport resolution)
    image_base64: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    
    # Metadata per Lux (scale factors, sempre 1.0 per browser scope)
    lux_scale_x: Optional[float] = None
    lux_scale_y: Optional[float] = None
    
    # Screenshot ridimensionato per Gemini (opzionale)
    gemini_image_base64: Optional[str] = None
    gemini_width: Optional[int] = None
    gemini_height: Optional[int] = None


class ElementRectResponse(BaseModel):
    """
    Response with element bounding rectangle.
    Dati grezzi - la Web App decide come usarli per Triple Verification.
    """
    success: bool
    error: Optional[str] = None
    
    # Element state
    found: bool = False
    visible: bool = False
    enabled: bool = False
    
    # Center coordinates (ready for clicking)
    x: Optional[int] = None
    y: Optional[int] = None
    
    # Full bounding box
    bounding_box: Optional[Dict[str, float]] = None  # {x, y, width, height}
    
    # Element info
    tag: Optional[str] = None
    text: Optional[str] = None
    element_count: Optional[int] = None
    selector_used: Optional[str] = None


class StatusResponse(BaseModel):
    """Service status response"""
    status: str
    version: str
    browser_sessions: int
    capabilities: Dict[str, bool]
    viewport: Dict[str, int]
    references: Dict[str, Dict[str, int]]


# ============================================================================
# COORDINATE CONVERTER (Utility - no logic, just math)
# ============================================================================

class CoordinateConverter:
    """
    Utility per conversione coordinate.
    Solo matematica, nessuna decisione.
    """
    
    @staticmethod
    def lux_sdk_to_viewport(x: int, y: int) -> Tuple[int, int]:
        """
        Lux SDK → Viewport.
        In v8.4.1: 1:1 mapping (stesso resolution).
        """
        # viewport = lux_sdk, nessuna conversione
        return x, y
    
    @staticmethod
    def normalized_to_viewport(x: int, y: int) -> Tuple[int, int]:
        """
        Gemini normalized (0-999) → Viewport pixels.
        Formula: pixel = normalized / 1000 * dimension
        """
        pixel_x = int(x / 1000 * VIEWPORT_WIDTH)
        pixel_y = int(y / 1000 * VIEWPORT_HEIGHT)
        return pixel_x, pixel_y
    
    @staticmethod
    def viewport_to_normalized(x: int, y: int) -> Tuple[int, int]:
        """Viewport → Gemini normalized (0-999)."""
        norm_x = int(x / VIEWPORT_WIDTH * 1000)
        norm_y = int(y / VIEWPORT_HEIGHT * 1000)
        norm_x = max(0, min(NORMALIZED_COORD_MAX, norm_x))
        norm_y = max(0, min(NORMALIZED_COORD_MAX, norm_y))
        return norm_x, norm_y
    
    @staticmethod
    def lux_sdk_to_screen(x: int, y: int, screen_width: int, screen_height: int) -> Tuple[int, int]:
        """Lux SDK → Screen (per desktop scope)."""
        scale_x = screen_width / LUX_SDK_WIDTH
        scale_y = screen_height / LUX_SDK_HEIGHT
        return int(x * scale_x), int(y * scale_y)
    
    @staticmethod
    def normalized_to_screen(x: int, y: int, screen_width: int, screen_height: int) -> Tuple[int, int]:
        """Gemini normalized → Screen."""
        pixel_x = int(x / 1000 * screen_width)
        pixel_y = int(y / 1000 * screen_height)
        return pixel_x, pixel_y


# ============================================================================
# IMAGE UTILITIES
# ============================================================================

def resize_image(image_bytes: bytes, target_width: int, target_height: int) -> Tuple[str, int, int]:
    """
    Resize image to target resolution.
    Returns (base64, width, height).
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("PIL not available")
    
    img = Image.open(io.BytesIO(image_bytes))
    resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    buffer = io.BytesIO()
    resized.save(buffer, format='PNG')
    buffer.seek(0)
    
    return base64.b64encode(buffer.read()).decode('utf-8'), target_width, target_height


# ============================================================================
# CLIPBOARD TYPING
# ============================================================================

def type_via_clipboard(text: str):
    """Type text using clipboard for non-US keyboards."""
    if not PYPERCLIP_AVAILABLE:
        pyautogui.typewrite(text, interval=0.05)
        return
    
    try:
        old_clipboard = ""
        try:
            old_clipboard = pyperclip.paste()
        except:
            pass
        
        pyperclip.copy(text)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        
        try:
            pyperclip.copy(old_clipboard)
        except:
            pass
    except:
        pyautogui.typewrite(text, interval=0.05)


# ============================================================================
# BROWSER SESSION MANAGER
# ============================================================================

class BrowserSession:
    """Manages a single browser session"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.pages: List[Page] = []
        self.current_page_index: int = 0
        self.created_at = datetime.now()
    
    @property
    def page(self) -> Optional[Page]:
        if self.pages and 0 <= self.current_page_index < len(self.pages):
            return self.pages[self.current_page_index]
        return None
    
    async def start(self, start_url: Optional[str] = None, headless: bool = False):
        """Start browser with viewport 1260×700."""
        self.playwright = await async_playwright().start()
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"🌐 Starting Edge: viewport {VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT}")
        
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            channel="msedge",
            headless=headless,
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
            ]
        )
        
        if self.context.pages:
            self.pages = list(self.context.pages)
        else:
            self.pages = [await self.context.new_page()]
        
        self.current_page_index = 0
        
        if start_url:
            await self.page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(0.5)
        
        logger.info(f"✅ Browser started: {self.session_id}")
    
    async def stop(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.context = None
        self.playwright = None
        self.pages = []
    
    def is_alive(self) -> bool:
        try:
            return self.context is not None and self.page is not None and not self.page.is_closed()
        except:
            return False
    
    async def get_viewport_bounds(self) -> Dict[str, Any]:
        if not self.page:
            raise RuntimeError("No active page")
        
        bounds = await self.page.evaluate("""() => ({
            window_x: window.screenX,
            window_y: window.screenY,
            viewport_width: window.innerWidth,
            viewport_height: window.innerHeight
        })""")
        
        return {
            "width": bounds['viewport_width'],
            "height": bounds['viewport_height']
        }
    
    async def capture_screenshot(self) -> bytes:
        if not self.page:
            raise RuntimeError("No active page")
        return await self.page.screenshot(type="png")
    
    async def get_accessibility_tree(self) -> Optional[Dict[str, Any]]:
        """Get the accessibility tree of the current page."""
        if not self.page:
            return None
        try:
            return await self.page.accessibility.snapshot()
        except Exception as e:
            logger.error(f"Accessibility tree error: {e}")
            return None
    
    async def get_element_rect(self, request: ElementRectRequest) -> ElementRectResponse:
        """Get element bounding rectangle - raw data only."""
        if not self.page:
            return ElementRectResponse(success=False, error="No active page")
        
        try:
            locator = None
            selector_description = ""
            
            # Build locator
            if request.selector:
                locator = self.page.locator(request.selector)
                selector_description = f"selector: {request.selector}"
            elif request.test_id:
                locator = self.page.get_by_test_id(request.test_id)
                selector_description = f"test_id: {request.test_id}"
            elif request.role and request.role_name:
                locator = self.page.get_by_role(request.role, name=request.role_name)
                selector_description = f"role: {request.role}, name: {request.role_name}"
            elif request.role:
                locator = self.page.get_by_role(request.role)
                selector_description = f"role: {request.role}"
            elif request.text:
                locator = self.page.get_by_text(request.text, exact=request.text_exact)
                selector_description = f"text: '{request.text}'"
            elif request.label:
                locator = self.page.get_by_label(request.label)
                selector_description = f"label: {request.label}"
            elif request.placeholder:
                locator = self.page.get_by_placeholder(request.placeholder)
                selector_description = f"placeholder: {request.placeholder}"
            else:
                return ElementRectResponse(success=False, error="No search criteria provided")
            
            count = await locator.count()
            
            if count == 0:
                return ElementRectResponse(
                    success=True, found=False, element_count=0,
                    selector_used=selector_description
                )
            
            if count > 1:
                if request.index is not None and request.index < count:
                    locator = locator.nth(request.index)
                else:
                    locator = locator.first
            
            is_visible = await locator.is_visible()
            
            if request.must_be_visible and not is_visible:
                return ElementRectResponse(
                    success=True, found=True, visible=False,
                    element_count=count, selector_used=selector_description
                )
            
            is_enabled = await locator.is_enabled()
            bbox = await locator.bounding_box()
            
            if not bbox:
                return ElementRectResponse(
                    success=True, found=True, visible=False,
                    enabled=is_enabled, element_count=count,
                    selector_used=selector_description
                )
            
            element_info = await locator.evaluate('''(el) => ({
                tag: el.tagName.toLowerCase(),
                text: el.innerText ? el.innerText.substring(0, 100) : null
            })''')
            
            center_x = int(bbox['x'] + bbox['width'] / 2)
            center_y = int(bbox['y'] + bbox['height'] / 2)
            
            return ElementRectResponse(
                success=True, found=True, visible=is_visible, enabled=is_enabled,
                x=center_x, y=center_y,
                bounding_box={"x": bbox['x'], "y": bbox['y'],
                             "width": bbox['width'], "height": bbox['height']},
                tag=element_info.get('tag'), text=element_info.get('text'),
                element_count=count, selector_used=selector_description
            )
            
        except Exception as e:
            logger.error(f"get_element_rect error: {e}")
            return ElementRectResponse(success=False, error=str(e))
    
    def get_tabs_info(self) -> List[Dict[str, Any]]:
        return [
            {"id": i, "url": p.url if not p.is_closed() else None, "is_current": i == self.current_page_index}
            for i, p in enumerate(self.pages)
        ]


class SessionManager:
    """Manages all browser sessions"""
    
    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
    
    async def create_session(self, start_url: Optional[str] = None, headless: bool = False) -> str:
        async with self._lock:
            session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            session = BrowserSession(session_id)
            await session.start(start_url, headless)
            self.sessions[session_id] = session
            return session_id
    
    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        return self.sessions.get(session_id)
    
    async def close_session(self, session_id: str) -> bool:
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session:
                await session.stop()
                return True
            return False
    
    def get_active_session(self) -> Optional[BrowserSession]:
        for session in self.sessions.values():
            if session.is_alive():
                return session
        return None
    
    def count(self) -> int:
        return len([s for s in self.sessions.values() if s.is_alive()])


session_manager = SessionManager()


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Architect's Hand - Tool Server",
    description="Hands Only Server - Execution without Intelligence (v8.4.2)",
    version=SERVICE_VERSION
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# ENDPOINTS: Status
# ============================================================================

@app.get("/")
async def root():
    return {
        "service": "Architect's Hand Tool Server",
        "version": SERVICE_VERSION,
        "mode": "HANDS_ONLY",
        "viewport": f"{VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT}"
    }


@app.get("/status", response_model=StatusResponse)
async def get_status():
    return StatusResponse(
        status="running",
        version=SERVICE_VERSION,
        browser_sessions=session_manager.count(),
        capabilities={
            "pyautogui": PYAUTOGUI_AVAILABLE,
            "pyperclip": PYPERCLIP_AVAILABLE,
            "playwright": PLAYWRIGHT_AVAILABLE,
            "pil": PIL_AVAILABLE
        },
        viewport={
            "width": VIEWPORT_WIDTH,
            "height": VIEWPORT_HEIGHT
        },
        references={
            "lux_sdk": {"width": LUX_SDK_WIDTH, "height": LUX_SDK_HEIGHT},
            "gemini_recommended": {"width": GEMINI_RECOMMENDED_WIDTH, "height": GEMINI_RECOMMENDED_HEIGHT},
            "normalized_range": {"min": 0, "max": NORMALIZED_COORD_MAX}
        }
    )


# ============================================================================
# ENDPOINTS: Screenshot
# ============================================================================

@app.post("/screenshot", response_model=ScreenshotResponse)
async def take_screenshot(request: ScreenshotRequest):
    """
    Cattura screenshot - dati grezzi per la Web App.
    
    Browser scope: 1260×700 (Lux native)
    Desktop scope: full screen
    """
    try:
        if request.scope == "browser":
            session = session_manager.get_session(request.session_id) if request.session_id else session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return ScreenshotResponse(success=False, error="No active browser session")
            
            screenshot_bytes = await session.capture_screenshot()
            viewport = await session.get_viewport_bounds()
            
            response = ScreenshotResponse(
                success=True,
                image_base64=base64.b64encode(screenshot_bytes).decode('utf-8'),
                width=viewport["width"],
                height=viewport["height"]
            )
            
            # Metadata per Lux (scale = 1.0 perché viewport = lux_sdk)
            if request.include_lux_metadata:
                response.lux_scale_x = 1.0
                response.lux_scale_y = 1.0
            
            # Opzionale: resize per Gemini
            if request.include_gemini_resize and PIL_AVAILABLE:
                gemini_b64, gw, gh = resize_image(
                    screenshot_bytes,
                    GEMINI_RECOMMENDED_WIDTH,
                    GEMINI_RECOMMENDED_HEIGHT
                )
                response.gemini_image_base64 = gemini_b64
                response.gemini_width = gw
                response.gemini_height = gh
            
            logger.info(f"📸 Screenshot: {viewport['width']}×{viewport['height']}")
            return response
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ScreenshotResponse(success=False, error="PyAutoGUI not available")
            
            screenshot = pyautogui.screenshot()
            buffer = io.BytesIO()
            screenshot.save(buffer, format='PNG')
            buffer.seek(0)
            screenshot_bytes = buffer.read()
            
            screen_w, screen_h = pyautogui.size()
            
            response = ScreenshotResponse(
                success=True,
                image_base64=base64.b64encode(screenshot_bytes).decode('utf-8'),
                width=screen_w,
                height=screen_h
            )
            
            if request.include_lux_metadata:
                response.lux_scale_x = screen_w / LUX_SDK_WIDTH
                response.lux_scale_y = screen_h / LUX_SDK_HEIGHT
            
            return response
        
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        return ScreenshotResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Click
# ============================================================================

@app.post("/click", response_model=ActionResponse)
async def do_click(request: ClickRequest):
    """Esegue click - la Web App ha già deciso le coordinate."""
    try:
        x, y = request.x, request.y
        
        if request.scope == "browser":
            session = session_manager.get_session(request.session_id) if request.session_id else session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            
            # Converti se necessario
            if request.coordinate_origin == "lux_sdk":
                x, y = CoordinateConverter.lux_sdk_to_viewport(x, y)
            elif request.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_viewport(x, y)
            
            # Esegui
            if request.click_type == "single":
                await session.page.mouse.click(x, y)
            elif request.click_type == "double":
                await session.page.mouse.dblclick(x, y)
            elif request.click_type == "right":
                await session.page.mouse.click(x, y, button="right")
            
            logger.info(f"🖱️ Click: ({x}, {y})")
            return ActionResponse(
                success=True,
                executed_with="playwright",
                details={"x": x, "y": y, "original": {"x": request.x, "y": request.y}}
            )
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(success=False, error="PyAutoGUI not available")
            
            screen_w, screen_h = pyautogui.size()
            
            if request.coordinate_origin == "lux_sdk":
                x, y = CoordinateConverter.lux_sdk_to_screen(x, y, screen_w, screen_h)
            elif request.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_screen(x, y, screen_w, screen_h)
            
            if request.click_type == "single":
                pyautogui.click(x, y)
            elif request.click_type == "double":
                pyautogui.doubleClick(x, y)
            elif request.click_type == "right":
                pyautogui.rightClick(x, y)
            
            logger.info(f"🖱️ Desktop Click: ({x}, {y})")
            return ActionResponse(success=True, executed_with="pyautogui", details={"x": x, "y": y})
    
    except Exception as e:
        logger.error(f"Click error: {e}")
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Type
# ============================================================================

@app.post("/type", response_model=ActionResponse)
async def do_type(request: TypeRequest):
    """Digita testo."""
    try:
        if request.scope == "browser":
            session = session_manager.get_session(request.session_id) if request.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            
            if request.selector:
                await session.page.click(request.selector)
                await asyncio.sleep(0.1)
            
            await session.page.keyboard.type(request.text, delay=50)
            logger.info(f"⌨️ Type: '{request.text[:20]}...' " if len(request.text) > 20 else f"⌨️ Type: '{request.text}'")
            return ActionResponse(success=True, executed_with="playwright")
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(success=False, error="PyAutoGUI not available")
            
            if request.method == "clipboard":
                type_via_clipboard(request.text)
            else:
                pyautogui.typewrite(request.text, interval=0.05)
            
            logger.info(f"⌨️ Desktop Type: '{request.text[:20]}...' " if len(request.text) > 20 else f"⌨️ Desktop Type: '{request.text}'")
            return ActionResponse(success=True, executed_with="pyautogui")
    
    except Exception as e:
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Scroll
# ============================================================================

@app.post("/scroll", response_model=ActionResponse)
async def do_scroll(request: ScrollRequest):
    """Esegue scroll."""
    try:
        if request.scope == "browser":
            session = session_manager.get_session(request.session_id) if request.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            
            delta_x, delta_y = 0, 0
            if request.direction == "up":
                delta_y = -request.amount
            elif request.direction == "down":
                delta_y = request.amount
            elif request.direction == "left":
                delta_x = -request.amount
            elif request.direction == "right":
                delta_x = request.amount
            
            await session.page.mouse.wheel(delta_x, delta_y)
            logger.info(f"📜 Scroll: {request.direction} {request.amount}px")
            return ActionResponse(success=True, executed_with="playwright")
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(success=False, error="PyAutoGUI not available")
            
            clicks = request.amount // 100
            if request.direction == "up":
                pyautogui.scroll(clicks)
            elif request.direction == "down":
                pyautogui.scroll(-clicks)
            
            logger.info(f"📜 Desktop Scroll: {request.direction} {clicks} clicks")
            return ActionResponse(success=True, executed_with="pyautogui")
    
    except Exception as e:
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Keypress
# ============================================================================

@app.post("/keypress", response_model=ActionResponse)
async def do_keypress(request: KeypressRequest):
    """Preme tasto o combinazione."""
    try:
        if request.scope == "browser":
            session = session_manager.get_session(request.session_id) if request.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            
            if "+" in request.key:
                keys = request.key.split("+")
                for key in keys[:-1]:
                    await session.page.keyboard.down(key)
                await session.page.keyboard.press(keys[-1])
                for key in reversed(keys[:-1]):
                    await session.page.keyboard.up(key)
            else:
                await session.page.keyboard.press(request.key)
            
            logger.info(f"⌨️ Keypress: {request.key}")
            return ActionResponse(success=True, executed_with="playwright")
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(success=False, error="PyAutoGUI not available")
            
            if "+" in request.key:
                pyautogui.hotkey(*request.key.lower().split("+"))
            else:
                pyautogui.press(request.key.lower())
            
            logger.info(f"⌨️ Desktop Keypress: {request.key}")
            return ActionResponse(success=True, executed_with="pyautogui")
    
    except Exception as e:
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Browser Session Management
# ============================================================================

@app.post("/browser/start")
async def browser_start(request: BrowserStartRequest):
    if not PLAYWRIGHT_AVAILABLE:
        raise HTTPException(status_code=500, detail="Playwright not available")
    
    try:
        session_id = await session_manager.create_session(request.start_url, request.headless)
        session = session_manager.get_session(session_id)
        
        return {
            "success": True,
            "session_id": session_id,
            "current_url": session.page.url if session and session.page else None,
            "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/browser/stop")
async def browser_stop(session_id: str = Query(...)):
    success = await session_manager.close_session(session_id)
    return {"success": success}


@app.get("/browser/status")
async def browser_status(session_id: Optional[str] = None):
    if session_id:
        session = session_manager.get_session(session_id)
        if session:
            return {
                "session_id": session_id,
                "is_alive": session.is_alive(),
                "current_url": session.page.url if session.page else None
            }
        return {"error": "Session not found"}
    
    return {
        "sessions": [
            {"session_id": sid, "is_alive": s.is_alive()}
            for sid, s in session_manager.sessions.items()
        ]
    }


# ============================================================================
# ENDPOINTS: Browser Navigation
# ============================================================================

@app.post("/browser/navigate")
async def browser_navigate(request: NavigateRequest):
    session = session_manager.get_session(request.session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        await session.page.goto(request.url, wait_until="domcontentloaded", timeout=30000)
        logger.info(f"🌐 Navigate: {request.url}")
        return {"success": True, "url": session.page.url}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/reload")
async def browser_reload(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        await session.page.reload(wait_until="domcontentloaded")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/back")
async def browser_back(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        await session.page.go_back()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/forward")
async def browser_forward(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        await session.page.go_forward()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# ENDPOINTS: Browser Tabs
# ============================================================================

@app.get("/browser/tabs")
async def browser_tabs(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if not session:
        return {"success": False, "error": "Session not found"}
    return {"success": True, "tabs": session.get_tabs_info()}


@app.post("/browser/tab/new")
async def browser_tab_new(request: TabRequest):
    session = session_manager.get_session(request.session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        new_page = await session.context.new_page()
        session.pages.append(new_page)
        session.current_page_index = len(session.pages) - 1
        
        if request.url:
            await new_page.goto(request.url, wait_until="domcontentloaded")
        
        return {"success": True, "tab_id": session.current_page_index}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/tab/close")
async def browser_tab_close(request: TabRequest):
    session = session_manager.get_session(request.session_id)
    if not session:
        return {"success": False, "error": "Session not found"}
    
    tab_id = request.tab_id if request.tab_id is not None else session.current_page_index
    
    if 0 <= tab_id < len(session.pages):
        try:
            await session.pages[tab_id].close()
            session.pages.pop(tab_id)
            if session.current_page_index >= len(session.pages):
                session.current_page_index = max(0, len(session.pages) - 1)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    return {"success": False, "error": "Tab not found"}


@app.post("/browser/tab/switch")
async def browser_tab_switch(request: TabRequest):
    session = session_manager.get_session(request.session_id)
    if not session:
        return {"success": False, "error": "Session not found"}
    
    if request.tab_id is not None and 0 <= request.tab_id < len(session.pages):
        session.current_page_index = request.tab_id
        await session.pages[request.tab_id].bring_to_front()
        return {"success": True, "tab_id": request.tab_id}
    
    return {"success": False, "error": "Tab not found"}


# ============================================================================
# ENDPOINTS: Browser DOM
# ============================================================================

@app.get("/browser/dom/tree")
async def browser_dom_tree(session_id: str = Query(...)):
    """
    Restituisce l'Accessibility Tree della pagina corrente.
    
    Usato dall'agente DOM Analyzer per:
    - Analizzare la struttura del sito
    - Identificare elementi interattivi
    - Pianificare strategie di automazione
    """
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        tree = await session.get_accessibility_tree()
        logger.info(f"🌳 DOM Tree requested for: {session.page.url}")
        return {
            "success": True,
            "url": session.page.url,
            "tree": tree
        }
    except Exception as e:
        logger.error(f"DOM tree error: {e}")
        return {"success": False, "error": str(e)}


@app.post("/browser/dom/element_rect", response_model=ElementRectResponse)
async def browser_element_rect(request: ElementRectRequest):
    """
    Ottieni coordinate elemento DOM.
    
    Restituisce dati grezzi:
    - x, y: centro elemento (viewport coords)
    - bounding_box: rettangolo completo
    - visible, enabled, found: stato elemento
    
    La Web App usa questi dati per Triple Verification.
    """
    session = session_manager.get_session(request.session_id)
    if not session or not session.is_alive():
        return ElementRectResponse(success=False, error="Session not found")
    
    result = await session.get_element_rect(request)
    if result.success and result.found:
        logger.info(f"📍 Element rect: ({result.x}, {result.y}) - {result.selector_used}")
    return result


@app.get("/browser/current_url")
async def browser_current_url(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    return {"success": True, "url": session.page.url}


# ============================================================================
# ENDPOINTS: Coordinate Conversion (Utility)
# ============================================================================

@app.post("/coordinates/convert")
async def coordinates_convert(request: CoordinateConvertRequest):
    """
    Utility per conversione coordinate.
    La Web App può usarlo se necessario, ma può anche calcolare localmente.
    """
    try:
        x, y = request.x, request.y
        result_x, result_y = x, y
        
        if PYAUTOGUI_AVAILABLE:
            screen_w, screen_h = pyautogui.size()
        else:
            screen_w, screen_h = 1920, 1080
        
        # FROM lux_sdk
        if request.from_space == "lux_sdk":
            if request.to_space == "viewport":
                result_x, result_y = CoordinateConverter.lux_sdk_to_viewport(x, y)
            elif request.to_space == "screen":
                result_x, result_y = CoordinateConverter.lux_sdk_to_screen(x, y, screen_w, screen_h)
            elif request.to_space == "normalized":
                # lux_sdk → viewport → normalized
                vx, vy = CoordinateConverter.lux_sdk_to_viewport(x, y)
                result_x, result_y = CoordinateConverter.viewport_to_normalized(vx, vy)
        
        # FROM normalized
        elif request.from_space == "normalized":
            if request.to_space == "viewport":
                result_x, result_y = CoordinateConverter.normalized_to_viewport(x, y)
            elif request.to_space == "screen":
                result_x, result_y = CoordinateConverter.normalized_to_screen(x, y, screen_w, screen_h)
            elif request.to_space == "lux_sdk":
                # normalized → viewport → lux_sdk (= viewport)
                result_x, result_y = CoordinateConverter.normalized_to_viewport(x, y)
        
        # FROM viewport
        elif request.from_space == "viewport":
            if request.to_space == "normalized":
                result_x, result_y = CoordinateConverter.viewport_to_normalized(x, y)
            elif request.to_space == "lux_sdk":
                # viewport = lux_sdk
                result_x, result_y = x, y
        
        return {
            "success": True,
            "x": result_x,
            "y": result_y,
            "from_space": request.from_space,
            "to_space": request.to_space
        }
    
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║      ARCHITECT'S HAND - TOOL SERVER v{SERVICE_VERSION}                ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  🖐️  MODE: HANDS ONLY                                        ║
║                                                              ║
║  Questo server fornisce SOLO esecuzione:                     ║
║  ├── Screenshot (dati grezzi)                                ║
║  ├── DOM tree (Accessibility Tree)                           ║
║  ├── DOM element_rect (dati grezzi)                          ║
║  ├── Click/Type/Scroll/Keypress (esecuzione)                 ║
║  └── Coordinate conversion (utility)                         ║
║                                                              ║
║  NESSUNA logica decisionale:                                 ║
║  ├── ❌ No Triple Verification (→ Web App)                   ║
║  ├── ❌ No Confidence scoring (→ Web App)                    ║
║  └── ❌ No Decision making (→ Web App)                       ║
║                                                              ║
║  VIEWPORT: {VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT} (Lux SDK native)                    ║
║  ├── Lux coords: 1:1 mapping (no conversion)                 ║
║  ├── DOM coords: viewport native                             ║
║  └── Gemini coords: normalized 0-999 (convert in Web App)    ║
║                                                              ║
║  Capabilities:                                               ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Playwright (Browser)                             ║
║    {'✅' if PYAUTOGUI_AVAILABLE else '❌'} PyAutoGUI (Desktop)                               ║
║    {'✅' if PIL_AVAILABLE else '❌'} PIL (Image resize)                                 ║
║                                                              ║
║  Endpoint: http://127.0.0.1:{SERVICE_PORT}                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT, log_level="info")
