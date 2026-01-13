#!/usr/bin/env python3
"""
tool_server.py v8.4.0 - Desktop App "Hands Only" Server
======================================================

TRIPLE VERIFICATION ARCHITECTURE
================================
This version adds comprehensive support for comparing coordinates from:
1. DOM (Playwright element rect)
2. Lux Vision (OpenAGI Lux SDK)
3. Gemini Vision (Google Gemini 2.5 Computer Use)

VIEWPORT STRATEGY:
- Single viewport: 1260×700 (Lux SDK native)
- Lux: 1:1 mapping, no conversion needed
- Gemini: normalized coords (0-999) denormalized to viewport
- DOM: native viewport coords

This compromise prioritizes Lux accuracy while Gemini's normalized
coordinate system adapts to any resolution.

CHANGELOG:
- v8.0.1: Fixed accessibility tree with JavaScript fallback
- v8.1.0: Added /browser/dom/element_rect for Triple Verification
- v8.2.0: Added 'normalized' coordinate_origin for Gemini 2.5
- v8.3.0: Viewport aligned to Lux SDK (1260×700)
- v8.4.0: TRIPLE VERIFICATION SUPPORT
         - Added /coordinates/triple_verify endpoint
         - Added /screenshot with multi-model optimization
         - Added confidence scoring and distance matrix
         - Added Gemini-specific screenshot resize option
"""

import asyncio
import base64
import io
import json
import logging
import math
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

SERVICE_VERSION = "8.4.0"
SERVICE_PORT = 8766

# ============================================================================
# MODEL REFERENCE RESOLUTIONS
# ============================================================================

# Lux SDK reference (model trained on this)
LUX_SDK_WIDTH = 1260
LUX_SDK_HEIGHT = 700

# Gemini 2.5 Computer Use recommended resolution
GEMINI_RECOMMENDED_WIDTH = 1440
GEMINI_RECOMMENDED_HEIGHT = 900

# Lux full screen reference (for desktop scope)
LUX_SCREEN_REF_WIDTH = 1920
LUX_SCREEN_REF_HEIGHT = 1200

# ============================================================================
# VIEWPORT CONFIGURATION (Lux-native for Triple Verification)
# ============================================================================
# We use Lux SDK resolution as the common coordinate space because:
# 1. Lux requires exact 1260×700 for optimal accuracy
# 2. Gemini's normalized coords (0-999) adapt to any resolution
# 3. DOM coords are always in viewport space
# ============================================================================
VIEWPORT_WIDTH = LUX_SDK_WIDTH   # 1260
VIEWPORT_HEIGHT = LUX_SDK_HEIGHT  # 700

# Gemini normalized coordinate range (0-999)
NORMALIZED_COORD_MAX = 999

# Triple Verification thresholds
TRIPLE_VERIFY_MATCH_THRESHOLD = 50      # pixels - coords within this = MATCH
TRIPLE_VERIFY_WARNING_THRESHOLD = 100   # pixels - coords within this = WARNING
TRIPLE_VERIFY_MISMATCH_THRESHOLD = 150  # pixels - coords beyond this = MISMATCH

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
    """Request for screenshot with multi-model support"""
    scope: Literal["browser", "desktop"] = "browser"
    session_id: Optional[str] = None
    # v8.4.0: Enhanced optimization options
    optimize_for: Optional[Literal["lux", "gemini", "both", "triple_verify"]] = None
    # v8.4.0: Option to include Gemini-optimized resize
    include_gemini_optimized: bool = False


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
    """Request to get element bounding rectangle"""
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


class TripleVerifyRequest(BaseModel):
    """
    Request to verify coordinates from multiple sources.
    
    Provide coordinates from any combination of sources:
    - dom: From /browser/dom/element_rect (viewport coords)
    - lux: From Lux Vision API (lux_sdk coords, 1260×700)
    - gemini: From Gemini Computer Use (normalized 0-999)
    
    At least 2 sources required for verification.
    """
    # DOM coordinates (already in viewport space)
    dom_x: Optional[int] = None
    dom_y: Optional[int] = None
    
    # Lux SDK coordinates (1260×700 reference)
    lux_x: Optional[int] = None
    lux_y: Optional[int] = None
    
    # Gemini normalized coordinates (0-999)
    gemini_x: Optional[int] = None
    gemini_y: Optional[int] = None
    
    # Optional: element description for logging
    element_description: Optional[str] = None


class CoordinateConvertRequest(BaseModel):
    """Request to convert coordinates between spaces"""
    x: int
    y: int
    from_space: Literal["viewport", "screen", "lux_sdk", "normalized"]
    to_space: Literal["viewport", "screen", "lux_sdk", "normalized"]
    session_id: Optional[str] = None


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
    """Response containing screenshot(s) optimized for different models"""
    success: bool
    error: Optional[str] = None
    # Original screenshot (viewport resolution)
    original: Optional[Dict[str, Any]] = None
    # Lux optimized (1260×700 - same as viewport in v8.4.0)
    lux_optimized: Optional[Dict[str, Any]] = None
    # v8.4.0: Gemini optimized (1440×900)
    gemini_optimized: Optional[Dict[str, Any]] = None


class ElementRectResponse(BaseModel):
    """Response with element bounding rectangle"""
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


class TripleVerifyResponse(BaseModel):
    """
    Response from triple verification with confidence scoring.
    
    Confidence levels:
    - HIGH: All sources agree within 50px
    - MEDIUM: Sources agree within 100px
    - LOW: Sources disagree by 100-150px
    - FAILED: Sources disagree by >150px or insufficient data
    """
    success: bool
    error: Optional[str] = None
    
    # Verification result
    confidence: Literal["HIGH", "MEDIUM", "LOW", "FAILED"]
    recommended_action: Literal["PROCEED", "RETRY", "FALLBACK", "ABORT"]
    
    # Coordinates in common space (viewport)
    viewport_coords: Optional[Dict[str, int]] = None  # Best estimate {x, y}
    
    # Individual source coords (converted to viewport)
    dom_viewport: Optional[Dict[str, int]] = None
    lux_viewport: Optional[Dict[str, int]] = None
    gemini_viewport: Optional[Dict[str, int]] = None
    
    # Distance matrix
    distances: Optional[Dict[str, float]] = None  # dom_lux, dom_gemini, lux_gemini
    
    # Sources used
    sources_provided: List[str] = []
    sources_count: int = 0
    
    # Debug info
    element_description: Optional[str] = None
    thresholds: Dict[str, int] = {
        "match": TRIPLE_VERIFY_MATCH_THRESHOLD,
        "warning": TRIPLE_VERIFY_WARNING_THRESHOLD,
        "mismatch": TRIPLE_VERIFY_MISMATCH_THRESHOLD
    }


class StatusResponse(BaseModel):
    """Service status response"""
    status: str
    version: str
    browser_sessions: int
    capabilities: Dict[str, bool]
    # v8.4.0: Model reference info
    model_references: Dict[str, Dict[str, int]]


# ============================================================================
# COORDINATE CONVERTER (v8.4.0 - Enhanced for Triple Verification)
# ============================================================================

class CoordinateConverter:
    """
    Converts coordinates between different spaces.
    
    Spaces:
    - viewport: Browser viewport (1260×700 in v8.4.0)
    - screen: Absolute screen coordinates
    - lux_sdk: Lux SDK reference (1260×700) - SAME AS VIEWPORT
    - normalized: Gemini 2.5 Computer Use (0-999)
    """
    
    @staticmethod
    def euclidean_distance(x1: int, y1: int, x2: int, y2: int) -> float:
        """Calculate Euclidean distance between two points"""
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    
    # ========== LUX SDK Conversions ==========
    
    @staticmethod
    def lux_sdk_to_screen(x: int, y: int, screen_width: int, screen_height: int) -> Tuple[int, int]:
        """Convert Lux SDK coords (1260×700) to screen coords"""
        scale_x = screen_width / LUX_SDK_WIDTH
        scale_y = screen_height / LUX_SDK_HEIGHT
        return int(x * scale_x), int(y * scale_y)
    
    @staticmethod
    def screen_to_lux_sdk(x: int, y: int, screen_width: int, screen_height: int) -> Tuple[int, int]:
        """Convert screen coords to Lux SDK coords"""
        scale_x = LUX_SDK_WIDTH / screen_width
        scale_y = LUX_SDK_HEIGHT / screen_height
        return int(x * scale_x), int(y * scale_y)
    
    @staticmethod
    def lux_sdk_to_viewport(x: int, y: int, viewport_width: int = VIEWPORT_WIDTH, 
                           viewport_height: int = VIEWPORT_HEIGHT) -> Tuple[int, int]:
        """
        Convert Lux SDK coords to viewport coords.
        In v8.4.0 with viewport=1260×700, this is 1:1 mapping.
        """
        if viewport_width == LUX_SDK_WIDTH and viewport_height == LUX_SDK_HEIGHT:
            return x, y
        scale_x = viewport_width / LUX_SDK_WIDTH
        scale_y = viewport_height / LUX_SDK_HEIGHT
        return int(x * scale_x), int(y * scale_y)
    
    @staticmethod
    def viewport_to_lux_sdk(x: int, y: int, viewport_width: int = VIEWPORT_WIDTH,
                           viewport_height: int = VIEWPORT_HEIGHT) -> Tuple[int, int]:
        """Convert viewport coords to Lux SDK coords. 1:1 in v8.4.0."""
        if viewport_width == LUX_SDK_WIDTH and viewport_height == LUX_SDK_HEIGHT:
            return x, y
        scale_x = LUX_SDK_WIDTH / viewport_width
        scale_y = LUX_SDK_HEIGHT / viewport_height
        return int(x * scale_x), int(y * scale_y)
    
    # ========== NORMALIZED (Gemini) Conversions ==========
    
    @staticmethod
    def normalized_to_viewport(x: int, y: int, viewport_width: int = VIEWPORT_WIDTH,
                              viewport_height: int = VIEWPORT_HEIGHT) -> Tuple[int, int]:
        """
        Convert Gemini normalized coords (0-999) to viewport coords.
        Formula: pixel = normalized / 1000 * dimension
        
        Example for 1260×700 viewport:
        - (500, 500) → (630, 350) center
        - (0, 0) → (0, 0) top-left
        - (999, 999) → (1259, 699) bottom-right
        """
        pixel_x = int(x / 1000 * viewport_width)
        pixel_y = int(y / 1000 * viewport_height)
        return pixel_x, pixel_y
    
    @staticmethod
    def viewport_to_normalized(x: int, y: int, viewport_width: int = VIEWPORT_WIDTH,
                              viewport_height: int = VIEWPORT_HEIGHT) -> Tuple[int, int]:
        """Convert viewport coords to Gemini normalized coords (0-999)."""
        norm_x = int(x / viewport_width * 1000)
        norm_y = int(y / viewport_height * 1000)
        norm_x = max(0, min(NORMALIZED_COORD_MAX, norm_x))
        norm_y = max(0, min(NORMALIZED_COORD_MAX, norm_y))
        return norm_x, norm_y
    
    @staticmethod
    def normalized_to_screen(x: int, y: int, screen_width: int, screen_height: int) -> Tuple[int, int]:
        """Convert Gemini normalized coords (0-999) to screen coords."""
        pixel_x = int(x / 1000 * screen_width)
        pixel_y = int(y / 1000 * screen_height)
        return pixel_x, pixel_y
    
    @staticmethod
    def screen_to_normalized(x: int, y: int, screen_width: int, screen_height: int) -> Tuple[int, int]:
        """Convert screen coords to Gemini normalized coords (0-999)."""
        norm_x = int(x / screen_width * 1000)
        norm_y = int(y / screen_height * 1000)
        norm_x = max(0, min(NORMALIZED_COORD_MAX, norm_x))
        norm_y = max(0, min(NORMALIZED_COORD_MAX, norm_y))
        return norm_x, norm_y
    
    @staticmethod
    def normalized_to_lux_sdk(x: int, y: int) -> Tuple[int, int]:
        """Convert Gemini normalized coords (0-999) to Lux SDK coords."""
        lux_x = int(x / 1000 * LUX_SDK_WIDTH)
        lux_y = int(y / 1000 * LUX_SDK_HEIGHT)
        return lux_x, lux_y
    
    @staticmethod
    def lux_sdk_to_normalized(x: int, y: int) -> Tuple[int, int]:
        """Convert Lux SDK coords to Gemini normalized coords (0-999)."""
        norm_x = int(x / LUX_SDK_WIDTH * 1000)
        norm_y = int(y / LUX_SDK_HEIGHT * 1000)
        norm_x = max(0, min(NORMALIZED_COORD_MAX, norm_x))
        norm_y = max(0, min(NORMALIZED_COORD_MAX, norm_y))
        return norm_x, norm_y
    
    # ========== v8.4.0: Gemini Recommended Resolution ==========
    
    @staticmethod
    def viewport_to_gemini_recommended(x: int, y: int, viewport_width: int = VIEWPORT_WIDTH,
                                       viewport_height: int = VIEWPORT_HEIGHT) -> Tuple[int, int]:
        """Convert viewport coords to Gemini recommended resolution (1440×900)."""
        scale_x = GEMINI_RECOMMENDED_WIDTH / viewport_width
        scale_y = GEMINI_RECOMMENDED_HEIGHT / viewport_height
        return int(x * scale_x), int(y * scale_y)
    
    @staticmethod
    def gemini_recommended_to_viewport(x: int, y: int, viewport_width: int = VIEWPORT_WIDTH,
                                       viewport_height: int = VIEWPORT_HEIGHT) -> Tuple[int, int]:
        """Convert Gemini recommended resolution coords to viewport."""
        scale_x = viewport_width / GEMINI_RECOMMENDED_WIDTH
        scale_y = viewport_height / GEMINI_RECOMMENDED_HEIGHT
        return int(x * scale_x), int(y * scale_y)


# ============================================================================
# IMAGE UTILITIES
# ============================================================================

def resize_image(image_bytes: bytes, target_width: int, target_height: int) -> Dict[str, Any]:
    """
    Resize image to target resolution.
    Returns dict with base64 image and scale factors.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("PIL not available for image resizing")
    
    img = Image.open(io.BytesIO(image_bytes))
    original_width, original_height = img.size
    
    resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
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
# CLIPBOARD TYPING
# ============================================================================

def type_via_clipboard(text: str):
    """Type text using clipboard (Ctrl+V) for non-US keyboards."""
    if not PYPERCLIP_AVAILABLE:
        logger.warning("Pyperclip not available, using typewrite")
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
        
    except Exception as e:
        logger.warning(f"Clipboard typing failed: {e}, using typewrite")
        pyautogui.typewrite(text, interval=0.05)


# ============================================================================
# TRIPLE VERIFICATION LOGIC (v8.4.0)
# ============================================================================

class TripleVerifier:
    """
    Verifies coordinates from multiple sources (DOM, Lux, Gemini).
    
    All coordinates are converted to viewport space for comparison.
    Returns confidence level and recommended action.
    """
    
    @staticmethod
    def verify(request: TripleVerifyRequest, viewport_width: int = VIEWPORT_WIDTH,
               viewport_height: int = VIEWPORT_HEIGHT) -> TripleVerifyResponse:
        """
        Verify coordinates from multiple sources.
        
        Returns confidence based on agreement:
        - HIGH: All agree within 50px → PROCEED
        - MEDIUM: Agree within 100px → PROCEED with caution
        - LOW: Disagree 100-150px → RETRY
        - FAILED: Disagree >150px → ABORT
        """
        sources = []
        viewport_coords = {}
        
        # Convert DOM coords (already in viewport space)
        if request.dom_x is not None and request.dom_y is not None:
            sources.append("dom")
            viewport_coords["dom"] = {"x": request.dom_x, "y": request.dom_y}
        
        # Convert Lux coords (1:1 with viewport in v8.4.0)
        if request.lux_x is not None and request.lux_y is not None:
            sources.append("lux")
            lux_vp = CoordinateConverter.lux_sdk_to_viewport(
                request.lux_x, request.lux_y, viewport_width, viewport_height
            )
            viewport_coords["lux"] = {"x": lux_vp[0], "y": lux_vp[1]}
        
        # Convert Gemini normalized coords
        if request.gemini_x is not None and request.gemini_y is not None:
            sources.append("gemini")
            gemini_vp = CoordinateConverter.normalized_to_viewport(
                request.gemini_x, request.gemini_y, viewport_width, viewport_height
            )
            viewport_coords["gemini"] = {"x": gemini_vp[0], "y": gemini_vp[1]}
        
        # Need at least 2 sources
        if len(sources) < 2:
            return TripleVerifyResponse(
                success=False,
                error=f"Need at least 2 coordinate sources, got {len(sources)}: {sources}",
                confidence="FAILED",
                recommended_action="ABORT",
                sources_provided=sources,
                sources_count=len(sources),
                element_description=request.element_description
            )
        
        # Calculate distances
        distances = {}
        max_distance = 0.0
        
        if "dom" in viewport_coords and "lux" in viewport_coords:
            d = CoordinateConverter.euclidean_distance(
                viewport_coords["dom"]["x"], viewport_coords["dom"]["y"],
                viewport_coords["lux"]["x"], viewport_coords["lux"]["y"]
            )
            distances["dom_lux"] = round(d, 2)
            max_distance = max(max_distance, d)
        
        if "dom" in viewport_coords and "gemini" in viewport_coords:
            d = CoordinateConverter.euclidean_distance(
                viewport_coords["dom"]["x"], viewport_coords["dom"]["y"],
                viewport_coords["gemini"]["x"], viewport_coords["gemini"]["y"]
            )
            distances["dom_gemini"] = round(d, 2)
            max_distance = max(max_distance, d)
        
        if "lux" in viewport_coords and "gemini" in viewport_coords:
            d = CoordinateConverter.euclidean_distance(
                viewport_coords["lux"]["x"], viewport_coords["lux"]["y"],
                viewport_coords["gemini"]["x"], viewport_coords["gemini"]["y"]
            )
            distances["lux_gemini"] = round(d, 2)
            max_distance = max(max_distance, d)
        
        # Determine confidence
        if max_distance <= TRIPLE_VERIFY_MATCH_THRESHOLD:
            confidence = "HIGH"
            recommended_action = "PROCEED"
        elif max_distance <= TRIPLE_VERIFY_WARNING_THRESHOLD:
            confidence = "MEDIUM"
            recommended_action = "PROCEED"
        elif max_distance <= TRIPLE_VERIFY_MISMATCH_THRESHOLD:
            confidence = "LOW"
            recommended_action = "RETRY"
        else:
            confidence = "FAILED"
            recommended_action = "FALLBACK"
        
        # Calculate best estimate (average of all sources)
        avg_x = sum(c["x"] for c in viewport_coords.values()) / len(viewport_coords)
        avg_y = sum(c["y"] for c in viewport_coords.values()) / len(viewport_coords)
        
        # If DOM is available and distances are small, prefer DOM (most reliable)
        if "dom" in viewport_coords and max_distance <= TRIPLE_VERIFY_WARNING_THRESHOLD:
            best_x, best_y = viewport_coords["dom"]["x"], viewport_coords["dom"]["y"]
        else:
            best_x, best_y = int(avg_x), int(avg_y)
        
        logger.info(f"🔍 Triple Verify: {sources} → confidence={confidence}, max_dist={max_distance:.1f}px")
        
        return TripleVerifyResponse(
            success=True,
            confidence=confidence,
            recommended_action=recommended_action,
            viewport_coords={"x": best_x, "y": best_y},
            dom_viewport=viewport_coords.get("dom"),
            lux_viewport=viewport_coords.get("lux"),
            gemini_viewport=viewport_coords.get("gemini"),
            distances=distances,
            sources_provided=sources,
            sources_count=len(sources),
            element_description=request.element_description
        )


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
        """Start browser with Edge and persistent profile."""
        self.playwright = await async_playwright().start()
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"🌐 Starting Edge browser with viewport {VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}")
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
        """Get exact viewport position on screen."""
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
        """Capture viewport screenshot at native resolution (1260×700)."""
        if not self.page:
            raise RuntimeError("No active page")
        return await self.page.screenshot(type="png")
    
    async def get_accessibility_tree(self) -> str:
        """Get accessibility tree for DOM analysis"""
        if not self.page:
            raise RuntimeError("No active page")
        
        try:
            if hasattr(self.page, 'accessibility'):
                try:
                    snapshot = await self.page.accessibility.snapshot()
                    if snapshot:
                        return self._format_a11y_tree(snapshot)
                except Exception as e:
                    logger.debug(f"Accessibility API failed: {e}")
            
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
                        
                        let text = '';
                        if (node.childNodes.length > 0) {
                            for (const child of node.childNodes) {
                                if (child.nodeType === Node.TEXT_NODE) {
                                    text += child.textContent.trim() + ' ';
                                }
                            }
                        }
                        text = text.trim().substring(0, 50);
                        
                        const isInteractive = ['a', 'button', 'input', 'select', 'textarea', 'label'].includes(tag) ||
                                             role || node.onclick || node.getAttribute('tabindex') || node.getAttribute('onclick');
                        const isContainer = ['div', 'section', 'article', 'main', 'nav', 'header', 'footer', 'aside'].includes(tag);
                        
                        if (isInteractive || depth < 3 || (isContainer && depth < 4)) {
                            let label = ariaLabel || placeholder || title || text;
                            if (label.length > 50) label = label.substring(0, 50) + '...';
                            let roleStr = role ? '[' + role + ']' : '<' + tag + '>';
                            let extras = [];
                            if (type) extras.push('type=' + type);
                            if (href) extras.push('href');
                            result += indent + roleStr + id + classes;
                            if (extras.length > 0) result += ' (' + extras.join(', ') + ')';
                            if (label) result += ' "' + label + '"';
                            result += '\\n';
                        }
                        
                        for (const child of node.children) {
                            result += extractNode(child, depth + 1);
                        }
                    }
                    return result;
                }
                return extractNode(document.body);
            }''')
            
            return dom_structure if dom_structure and dom_structure.strip() else "DOM tree empty"
            
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
        """Get bounding rectangle of a DOM element for Triple Verification."""
        if not self.page:
            return ElementRectResponse(success=False, error="No active page")
        
        try:
            locator = None
            selector_description = ""
            
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
                return ElementRectResponse(
                    success=False,
                    error="Must provide at least one search criteria"
                )
            
            count = await locator.count()
            
            if count == 0:
                return ElementRectResponse(
                    success=True, found=False, element_count=0,
                    selector_used=selector_description, error="Element not found"
                )
            
            if count > 1 and request.index is not None:
                if request.index >= count:
                    return ElementRectResponse(
                        success=True, found=True, element_count=count,
                        selector_used=selector_description,
                        error=f"Index {request.index} out of range ({count} elements)"
                    )
                locator = locator.nth(request.index)
            elif count > 1:
                locator = locator.first
            
            is_visible = await locator.is_visible()
            
            if request.must_be_visible and not is_visible:
                return ElementRectResponse(
                    success=True, found=True, visible=False, element_count=count,
                    selector_used=selector_description, error="Element not visible"
                )
            
            is_enabled = await locator.is_enabled()
            bbox = await locator.bounding_box()
            
            if not bbox:
                return ElementRectResponse(
                    success=True, found=True, visible=False, enabled=is_enabled,
                    element_count=count, selector_used=selector_description,
                    error="No bounding box"
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
            logger.error(f"Error getting element rect: {e}")
            return ElementRectResponse(success=False, error=str(e))
    
    def get_tabs_info(self) -> List[Dict[str, Any]]:
        """Get info about all tabs"""
        return [
            {
                "id": i,
                "url": page.url if not page.is_closed() else None,
                "title": "",
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
    
    async def close_all(self):
        for session_id in list(self.sessions.keys()):
            await self.close_session(session_id)
    
    def get_active_session(self) -> Optional[BrowserSession]:
        for session in self.sessions.values():
            if session.is_alive():
                return session
        return None
    
    def count(self) -> int:
        return len([s for s in self.sessions.values() if s.is_alive()])


# Global session manager
session_manager = SessionManager()


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Architect's Hand - Tool Server",
    description="Desktop App with Triple Verification Support (v8.4.0)",
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
        "viewport": f"{VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT}",
        "features": ["triple_verification", "multi_model_screenshots"]
    }


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get service status with model reference info"""
    return StatusResponse(
        status="running",
        version=SERVICE_VERSION,
        browser_sessions=session_manager.count(),
        capabilities={
            "pyautogui": PYAUTOGUI_AVAILABLE,
            "pyperclip": PYPERCLIP_AVAILABLE,
            "playwright": PLAYWRIGHT_AVAILABLE,
            "pil": PIL_AVAILABLE,
            "triple_verification": True
        },
        model_references={
            "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            "lux_sdk": {"width": LUX_SDK_WIDTH, "height": LUX_SDK_HEIGHT},
            "gemini_recommended": {"width": GEMINI_RECOMMENDED_WIDTH, "height": GEMINI_RECOMMENDED_HEIGHT},
            "normalized_range": {"min": 0, "max": NORMALIZED_COORD_MAX}
        }
    )


@app.get("/screen")
async def get_screen_info():
    """Get screen and model reference information"""
    info = {
        "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        "lux_sdk": {"width": LUX_SDK_WIDTH, "height": LUX_SDK_HEIGHT},
        "gemini_recommended": {"width": GEMINI_RECOMMENDED_WIDTH, "height": GEMINI_RECOMMENDED_HEIGHT},
        "viewport_matches_lux": VIEWPORT_WIDTH == LUX_SDK_WIDTH and VIEWPORT_HEIGHT == LUX_SDK_HEIGHT,
        "normalized_range": {"min": 0, "max": NORMALIZED_COORD_MAX},
        "triple_verify_thresholds": {
            "match": TRIPLE_VERIFY_MATCH_THRESHOLD,
            "warning": TRIPLE_VERIFY_WARNING_THRESHOLD,
            "mismatch": TRIPLE_VERIFY_MISMATCH_THRESHOLD
        }
    }
    
    if PYAUTOGUI_AVAILABLE:
        size = pyautogui.size()
        info["screen"] = {"width": size.width, "height": size.height}
    
    return info


# ============================================================================
# ENDPOINTS: Screenshot (v8.4.0 - Multi-model support)
# ============================================================================

@app.post("/screenshot", response_model=ScreenshotResponse)
async def take_screenshot(request: ScreenshotRequest):
    """
    Take screenshot with optional multi-model optimization.
    
    optimize_for options:
    - lux: Returns lux_optimized (1260×700, same as viewport)
    - gemini: Returns original (use with normalized coords)
    - both: Returns both lux_optimized and original
    - triple_verify: Returns all variants for verification
    
    include_gemini_optimized: If true, also resize to 1440×900 for Gemini
    """
    try:
        if request.scope == "browser":
            session = None
            if request.session_id:
                session = session_manager.get_session(request.session_id)
            else:
                session = session_manager.get_active_session()
            
            if not session or not session.is_alive():
                return ScreenshotResponse(
                    success=False,
                    error="No active browser session"
                )
            
            screenshot_bytes = await session.capture_screenshot()
            viewport = await session.get_viewport_bounds()
            
            result = ScreenshotResponse(success=True)
            
            # Original (viewport resolution = 1260×700)
            original_data = screenshot_to_base64(
                screenshot_bytes, viewport["width"], viewport["height"]
            )
            
            # Always include original for Gemini (it uses normalized coords)
            if request.optimize_for in [None, "gemini", "both", "triple_verify"]:
                result.original = original_data
            
            # Lux optimized (same as viewport in v8.4.0)
            if request.optimize_for in ["lux", "both", "triple_verify"]:
                result.lux_optimized = {
                    **original_data,
                    "original_width": viewport["width"],
                    "original_height": viewport["height"],
                    "scale_x": 1.0,
                    "scale_y": 1.0
                }
            
            # v8.4.0: Optional Gemini-optimized resize
            if request.include_gemini_optimized and PIL_AVAILABLE:
                gemini_data = resize_image(
                    screenshot_bytes,
                    GEMINI_RECOMMENDED_WIDTH,
                    GEMINI_RECOMMENDED_HEIGHT
                )
                result.gemini_optimized = gemini_data
                logger.info(f"📸 Screenshot with Gemini resize: {VIEWPORT_WIDTH}x{VIEWPORT_HEIGHT} → {GEMINI_RECOMMENDED_WIDTH}x{GEMINI_RECOMMENDED_HEIGHT}")
            
            logger.info(f"📸 Screenshot captured: {viewport['width']}x{viewport['height']}")
            return result
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ScreenshotResponse(success=False, error="PyAutoGUI not available")
            
            screenshot = pyautogui.screenshot()
            buffer = io.BytesIO()
            screenshot.save(buffer, format='PNG')
            buffer.seek(0)
            screenshot_bytes = buffer.read()
            
            screen_width, screen_height = pyautogui.size()
            
            result = ScreenshotResponse(success=True)
            
            if request.optimize_for in [None, "gemini", "both", "triple_verify"]:
                result.original = screenshot_to_base64(
                    screenshot_bytes, screen_width, screen_height
                )
            
            if request.optimize_for in ["lux", "both", "triple_verify"]:
                result.lux_optimized = resize_image(
                    screenshot_bytes, LUX_SDK_WIDTH, LUX_SDK_HEIGHT
                )
            
            if request.include_gemini_optimized and PIL_AVAILABLE:
                result.gemini_optimized = resize_image(
                    screenshot_bytes,
                    GEMINI_RECOMMENDED_WIDTH,
                    GEMINI_RECOMMENDED_HEIGHT
                )
            
            return result
        
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        return ScreenshotResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Triple Verification (v8.4.0)
# ============================================================================

@app.post("/coordinates/triple_verify", response_model=TripleVerifyResponse)
async def triple_verify(request: TripleVerifyRequest):
    """
    Verify coordinates from multiple sources (DOM, Lux, Gemini).
    
    ┌─────────────────────────────────────────────────────────────────┐
    │  TRIPLE VERIFICATION                                            │
    │                                                                 │
    │  Provide coords from 2-3 sources:                              │
    │  - dom_x, dom_y: From /browser/dom/element_rect               │
    │  - lux_x, lux_y: From Lux Vision API (1260×700)               │
    │  - gemini_x, gemini_y: From Gemini Computer Use (0-999)       │
    │                                                                 │
    │  Returns:                                                       │
    │  - confidence: HIGH/MEDIUM/LOW/FAILED                          │
    │  - recommended_action: PROCEED/RETRY/FALLBACK/ABORT            │
    │  - viewport_coords: Best estimate for clicking                 │
    │  - distances: Pairwise distances for debugging                 │
    └─────────────────────────────────────────────────────────────────┘
    
    Thresholds:
    - HIGH confidence: max distance ≤ 50px → PROCEED
    - MEDIUM confidence: max distance ≤ 100px → PROCEED with caution
    - LOW confidence: max distance ≤ 150px → RETRY
    - FAILED: max distance > 150px → FALLBACK or ABORT
    """
    return TripleVerifier.verify(request, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)


# ============================================================================
# ENDPOINTS: Click
# ============================================================================

@app.post("/click", response_model=ActionResponse)
async def do_click(request: ClickRequest):
    """Perform click action with coordinate conversion."""
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
                return ActionResponse(success=False, error="No active browser session")
            
            viewport = await session.get_viewport_bounds()
            
            # Convert coordinates
            if request.coordinate_origin == "lux_sdk":
                x, y = CoordinateConverter.lux_sdk_to_viewport(
                    x, y, viewport["width"], viewport["height"]
                )
                if viewport["width"] == LUX_SDK_WIDTH and viewport["height"] == LUX_SDK_HEIGHT:
                    conversion_applied = "none (1:1 mapping)"
                else:
                    conversion_applied = "lux_sdk→viewport"
            
            elif request.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_viewport(
                    x, y, viewport["width"], viewport["height"]
                )
                conversion_applied = "normalized→viewport"
            
            # Validate
            if not (0 <= x <= viewport["width"] and 0 <= y <= viewport["height"]):
                return ActionResponse(
                    success=False,
                    error=f"Coordinates ({x}, {y}) outside viewport",
                    details={"viewport": viewport}
                )
            
            # Execute
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
                    "viewport_coords": {"x": x, "y": y},
                    "original_coords": {"x": original_x, "y": original_y},
                    "coordinate_origin": request.coordinate_origin,
                    "conversion": conversion_applied
                }
            )
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(success=False, error="PyAutoGUI not available")
            
            screen_width, screen_height = pyautogui.size()
            
            if request.coordinate_origin == "lux_sdk":
                x, y = CoordinateConverter.lux_sdk_to_screen(x, y, screen_width, screen_height)
                conversion_applied = "lux_sdk→screen"
            elif request.coordinate_origin == "normalized":
                x, y = CoordinateConverter.normalized_to_screen(x, y, screen_width, screen_height)
                conversion_applied = "normalized→screen"
            
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
                    "screen_coords": {"x": x, "y": y},
                    "original_coords": {"x": original_x, "y": original_y},
                    "conversion": conversion_applied
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
    """Type text."""
    try:
        if request.scope == "browser":
            session = session_manager.get_session(request.session_id) if request.session_id else session_manager.get_active_session()
            if not session or not session.is_alive():
                return ActionResponse(success=False, error="No active browser session")
            
            if request.selector:
                await session.page.click(request.selector)
                await asyncio.sleep(0.1)
            
            await session.page.keyboard.type(request.text, delay=50)
            return ActionResponse(success=True, executed_with="playwright")
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(success=False, error="PyAutoGUI not available")
            
            if request.method == "clipboard":
                type_via_clipboard(request.text)
            else:
                pyautogui.typewrite(request.text, interval=0.05)
            
            return ActionResponse(success=True, executed_with="pyautogui")
    
    except Exception as e:
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Scroll
# ============================================================================

@app.post("/scroll", response_model=ActionResponse)
async def do_scroll(request: ScrollRequest):
    """Scroll in the specified direction."""
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
            return ActionResponse(success=True, executed_with="playwright")
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(success=False, error="PyAutoGUI not available")
            
            clicks = request.amount // 100
            if request.direction == "up":
                pyautogui.scroll(clicks)
            elif request.direction == "down":
                pyautogui.scroll(-clicks)
            
            return ActionResponse(success=True, executed_with="pyautogui")
    
    except Exception as e:
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Keypress
# ============================================================================

@app.post("/keypress", response_model=ActionResponse)
async def do_keypress(request: KeypressRequest):
    """Press a key or key combination."""
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
            
            return ActionResponse(success=True, executed_with="playwright")
        
        elif request.scope == "desktop":
            if not PYAUTOGUI_AVAILABLE:
                return ActionResponse(success=False, error="PyAutoGUI not available")
            
            if "+" in request.key:
                keys = request.key.lower().split("+")
                pyautogui.hotkey(*keys)
            else:
                pyautogui.press(request.key.lower())
            
            return ActionResponse(success=True, executed_with="pyautogui")
    
    except Exception as e:
        return ActionResponse(success=False, error=str(e))


# ============================================================================
# ENDPOINTS: Browser Session Management
# ============================================================================

@app.post("/browser/start")
async def browser_start(request: BrowserStartRequest):
    """Start a new browser session."""
    if not PLAYWRIGHT_AVAILABLE:
        raise HTTPException(status_code=500, detail="Playwright not available")
    
    try:
        session_id = await session_manager.create_session(request.start_url, request.headless)
        session = session_manager.get_session(session_id)
        
        return {
            "success": True,
            "session_id": session_id,
            "current_url": session.page.url if session and session.page else None,
            "viewport": {
                "width": VIEWPORT_WIDTH,
                "height": VIEWPORT_HEIGHT,
                "matches_lux_sdk": True
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/browser/stop")
async def browser_stop(session_id: str = Query(...)):
    """Stop a browser session."""
    success = await session_manager.close_session(session_id)
    return {"success": success}


@app.get("/browser/status")
async def browser_status(session_id: Optional[str] = None):
    """Get browser session status."""
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
                "viewport": viewport
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
    """Navigate to URL."""
    session = session_manager.get_session(request.session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    
    try:
        await session.page.goto(request.url, wait_until="domcontentloaded", timeout=30000)
        return {"success": True, "url": session.page.url}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/browser/reload")
async def browser_reload(session_id: str = Query(...)):
    """Reload current page."""
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
    """Go back in history."""
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
    """Go forward in history."""
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
    """List all tabs."""
    session = session_manager.get_session(session_id)
    if not session:
        return {"success": False, "error": "Session not found"}
    return {"success": True, "tabs": session.get_tabs_info()}


@app.post("/browser/tab/new")
async def browser_tab_new(request: TabRequest):
    """Open new tab."""
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
    """Close a tab."""
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
    """Switch to a different tab."""
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
    """Get accessibility tree."""
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
    Get element bounding rectangle for Triple Verification.
    
    Returns center coordinates (x, y) in viewport space.
    Use with /coordinates/triple_verify to compare with Lux and Gemini.
    """
    session = session_manager.get_session(request.session_id)
    if not session or not session.is_alive():
        return ElementRectResponse(success=False, error="Session not found")
    
    return await session.get_element_rect(request)


@app.get("/browser/current_url")
async def browser_current_url(session_id: str = Query(...)):
    """Get current page URL."""
    session = session_manager.get_session(session_id)
    if not session or not session.is_alive():
        return {"success": False, "error": "Session not found"}
    return {"success": True, "url": session.page.url}


# ============================================================================
# ENDPOINTS: Coordinate Utilities
# ============================================================================

@app.post("/coordinates/convert")
async def coordinates_convert(request: CoordinateConvertRequest):
    """Convert coordinates between spaces."""
    try:
        x, y = request.x, request.y
        result_x, result_y = x, y
        
        # Get dimensions
        viewport_width, viewport_height = VIEWPORT_WIDTH, VIEWPORT_HEIGHT
        if PYAUTOGUI_AVAILABLE:
            screen_width, screen_height = pyautogui.size()
        else:
            screen_width, screen_height = 1920, 1080
        
        # FROM lux_sdk
        if request.from_space == "lux_sdk":
            if request.to_space == "viewport":
                result_x, result_y = CoordinateConverter.lux_sdk_to_viewport(x, y)
            elif request.to_space == "screen":
                result_x, result_y = CoordinateConverter.lux_sdk_to_screen(x, y, screen_width, screen_height)
            elif request.to_space == "normalized":
                result_x, result_y = CoordinateConverter.lux_sdk_to_normalized(x, y)
        
        # FROM viewport
        elif request.from_space == "viewport":
            if request.to_space == "lux_sdk":
                result_x, result_y = CoordinateConverter.viewport_to_lux_sdk(x, y)
            elif request.to_space == "normalized":
                result_x, result_y = CoordinateConverter.viewport_to_normalized(x, y)
        
        # FROM screen
        elif request.from_space == "screen":
            if request.to_space == "lux_sdk":
                result_x, result_y = CoordinateConverter.screen_to_lux_sdk(x, y, screen_width, screen_height)
            elif request.to_space == "normalized":
                result_x, result_y = CoordinateConverter.screen_to_normalized(x, y, screen_width, screen_height)
        
        # FROM normalized
        elif request.from_space == "normalized":
            if request.to_space == "viewport":
                result_x, result_y = CoordinateConverter.normalized_to_viewport(x, y)
            elif request.to_space == "screen":
                result_x, result_y = CoordinateConverter.normalized_to_screen(x, y, screen_width, screen_height)
            elif request.to_space == "lux_sdk":
                result_x, result_y = CoordinateConverter.normalized_to_lux_sdk(x, y)
        
        return {
            "success": True,
            "x": result_x,
            "y": result_y,
            "from_space": request.from_space,
            "to_space": request.to_space,
            "original": {"x": x, "y": y}
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
║  🎯 TRIPLE VERIFICATION SUPPORT                              ║
║                                                              ║
║  Common Coordinate Space: VIEWPORT (1260×700)                ║
║  ├── DOM:    Native viewport coords                          ║
║  ├── Lux:    1:1 mapping (1260×700 = viewport)              ║
║  └── Gemini: Normalized (0-999) → denormalize to viewport   ║
║                                                              ║
║  Model References:                                           ║
║  ├── Lux SDK:    1260×700 (viewport-native)                 ║
║  └── Gemini:     1440×900 (recommended, optional resize)    ║
║                                                              ║
║  Verification Thresholds:                                    ║
║  ├── HIGH:   ≤{TRIPLE_VERIFY_MATCH_THRESHOLD}px  → PROCEED                            ║
║  ├── MEDIUM: ≤{TRIPLE_VERIFY_WARNING_THRESHOLD}px → PROCEED with caution               ║
║  ├── LOW:    ≤{TRIPLE_VERIFY_MISMATCH_THRESHOLD}px → RETRY                              ║
║  └── FAILED: >{TRIPLE_VERIFY_MISMATCH_THRESHOLD}px → FALLBACK/ABORT                     ║
║                                                              ║
║  New Endpoint:                                               ║
║    POST /coordinates/triple_verify                           ║
║                                                              ║
║  Capabilities:                                               ║
║    {'✅' if PLAYWRIGHT_AVAILABLE else '❌'} Playwright (Browser)                             ║
║    {'✅' if PYAUTOGUI_AVAILABLE else '❌'} PyAutoGUI (Desktop)                               ║
║    {'✅' if PIL_AVAILABLE else '❌'} PIL (Image processing)                             ║
║                                                              ║
║  Endpoint: http://127.0.0.1:{SERVICE_PORT}                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(app, host="127.0.0.1", port=SERVICE_PORT, log_level="info")
