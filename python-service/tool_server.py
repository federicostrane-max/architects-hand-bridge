#!/usr/bin/env python3
"""
tool_server.py v10.0.0 - Desktop App "Hands Only" Server + Playwright MCP Style
================================================================================

NOVITÀ v10.0.0: PLAYWRIGHT MCP COMPATIBILITY
============================================
Nuove funzionalità ispirate a Playwright MCP per automazione avanzata:
- Accessibility Ref System: ogni elemento ha un ref ID univoco (es. "e3")
- Click by Ref: clicca elementi direttamente per ref invece di coordinate
- Smart Waiting: waitForSelector, waitForLoadState invece di sleep fissi
- File Upload: upload file su input type=file
- Drag and Drop: trascina elementi
- Select Option: selezione dropdown
- Hover: hover su elementi
- Error Recovery: auto-retry con exponential backoff

CHANGELOG:
- v8.4.2: Aggiunto /browser/dom/tree endpoint
- v8.4.3: Integrato ngrok tunnel automatico
- v8.4.4: Fix accessibility API deprecata → estrazione DOM via JavaScript
- v8.5.0: Sistema di pairing automatico con Web App
- v9.0.0: Claude Computer Use compatibility (hold_key, wait, triple_click, auto-screenshot)
- v10.0.0: Playwright MCP compatibility (ref system, smart waiting, file upload, drag, hover)
- v10.1.0: Auto-snapshot DOM after actions (include_snapshot parameter for agent awareness)
- v10.2.0: Playwright MCP alignment - snapshot ALWAYS included for browser actions, semantic attributes [active] [checked] [disabled] etc.
"""

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import sys
import time
import atexit
import requests
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

SERVICE_VERSION = "10.2.0"  # Always snapshot for browser actions (Playwright MCP style)
SERVICE_PORT = 8766

# ============================================================================
# PAIRING CONFIGURATION
# ============================================================================

PAIRING_CONFIG_FILE = Path.home() / ".tool_server_config.json"
PAIRING_CONFIG = None  # Will be loaded from file

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
# PAIRING FUNCTIONS
# ============================================================================

def load_pairing_config() -> Optional[Dict]:
    """Load pairing config from file"""
    global PAIRING_CONFIG
    if PAIRING_CONFIG_FILE.exists():
        try:
            with open(PAIRING_CONFIG_FILE, 'r') as f:
                PAIRING_CONFIG = json.load(f)
                logger.info(f"✅ Loaded pairing config for user: {PAIRING_CONFIG.get('user_id', 'unknown')[:8]}...")
                return PAIRING_CONFIG
        except Exception as e:
            logger.error(f"❌ Failed to load pairing config: {e}")
    return None

def save_pairing_config(config: Dict):
    """Save pairing config to file"""
    global PAIRING_CONFIG
    try:
        with open(PAIRING_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        PAIRING_CONFIG = config
        logger.info(f"✅ Saved pairing config to {PAIRING_CONFIG_FILE}")
    except Exception as e:
        logger.error(f"❌ Failed to save pairing config: {e}")

def delete_pairing_config():
    """Delete pairing config file"""
    global PAIRING_CONFIG
    if PAIRING_CONFIG_FILE.exists():
        try:
            PAIRING_CONFIG_FILE.unlink()
            PAIRING_CONFIG = None
            logger.info("✅ Deleted pairing config")
        except Exception as e:
            logger.error(f"❌ Failed to delete pairing config: {e}")

def do_pairing(token: str) -> bool:
    """Perform pairing with the web app using a token"""
    logger.info(f"🔗 Attempting pairing with token: {token}")

    # Default Supabase URL (hardcoded for this project)
    # This will be overwritten by the response
    SUPABASE_URL = "https://vjeafbnkycxfzpxwkifw.supabase.co"

    try:
        response = requests.post(
            f"{SUPABASE_URL}/functions/v1/tool-server-pair",
            json={
                "action": "validate",
                "token": token.upper(),
                "device_name": os.environ.get("COMPUTERNAME", "Desktop"),
                "ngrok_url": NGROK_PUBLIC_URL
            },
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code != 200:
            logger.error(f"❌ Pairing failed: HTTP {response.status_code}")
            try:
                error_data = response.json()
                logger.error(f"   Error: {error_data.get('error', 'Unknown error')}")
            except:
                pass
            return False

        data = response.json()

        if not data.get("success"):
            logger.error(f"❌ Pairing failed: {data.get('error', 'Unknown error')}")
            return False

        # Save config
        config = {
            "user_id": data["user_id"],
            "device_secret": data["device_secret"],
            "supabase_url": data.get("supabase_url", SUPABASE_URL),
            "function_url": data.get("function_url", f"{SUPABASE_URL}/functions/v1/tool-server-pair"),
            "paired_at": datetime.now().isoformat()
        }
        save_pairing_config(config)

        logger.info("✅ Pairing successful!")
        logger.info(f"   User ID: {config['user_id'][:8]}...")
        logger.info(f"   Config saved to: {PAIRING_CONFIG_FILE}")

        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Pairing request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Pairing error: {e}")
        return False

def update_ngrok_url(ngrok_url: str) -> bool:
    """Update ngrok URL on the server"""
    global PAIRING_CONFIG

    if not PAIRING_CONFIG:
        PAIRING_CONFIG = load_pairing_config()

    if not PAIRING_CONFIG:
        logger.warning("⚠️ No pairing config found - skipping URL update")
        return False

    try:
        response = requests.post(
            PAIRING_CONFIG["function_url"],
            json={
                "action": "update_url",
                "user_id": PAIRING_CONFIG["user_id"],
                "device_secret": PAIRING_CONFIG["device_secret"],
                "ngrok_url": ngrok_url
            },
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code == 401:
            logger.error("❌ Pairing revoked or expired. Run with --pair to re-pair.")
            return False

        if response.status_code != 200:
            logger.error(f"❌ Failed to update URL: HTTP {response.status_code}")
            return False

        data = response.json()
        if data.get("success"):
            logger.info(f"✅ ngrok URL synced to web app: {ngrok_url}")
            return True
        else:
            logger.error(f"❌ Failed to update URL: {data.get('error', 'Unknown error')}")
            return False

    except Exception as e:
        logger.error(f"❌ Failed to update URL: {e}")
        return False

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Tool Server - Desktop automation server with web app pairing"
    )
    parser.add_argument(
        "--pair",
        metavar="CODE",
        help="Pair with web app using a 6-character code"
    )
    parser.add_argument(
        "--unpair",
        action="store_true",
        help="Remove pairing configuration"
    )
    parser.add_argument(
        "--no-ngrok",
        action="store_true",
        help="Disable ngrok tunnel"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=SERVICE_PORT,
        help=f"Port to run on (default: {SERVICE_PORT})"
    )
    return parser.parse_args()

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
    click_type: Literal["single", "double", "right", "triple"] = "single"
    session_id: Optional[str] = None
    include_screenshot: bool = False  # v9.0.0: Auto-screenshot after action
    include_snapshot: bool = False  # v10.1.0: Auto-snapshot DOM after action

class TypeRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    text: str
    method: Literal["clipboard", "keystrokes"] = "clipboard"
    session_id: Optional[str] = None
    selector: Optional[str] = None
    include_screenshot: bool = False
    include_snapshot: bool = False  # v10.1.0: Auto-snapshot DOM after action

class ScrollRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = 300
    session_id: Optional[str] = None
    include_screenshot: bool = False
    include_snapshot: bool = False  # v10.1.0: Auto-snapshot DOM after action

class KeypressRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    key: str
    session_id: Optional[str] = None
    include_screenshot: bool = False
    include_snapshot: bool = False  # v10.1.0: Auto-snapshot DOM after action

# v9.0.0: New actions for Claude Computer Use compatibility
class HoldKeyRequest(BaseModel):
    scope: Literal["browser", "desktop"] = "browser"
    key: str
    duration: float = 1.0  # seconds
    session_id: Optional[str] = None
    include_screenshot: bool = False

class WaitRequest(BaseModel):
    duration: float = 1.0  # seconds
    include_screenshot: bool = False
    session_id: Optional[str] = None  # For browser screenshot after wait

# v10.0.0: New Playwright MCP-style models
class ClickByRefRequest(BaseModel):
    """Click element by ref ID from accessibility snapshot"""
    session_id: str
    ref: str  # e.g., "e3", "e15"
    click_type: Literal["single", "double", "right", "triple"] = "single"
    include_screenshot: bool = False
    include_snapshot: bool = False  # v10.1.0: Auto-snapshot DOM after action

class HoverRequest(BaseModel):
    """Hover over element"""
    scope: Literal["browser", "desktop"] = "browser"
    session_id: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    ref: Optional[str] = None  # Alternative: hover by ref
    selector: Optional[str] = None  # Alternative: hover by selector
    include_screenshot: bool = False

class DragRequest(BaseModel):
    """Drag from one position to another"""
    scope: Literal["browser", "desktop"] = "browser"
    session_id: Optional[str] = None
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    coordinate_origin: Literal["viewport", "screen", "lux_sdk", "normalized"] = "viewport"
    include_screenshot: bool = False

class SelectOptionRequest(BaseModel):
    """Select option from dropdown"""
    session_id: str
    selector: Optional[str] = None
    ref: Optional[str] = None
    value: Optional[str] = None  # Select by value
    label: Optional[str] = None  # Select by visible text
    index: Optional[int] = None  # Select by index
    include_screenshot: bool = False

class FileUploadRequest(BaseModel):
    """Upload file to input element"""
    session_id: str
    selector: Optional[str] = None
    ref: Optional[str] = None
    file_path: str  # Local path to file
    include_screenshot: bool = False

class WaitForSelectorRequest(BaseModel):
    """Wait for element to appear/disappear"""
    session_id: str
    selector: str
    state: Literal["attached", "detached", "visible", "hidden"] = "visible"
    timeout: int = 30000  # ms
    include_screenshot: bool = False

class WaitForLoadStateRequest(BaseModel):
    """Wait for page load state"""
    session_id: str
    state: Literal["load", "domcontentloaded", "networkidle"] = "load"
    timeout: int = 30000  # ms
    include_screenshot: bool = False

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
    # v9.0.0: Auto-screenshot after action
    screenshot_base64: Optional[str] = None
    screenshot_width: Optional[int] = None
    screenshot_height: Optional[int] = None
    # v10.1.0: Auto-snapshot DOM after action (for agent awareness)
    snapshot: Optional[str] = None  # Text snapshot like "- button 'Submit' [ref=e3]"
    snapshot_url: Optional[str] = None
    snapshot_title: Optional[str] = None
    snapshot_ref_count: Optional[int] = None

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
    # v10.0.0: Coordinate system info for consistency with vision tools
    coordinate_system: str = "viewport"  # Always viewport (1260×700)
    source: str = "dom_element_rect"
    viewport: Dict[str, int] = {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}

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

# v9.0.0: Auto-screenshot helper
async def take_auto_screenshot(session: Optional['BrowserSession'] = None, scope: str = "browser") -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Take a screenshot and return (base64, width, height)"""
    try:
        if scope == "browser" and session and session.is_alive():
            # Small delay to let UI update
            await asyncio.sleep(0.3)
            data = await session.page.screenshot(type="png")
            vp = await session.page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
            return base64.b64encode(data).decode(), vp['w'], vp['h']
        elif scope == "desktop" and PYAUTOGUI_AVAILABLE:
            await asyncio.sleep(0.3)
            shot = pyautogui.screenshot()
            buf = io.BytesIO()
            shot.save(buf, format='PNG')
            sw, sh = pyautogui.size()
            return base64.b64encode(buf.getvalue()).decode(), sw, sh
    except Exception as e:
        logger.warning(f"⚠️ Auto-screenshot failed: {e}")
    return None, None, None

# v10.1.0: Auto-snapshot helper for DOM structure after actions
async def take_auto_snapshot(session: Optional['BrowserSession'] = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    """
    Take a DOM snapshot and return (text_snapshot, url, title, ref_count).
    Returns the text representation of interactive elements for agent consumption.
    """
    try:
        if session and session.is_alive():
            # Small delay to let UI update after action
            await asyncio.sleep(0.3)
            tree = await session.get_accessibility_tree(include_refs=True)
            if tree and 'text_snapshot' in tree:
                return (
                    tree.get('text_snapshot', ''),
                    tree.get('url', ''),
                    tree.get('title', ''),
                    tree.get('ref_count', 0)
                )
    except Exception as e:
        logger.warning(f"⚠️ Auto-snapshot failed: {e}")
    return None, None, None, None

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
        # v10.0.0: Ref system for element tracking
        self._element_refs: Dict[str, Dict[str, Any]] = {}  # ref -> element info with coordinates
        self._ref_counter = 0

    @property
    def page(self):
        if self.pages and 0 <= self.current_page_index < len(self.pages):
            return self.pages[self.current_page_index]
        return None

    def _generate_ref(self) -> str:
        """Generate unique ref ID like 'e1', 'e2', etc."""
        self._ref_counter += 1
        return f"e{self._ref_counter}"

    def get_element_by_ref(self, ref: str) -> Optional[Dict[str, Any]]:
        """Get element info by ref ID"""
        return self._element_refs.get(ref)

    def clear_refs(self):
        """Clear all refs (call before new snapshot)"""
        self._element_refs = {}
        self._ref_counter = 0
    
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
    
    async def get_accessibility_tree(self, include_refs: bool = True):
        """
        Get DOM tree with ref IDs (Playwright MCP style).
        Each interactive element gets a unique ref like 'e1', 'e2', etc.
        """
        if not self.page:
            return None

        # Clear refs before new snapshot
        if include_refs:
            self.clear_refs()

        try:
            # NOTE: We skip aria_snapshot() because it doesn't generate ref IDs.
            # Our JavaScript fallback generates refs (e1, e2, etc.) needed for click_by_ref.
            # The aria_snapshot is good for accessibility but lacks the ref system we need.

            # Extract interactive elements via JavaScript with ref IDs (Playwright MCP style)
            raw_elements = await self.page.evaluate('''() => {
                // Get active element for [active] attribute
                const activeElement = document.activeElement;

                // Get all interactive elements
                const interactive = document.querySelectorAll(
                    'a, button, input, select, textarea, ' +
                    '[role="button"], [role="link"], [role="textbox"], [role="menuitem"], ' +
                    '[role="tab"], [role="checkbox"], [role="radio"], [role="switch"], ' +
                    '[role="option"], [role="combobox"], [role="listbox"], ' +
                    '[onclick], [tabindex]:not([tabindex="-1"]), ' +
                    'label, img[alt], [aria-label], h1, h2, h3, h4, h5, h6'
                );
                const elements = [];

                interactive.forEach((el, index) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const isVisible = style.display !== 'none' &&
                                     style.visibility !== 'hidden' &&
                                     rect.width > 0 && rect.height > 0;

                    if (isVisible && rect.top < window.innerHeight && rect.bottom > 0) {
                        const tag = el.tagName.toLowerCase();
                        const role = el.getAttribute('role') ||
                                    (tag === 'a' ? 'link' :
                                     tag === 'button' ? 'button' :
                                     tag === 'input' ? (el.type === 'checkbox' ? 'checkbox' :
                                                        el.type === 'radio' ? 'radio' : 'textbox') :
                                     tag === 'select' ? 'combobox' :
                                     tag === 'textarea' ? 'textbox' :
                                     tag.match(/^h[1-6]$/) ? 'heading' : tag);

                        const name = el.getAttribute('aria-label') ||
                                    el.getAttribute('title') ||
                                    el.getAttribute('placeholder') ||
                                    el.getAttribute('alt') ||
                                    (tag === 'input' && el.type === 'submit' ? el.value : null) ||
                                    (tag === 'label' ? el.textContent?.trim().slice(0, 50) : null) ||
                                    (tag === 'button' || tag === 'a' ? el.textContent?.trim().slice(0, 50) : null) ||
                                    (tag.match(/^h[1-6]$/) ? el.textContent?.trim().slice(0, 50) : null);

                        // Semantic attributes (Playwright MCP style)
                        const isActive = el === activeElement;
                        const isDisabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                        const isChecked = el.checked === true || el.getAttribute('aria-checked') === 'true';
                        const isExpanded = el.getAttribute('aria-expanded') === 'true';
                        const isSelected = el.getAttribute('aria-selected') === 'true';
                        const isRequired = el.required || el.getAttribute('aria-required') === 'true';
                        const isReadonly = el.readOnly || el.getAttribute('aria-readonly') === 'true';

                        elements.push({
                            _index: index,
                            tag: tag,
                            role: role,
                            name: name || null,
                            text: el.textContent?.trim().slice(0, 100) || null,
                            x: Math.round(rect.x + rect.width / 2),
                            y: Math.round(rect.y + rect.height / 2),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            top: Math.round(rect.top),
                            left: Math.round(rect.left),
                            id: el.id || null,
                            className: el.className || null,
                            testId: el.getAttribute('data-testid') || null,
                            value: el.value || null,
                            type: el.type || null,
                            href: el.href || null,
                            // Semantic attributes
                            active: isActive,
                            disabled: isDisabled,
                            checked: isChecked,
                            expanded: isExpanded,
                            selected: isSelected,
                            required: isRequired,
                            readonly: isReadonly,
                        });
                    }
                });

                return {
                    url: window.location.href,
                    title: document.title,
                    viewport: { width: window.innerWidth, height: window.innerHeight },
                    elements: elements
                };
            }''')

            # Assign refs to each element and store mapping
            elements_with_refs = []
            for el in raw_elements.get('elements', []):
                ref = self._generate_ref()
                el['ref'] = ref
                # Store in ref map for later lookup
                self._element_refs[ref] = {
                    'x': el['x'],
                    'y': el['y'],
                    'width': el['width'],
                    'height': el['height'],
                    'tag': el['tag'],
                    'role': el['role'],
                    'name': el['name'],
                    'selector': self._build_selector(el),
                }
                elements_with_refs.append(el)

            # Build text representation (like Playwright MCP)
            text_snapshot = self._build_text_snapshot(elements_with_refs)

            return {
                'type': 'interactive_elements_with_refs',
                'url': raw_elements.get('url'),
                'title': raw_elements.get('title'),
                'viewport': raw_elements.get('viewport'),
                'elements': elements_with_refs,
                'text_snapshot': text_snapshot,
                'ref_count': len(elements_with_refs)
            }

        except Exception as e:
            logger.error(f"❌ DOM tree extraction failed: {e}")
            return {"error": str(e)}

    def _build_selector(self, el: Dict) -> str:
        """Build a CSS selector for the element"""
        if el.get('id'):
            return f"#{el['id']}"
        if el.get('testId'):
            return f"[data-testid=\"{el['testId']}\"]"
        if el.get('tag') and el.get('name'):
            # Escape quotes in name
            name = el['name'].replace('"', '\\"')[:30]
            return f"{el['tag']}:has-text(\"{name}\")"
        return f"{el.get('tag', 'div')}"

    def _build_text_snapshot(self, elements: List[Dict]) -> str:
        """
        Build text representation of the page (Playwright MCP style).
        Format: - role "name" [attr1] [attr2] [ref=eN]: value
        """
        lines = []
        for el in elements:
            ref = el.get('ref', '?')
            role = el.get('role', el.get('tag', '?'))
            name = el.get('name') or ''
            if name:
                name = name[:40]

            # Build attributes list (Playwright MCP style)
            attrs = []
            if el.get('active'):
                attrs.append('[active]')
            if el.get('disabled'):
                attrs.append('[disabled]')
            if el.get('checked'):
                attrs.append('[checked]')
            if el.get('expanded'):
                attrs.append('[expanded]')
            if el.get('selected'):
                attrs.append('[selected]')
            if el.get('required'):
                attrs.append('[required]')
            if el.get('readonly'):
                attrs.append('[readonly]')

            # Add ref at the end of attributes
            attrs.append(f'[ref={ref}]')
            attrs_str = ' '.join(attrs)

            # Get value for inputs (shown after colon)
            value = el.get('value', '')
            if value and role in ('textbox', 'combobox', 'checkbox', 'radio'):
                value = str(value)[:30]

            # Format: - role "name" [attr1] [ref=eN]: value
            if name and value:
                lines.append(f'- {role} "{name}" {attrs_str}: {value}')
            elif name:
                lines.append(f'- {role} "{name}" {attrs_str}')
            elif value:
                lines.append(f'- {role} {attrs_str}: {value}')
            else:
                lines.append(f'- {role} {attrs_str}')

        return "\n".join(lines)
    
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

# ──────────────────────────────────────────────────────────────────────────────
# CORS Middleware Custom - FIX per ngrok free tier
# Il problema: ngrok free mostra warning page che intercetta OPTIONS preflight
# Soluzione: gestire CORS headers manualmente per TUTTE le risposte
# ──────────────────────────────────────────────────────────────────────────────

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class CustomCORSMiddleware(BaseHTTPMiddleware):
    """
    Custom CORS middleware che:
    1. Gestisce OPTIONS preflight esplicitamente
    2. Aggiunge CORS headers a TUTTE le risposte
    """

    async def dispatch(self, request, call_next):
        # CORS headers comuni
        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "86400",  # Cache preflight per 24h
        }

        # Se è OPTIONS (preflight), rispondi subito con 200
        if request.method == "OPTIONS":
            return Response(
                status_code=200,
                headers=cors_headers
            )

        # Per altre richieste, procedi e aggiungi headers alla risposta
        response = await call_next(request)

        # Aggiungi CORS headers alla risposta
        for key, value in cors_headers.items():
            response.headers[key] = value

        return response

# Aggiungi il nostro middleware custom PRIMA del CORS standard
app.add_middleware(CustomCORSMiddleware)

# CORS standard come fallback (in caso il nostro middleware abbia problemi)
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
        session = None

        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")

            if req.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_viewport(x, y)

            if req.click_type == "double":
                await session.page.mouse.dblclick(x, y)
            elif req.click_type == "triple":
                await session.page.mouse.click(x, y, click_count=3)
            elif req.click_type == "right":
                await session.page.mouse.click(x, y, button="right")
            else:
                await session.page.mouse.click(x, y)

            logger.info(f"🖱️ Click: ({x}, {y}) [{req.click_type}]")
            response = ActionResponse(success=True, executed_with="playwright", details={"x": x, "y": y, "click_type": req.click_type})

        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            sw, sh = pyautogui.size()
            if req.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_screen(x, y, sw, sh)
            elif req.coordinate_origin == "lux_sdk":
                x, y = CoordinateConverter.lux_sdk_to_screen(x, y, sw, sh)

            if req.click_type == "double":
                pyautogui.doubleClick(x, y)
            elif req.click_type == "triple":
                pyautogui.tripleClick(x, y)
            elif req.click_type == "right":
                pyautogui.rightClick(x, y)
            else:
                pyautogui.click(x, y)

            response = ActionResponse(success=True, executed_with="pyautogui", details={"x": x, "y": y, "click_type": req.click_type})
        else:
            return ActionResponse(success=False, error="Invalid scope or PyAutoGUI not available")

        # v9.0.0: Auto-screenshot after action (optional)
        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, req.scope)
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        # v10.2.0: ALWAYS include snapshot for browser actions (Playwright MCP style)
        if session and session.is_alive():
            snap, snap_url, snap_title, snap_count = await take_auto_snapshot(session)
            response.snapshot = snap
            response.snapshot_url = snap_url
            response.snapshot_title = snap_title
            response.snapshot_ref_count = snap_count

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/type", response_model=ActionResponse)
async def do_type(req: TypeRequest):
    try:
        session = None
        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            if req.selector:
                await session.page.click(req.selector)
            await session.page.keyboard.type(req.text, delay=50)
            logger.info(f"⌨️ Type: '{req.text[:20]}...'")
            response = ActionResponse(success=True, executed_with="playwright")
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            type_via_clipboard(req.text) if req.method == "clipboard" else pyautogui.typewrite(req.text)
            response = ActionResponse(success=True, executed_with="pyautogui")
        else:
            return ActionResponse(success=False, error="Invalid scope")

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, req.scope)
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        # v10.2.0: ALWAYS include snapshot for browser actions (Playwright MCP style)
        if session and session.is_alive():
            snap, snap_url, snap_title, snap_count = await take_auto_snapshot(session)
            response.snapshot = snap
            response.snapshot_url = snap_url
            response.snapshot_title = snap_title
            response.snapshot_ref_count = snap_count

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/scroll", response_model=ActionResponse)
async def do_scroll(req: ScrollRequest):
    try:
        session = None
        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            dx, dy = (0, -req.amount) if req.direction == "up" else (0, req.amount) if req.direction == "down" else (-req.amount, 0) if req.direction == "left" else (req.amount, 0)
            await session.page.mouse.wheel(dx, dy)
            logger.info(f"📜 Scroll: {req.direction}")
            response = ActionResponse(success=True, executed_with="playwright")
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            clicks = req.amount // 100
            pyautogui.scroll(clicks if req.direction == "up" else -clicks)
            response = ActionResponse(success=True, executed_with="pyautogui")
        else:
            return ActionResponse(success=False, error="Invalid scope")

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, req.scope)
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        # v10.2.0: ALWAYS include snapshot for browser actions (Playwright MCP style)
        if session and session.is_alive():
            snap, snap_url, snap_title, snap_count = await take_auto_snapshot(session)
            response.snapshot = snap
            response.snapshot_url = snap_url
            response.snapshot_title = snap_title
            response.snapshot_ref_count = snap_count

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/keypress", response_model=ActionResponse)
async def do_keypress(req: KeypressRequest):
    try:
        session = None
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
            response = ActionResponse(success=True, executed_with="playwright")
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey(*req.key.lower().split("+")) if "+" in req.key else pyautogui.press(req.key.lower())
            response = ActionResponse(success=True, executed_with="pyautogui")
        else:
            return ActionResponse(success=False, error="Invalid scope")

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, req.scope)
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        # v10.2.0: ALWAYS include snapshot for browser actions (Playwright MCP style)
        if session and session.is_alive():
            snap, snap_url, snap_title, snap_count = await take_auto_snapshot(session)
            response.snapshot = snap
            response.snapshot_url = snap_url
            response.snapshot_title = snap_title
            response.snapshot_ref_count = snap_count

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

# v9.0.0: New endpoints for Claude Computer Use compatibility
@app.post("/hold_key", response_model=ActionResponse)
async def do_hold_key(req: HoldKeyRequest):
    """Hold a key down for a specified duration"""
    try:
        session = None
        if req.duration > 100:
            return ActionResponse(success=False, error="Duration too long (max 100s)")

        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            await session.page.keyboard.down(req.key)
            await asyncio.sleep(req.duration)
            await session.page.keyboard.up(req.key)
            logger.info(f"⌨️ Hold key: {req.key} for {req.duration}s")
            response = ActionResponse(success=True, executed_with="playwright", details={"key": req.key, "duration": req.duration})
        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            pyautogui.keyDown(req.key.lower())
            await asyncio.sleep(req.duration)
            pyautogui.keyUp(req.key.lower())
            response = ActionResponse(success=True, executed_with="pyautogui", details={"key": req.key, "duration": req.duration})
        else:
            return ActionResponse(success=False, error="Invalid scope")

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, req.scope)
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/wait", response_model=ActionResponse)
async def do_wait(req: WaitRequest):
    """Wait for a specified duration (useful for letting UI settle)"""
    try:
        if req.duration > 100:
            return ActionResponse(success=False, error="Duration too long (max 100s)")

        logger.info(f"⏳ Wait: {req.duration}s")
        await asyncio.sleep(req.duration)

        response = ActionResponse(success=True, executed_with="asyncio", details={"duration": req.duration})

        if req.include_screenshot:
            session = None
            if req.session_id:
                session = session_manager.get_session(req.session_id)
            elif session_manager.get_active_session():
                session = session_manager.get_active_session()

            scope = "browser" if session and session.is_alive() else "desktop"
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, scope)
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

# ============================================================================
# v10.0.0: Playwright MCP-style endpoints
# ============================================================================

async def _retry_with_backoff(func, max_retries: int = 3, base_delay: float = 0.5):
    """Execute function with exponential backoff retry"""
    last_error = None
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"⚠️ Retry {attempt + 1}/{max_retries} after {delay}s: {e}")
                await asyncio.sleep(delay)
    raise last_error

@app.post("/click_by_ref", response_model=ActionResponse)
async def do_click_by_ref(req: ClickByRefRequest):
    """Click element by ref ID from accessibility snapshot"""
    try:
        session = session_manager.get_session(req.session_id)
        if not session or not session.is_alive():
            return ActionResponse(success=False, error="Session not found")

        element = session.get_element_by_ref(req.ref)
        if not element:
            return ActionResponse(success=False, error=f"Ref '{req.ref}' not found. Call /browser/dom/tree first to get fresh refs.")

        x, y = element['x'], element['y']

        async def click_action():
            if req.click_type == "double":
                await session.page.mouse.dblclick(x, y)
            elif req.click_type == "triple":
                await session.page.mouse.click(x, y, click_count=3)
            elif req.click_type == "right":
                await session.page.mouse.click(x, y, button="right")
            else:
                await session.page.mouse.click(x, y)

        await _retry_with_backoff(click_action)

        logger.info(f"🖱️ Click by ref: {req.ref} → ({x}, {y}) [{req.click_type}]")
        response = ActionResponse(
            success=True,
            executed_with="playwright",
            details={"ref": req.ref, "x": x, "y": y, "click_type": req.click_type, "element": element}
        )

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, "browser")
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        # v10.2.0: ALWAYS include snapshot for browser actions (Playwright MCP style)
        if session and session.is_alive():
            snap, snap_url, snap_title, snap_count = await take_auto_snapshot(session)
            response.snapshot = snap
            response.snapshot_url = snap_url
            response.snapshot_title = snap_title
            response.snapshot_ref_count = snap_count

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/hover", response_model=ActionResponse)
async def do_hover(req: HoverRequest):
    """Hover over element by coordinates, ref, or selector"""
    try:
        session = None
        x, y = req.x, req.y

        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")

            # Resolve coordinates from ref or selector
            if req.ref:
                element = session.get_element_by_ref(req.ref)
                if not element:
                    return ActionResponse(success=False, error=f"Ref '{req.ref}' not found")
                x, y = element['x'], element['y']
            elif req.selector:
                locator = session.page.locator(req.selector)
                bbox = await locator.bounding_box()
                if not bbox:
                    return ActionResponse(success=False, error=f"Selector '{req.selector}' not found")
                x, y = int(bbox['x'] + bbox['width']/2), int(bbox['y'] + bbox['height']/2)
            elif x is None or y is None:
                return ActionResponse(success=False, error="Provide x/y coordinates, ref, or selector")

            await session.page.mouse.move(x, y)
            logger.info(f"🎯 Hover: ({x}, {y})")
            response = ActionResponse(success=True, executed_with="playwright", details={"x": x, "y": y})

        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            if x is None or y is None:
                return ActionResponse(success=False, error="Provide x/y coordinates for desktop")
            pyautogui.moveTo(x, y)
            response = ActionResponse(success=True, executed_with="pyautogui", details={"x": x, "y": y})
        else:
            return ActionResponse(success=False, error="Invalid scope")

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, req.scope)
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/drag", response_model=ActionResponse)
async def do_drag(req: DragRequest):
    """Drag from one position to another"""
    try:
        session = None
        start_x, start_y = req.start_x, req.start_y
        end_x, end_y = req.end_x, req.end_y

        if req.scope == "browser":
            session = session_manager.get_session(req.session_id) if req.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")

            if req.coordinate_origin == "normalized":
                start_x, start_y = CoordinateConverter.normalized_to_viewport(start_x, start_y)
                end_x, end_y = CoordinateConverter.normalized_to_viewport(end_x, end_y)

            # Perform drag
            await session.page.mouse.move(start_x, start_y)
            await session.page.mouse.down()
            await session.page.mouse.move(end_x, end_y, steps=10)  # Smooth drag
            await session.page.mouse.up()

            logger.info(f"🎯 Drag: ({start_x},{start_y}) → ({end_x},{end_y})")
            response = ActionResponse(success=True, executed_with="playwright",
                                      details={"start": {"x": start_x, "y": start_y}, "end": {"x": end_x, "y": end_y}})

        elif req.scope == "desktop" and PYAUTOGUI_AVAILABLE:
            sw, sh = pyautogui.size()
            if req.coordinate_origin == "normalized":
                start_x, start_y = CoordinateConverter.normalized_to_screen(start_x, start_y, sw, sh)
                end_x, end_y = CoordinateConverter.normalized_to_screen(end_x, end_y, sw, sh)
            elif req.coordinate_origin == "lux_sdk":
                start_x, start_y = CoordinateConverter.lux_sdk_to_screen(start_x, start_y, sw, sh)
                end_x, end_y = CoordinateConverter.lux_sdk_to_screen(end_x, end_y, sw, sh)

            pyautogui.moveTo(start_x, start_y)
            pyautogui.drag(end_x - start_x, end_y - start_y, duration=0.5)
            response = ActionResponse(success=True, executed_with="pyautogui",
                                      details={"start": {"x": start_x, "y": start_y}, "end": {"x": end_x, "y": end_y}})
        else:
            return ActionResponse(success=False, error="Invalid scope")

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, req.scope)
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/select_option", response_model=ActionResponse)
async def do_select_option(req: SelectOptionRequest):
    """Select option from dropdown"""
    try:
        session = session_manager.get_session(req.session_id)
        if not session or not session.is_alive():
            return ActionResponse(success=False, error="Session not found")

        # Resolve locator
        locator = None
        if req.ref:
            element = session.get_element_by_ref(req.ref)
            if not element:
                return ActionResponse(success=False, error=f"Ref '{req.ref}' not found")
            locator = session.page.locator(element['selector'])
        elif req.selector:
            locator = session.page.locator(req.selector)
        else:
            return ActionResponse(success=False, error="Provide ref or selector")

        # Select option
        if req.value is not None:
            await locator.select_option(value=req.value)
        elif req.label is not None:
            await locator.select_option(label=req.label)
        elif req.index is not None:
            await locator.select_option(index=req.index)
        else:
            return ActionResponse(success=False, error="Provide value, label, or index")

        logger.info(f"📋 Select option: {req.value or req.label or f'index {req.index}'}")
        response = ActionResponse(success=True, executed_with="playwright",
                                  details={"value": req.value, "label": req.label, "index": req.index})

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, "browser")
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/file_upload", response_model=ActionResponse)
async def do_file_upload(req: FileUploadRequest):
    """Upload file to input element"""
    try:
        session = session_manager.get_session(req.session_id)
        if not session or not session.is_alive():
            return ActionResponse(success=False, error="Session not found")

        # Check file exists
        file_path = Path(req.file_path)
        if not file_path.exists():
            return ActionResponse(success=False, error=f"File not found: {req.file_path}")

        # Resolve locator
        locator = None
        if req.ref:
            element = session.get_element_by_ref(req.ref)
            if not element:
                return ActionResponse(success=False, error=f"Ref '{req.ref}' not found")
            locator = session.page.locator(element['selector'])
        elif req.selector:
            locator = session.page.locator(req.selector)
        else:
            # Try to find file input
            locator = session.page.locator('input[type="file"]').first

        await locator.set_input_files(str(file_path))

        logger.info(f"📁 File upload: {file_path.name}")
        response = ActionResponse(success=True, executed_with="playwright",
                                  details={"file": str(file_path), "name": file_path.name})

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, "browser")
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.post("/wait_for_selector", response_model=ActionResponse)
async def do_wait_for_selector(req: WaitForSelectorRequest):
    """Wait for element to appear/disappear (smart waiting)"""
    try:
        session = session_manager.get_session(req.session_id)
        if not session or not session.is_alive():
            return ActionResponse(success=False, error="Session not found")

        logger.info(f"⏳ Wait for selector: {req.selector} [{req.state}]")
        await session.page.wait_for_selector(req.selector, state=req.state, timeout=req.timeout)

        response = ActionResponse(success=True, executed_with="playwright",
                                  details={"selector": req.selector, "state": req.state})

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, "browser")
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        return response
    except Exception as e:
        # Timeout is expected in some cases
        if "Timeout" in str(e):
            return ActionResponse(success=False, error=f"Timeout waiting for selector: {req.selector}",
                                  details={"selector": req.selector, "state": req.state, "timeout_ms": req.timeout})
        return ActionResponse(success=False, error=str(e))

@app.post("/wait_for_load_state", response_model=ActionResponse)
async def do_wait_for_load_state(req: WaitForLoadStateRequest):
    """Wait for page load state (smart waiting)"""
    try:
        session = session_manager.get_session(req.session_id)
        if not session or not session.is_alive():
            return ActionResponse(success=False, error="Session not found")

        logger.info(f"⏳ Wait for load state: {req.state}")
        await session.page.wait_for_load_state(req.state, timeout=req.timeout)

        response = ActionResponse(success=True, executed_with="playwright",
                                  details={"state": req.state})

        if req.include_screenshot:
            ss_b64, ss_w, ss_h = await take_auto_screenshot(session, "browser")
            response.screenshot_base64 = ss_b64
            response.screenshot_width = ss_w
            response.screenshot_height = ss_h

        return response
    except Exception as e:
        return ActionResponse(success=False, error=str(e))

@app.get("/browser/snapshot")
async def browser_snapshot(session_id: str = Query(...), format: str = Query("text")):
    """
    Get page snapshot in text format (Playwright MCP style).
    Returns a text representation of interactive elements with ref IDs.
    """
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}

    tree = await session.get_accessibility_tree(include_refs=True)

    if not tree:
        return {"success": False, "error": "Failed to get accessibility tree"}

    if format == "text":
        # Return text snapshot with ref IDs for LLM consumption
        return {
            "success": True,
            "url": tree.get('url'),
            "title": tree.get('title'),
            "snapshot": tree.get('text_snapshot', ''),
            "ref_count": tree.get('ref_count', 0)
        }
    else:
        return {"success": True, **tree}

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
    args = parse_args()

    # Handle --unpair
    if args.unpair:
        delete_pairing_config()
        print("✅ Pairing configuration removed")
        sys.exit(0)

    # Start ngrok tunnel (unless disabled)
    ngrok_url = None
    if not args.no_ngrok:
        ngrok_url = start_ngrok_tunnel(args.port)

    # Handle --pair
    if args.pair:
        if not ngrok_url:
            print("❌ Cannot pair without ngrok. Remove --no-ngrok flag.")
            sys.exit(1)

        success = do_pairing(args.pair)
        if not success:
            print("\n❌ Pairing failed. Check the token and try again.")
            sys.exit(1)

        print("\n✅ Pairing successful! Starting server...\n")

    # Load existing pairing config
    load_pairing_config()

    # Update ngrok URL if paired
    if ngrok_url and PAIRING_CONFIG:
        update_ngrok_url(ngrok_url)

    # Determine pairing status for display
    pairing_status = "PAIRED" if PAIRING_CONFIG else "NOT PAIRED"
    pairing_user = PAIRING_CONFIG.get("user_id", "")[:8] + "..." if PAIRING_CONFIG else "N/A"

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║      ARCHITECT'S HAND - TOOL SERVER v{SERVICE_VERSION}                ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  🖐️  MODE: HANDS ONLY                                        ║
║                                                              ║
║  ENDPOINTS:                                                  ║
║  ├── 🏠 LOCAL:  http://127.0.0.1:{args.port}                       ║
║  └── 🔒 PUBLIC: {(ngrok_url or 'NOT AVAILABLE'):<42} ║
║                                                              ║
║  PAIRING: {pairing_status:<10} User: {pairing_user:<24} ║
║                                                              ║
║  VIEWPORT: {VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT} (Lux SDK native)                    ║
║                                                              ║
║  Capabilities:                                               ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Playwright     {'✅' if PYAUTOGUI_AVAILABLE else '❌'} PyAutoGUI                  ║
║    {'✅' if PIL_AVAILABLE else '❌'} PIL            {'✅' if PYNGROK_AVAILABLE else '❌'} ngrok                      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")

    if ngrok_url and not PAIRING_CONFIG:
        print(f"💡 To enable auto-sync, run: python tool_server.py --pair <CODE>")
        print(f"   Get the code from the web app settings.\n")

    if ngrok_url and PAIRING_CONFIG:
        print(f"✅ Auto-sync enabled - ngrok URL will be sent to web app automatically\n")
    elif ngrok_url:
        print(f"📋 Copy this URL for Lovable: {ngrok_url}\n")

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
