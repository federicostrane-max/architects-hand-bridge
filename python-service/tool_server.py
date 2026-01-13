#!/usr/bin/env python3
"""
tool_server.py v8.3.0 - Desktop App "Hands Only" Server
======================================================

Derived from tasker_service_v7.py - REMOVED all "brain" logic.

This server provides ONLY execution capabilities ("hands").
All intelligence (planning, decision-making, self-healing) stays in the Web App.

SCOPES:

1. BROWSER (Playwright + Edge)
   - Screenshot: viewport only (1260x700 - aligned with Lux SDK)
   - Click/Type/Scroll: coordinate-based (relative to viewport)
   - Chrome actions: API-based (navigate, reload, back, forward, tabs)
   - Used by: Lux AND Gemini (same browser instance)

2. DESKTOP (PyAutoGUI)
   - Screenshot: full screen
   - Click/Type/Keypress: screen coordinates (with lux_sdk conversion)
   - Used by: Lux only
   - Can control: Excel, Outlook, any app

COORDINATE SYSTEMS:
- viewport: relative to browser viewport (0,0 = top-left of page content)
- screen: absolute screen coordinates
- lux_sdk: Lux SDK coordinates (1260x700 reference) - NOW SAME AS VIEWPORT!
- normalized: Gemini 2.5 Computer Use coordinates (0-999 range) - requires denormalization

CHANGELOG:
- v8.0.1: Fixed accessibility tree with JavaScript fallback
- v8.1.0: Added /browser/dom/element_rect for Triple Verification (DOM + Lux + Gemini)
- v8.2.0: Added 'normalized' coordinate_origin for Gemini 2.5 Computer Use (0-999 range)
- v8.3.0: VIEWPORT ALIGNED TO LUX SDK (1260x700) - No more resize/conversion for browser scope!
         - Viewport now matches Lux SDK reference exactly
         - Eliminated resize_for_lux() overhead for browser screenshots
         - lux_sdk → viewport conversion is now 1:1 (no scaling)
         - Improved accuracy: no more rounding errors from coordinate conversion
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
from typing import Any, Optional, Literal, List, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ============================================================================
# CONFIGURATION
# ============================================================================

SERVICE_VERSION = "8.3.0"
SERVICE_PORT = 8766  # 8765 is used by tasker_service.py

# Lux SDK reference resolution (model trained on this)
LUX_SDK_WIDTH = 1260
LUX_SDK_HEIGHT = 700

# Lux full screen reference (for desktop scope)
LUX_SCREEN_REF_WIDTH = 1920
LUX_SCREEN_REF_HEIGHT = 1200

# ============================================================================
# v8.3.0 CHANGE: Viewport NOW MATCHES Lux SDK reference!
# ============================================================================
# This eliminates the need for:
# 1. Resizing screenshots before sending to Lux
# 2. Converting coordinates from lux_sdk to viewport
# 3. Potential rounding errors from coordinate scaling
#
# The browser viewport is set to exactly 1260x700, which is the resolution
# Lux was trained on. Screenshots are captured at this resolution and
# coordinates from Lux can be used directly without any conversion.
# ============================================================================
VIEWPORT_WIDTH = LUX_SDK_WIDTH   # 1260 (was 1280)
VIEWPORT_HEIGHT = LUX_SDK_HEIGHT  # 700 (was 720)

# Gemini 2.5 Computer Use normalized coordinate range
# The model outputs coordinates in 0-999 range regardless of image dimensions
NORMALIZED_COORD_MAX = 999

# Browser profile directory (shared between Lux and Gemini)
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

# PyAutoGUI
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
    logger.info("✅ PyAutoGUI available")
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    logger.warning("⚠️ PyAutoGUI not available")

# Pyperclip (for clipboard typing - Italian keyboard support)
try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
    logger.info("✅ Pyperclip available")
except ImportError:
    PYPERCLIP_AVAILABLE = False
    logger.warning("⚠️ Pyperclip not available")

# PIL for image processing
try:
    from PIL import Image
    PIL_AVAILABLE = True
    logger.info("✅ PIL available")
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("⚠️ PIL not available")

# Playwright
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
    optimize_for: Optional[Literal["lux", "gemini", "both"]] = None


class ClickRequest(BaseModel):
    """Request for click action"""
    scope: Literal["browser", "desktop"] = "browser"
    x: int
    y: int
    # v8.2.0: Added 'normalized' for Gemini 2.5 Computer Use
    # v8.3.0: lux_sdk is now 1:1 with viewport (no conversion needed)
    coordinate_origin: Literal["viewport", "screen", "lux_sdk", "normalized"] = "viewport"
    click_type: Literal["single", "double", "right"] = "single"
    session_id: Optional[str] = None


class TypeRequest(BaseModel):
    """Request for type action"""
    scope: Literal["browser", "desktop"] = "browser"
    text: str
    method: Literal["clipboard", "keystrokes"] = "clipboard"
    session_id: Optional[str] = None
    # For browser: optional selector to focus first
    selector: Optional[str] = None


class ScrollRequest(BaseModel):
    """Request for scroll action"""
    scope: Literal["browser", "desktop"] = "browser"
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = 300
    # v8.2.0: Added coordinate_origin for scroll position
    x: Optional[int] = None
    y: Optional[int] = None
    coordinate_origin: Literal["viewport", "screen", "lux_sdk", "normalized"] = "viewport"
    session_id: Optional[str] = None


class KeypressRequest(BaseModel):
    """Request for keypress action"""
    scope: Literal["browser", "desktop"] = "browser"
    key: str  # e.g., "Enter", "Escape", "Ctrl+C", "Alt+Tab"
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


class CoordinateConvertRequest(BaseModel):
    """Request to convert coordinates between spaces"""
    x: int
    y: int
    # v8.2.0: Added 'normalized' option
    from_space: Literal["viewport", "screen", "lux_sdk", "normalized"]
    to_space: Literal["viewport", "screen", "lux_sdk", "normalized"]
    session_id: Optional[str] = None


class CoordinateValidateRequest(BaseModel):
    """Request to validate if coordinates are clickable"""
    scope: Literal["browser", "desktop"] = "browser"
    x: int
    y: int
    # v8.2.0: Added 'normalized' option
    coordinate_origin: Literal["viewport", "screen", "lux_sdk", "normalized"] = "viewport"
    session_id: Optional[str] = None


class ElementRectRequest(BaseModel):
    """
    Request to get element bounding rectangle for Triple Verification.
    
    Used by Orchestrator to get DOM coordinates and compare with Vision coordinates.
    At least one search criteria must be provided.
    """
    session_id: str
    # Multiple ways to find element - at least one required
    selector: Optional[str] = None           # CSS selector: "button.send-btn", "#submit"
    text: Optional[str] = None               # Find by text content: "Send", "Submit"
    text_exact: Optional[bool] = False       # True = exact match, False = contains
    role: Optional[str] = None               # ARIA role: "button", "link", "textbox"
    role_name: Optional[str] = None          # Role + name: role="button" with name "Send"
    test_id: Optional[str] = None            # data-testid attribute
    placeholder: Optional[str] = None        # Input placeholder text
    label: Optional[str] = None              # Label text (for form fields)
    # Options
    index: Optional[int] = 0                 # If multiple matches, which one (0-based)
    must_be_visible: Optional[bool] = True   # Only return if element is visible


# ============================================================================
# PYDANTIC MODELS - Responses
# ============================================================================

class ActionResponse(BaseModel):
    """Generic response for actions"""
    success: bool
    error: Optional[str] = None
    # Additional info depending on action
    executed_with: Optional[str] = None  # "playwright" or "pyautogui"
    details: Optional[Dict[str, Any]] = None


class ScreenshotResponse(BaseModel):
    """Response containing screenshot(s)"""
    success: bool
    error: Optional[str] = None
    # v8.3.0: For browser scope, original IS lux_optimized (same resolution)
    original: Optional[Dict[str, Any]] = None  # {image_base64, width, height}
    lux_optimized: Optional[Dict[str, Any]] = None  # {image_base64, width, height, scale_x, scale_y}


class StatusResponse(BaseModel):
    """Service status response"""
    status: str
    version: str
    browser_sessions: int
    capabilities: Dict[str, bool]


class ElementRectResponse(BaseModel):
    """
    Response with element bounding rectangle.
    
    Returns center coordinates (x, y) ready for clicking,
    plus full bounding box and element metadata.
    """
    success: bool
    error: Optional[str] = None
    # Element state
    found: bool = False
    visible: bool = False
    enabled: bool = False
    # Coordinates (center point - ready for clicking)
    x: Optional[int] = None
    y: Optional[int] = None
    # Full bounding box
    bounding_box: Optional[Dict[str, float]] = None  # {x, y, width, height}
    # Element info
    tag: Optional[str] = None
    text: Optional[str] = None
    element_count: Optional[int] = None  # How many elements matched
    # For debugging
    selector_used: Optional[str] = None


# ============================================================================
# SCREENSHOT UTILITIES
# ============================================================================

def resize_for_lux(image_bytes: bytes, target_width: int = LUX_SDK_WIDTH, 
                   target_height: int = LUX_SDK_HEIGHT) -> Dict[str, Any]:
    """
    Resize image to Lux SDK reference resolution.
    Returns dict with base64 image and scale factors for coordinate conversion.
    
    v8.3.0 NOTE: For browser scope, this is NO LONGER NEEDED since viewport
    is already at 1260x700. This function is still used for DESKTOP scope
    where screen resolution varies.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("PIL not available for image resizing")
    
    img = Image.open(io.BytesIO(image_bytes))
    original_width, original_height = img.size
    
    # Resize to Lux SDK reference
    resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    # Convert to base64
    buffer = io.BytesIO()
    resized.save(buffer, format='PNG')
    buffer.seek(0)
    
    return {
        "image_base64": base64.b64encode(buffer.read()).decode('utf-8'),
        "width": target_width,
        "height": target_height,
        "original_width": original_width,
        "original_height": original_height,
        "scale_x": original_width / target_width,
        "scale_y": original_height / target_height
    }


def screenshot_to_base64(image_bytes: bytes, width: int, height: int) -> Dict[str, Any]:
    """Convert screenshot bytes to base64 with metadata"""
    return {
        "image_base64": base64.b64encode(image_bytes).decode('utf-8'),
        "width": width,
        "height": height
    }


# ============================================================================
# CLIPBOARD TYPING (for non-US keyboards)
# ============================================================================

def type_via_clipboard(text: str):
    """
    Type text using clipboard (Ctrl+V) instead of typewrite().
    Required for non-US keyboards (e.g., Italian) where special 
    characters don't type correctly with pyautogui.typewrite().
    """
    if not PYPERCLIP_AVAILABLE:
        logger.warning("Pyperclip not available, using typewrite")
        pyautogui.typewrite(text, interval=0.05)
        return
    
    try:
        # Save current clipboard
        old_clipboard = ""
        try:
            old_clipboard = pyperclip.paste()
        except:
            pass
        
        # Copy text to clipboard
        pyperclip.copy(text)
        
        # Paste with Ctrl+V
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        
        # Restore clipboard
        try:
            pyperclip.copy(old_clipboard)
        except:
            pass
        
    except Exception as e:
        logger.warning(f"Clipboard typing failed: {e}, using typewrite")
        pyautogui.typewrite(text, interval=0.05)


# ============================================================================
# COORDINATE CONVERTER (v8.3.0 - lux_sdk ↔ viewport is now 1:1 for browser)
# ============================================================================

class CoordinateConverter:
    """
    Converts coordinates between different spaces.
    
    Supported spaces:
    - viewport: Browser viewport coordinates (1260x700 - same as Lux SDK!)
    - screen: Absolute screen coordinates
    - lux_sdk: Lux SDK reference (1260x700) - NOW IDENTICAL TO VIEWPORT
    - normalized: Gemini 2.5 Computer Use (0-999 range)
    
    v8.3.0 CHANGE: Since viewport is now 1260x700 (same as Lux SDK),
    lux_sdk ↔ viewport conversions are 1:1 (no scaling needed).
    """
    
    # ========== LUX SDK Conversions ==========
    
    @staticmethod
    def lux_sdk_to_screen(x: int, y: int, screen_width: int, screen_height: int) -> tuple:
        """Convert Lux SDK coords (1260x700) to screen coords"""
        scale_x = screen_width / LUX_SDK_WIDTH
        scale_y = screen_height / LUX_SDK_HEIGHT
        return int(x * scale_x), int(y * scale_y)
    
    @staticmethod
    def screen_to_lux_sdk(x: int, y: int, screen_width: int, screen_height: int) -> tuple:
        """Convert screen coords to Lux SDK coords"""
        scale_x = LUX_SDK_WIDTH / screen_width
        scale_y = LUX_SDK_HEIGHT / screen_height
        return int(x * scale_x), int(y * scale_y)
    
    @staticmethod
    def lux_sdk_to_viewport(x: int, y: int, viewport_width: int, viewport_height: int) -> tuple:
        """
        Convert Lux SDK coords to viewport coords.
        
        v8.3.0: Since viewport is now 1260x700 (same as Lux SDK),
        this is effectively a 1:1 mapping (no conversion needed).
        We keep the function for API compatibility and for cases
        where viewport might differ (e.g., future changes).
        """
        # If viewport matches Lux SDK (the default now), no conversion needed
        if viewport_width == LUX_SDK_WIDTH and viewport_height == LUX_SDK_HEIGHT:
            return x, y
        
        # Fallback for non-standard viewports
        scale_x = viewport_width / LUX_SDK_WIDTH
        scale_y = viewport_height / LUX_SDK_HEIGHT
        return int(x * scale_x), int(y * scale_y)
    
    @staticmethod
    def viewport_to_lux_sdk(x: int, y: int, viewport_width: int, viewport_height: int) -> tuple:
        """
        Convert viewport coords to Lux SDK coords.
        
        v8.3.0: 1:1 mapping when viewport is 1260x700.
        """
        if viewport_width == LUX_SDK_WIDTH and viewport_height == LUX_SDK_HEIGHT:
            return x, y
        
        scale_x = LUX_SDK_WIDTH / viewport_width
        scale_y = LUX_SDK_HEIGHT / viewport_height
        return int(x * scale_x), int(y * scale_y)
    
    # ========== NORMALIZED Conversions (Gemini 2.5 Computer Use) ==========
    
    @staticmethod
    def normalized_to_viewport(x: int, y: int, viewport_width: int, viewport_height: int) -> tuple:
        """
        Convert Gemini 2.5 normalized coords (0-999) to viewport coords.
        
        Gemini 2.5 Computer Use outputs coordinates in 0-999 range
        regardless of input image dimensions.
        
        Formula: pixel = normalized / 1000 * dimension
        
        Example for 1260x700 viewport (v8.3.0 default):
        - (500, 500) normalized → (630, 350) viewport (center)
        - (0, 0) normalized → (0, 0) viewport (top-left)
        - (999, 999) normalized → (1259, 699) viewport (bottom-right)
        """
        # Use 1000 as divisor (normalized range is 0-999, so 999 maps to ~99.9%)
        pixel_x = int(x / 1000 * viewport_width)
        pixel_y = int(y / 1000 * viewport_height)
        return pixel_x, pixel_y
    
    @staticmethod
    def viewport_to_normalized(x: int, y: int, viewport_width: int, viewport_height: int) -> tuple:
        """
        Convert viewport coords to Gemini 2.5 normalized coords (0-999).
        
        Formula: normalized = pixel / dimension * 1000
        """
        norm_x = int(x / viewport_width * 1000)
        norm_y = int(y / viewport_height * 1000)
        # Clamp to 0-999 range
        norm_x = max(0, min(NORMALIZED_COORD_MAX, norm_x))
        norm_y = max(0, min(NORMALIZED_COORD_MAX, norm_y))
        return norm_x, norm_y
    
    @staticmethod
    def normalized_to_screen(x: int, y: int, screen_width: int, screen_height: int) -> tuple:
        """Convert Gemini 2.5 normalized coords (0-999) to screen coords."""
        pixel_x = int(x / 1000 * screen_width)
        pixel_y = int(y / 1000 * screen_height)
        return pixel_x, pixel_y
    
    @staticmethod
    def screen_to_normalized(x: int, y: int, screen_width: int, screen_height: int) -> tuple:
        """Convert screen coords to Gemini 2.5 normalized coords (0-999)."""
        norm_x = int(x / screen_width * 1000)
        norm_y = int(y / screen_height * 1000)
        norm_x = max(0, min(NORMALIZED_COORD_MAX, norm_x))
        norm_y = max(0, min(NORMALIZED_COORD_MAX, norm_y))
        return norm_x, norm_y
    
    @staticmethod
    def normalized_to_lux_sdk(x: int, y: int) -> tuple:
        """
        Convert Gemini 2.5 normalized coords (0-999) to Lux SDK coords (1260x700).
        
        This is a direct conversion without needing actual dimensions,
        since both are relative coordinate systems.
        """
        lux_x = int(x / 1000 * LUX_SDK_WIDTH)
        lux_y = int(y / 1000 * LUX_SDK_HEIGHT)
        return lux_x, lux_y
    
    @staticmethod
    def lux_sdk_to_normalized(x: int, y: int) -> tuple:
        """Convert Lux SDK coords (1260x700) to Gemini 2.5 normalized coords (0-999)."""
        norm_x = int(x / LUX_SDK_WIDTH * 1000)
        norm_y = int(y / LUX_SDK_HEIGHT * 1000)
        norm_x = max(0, min(NORMALIZED_COORD_MAX, norm_x))
        norm_y = max(0, min(NORMALIZED_COORD_MAX, norm_y))
        return norm_x, norm_y


# ============================================================================
# BROWSER SESSION MANAGER
# ============================================================================

class BrowserSession:
    """Manages a single browser session with Edge"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.pages: List[Page] = []
        self.current_page_index: int = 0
        self.created_at = datetime.now()
    
    @property
    def page(self) -> Optional[Page]:
        """Get current active page"""
        if self.pages and 0 <= self.current_page_index < len(self.pages):
            return self.pages[self.current_page_index]
        return None
    
    async def start(self, start_url: Optional[str] = None, headless: bool = False):
        """
        Start browser with Edge and persistent profile.
        
        v8.3.0: Viewport is now 1260x700 (matching Lux SDK reference).
        This eliminates the need for screenshot resizing and coordinate conversion.
        """
        self.playwright = await async_playwright().start()
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"🌐 Starting Edge browser with viewport {VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT} (Lux SDK native)")
        logger.info(f"📁 Profile: {BROWSER_PROFILE_DIR}")
        
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
        
        # Get or create first page
        if self.context.pages:
            self.pages = list(self.context.pages)
        else:
            page = await self.context.new_page()
            self.pages = [page]
        
        self.current_page_index = 0
        
        if start_url:
            await self.page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(0.5)
        
        logger.info(f"✅ Browser started, session: {self.session_id}")
    
    async def stop(self):
        """Stop browser and cleanup"""
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.context = None
        self.playwright = None
        self.pages = []
        logger.info(f"🛑 Browser stopped, session: {self.session_id}")
    
    def is_alive(self) -> bool:
        """Check if browser is still running"""
        try:
            return self.context is not None and self.page is not None and not self.page.is_closed()
        except:
            return False
    
    async def get_viewport_bounds(self) -> Dict[str, Any]:
        """
        Get exact viewport position on screen using JavaScript.
        Used for coordinate validation.
        
        v8.3.0: viewport_width and viewport_height should be 1260x700.
        """
        if not self.page:
            raise RuntimeError("No active page")
        
        bounds = await self.page.evaluate("""
            () => {
                return {
                    window_x: window.screenX,
                    window_y: window.screenY,
                    inner_offset_x: window.outerWidth - window.innerWidth,
                    inner_offset_y: window.outerHeight - window.innerHeight,
                    viewport_width: window.innerWidth,
                    viewport_height: window.innerHeight
                }
            }
        """)
        
        return {
            "x": bounds['window_x'],
            "y": bounds['window_y'] + bounds['inner_offset_y'],
            "width": bounds['viewport_width'],
            "height": bounds['viewport_height'],
            "chrome_height": bounds['inner_offset_y']
        }
    
    async def capture_screenshot(self) -> bytes:
        """
        Capture viewport screenshot.
        
        v8.3.0: Screenshot is now captured at 1260x700 (Lux SDK native resolution).
        No resizing needed before sending to Lux!
        """
        if not self.page:
            raise RuntimeError("No active page")
        return await self.page.screenshot(type="png")
    
    async def get_accessibility_tree(self) -> str:
        """Get accessibility tree for DOM analysis"""
        if not self.page:
            raise RuntimeError("No active page")
        
        try:
            # Try native accessibility API first
            if hasattr(self.page, 'accessibility'):
                try:
                    snapshot = await self.page.accessibility.snapshot()
                    if snapshot:
                        return self._format_a11y_tree(snapshot)
                except Exception as e:
                    logger.debug(f"Accessibility API failed: {e}, using JavaScript fallback")
            
            # Fallback: use JavaScript to extract DOM structure
            dom_structure = await self.page.evaluate('''() => {
                function extractNode(node, depth = 0) {
                    if (!node || depth > 10) return '';
                    
                    let result = '';
                    const indent = '  '.repeat(depth);
                    
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        const tag = node.tagName.toLowerCase();
                        const role = node.getAttribute('role') || '';
                        const ariaLabel = node.getAttribute('aria-label') || '';
                        const placeholder = node.getAttribute('placeholder') || '';
                        const title = node.getAttribute('title') || '';
                        const type = node.getAttribute('type') || '';
                        const href = node.getAttribute('href') || '';
                        const id = node.id ? '#' + node.id : '';
                        const classes = node.className && typeof node.className === 'string' ? 
                                        '.' + node.className.split(' ')[0] : '';
                        
                        // Get visible text (first 50 chars)
                        let text = '';
                        if (node.childNodes.length > 0) {
                            for (const child of node.childNodes) {
                                if (child.nodeType === Node.TEXT_NODE) {
                                    text += child.textContent.trim() + ' ';
                                }
                            }
                        }
                        text = text.trim().substring(0, 50);
                        
                        // Determine if element is interactive or important
                        const isInteractive = ['a', 'button', 'input', 'select', 'textarea', 'label'].includes(tag) ||
                                             role || 
                                             node.onclick || 
                                             node.getAttribute('tabindex') ||
                                             node.getAttribute('onclick');
                        
                        const isContainer = ['div', 'section', 'article', 'main', 'nav', 'header', 'footer', 'aside'].includes(tag);
                        
                        // Always include interactive elements and shallow containers
                        if (isInteractive || depth < 3 || (isContainer && depth < 4)) {
                            // Build label from available sources
                            let label = ariaLabel || placeholder || title || text;
                            if (label.length > 50) label = label.substring(0, 50) + '...';
                            
                            // Build element description
                            let roleStr = role ? '[' + role + ']' : '<' + tag + '>';
                            let extras = [];
                            if (type) extras.push('type=' + type);
                            if (href) extras.push('href');
                            
                            result += indent + roleStr + id + classes;
                            if (extras.length > 0) result += ' (' + extras.join(', ') + ')';
                            if (label) result += ' "' + label + '"';
                            result += '\\n';
                        }
                        
                        // Recurse into children
                        for (const child of node.children) {
                            result += extractNode(child, depth + 1);
                        }
                    }
                    return result;
                }
                return extractNode(document.body);
            }''')
            
            if dom_structure and dom_structure.strip():
                return dom_structure
            else:
                return "DOM tree empty or not accessible"
            
        except Exception as e:
            return f"Error getting DOM tree: {e}"
    
    def _format_a11y_tree(self, node: dict, indent: int = 0) -> str:
        """Format accessibility tree as readable text"""
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
    
    async def get_element_rect(self, request: ElementRectRequest) -> ElementRectResponse:
        """
        Get bounding rectangle of a DOM element.
        
        Used for Triple Verification: DOM + Lux + Gemini coordinate comparison.
        Returns center coordinates ready for clicking.
        
        v8.3.0: Returned coordinates are in viewport space (1260x700),
        which is now identical to Lux SDK space. No conversion needed!
        """
        if not self.page:
            return ElementRectResponse(success=False, error="No active page")
        
        try:
            locator = None
            selector_description = ""
            
            # Build locator based on provided criteria (in priority order)
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
                if request.text_exact:
                    locator = self.page.get_by_text(request.text, exact=True)
                else:
                    locator = self.page.get_by_text(request.text)
                selector_description = f"text: '{request.text}' (exact={request.text_exact})"
            
            elif request.label:
                locator = self.page.get_by_label(request.label)
                selector_description = f"label: {request.label}"
            
            elif request.placeholder:
                locator = self.page.get_by_placeholder(request.placeholder)
                selector_description = f"placeholder: {request.placeholder}"
            
            else:
                return ElementRectResponse(
                    success=False,
                    error="Must provide at least one: selector, text, role, test_id, label, or placeholder"
                )
            
            # Count matches
            count = await locator.count()
            
            if count == 0:
                return ElementRectResponse(
                    success=True,
                    found=False,
                    element_count=0,
                    selector_used=selector_description,
                    error="Element not found"
                )
            
            # Select specific element if multiple matches
            if count > 1 and request.index is not None:
                if request.index >= count:
                    return ElementRectResponse(
                        success=True,
                        found=True,
                        element_count=count,
                        selector_used=selector_description,
                        error=f"Requested index {request.index} but only {count} elements found"
                    )
                locator = locator.nth(request.index)
            elif count > 1:
                locator = locator.first
            
            # Check visibility
            is_visible = await locator.is_visible()
            
            if request.must_be_visible and not is_visible:
                return ElementRectResponse(
                    success=True,
                    found=True,
                    visible=False,
                    element_count=count,
                    selector_used=selector_description,
                    error="Element found but not visible"
                )
            
            # Check if enabled (for form elements)
            is_enabled = await locator.is_enabled()
            
            # Get bounding box
            bbox = await locator.bounding_box()
            
            if not bbox:
                return ElementRectResponse(
                    success=True,
                    found=True,
                    visible=False,
                    enabled=is_enabled,
                    element_count=count,
                    selector_used=selector_description,
                    error="Element has no bounding box (may be hidden or zero-size)"
                )
            
            # Get element info
            element_info = await locator.evaluate('''(el) => {
                return {
                    tag: el.tagName.toLowerCase(),
                    text: el.innerText ? el.innerText.substring(0, 100) : null
                }
            }''')
            
            # Calculate center point (for clicking)
            # v8.3.0: These are viewport coords = Lux SDK coords (1:1)
            center_x = int(bbox['x'] + bbox['width'] / 2)
            center_y = int(bbox['y'] + bbox['height'] / 2)
            
            return ElementRectResponse(
                success=True,
                found=True,
                visible=is_visible,
                enabled=is_enabled,
                x=center_x,
                y=center_y,
                bounding_box={
                    "x": bbox['x'],
                    "y": bbox['y'],
                    "width": bbox['width'],
                    "height": bbox['height']
                },
                tag=element_info.get('tag'),
                text=element_info.get('text'),
                element_count=count,
                selector_used=selector_description
            )
            
        except Exception as e:
            logger.error(f"Error getting element rect: {e}")
            return ElementRectResponse(success=False, error=str(e))
    
    def get_tabs_info(self) -> List[Dict[str, Any]]:
        """Get info about all tabs"""
        return [
            {
                "id": i,
                "url": page.url if not page.is_closed() else None,
                "title": "",  # Would need async call
                "is_current": i == self.current_page_index
            }
            for i, page in enumerate(self.pages)
        ]


class SessionManager:
    """Manages all browser sessions"""
    
    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
    
    async def create_session(self, start_url: Optional[str] = None, headless: bool = False) -> str:
        """Create new browser session"""
        async with self._lock:
            session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            session = BrowserSession(session_id)
            await session.start(start_url, headless)
            self.sessions[session_id] = session
            return session_id
    
    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    async def close_session(self, session_id: str) -> bool:
        """Close and remove session"""
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session:
                await session.stop()
                return True
            return False
    
    async def close_all(self):
        """Close all sessions"""
        for session_id in list(self.sessions.keys()):
            await self.close_session(session_id)
    
    def get_active_session(self) -> Optional[BrowserSession]:
        """Get the first active session (convenience method)"""
        for session in self.sessions.values():
            if session.is_alive():
                return session
        return None
    
    def count(self) -> int:
        """Count active sessions"""
        return len([s for s in self.sessions.values() if s.is_alive()])


# Global session manager
session_manager = SessionManager()


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Architect's Hand - Tool Server",
    description="Desktop App 'Hands Only' Server - Execution without Intelligence (v8.3.0: Lux-native viewport)",
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
        "viewport": f"{VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT} (Lux SDK native)"
    }


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get service status"""
    return StatusResponse(
        status="running",
        version=SERVICE_VERSION,
        browser_sessions=session_manager.count(),
        capabilities={
            "pyautogui": PYAUTOGUI_AVAILABLE,
            "pyperclip": PYPERCLIP_AVAILABLE,
            "playwright": PLAYWRIGHT_AVAILABLE,
            "pil": PIL_AVAILABLE
        }
    )


@app.get("/screen")
async def get_screen_info():
    """Get screen information"""
    info = {
        "lux_sdk_reference": {"width": LUX_SDK_WIDTH, "height": LUX_SDK_HEIGHT},
        "viewport_reference": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        "viewport_matches_lux": VIEWPORT_WIDTH == LUX_SDK_WIDTH and VIEWPORT_HEIGHT == LUX_SDK_HEIGHT,
        "normalized_range": {"min": 0, "max": NORMALIZED_COORD_MAX}
    }
    
    if PYAUTOGUI_AVAILABLE:
        size = pyautogui.size()
        info["screen"] = {"width": size.width, "height": size.height}
        info["lux_scale"] = {
            "x": size.width / LUX_SDK_WIDTH,
            "y": size.height / LUX_SDK_HEIGHT
        }
        info["normalized_scale"] = {
            "x": size.width / 1000,
            "y": size.height / 1000
        }
    
    return info


# ============================================================================
# ENDPOINTS: Screenshot (v8.3.0 - Simplified for browser scope)
# ============================================================================

@app.post("/screenshot", response_model=ScreenshotResponse)
async def take_screenshot(request: ScreenshotRequest):
    """
    Take screenshot based on scope.
    - browser: viewport only (1260x700 - Lux SDK native, NO RESIZE NEEDED!)
    - desktop: full screen (requires resize for Lux)
    
    v8.3.0 CHANGE: For browser scope, screenshot is already at Lux SDK resolution.
    The lux_optimized field returns the same image with scale factors of 1.0.
    """
    try:
        if request.scope == "browser":
            # Get browser session
            session = None
            if request.session_id:
                session = session_manager.get_session(request.session_id)
            else:
                session = session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return ScreenshotResponse(
                    success=False,
                    error="No active browser session. Start one with POST /browser/start"
                )
            
            # Capture viewport screenshot (already at 1260x700!)
            screenshot_bytes = await session.capture_screenshot()
            viewport = await session.get_viewport_bounds()
            
            result = ScreenshotResponse(success=True)
            
            # Original screenshot (1260x700 - same as Lux SDK!)
            original_data = screenshot_to_base64(
                screenshot_bytes, 
                viewport["width"], 
                viewport["height"]
            )
            
            # For Gemini or general use
            if request.optimize_for in [None, "gemini", "both"]:
                result.original = original_data
            
            # For Lux: NO RESIZE NEEDED! Just add scale factors for API compatibility
            if request.optimize_for in ["lux", "both"]:
                result.lux_optimized = {
                    **original_data,
                    "original_width": viewport["width"],
                    "original_height": viewport["height"],
                    "scale_x": 1.0,  # No scaling needed!
                    "scale_y": 1.0   # Viewport = Lux SDK resolution
                }
                logger.info(f"📸 Browser screenshot {viewport['width']}x{viewport['height']} (Lux-native, no resize)")
            
            return result
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ScreenshotResponse(
                    success=False,
                    error="PyAutoGUI not available for desktop screenshots"
                )
            
            # Capture full screen (varies by user's monitor)
            screenshot = pyautogui.screenshot()
            
            # Convert to bytes
            buffer = io.BytesIO()
            screenshot.save(buffer, format='PNG')
            buffer.seek(0)
            screenshot_bytes = buffer.read()
            
            screen_width, screen_height = pyautogui.size()
            
            result = ScreenshotResponse(success=True)
            
            # Original (full screen resolution)
            if request.optimize_for in [None, "gemini", "both"]:
                result.original = screenshot_to_base64(
                    screenshot_bytes,
                    screen_width,
                    screen_height
                )
            
            # Lux optimized: RESIZE STILL NEEDED for desktop (screen varies)
            if request.optimize_for in ["lux", "both"]:
                result.lux_optimized = resize_for_lux(screenshot_bytes)
                logger.info(f"📸 Desktop screenshot {screen_width}x{screen_height} → resized to {LUX_SDK_WIDTH}x{LUX_SDK_HEIGHT}")
            
            return result
        
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        return ScreenshotResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Click (v8.3.0 - lux_sdk is now 1:1 with viewport)
# ============================================================================

@app.post("/click", response_model=ActionResponse)
async def do_click(request: ClickRequest):
    """
    Perform click action.
    - browser scope: uses Playwright (coordinates relative to viewport)
    - desktop scope: uses PyAutoGUI (screen coordinates)
    
    Supports coordinate_origin:
    - viewport: Browser viewport coordinates (1260x700)
    - screen: Absolute screen coordinates
    - lux_sdk: Lux SDK coordinates (1260x700) - NOW SAME AS VIEWPORT!
    - normalized: Gemini 2.5 Computer Use (0-999 range)
    
    v8.3.0: For browser scope, lux_sdk coordinates are used directly
    without conversion (viewport = Lux SDK resolution).
    """
    try:
        x, y = request.x, request.y
        original_x, original_y = x, y
        conversion_applied = "none"
        
        if request.scope == "browser":
            # Get browser session
            session = None
            if request.session_id:
                session = session_manager.get_session(request.session_id)
            else:
                session = session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return ActionResponse(
                    success=False,
                    error="No active browser session"
                )
            
            viewport = await session.get_viewport_bounds()
            
            # Convert coordinates if needed
            if request.coordinate_origin == "lux_sdk":
                # v8.3.0: Check if viewport matches Lux SDK (should be true now)
                if viewport["width"] == LUX_SDK_WIDTH and viewport["height"] == LUX_SDK_HEIGHT:
                    # NO CONVERSION NEEDED! Direct 1:1 mapping
                    conversion_applied = "none (viewport = Lux SDK)"
                    logger.info(f"🎯 Lux SDK ({x}, {y}) → Viewport ({x}, {y}) [1:1, no conversion]")
                else:
                    # Fallback if viewport is different (shouldn't happen in v8.3.0)
                    x, y = CoordinateConverter.lux_sdk_to_viewport(
                        x, y, viewport["width"], viewport["height"]
                    )
                    conversion_applied = f"lux_sdk→viewport (scale: {viewport['width']/LUX_SDK_WIDTH:.3f}, {viewport['height']/LUX_SDK_HEIGHT:.3f})"
                    logger.warning(f"⚠️ Viewport mismatch! Lux SDK ({original_x}, {original_y}) → Viewport ({x}, {y})")
            
            elif request.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_viewport(
                    x, y, viewport["width"], viewport["height"]
                )
                conversion_applied = "normalized→viewport"
                logger.info(f"🔄 Normalized ({original_x}, {original_y}) → Viewport ({x}, {y})")
            
            # viewport and screen coordinates pass through directly for browser scope
            
            # Validate coordinates are within viewport
            if not (0 <= x <= viewport["width"] and 0 <= y <= viewport["height"]):
                return ActionResponse(
                    success=False,
                    error=f"Coordinates ({x}, {y}) outside viewport bounds ({viewport['width']}x{viewport['height']})",
                    details={
                        "viewport": viewport, 
                        "requested": {"x": original_x, "y": original_y},
                        "converted": {"x": x, "y": y},
                        "coordinate_origin": request.coordinate_origin,
                        "conversion_applied": conversion_applied
                    }
                )
            
            # Execute click with Playwright
            if request.click_type == "single":
                await session.page.mouse.click(x, y)
            elif request.click_type == "double":
                await session.page.mouse.dblclick(x, y)
            elif request.click_type == "right":
                await session.page.mouse.click(x, y, button="right")
            
            return ActionResponse(
                success=True,
                executed_with="playwright",
                details={
                    "scope": "browser",
                    "click_type": request.click_type,
                    "viewport_coords": {"x": x, "y": y},
                    "original_coords": {"x": original_x, "y": original_y},
                    "coordinate_origin": request.coordinate_origin,
                    "conversion_applied": conversion_applied,
                    "viewport_size": {"width": viewport["width"], "height": viewport["height"]}
                }
            )
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(
                    success=False,
                    error="PyAutoGUI not available"
                )
            
            screen_width, screen_height = pyautogui.size()
            
            # Convert coordinates if needed (desktop ALWAYS needs conversion for lux_sdk)
            if request.coordinate_origin == "lux_sdk":
                x, y = CoordinateConverter.lux_sdk_to_screen(
                    x, y, screen_width, screen_height
                )
                conversion_applied = f"lux_sdk→screen (scale: {screen_width/LUX_SDK_WIDTH:.3f}, {screen_height/LUX_SDK_HEIGHT:.3f})"
                logger.info(f"🔄 Lux SDK ({original_x}, {original_y}) → Screen ({x}, {y})")
            
            elif request.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_screen(
                    x, y, screen_width, screen_height
                )
                conversion_applied = "normalized→screen"
                logger.info(f"🔄 Normalized ({original_x}, {original_y}) → Screen ({x}, {y})")
            
            # Execute click with PyAutoGUI
            if request.click_type == "single":
                pyautogui.click(x, y)
            elif request.click_type == "double":
                pyautogui.doubleClick(x, y)
            elif request.click_type == "right":
                pyautogui.rightClick(x, y)
            
            return ActionResponse(
                success=True,
                executed_with="pyautogui",
                details={
                    "scope": "desktop",
                    "click_type": request.click_type,
                    "screen_coords": {"x": x, "y": y},
                    "original_coords": {"x": original_x, "y": original_y},
                    "coordinate_origin": request.coordinate_origin,
                    "conversion_applied": conversion_applied
                }
            )
    
    except Exception as e:
        logger.error(f"Click error: {e}")
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Type
# ============================================================================

@app.post("/type", response_model=ActionResponse)
async def do_type(request: TypeRequest):
    """
    Type text.
    - browser scope: uses Playwright keyboard
    - desktop scope: uses PyAutoGUI with clipboard support
    """
    try:
        if request.scope == "browser":
            session = None
            if request.session_id:
                session = session_manager.get_session(request.session_id)
            else:
                session = session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return ActionResponse(
                    success=False,
                    error="No active browser session"
                )
            
            # Focus on selector if provided
            if request.selector:
                await session.page.click(request.selector)
                await asyncio.sleep(0.1)
            
            # Type text
            await session.page.keyboard.type(request.text, delay=50)
            
            return ActionResponse(
                success=True,
                executed_with="playwright",
                details={"text_length": len(request.text), "selector": request.selector}
            )
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(
                    success=False,
                    error="PyAutoGUI not available"
                )
            
            if request.method == "clipboard":
                type_via_clipboard(request.text)
            else:
                pyautogui.typewrite(request.text, interval=0.05)
            
            return ActionResponse(
                success=True,
                executed_with="pyautogui",
                details={"text_length": len(request.text), "method": request.method}
            )
    
    except Exception as e:
        logger.error(f"Type error: {e}")
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Scroll
# ============================================================================

@app.post("/scroll", response_model=ActionResponse)
async def do_scroll(request: ScrollRequest):
    """Scroll in the specified direction"""
    try:
        if request.scope == "browser":
            session = None
            if request.session_id:
                session = session_manager.get_session(request.session_id)
            else:
                session = session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return ActionResponse(
                    success=False,
                    error="No active browser session"
                )
            
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
            
            return ActionResponse(
                success=True,
                executed_with="playwright",
                details={"direction": request.direction, "amount": request.amount}
            )
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(
                    success=False,
                    error="PyAutoGUI not available"
                )
            
            clicks = request.amount // 100  # Convert pixels to scroll clicks
            if request.direction == "up":
                pyautogui.scroll(clicks)
            elif request.direction == "down":
                pyautogui.scroll(-clicks)
            # Left/right scroll not well supported by pyautogui
            
            return ActionResponse(
                success=True,
                executed_with="pyautogui",
                details={"direction": request.direction, "clicks": clicks}
            )
    
    except Exception as e:
        logger.error(f"Scroll error: {e}")
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Keypress
# ============================================================================

@app.post("/keypress", response_model=ActionResponse)
async def do_keypress(request: KeypressRequest):
    """Press a key or key combination"""
    try:
        if request.scope == "browser":
            session = None
            if request.session_id:
                session = session_manager.get_session(request.session_id)
            else:
                session = session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return ActionResponse(
                    success=False,
                    error="No active browser session"
                )
            
            # Handle key combinations (e.g., "Ctrl+C")
            if "+" in request.key:
                keys = request.key.split("+")
                for key in keys[:-1]:
                    await session.page.keyboard.down(key)
                await session.page.keyboard.press(keys[-1])
                for key in reversed(keys[:-1]):
                    await session.page.keyboard.up(key)
            else:
                await session.page.keyboard.press(request.key)
            
            return ActionResponse(
                success=True,
                executed_with="playwright",
                details={"key": request.key}
            )
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(
                    success=False,
                    error="PyAutoGUI not available"
                )
            
            # Handle key combinations
            if "+" in request.key:
                keys = request.key.lower().split("+")
                pyautogui.hotkey(*keys)
            else:
                pyautogui.press(request.key.lower())
            
            return ActionResponse(
                success=True,
                executed_with="pyautogui",
                details={"key": request.key}
            )
    
    except Exception as e:
        logger.error(f"Keypress error: {e}")
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Browser Session Management
# ============================================================================

@app.post("/browser/start")
async def browser_start(request: BrowserStartRequest):
    """Start a new browser session with Lux-native viewport (1260x700)"""
    if not PLAYWRIGHT_AVAILABLE:
        raise HTTPException(status_code=500, detail="Playwright not available")
    
    try:
        session_id = await session_manager.create_session(
            start_url=request.start_url,
            headless=request.headless
        )
        
        session = session_manager.get_session(session_id)
        current_url = session.page.url if session and session.page else None
        
        return {
            "success": True,
            "session_id": session_id,
            "current_url": current_url,
            "viewport": {
                "width": VIEWPORT_WIDTH,
                "height": VIEWPORT_HEIGHT,
                "matches_lux_sdk": True
            }
        }
    except Exception as e:
        logger.error(f"Browser start error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/browser/stop")
async def browser_stop(session_id: str = Query(...)):
    """Stop a browser session"""
    success = await session_manager.close_session(session_id)
    return {"success": success, "session_id": session_id}


@app.get("/browser/status")
async def browser_status(session_id: Optional[str] = None):
    """Get browser session status"""
    if session_id:
        session = session_manager.get_session(session_id)
        if session:
            viewport = None
            try:
                if session.is_alive():
                    viewport = await session.get_viewport_bounds()
            except:
                pass
            
            return {
                "session_id": session_id,
                "is_alive": session.is_alive(),
                "current_url": session.page.url if session.page else None,
                "tabs_count": len(session.pages),
                "viewport": viewport
            }
        return {"error": "Session not found"}
    
    # Return all sessions
    return {
        "sessions": [
            {
                "session_id": sid,
                "is_alive": s.is_alive(),
                "current_url": s.page.url if s.page else None
            }
            for sid, s in session_manager.sessions.items()
        ]
    }


# ============================================================================
# ENDPOINTS: Browser Navigation (API-based, no coordinates)
# ============================================================================

@app.post("/browser/navigate")
async def browser_navigate(request: NavigateRequest):
    """Navigate to URL using Playwright API"""
    session = session_manager.get_session(request.session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found or not alive"}
    
    try:
        await session.page.goto(request.url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(0.5)
        return {"success": True, "url": session.page.url}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/reload")
async def browser_reload(session_id: str = Query(...)):
    """Reload current page"""
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        await session.page.reload(wait_until="domcontentloaded", timeout=30000)
        return {"success": True, "url": session.page.url}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/back")
async def browser_back(session_id: str = Query(...)):
    """Go back in history"""
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        await session.page.go_back(wait_until="domcontentloaded", timeout=30000)
        return {"success": True, "url": session.page.url}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/forward")
async def browser_forward(session_id: str = Query(...)):
    """Go forward in history"""
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        await session.page.go_forward(wait_until="domcontentloaded", timeout=30000)
        return {"success": True, "url": session.page.url}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# ENDPOINTS: Browser Tabs
# ============================================================================

@app.get("/browser/tabs")
async def browser_tabs(session_id: str = Query(...)):
    """List all tabs"""
    session = session_manager.get_session(session_id)
    if not session:
        return {"success": False, "error": "Session not found"}
    
    return {"success": True, "tabs": session.get_tabs_info()}


@app.post("/browser/tab/new")
async def browser_tab_new(request: TabRequest):
    """Open new tab"""
    session = session_manager.get_session(request.session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        new_page = await session.context.new_page()
        session.pages.append(new_page)
        session.current_page_index = len(session.pages) - 1
        
        if request.url:
            await new_page.goto(request.url, wait_until="domcontentloaded", timeout=30000)
        
        return {
            "success": True,
            "tab_id": session.current_page_index,
            "url": new_page.url
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/tab/close")
async def browser_tab_close(request: TabRequest):
    """Close a tab"""
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
            return {"success": True, "remaining_tabs": len(session.pages)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    return {"success": False, "error": "Tab not found"}


@app.post("/browser/tab/switch")
async def browser_tab_switch(request: TabRequest):
    """Switch to a different tab"""
    session = session_manager.get_session(request.session_id)
    if not session:
        return {"success": False, "error": "Session not found"}
    
    if request.tab_id is not None and 0 <= request.tab_id < len(session.pages):
        session.current_page_index = request.tab_id
        await session.pages[request.tab_id].bring_to_front()
        return {
            "success": True,
            "tab_id": request.tab_id,
            "url": session.page.url
        }
    
    return {"success": False, "error": "Tab not found"}


# ============================================================================
# ENDPOINTS: Browser DOM
# ============================================================================

@app.get("/browser/dom/tree")
async def browser_dom_tree(session_id: str = Query(...)):
    """Get accessibility tree"""
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        tree = await session.get_accessibility_tree()
        return {"success": True, "tree": tree}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/dom/element_rect", response_model=ElementRectResponse)
async def browser_element_rect(request: ElementRectRequest):
    """
    Get bounding rectangle of a DOM element.
    
    ┌─────────────────────────────────────────────────────────────────┐
    │  TRIPLE VERIFICATION SUPPORT                                    │
    │                                                                 │
    │  v8.3.0: Coordinates are in viewport space (1260x700)          │
    │  which is NOW IDENTICAL to Lux SDK space!                       │
    │                                                                 │
    │  This endpoint provides DOM coordinates for comparison with:   │
    │  1. Lux Vision coordinates (lux_sdk = viewport: 1260x700)      │
    │  2. Gemini Vision coordinates (normalized: 0-999)              │
    │                                                                 │
    │  If all 3 agree (< 50px distance), proceed with high confidence│
    │  If mismatch > 150px, something is wrong (overlay, hidden, etc)│
    └─────────────────────────────────────────────────────────────────┘
    
    Multiple ways to find element:
    - selector: CSS selector (e.g., "button.send-btn", "#submit")
    - text: Find by text content (exact or contains)
    - role: ARIA role (e.g., "button", "link")
    - role + role_name: Role with accessible name
    - test_id: data-testid attribute
    - label: Label text (for form fields)
    - placeholder: Input placeholder
    
    Returns center coordinates (x, y) ready for clicking.
    """
    session = session_manager.get_session(request.session_id)
    if not session or not session.is_alive():
        return ElementRectResponse(success=False, error="Session not found")
    
    return await session.get_element_rect(request)


@app.get("/browser/current_url")
async def browser_current_url(session_id: str = Query(...)):
    """Get current page URL"""
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    return {"success": True, "url": session.page.url}


# ============================================================================
# ENDPOINTS: Coordinate Utilities (v8.3.0 - Updated for Lux-native viewport)
# ============================================================================

@app.post("/coordinates/convert")
async def coordinates_convert(request: CoordinateConvertRequest):
    """
    Convert coordinates between different spaces.
    
    Supported spaces:
    - viewport: Browser viewport (1260x700 - same as Lux SDK!)
    - screen: Absolute screen coordinates
    - lux_sdk: Lux SDK reference (1260x700) - NOW SAME AS VIEWPORT
    - normalized: Gemini 2.5 Computer Use (0-999 range)
    
    v8.3.0: viewport ↔ lux_sdk conversions are now 1:1 (no scaling).
    """
    try:
        x, y = request.x, request.y
        
        # Get reference dimensions
        if request.session_id:
            session = session_manager.get_session(request.session_id)
            if session and session.is_alive():
                viewport = await session.get_viewport_bounds()
                ref_width = viewport["width"]
                ref_height = viewport["height"]
            else:
                ref_width, ref_height = VIEWPORT_WIDTH, VIEWPORT_HEIGHT
        else:
            if PYAUTOGUI_AVAILABLE:
                ref_width, ref_height = pyautogui.size()
            else:
                ref_width, ref_height = 1920, 1080
        
        # Perform conversion
        result_x, result_y = x, y
        conversion_note = ""
        
        # ===== FROM lux_sdk =====
        if request.from_space == "lux_sdk":
            if request.to_space == "viewport":
                result_x, result_y = CoordinateConverter.lux_sdk_to_viewport(x, y, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
                if VIEWPORT_WIDTH == LUX_SDK_WIDTH and VIEWPORT_HEIGHT == LUX_SDK_HEIGHT:
                    conversion_note = "1:1 mapping (viewport = Lux SDK)"
            elif request.to_space == "screen":
                result_x, result_y = CoordinateConverter.lux_sdk_to_screen(x, y, ref_width, ref_height)
            elif request.to_space == "normalized":
                result_x, result_y = CoordinateConverter.lux_sdk_to_normalized(x, y)
        
        # ===== FROM viewport =====
        elif request.from_space == "viewport":
            if request.to_space == "lux_sdk":
                result_x, result_y = CoordinateConverter.viewport_to_lux_sdk(x, y, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
                if VIEWPORT_WIDTH == LUX_SDK_WIDTH and VIEWPORT_HEIGHT == LUX_SDK_HEIGHT:
                    conversion_note = "1:1 mapping (viewport = Lux SDK)"
            elif request.to_space == "normalized":
                result_x, result_y = CoordinateConverter.viewport_to_normalized(x, y, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
            elif request.to_space == "screen":
                # For this conversion, need to know browser window position
                conversion_note = "viewport→screen requires browser window position"
        
        # ===== FROM screen =====
        elif request.from_space == "screen":
            if request.to_space == "lux_sdk":
                result_x, result_y = CoordinateConverter.screen_to_lux_sdk(x, y, ref_width, ref_height)
            elif request.to_space == "normalized":
                result_x, result_y = CoordinateConverter.screen_to_normalized(x, y, ref_width, ref_height)
            elif request.to_space == "viewport":
                conversion_note = "screen→viewport requires browser window position"
        
        # ===== FROM normalized =====
        elif request.from_space == "normalized":
            if request.to_space == "viewport":
                result_x, result_y = CoordinateConverter.normalized_to_viewport(x, y, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
            elif request.to_space == "screen":
                result_x, result_y = CoordinateConverter.normalized_to_screen(x, y, ref_width, ref_height)
            elif request.to_space == "lux_sdk":
                result_x, result_y = CoordinateConverter.normalized_to_lux_sdk(x, y)
        
        response = {
            "success": True,
            "x": result_x,
            "y": result_y,
            "from_space": request.from_space,
            "to_space": request.to_space,
            "original": {"x": x, "y": y},
            "reference_dimensions": {"width": ref_width, "height": ref_height},
            "viewport_dimensions": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            "viewport_matches_lux": VIEWPORT_WIDTH == LUX_SDK_WIDTH and VIEWPORT_HEIGHT == LUX_SDK_HEIGHT
        }
        
        if conversion_note:
            response["note"] = conversion_note
        
        return response
    
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/coordinates/validate")
async def coordinates_validate(request: CoordinateValidateRequest):
    """Validate if coordinates point to a clickable area"""
    try:
        x, y = request.x, request.y
        original_x, original_y = x, y
        conversion_applied = "none"
        
        if request.scope == "browser":
            session = None
            if request.session_id:
                session = session_manager.get_session(request.session_id)
            else:
                session = session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return {"success": False, "error": "No active browser session"}
            
            viewport = await session.get_viewport_bounds()
            
            # Convert coordinates if needed
            if request.coordinate_origin == "lux_sdk":
                if viewport["width"] == LUX_SDK_WIDTH and viewport["height"] == LUX_SDK_HEIGHT:
                    conversion_applied = "none (1:1 mapping)"
                else:
                    x, y = CoordinateConverter.lux_sdk_to_viewport(
                        x, y, viewport["width"], viewport["height"]
                    )
                    conversion_applied = "lux_sdk→viewport"
            elif request.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_viewport(
                    x, y, viewport["width"], viewport["height"]
                )
                conversion_applied = "normalized→viewport"
            
            # Check if within viewport
            in_viewport = (0 <= x <= viewport["width"] and 0 <= y <= viewport["height"])
            
            # Get element at coordinates
            element_info = None
            if in_viewport:
                try:
                    element_info = await session.page.evaluate('''(coords) => {
                        const el = document.elementFromPoint(coords.x, coords.y);
                        if (el) {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return {
                                found: true,
                                tag: el.tagName.toLowerCase(),
                                id: el.id || null,
                                className: el.className || null,
                                text: el.innerText ? el.innerText.substring(0, 50) : null,
                                clickable: style.pointerEvents !== 'none' && style.visibility !== 'hidden',
                                rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
                            };
                        }
                        return { found: false };
                    }''', {"x": x, "y": y})
                except:
                    pass
            
            return {
                "success": True,
                "valid": in_viewport,
                "in_viewport": in_viewport,
                "viewport_coords": {"x": x, "y": y},
                "original_coords": {"x": original_x, "y": original_y},
                "coordinate_origin": request.coordinate_origin,
                "conversion_applied": conversion_applied,
                "element_info": element_info,
                "viewport_bounds": viewport,
                "viewport_matches_lux": viewport["width"] == LUX_SDK_WIDTH and viewport["height"] == LUX_SDK_HEIGHT
            }
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return {"success": False, "error": "PyAutoGUI not available"}
            
            screen_width, screen_height = pyautogui.size()
            
            # Convert if needed
            if request.coordinate_origin == "lux_sdk":
                x, y = CoordinateConverter.lux_sdk_to_screen(x, y, screen_width, screen_height)
                conversion_applied = "lux_sdk→screen"
            elif request.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_screen(x, y, screen_width, screen_height)
                conversion_applied = "normalized→screen"
            
            in_screen = (0 <= x <= screen_width and 0 <= y <= screen_height)
            
            # Get pixel color at coordinates
            pixel_color = None
            if in_screen:
                try:
                    screenshot = pyautogui.screenshot(region=(x, y, 1, 1))
                    pixel_color = screenshot.getpixel((0, 0))
                except:
                    pass
            
            return {
                "success": True,
                "valid": in_screen,
                "in_screen": in_screen,
                "screen_coords": {"x": x, "y": y},
                "original_coords": {"x": original_x, "y": original_y},
                "coordinate_origin": request.coordinate_origin,
                "conversion_applied": conversion_applied,
                "pixel_color": pixel_color,
                "screen_bounds": {"width": screen_width, "height": screen_height}
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
║  "Hands Only" - Pure Execution, No Intelligence              ║
║                                                              ║
║  🎯 v8.3.0: VIEWPORT = LUX SDK (1260x700)                    ║
║     • No screenshot resize for browser scope                 ║
║     • No coordinate conversion for lux_sdk → viewport        ║
║     • Direct 1:1 mapping = maximum accuracy!                 ║
║                                                              ║
║  COORDINATE SYSTEMS SUPPORTED:                               ║
║    • viewport   - Browser viewport (1260x700 = Lux SDK!)     ║
║    • screen     - Absolute screen coordinates                ║
║    • lux_sdk    - Lux SDK reference (1260x700 = viewport!)   ║
║    • normalized - Gemini 2.5 Computer Use (0-999)            ║
║                                                              ║
║  BROWSER SCOPE (Playwright + Edge):                         ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Screenshot (1260x700 - Lux native!)               ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Click/Type/Scroll (all coordinate systems)        ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Navigate/Reload/Back/Forward (API)                ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Tab management (API)                              ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} DOM tree (Accessibility + JS fallback)            ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Element rect (Triple Verification support)        ║
║                                                              ║
║  DESKTOP SCOPE (PyAutoGUI):                                  ║
║    {'✅' if PYAUTOGUI_AVAILABLE else '❌'} Screenshot (full screen + resize for Lux)          ║
║    {'✅' if PYAUTOGUI_AVAILABLE else '❌'} Click/Type/Keypress (all coordinate systems)       ║
║    {'✅' if PYPERCLIP_AVAILABLE else '❌'} Clipboard typing (Italian keyboard support)        ║
║                                                              ║
║  Endpoint: http://127.0.0.1:{SERVICE_PORT}                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT, log_level="info")
