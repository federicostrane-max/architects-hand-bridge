#!/usr/bin/env python3
"""
tool_server.py v8.4.3 - Desktop App "Hands Only" Server + ngrok
===============================================================

NOVITÀ v8.4.3: NGROK INTEGRATO
==============================
Il server avvia automaticamente un tunnel ngrok per essere raggiungibile
via HTTPS dalla Web App Lovable (che gira su HTTPS e non può chiamare HTTP).

Basta avviare questo file e l'URL pubblico apparirà nel banner!

CHANGELOG:
- v8.4.2: Aggiunto /browser/dom/tree endpoint
- v8.4.3: Integrato ngrok tunnel automatico
"""

import asyncio
import base64
import io
import json
import logging
import os
import sys
import time
import atexit
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Literal, List, Dict, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ============================================================================
# NGROK CONFIGURATION
# ============================================================================

NGROK_ENABLED = True
NGROK_PUBLIC_URL = None

try:
    from pyngrok import ngrok
    PYNGROK_AVAILABLE = True
except ImportError:
    PYNGROK_AVAILABLE = False
    NGROK_ENABLED = False

# ============================================================================
# CONFIGURATION
# ============================================================================

SERVICE_VERSION = "8.4.3"
SERVICE_PORT = 8766

LUX_SDK_WIDTH = 1260
LUX_SDK_HEIGHT = 700
GEMINI_RECOMMENDED_WIDTH = 1440
GEMINI_RECOMMENDED_HEIGHT = 900

VIEWPORT_WIDTH = LUX_SDK_WIDTH
VIEWPORT_HEIGHT = LUX_SDK_HEIGHT
NORMALIZED_COORD_MAX = 999
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
logging.getLogger("pyngrok").setLevel(logging.WARNING)

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
    from playwright.async_api import async_playwright, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
    logger.info("✅ Playwright available")
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("⚠️ Playwright not available")

if PYNGROK_AVAILABLE:
    logger.info("✅ pyngrok available")
else:
    logger.warning("⚠️ pyngrok not available - install with: pip install pyngrok")

# ============================================================================
# NGROK TUNNEL
# ============================================================================

def start_ngrok_tunnel(port: int) -> Optional[str]:
    global NGROK_PUBLIC_URL
    if not PYNGROK_AVAILABLE or not NGROK_ENABLED:
        return None
    try:
        public_url = ngrok.connect(port, "http").public_url
        NGROK_PUBLIC_URL = public_url
        logger.info(f"🔒 ngrok tunnel: {public_url}")
        return public_url
    except Exception as e:
        logger.error(f"❌ ngrok failed: {e}")
        return None

def stop_ngrok_tunnel():
    if PYNGROK_AVAILABLE:
        try:
            ngrok.kill()
        except:
            pass

atexit.register(stop_ngrok_tunnel)

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ScreenshotRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    session_id: Optional[str] = None
    include_lux_metadata: bool = True
    include_gemini_resize: bool = False

class ClickRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    x: int
    y: int
    coordinate_origin: Literal["viewport", "screen", "lux_sdk", "normalized"] = "viewport"
    click_type: Literal["single", "double", "right"] = "single"
    session_id: Optional[str] = None

class TypeRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    text: str
    method: Literal["clipboard", "keystrokes"] = "clipboard"
    session_id: Optional[str] = None
    selector: Optional[str] = None

class ScrollRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = 300
    session_id: Optional[str] = None

class KeypressRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    key: str
    session_id: Optional[str] = None

class BrowserStartRequest(BaseModel):
    start_url: Optional[str] = None
    headless: bool = False

class NavigateRequest(BaseModel):
    session_id: str
    url: str

class TabRequest(BaseModel):
    session_id: str
    tab_id: Optional[int] = None
    url: Optional[str] = None

class ElementRectRequest(BaseModel):
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

class ActionResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    executed_with: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class ScreenshotResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    image_base64: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    lux_scale_x: Optional[float] = None
    lux_scale_y: Optional[float] = None

class ElementRectResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    found: bool = False
    visible: bool = False
    enabled: bool = False
    x: Optional[int] = None
    y: Optional[int] = None
    bounding_box: Optional[Dict[str, float]] = None
    tag: Optional[str] = None
    text: Optional[str] = None
    element_count: Optional[int] = None
    selector_used: Optional[str] = None

# ============================================================================
# COORDINATE CONVERTER
# ============================================================================

class CoordinateConverter:
    @staticmethod
    def lux_sdk_to_viewport(x: int, y: int) -> Tuple[int, int]:
        return x, y
    
    @staticmethod
    def normalized_to_viewport(x: int, y: int) -> Tuple[int, int]:
        return int(x / 1000 * VIEWPORT_WIDTH), int(y / 1000 * VIEWPORT_HEIGHT)
    
    @staticmethod
    def viewport_to_normalized(x: int, y: int) -> Tuple[int, int]:
        return (
            max(0, min(999, int(x / VIEWPORT_WIDTH * 1000))),
            max(0, min(999, int(y / VIEWPORT_HEIGHT * 1000)))
        )
    
    @staticmethod
    def lux_sdk_to_screen(x: int, y: int, sw: int, sh: int) -> Tuple[int, int]:
        return int(x * sw / LUX_SDK_WIDTH), int(y * sh / LUX_SDK_HEIGHT)
    
    @staticmethod
    def normalized_to_screen(x: int, y: int, sw: int, sh: int) -> Tuple[int, int]:
        return int(x / 1000 * sw), int(y / 1000 * sh)

# ============================================================================
# UTILITIES
# ============================================================================

def resize_image(image_bytes: bytes, tw: int, th: int) -> Tuple[str, int, int]:
    img = Image.open(io.BytesIO(image_bytes))
    resized = img.resize((tw, th), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8'), tw, th

def type_via_clipboard(text: str):
    if PYPERCLIP_AVAILABLE:
        try:
            old = pyperclip.paste()
        except:
            old = ""
        pyperclip.copy(text)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        try:
            pyperclip.copy(old)
        except:
            pass
    else:
        pyautogui.typewrite(text, interval=0.05)

# ============================================================================
# BROWSER SESSION
# ============================================================================

class BrowserSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.pages: List[Page] = []
        self.current_page_index = 0
    
    @property
    def page(self):
        if self.pages and 0 <= self.current_page_index < len(self.pages):
            return self.pages[self.current_page_index]
        return None
    
    async def start(self, start_url: Optional[str] = None, headless: bool = False):
        self.playwright = await async_playwright().start()
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            channel="msedge",
            headless=headless,
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            args=["--disable-blink-features=AutomationControlled", "--disable-infobars", "--no-first-run"]
        )
        
        self.pages = list(self.context.pages) if self.context.pages else [await self.context.new_page()]
        
        if start_url and self.page:
            await self.page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
        
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
    
    async def get_accessibility_tree(self):
        if self.page:
            return await self.page.accessibility.snapshot()
        return None
    
    async def get_element_rect(self, req: ElementRectRequest) -> ElementRectResponse:
        if not self.page:
            return ElementRectResponse(success=False, error="No active page")
        
        try:
            locator = None
            desc = ""
            
            if req.selector:
                locator = self.page.locator(req.selector)
                desc = f"selector: {req.selector}"
            elif req.test_id:
                locator = self.page.get_by_test_id(req.test_id)
                desc = f"test_id: {req.test_id}"
            elif req.role and req.role_name:
                locator = self.page.get_by_role(req.role, name=req.role_name)
                desc = f"role: {req.role}, name: {req.role_name}"
            elif req.role:
                locator = self.page.get_by_role(req.role)
                desc = f"role: {req.role}"
            elif req.text:
                locator = self.page.get_by_text(req.text, exact=req.text_exact)
                desc = f"text: '{req.text}'"
            elif req.label:
                locator = self.page.get_by_label(req.label)
                desc = f"label: {req.label}"
            elif req.placeholder:
                locator = self.page.get_by_placeholder(req.placeholder)
                desc = f"placeholder: {req.placeholder}"
            else:
                return ElementRectResponse(success=False, error="No criteria")
            
            count = await locator.count()
            if count == 0:
                return ElementRectResponse(success=True, found=False, element_count=0, selector_used=desc)
            
            if count > 1:
                locator = locator.nth(req.index) if req.index < count else locator.first
            
            visible = await locator.is_visible()
            if req.must_be_visible and not visible:
                return ElementRectResponse(success=True, found=True, visible=False, element_count=count, selector_used=desc)
            
            enabled = await locator.is_enabled()
            bbox = await locator.bounding_box()
            
            if not bbox:
                return ElementRectResponse(success=True, found=True, visible=False, enabled=enabled, element_count=count, selector_used=desc)
            
            info = await locator.evaluate('(el) => ({tag: el.tagName.toLowerCase(), text: el.innerText?.substring(0,100)})')
            
            return ElementRectResponse(
                success=True, found=True, visible=visible, enabled=enabled,
                x=int(bbox['x'] + bbox['width']/2),
                y=int(bbox['y'] + bbox['height']/2),
                bounding_box=bbox,
                tag=info.get('tag'), text=info.get('text'),
                element_count=count, selector_used=desc
            )
        except Exception as e:
            return ElementRectResponse(success=False, error=str(e))

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
    
    async def create_session(self, start_url: Optional[str] = None, headless: bool = False) -> str:
        async with self._lock:
            sid = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            session = BrowserSession(sid)
            await session.start(start_url, headless)
            self.sessions[sid] = session
            return sid
    
    def get_session(self, sid: str):
        return self.sessions.get(sid)
    
    async def close_session(self, sid: str) -> bool:
        async with self._lock:
            session = self.sessions.pop(sid, None)
            if session:
                await session.stop()
                return True
            return False
    
    def get_active_session(self):
        for s in self.sessions.values():
            if s.is_alive():
                return s
        return None
    
    def count(self) -> int:
        return len([s for s in self.sessions.values() if s.is_alive()])

session_manager = SessionManager()

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(title="Tool Server", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"service": "Tool Server", "version": SERVICE_VERSION, "ngrok_url": NGROK_PUBLIC_URL}

@app.get("/status")
async def get_status():
    return {
        "status": "running",
        "version": SERVICE_VERSION,
        "browser_sessions": session_manager.count(),
        "capabilities": {"pyautogui": PYAUTOGUI_AVAILABLE, "pyperclip": PYPERCLIP_AVAILABLE, "playwright": PLAYWRIGHT_AVAILABLE, "pil": PIL_AVAILABLE, "ngrok": PYNGROK_AVAILABLE},
        "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        "ngrok_url": NGROK_PUBLIC_URL,
        "references": {"lux_sdk": {"width": LUX_SDK_WIDTH, "height": LUX_SDK_HEIGHT}, "gemini_recommended": {"width": GEMINI_RECOMMENDED_WIDTH, "height": GEMINI_RECOMMENDED_HEIGHT}, "normalized_range": {"min": 0, "max": 999}}
    }

@app.post("/screenshot", response_model=ScreenshotResponse)
async def take_screenshot(req: ScreenshotRequest):
    try:
        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ScreenshotResponse(success=False, error="No active browser session")
            
            data = await session.page.screenshot(type="png")
            vp = await session.page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
            
            resp = ScreenshotResponse(success=True, image_base64=base64.b64encode(data).decode(), width=vp['w'], height=vp['h'])
            if req.include_lux_metadata:
                resp.lux_scale_x = resp.lux_scale_y = 1.0
            logger.info(f"📸 Screenshot: {vp['w']}×{vp['h']}")
            return resp
        
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            shot = pyautogui.screenshot()
            buf = io.BytesIO()
            shot.save(buf, format='PNG')
            sw, sh = pyautogui.size()
            return ScreenshotResponse(success=True, image_base64=base64.b64encode(buf.getvalue()).decode(), width=sw, height=sh, lux_scale_x=sw/LUX_SDK_WIDTH, lux_scale_y=sh/LUX_SDK_HEIGHT)
    except Exception as e:
        return ScreenshotResponse(success=False, error=str(e))

@app.post("/click", response_model=ActionResponse)
async def do_click(req: ClickRequest):
    try:
        x, y = req.x, req.y
        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            
            if req.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_viewport(x, y)
            
            if req.click_type == "double":
                await session.page.mouse.dblclick(x, y)
            elif req.click_type == "right":
                await session.page.mouse.click(x, y, button="right")
            else:
                await session.page.mouse.click(x, y)
            
            logger.info(f"🖱️ Click: ({x}, {y})")
            return ActionResponse(success=True, executed_with="playwright", details={"x": x, "y": y})
        
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            sw, sh = pyautogui.size()
            if req.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_screen(x, y, sw, sh)
            elif req.coordinate_origin == "lux_sdk":
                x, y = CoordinateConverter.lux_sdk_to_screen(x, y, sw, sh)
            
            if req.click_type == "double":
                pyautogui.doubleClick(x, y)
            elif req.click_type == "right":
                pyautogui.rightClick(x, y)
            else:
                pyautogui.click(x, y)
            
            return ActionResponse(success=True, executed_with="pyautogui", details={"x": x, "y": y})
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/type", response_model=ActionResponse)
async def do_type(req: TypeRequest):
    try:
        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            if req.selector:
                await session.page.click(req.selector)
            await session.page.keyboard.type(req.text, delay=50)
            logger.info(f"⌨️ Type: '{req.text[:20]}...'")
            return ActionResponse(success=True, executed_with="playwright")
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            type_via_clipboard(req.text) if req.method == "clipboard" else pyautogui.typewrite(req.text)
            return ActionResponse(success=True, executed_with="pyautogui")
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/scroll", response_model=ActionResponse)
async def do_scroll(req: ScrollRequest):
    try:
        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            dx, dy = (0, -req.amount) if req.direction == "up" else (0, req.amount) if req.direction == "down" else (-req.amount, 0) if req.direction == "left" else (req.amount, 0)
            await session.page.mouse.wheel(dx, dy)
            logger.info(f"📜 Scroll: {req.direction}")
            return ActionResponse(success=True, executed_with="playwright")
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            clicks = req.amount // 100
            pyautogui.scroll(clicks if req.direction == "up" else -clicks)
            return ActionResponse(success=True, executed_with="pyautogui")
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/keypress", response_model=ActionResponse)
async def do_keypress(req: KeypressRequest):
    try:
        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            if "+" in req.key:
                keys = req.key.split("+")
                for k in keys[:-1]:
                    await session.page.keyboard.down(k)
                await session.page.keyboard.press(keys[-1])
                for k in reversed(keys[:-1]):
                    await session.page.keyboard.up(k)
            else:
                await session.page.keyboard.press(req.key)
            logger.info(f"⌨️ Key: {req.key}")
            return ActionResponse(success=True, executed_with="playwright")
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey(*req.key.lower().split("+")) if "+" in req.key else pyautogui.press(req.key.lower())
            return ActionResponse(success=True, executed_with="pyautogui")
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

# Browser endpoints
@app.post("/browser/start")
async def browser_start(req: BrowserStartRequest):
    if not PLAYWRIGHT_AVAILABLE:
        raise HTTPException(500, "Playwright not available")
    sid = await session_manager.create_session(req.start_url, req.headless)
    session = session_manager.get_session(sid)
    return {"success": True, "session_id": sid, "current_url": session.page.url if session and session.page else None, "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}}

@app.post("/browser/stop")
async def browser_stop(session_id: str = Query(...)):
    return {"success": await session_manager.close_session(session_id)}

@app.get("/browser/status")
async def browser_status(session_id: Optional[str] = None):
    if session_id:
        s = session_manager.get_session(session_id)
        return {"session_id": session_id, "is_alive": s.is_alive(), "current_url": s.page.url if s and s.page else None} if s else {"error": "Not found"}
    return {"sessions": [{"session_id": k, "is_alive": v.is_alive()} for k, v in session_manager.sessions.items()]}

@app.post("/browser/navigate")
async def browser_navigate(req: NavigateRequest):
    session = session_manager.get_session(req.session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    await session.page.goto(req.url, wait_until="domcontentloaded", timeout=30000)
    logger.info(f"🌐 Navigate: {req.url}")
    return {"success": True, "url": session.page.url}

@app.post("/browser/reload")
async def browser_reload(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    await session.page.reload()
    return {"success": True}

@app.post("/browser/back")
async def browser_back(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if session and session.is_alive():
        await session.page.go_back()
        return {"success": True}
    return {"success": False}

@app.post("/browser/forward")
async def browser_forward(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if session and session.is_alive():
        await session.page.go_forward()
        return {"success": True}
    return {"success": False}

@app.get("/browser/tabs")
async def browser_tabs(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if not session:
        return {"success": False}
    return {"success": True, "tabs": [{"id": i, "url": p.url if not p.is_closed() else None, "is_current": i == session.current_page_index} for i, p in enumerate(session.pages)]}

@app.post("/browser/tab/new")
async def browser_tab_new(req: TabRequest):
    session = session_manager.get_session(req.session_id)
    if not session or not session.is_alive():
        return {"success": False}
    new_page = await session.context.new_page()
    session.pages.append(new_page)
    session.current_page_index = len(session.pages) - 1
    if req.url:
        await new_page.goto(req.url)
    return {"success": True, "tab_id": session.current_page_index}

@app.post("/browser/tab/close")
async def browser_tab_close(req: TabRequest):
    session = session_manager.get_session(req.session_id)
    if not session:
        return {"success": False}
    tid = req.tab_id if req.tab_id is not None else session.current_page_index
    if 0 <= tid < len(session.pages):
        await session.pages[tid].close()
        session.pages.pop(tid)
        session.current_page_index = min(session.current_page_index, len(session.pages) - 1)
        return {"success": True}
    return {"success": False}

@app.post("/browser/tab/switch")
async def browser_tab_switch(req: TabRequest):
    session = session_manager.get_session(req.session_id)
    if session and req.tab_id is not None and 0 <= req.tab_id < len(session.pages):
        session.current_page_index = req.tab_id
        await session.pages[req.tab_id].bring_to_front()
        return {"success": True}
    return {"success": False}

# DOM endpoints
@app.get("/browser/dom/tree")
async def browser_dom_tree(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    tree = await session.get_accessibility_tree()
    logger.info(f"🌳 DOM Tree: {session.page.url}")
    return {"success": True, "url": session.page.url, "tree": tree}

@app.post("/browser/dom/element_rect", response_model=ElementRectResponse)
async def browser_element_rect(req: ElementRectRequest):
    session = session_manager.get_session(req.session_id)
    if not session or not session.is_alive():
        return ElementRectResponse(success=False, error="Session not found")
    result = await session.get_element_rect(req)
    if result.found:
        logger.info(f"📍 Element: ({result.x}, {result.y})")
    return result

@app.get("/browser/current_url")
async def browser_current_url(session_id: str = Query(...)):
    session = session_manager.get_session(session_id)
    if session and session.is_alive():
        return {"success": True, "url": session.page.url}
    return {"success": False}

@app.post("/coordinates/convert")
async def coordinates_convert(x: int, y: int, from_space: str, to_space: str):
    rx, ry = x, y
    sw, sh = pyautogui.size() if PYAUTOGUI_AVAILABLE else (1920, 1080)
    
    if from_space == "normalized" and to_space == "viewport":
        rx, ry = CoordinateConverter.normalized_to_viewport(x, y)
    elif from_space == "viewport" and to_space == "normalized":
        rx, ry = CoordinateConverter.viewport_to_normalized(x, y)
    elif from_space == "lux_sdk" and to_space == "screen":
        rx, ry = CoordinateConverter.lux_sdk_to_screen(x, y, sw, sh)
    
    return {"success": True, "x": rx, "y": ry}

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    ngrok_url = start_ngrok_tunnel(SERVICE_PORT)
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║      ARCHITECT'S HAND - TOOL SERVER v{SERVICE_VERSION}                ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  🖐️  MODE: HANDS ONLY                                        ║
║                                                              ║
║  ENDPOINTS:                                                  ║
║  ├── 🏠 LOCAL:  http://127.0.0.1:{SERVICE_PORT}                       ║
║  └── 🔒 PUBLIC: {(ngrok_url or 'NOT AVAILABLE'):<42} ║
║                                                              ║
║  VIEWPORT: {VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT} (Lux SDK native)                    ║
║                                                              ║
║  Capabilities:                                               ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Playwright     {'✅' if PYAUTOGUI_AVAILABLE else '❌'} PyAutoGUI                  ║
║    {'✅' if PIL_AVAILABLE else '❌'} PIL            {'✅' if PYNGROK_AVAILABLE else '❌'} ngrok                      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    if ngrok_url:
        print(f"📋 Copy this URL for Lovable: {ngrok_url}\n")
    
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT, log_level="info")
