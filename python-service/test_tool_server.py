#!/usr/bin/env python3
"""
Test Script per Tool Server v8.0
Testa tutti gli endpoint sistematicamente

v1.1 - Fix: keypress usa "key" invece di "keys"
     - Fix: browser_stop usa query param invece di body
"""

import requests
import json
import time
import base64
from datetime import datetime

# ============================================================
# CONFIGURAZIONE
# ============================================================

TOOL_SERVER_URL = "http://127.0.0.1:8766"
TEST_URL = "https://www.google.com"
TIMEOUT = 30

# Colori per output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def ok(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")

def fail(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.RESET}")

def info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.RESET}")

def warn(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.RESET}")

def header(msg):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}{Colors.RESET}\n")

# ============================================================
# TEST FUNCTIONS
# ============================================================

def test_root():
    """Test GET / - Info endpoint"""
    try:
        r = requests.get(f"{TOOL_SERVER_URL}/", timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            ok(f"Root endpoint: {data.get('service', 'OK')} v{data.get('version', '?')}")
            return True
        else:
            fail(f"Root endpoint: HTTP {r.status_code}")
            return False
    except Exception as e:
        fail(f"Root endpoint: {e}")
        return False

def test_health():
    """Test GET /health"""
    try:
        r = requests.get(f"{TOOL_SERVER_URL}/health", timeout=TIMEOUT)
        if r.status_code == 200:
            ok(f"Health endpoint: {r.json()}")
            return True
        elif r.status_code == 404:
            warn("Health endpoint: /health non esiste (non critico)")
            return True  # Non critico
        else:
            fail(f"Health endpoint: HTTP {r.status_code}")
            return False
    except Exception as e:
        fail(f"Health endpoint: {e}")
        return False

def test_browser_start(url=TEST_URL):
    """Test POST /browser/start"""
    try:
        r = requests.post(
            f"{TOOL_SERVER_URL}/browser/start",
            json={"start_url": url},
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            session_id = data.get("session_id")
            if session_id:
                ok(f"Browser start: session_id = {session_id[:20]}...")
                return session_id
            else:
                fail(f"Browser start: no session_id in response: {data}")
                return None
        else:
            fail(f"Browser start: HTTP {r.status_code} - {r.text[:200]}")
            return None
    except Exception as e:
        fail(f"Browser start: {e}")
        return None

def test_browser_sessions():
    """Test GET /browser/sessions"""
    try:
        r = requests.get(f"{TOOL_SERVER_URL}/browser/sessions", timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            ok(f"Browser sessions: {len(data.get('sessions', []))} active")
            return True
        elif r.status_code == 404:
            warn("Browser sessions: endpoint non esiste")
            return True
        else:
            fail(f"Browser sessions: HTTP {r.status_code}")
            return False
    except Exception as e:
        fail(f"Browser sessions: {e}")
        return False

def test_screenshot(session_id, scope="browser"):
    """Test POST /screenshot"""
    try:
        payload = {"scope": scope}
        if session_id:
            payload["session_id"] = session_id
            
        r = requests.post(
            f"{TOOL_SERVER_URL}/screenshot",
            json=payload,
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            # Check for image data
            if data.get("original", {}).get("image_base64"):
                img_size = len(data["original"]["image_base64"])
                width = data["original"].get("width", "?")
                height = data["original"].get("height", "?")
                ok(f"Screenshot ({scope}): {width}x{height}, {img_size//1024}KB base64")
                
                # Check for lux_optimized
                if data.get("lux_optimized"):
                    lux_w = data["lux_optimized"].get("width", "?")
                    lux_h = data["lux_optimized"].get("height", "?")
                    info(f"  └── Lux optimized: {lux_w}x{lux_h}")
                return True
            elif data.get("image_base64"):
                img_size = len(data["image_base64"])
                ok(f"Screenshot ({scope}): {img_size//1024}KB base64")
                return True
            else:
                fail(f"Screenshot ({scope}): no image in response")
                return False
        else:
            fail(f"Screenshot ({scope}): HTTP {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        fail(f"Screenshot ({scope}): {e}")
        return False

def test_dom_tree(session_id):
    """Test GET /browser/dom/tree"""
    try:
        r = requests.get(
            f"{TOOL_SERVER_URL}/browser/dom/tree",
            params={"session_id": session_id},
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            tree = data.get("tree", "")
            if tree and not tree.startswith("Error"):
                lines = tree.count("\n") + 1
                ok(f"DOM tree: {lines} lines, {len(tree)} chars")
                # Show first 200 chars
                preview = tree[:200].replace("\n", " ")
                info(f"  └── Preview: {preview}...")
                return True
            elif tree.startswith("Error"):
                warn(f"DOM tree: {tree[:100]}")
                return False
            else:
                warn("DOM tree: empty response")
                return True
        else:
            fail(f"DOM tree: HTTP {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        fail(f"DOM tree: {e}")
        return False

def test_current_url(session_id):
    """Test GET /browser/current_url"""
    try:
        r = requests.get(
            f"{TOOL_SERVER_URL}/browser/current_url",
            params={"session_id": session_id},
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            url = data.get("url", "?")
            ok(f"Current URL: {url}")
            return True
        elif r.status_code == 404:
            warn("Current URL: endpoint non esiste")
            return True
        else:
            fail(f"Current URL: HTTP {r.status_code}")
            return False
    except Exception as e:
        fail(f"Current URL: {e}")
        return False

def test_click(session_id, x=500, y=300):
    """Test POST /click"""
    try:
        r = requests.post(
            f"{TOOL_SERVER_URL}/click",
            json={
                "scope": "browser",
                "x": x,
                "y": y,
                "session_id": session_id,
                "coordinate_origin": "viewport"
            },
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"Click ({x}, {y}): {data.get('success', data)}")
            return True
        else:
            fail(f"Click: HTTP {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        fail(f"Click: {e}")
        return False

def test_type(session_id, text="Hello Tool Server!"):
    """Test POST /type"""
    try:
        r = requests.post(
            f"{TOOL_SERVER_URL}/type",
            json={
                "scope": "browser",
                "text": text,
                "session_id": session_id,
                "method": "clipboard"
            },
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"Type '{text[:20]}...': {data.get('success', data)}")
            return True
        else:
            fail(f"Type: HTTP {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        fail(f"Type: {e}")
        return False

def test_scroll(session_id, direction="down"):
    """Test POST /scroll"""
    try:
        r = requests.post(
            f"{TOOL_SERVER_URL}/scroll",
            json={
                "scope": "browser",
                "direction": direction,
                "amount": 300,
                "session_id": session_id
            },
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"Scroll {direction}: {data.get('success', data)}")
            return True
        else:
            fail(f"Scroll: HTTP {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        fail(f"Scroll: {e}")
        return False

def test_keypress(session_id, key="Tab"):
    """Test POST /keypress"""
    try:
        r = requests.post(
            f"{TOOL_SERVER_URL}/keypress",
            json={
                "scope": "browser",
                "key": key,  # FIX: era "keys", ora "key"
                "session_id": session_id
            },
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"Keypress '{key}': {data.get('success', data)}")
            return True
        else:
            fail(f"Keypress: HTTP {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        fail(f"Keypress: {e}")
        return False

def test_navigate(session_id, url="https://www.bing.com"):
    """Test POST /browser/navigate"""
    try:
        r = requests.post(
            f"{TOOL_SERVER_URL}/browser/navigate",
            json={
                "session_id": session_id,
                "url": url
            },
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"Navigate to {url}: {data.get('success', data)}")
            return True
        else:
            fail(f"Navigate: HTTP {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        fail(f"Navigate: {e}")
        return False

def test_browser_stop(session_id):
    """Test POST /browser/stop"""
    try:
        # FIX: usa query parameter invece di body
        r = requests.post(
            f"{TOOL_SERVER_URL}/browser/stop?session_id={session_id}",
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            ok(f"Browser stop: {data.get('success', data)}")
            return True
        else:
            fail(f"Browser stop: HTTP {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        fail(f"Browser stop: {e}")
        return False

def test_desktop_screenshot():
    """Test desktop screenshot (PyAutoGUI)"""
    try:
        r = requests.post(
            f"{TOOL_SERVER_URL}/screenshot",
            json={"scope": "desktop"},
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("original", {}).get("image_base64") or data.get("image_base64"):
                ok("Desktop screenshot: OK")
                return True
            else:
                fail("Desktop screenshot: no image")
                return False
        else:
            fail(f"Desktop screenshot: HTTP {r.status_code}")
            return False
    except Exception as e:
        fail(f"Desktop screenshot: {e}")
        return False

# ============================================================
# MAIN TEST RUNNER
# ============================================================

def run_all_tests():
    """Esegue tutti i test in sequenza"""
    
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"  TOOL SERVER TEST SUITE v1.1")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Target: {TOOL_SERVER_URL}")
    print(f"{'='*60}{Colors.RESET}\n")
    
    results = {
        "passed": 0,
        "failed": 0,
        "warnings": 0
    }
    
    session_id = None
    
    # ──────────────────────────────────────────────────────
    # BASIC TESTS
    # ──────────────────────────────────────────────────────
    
    header("1. BASIC CONNECTIVITY")
    
    if test_root():
        results["passed"] += 1
    else:
        results["failed"] += 1
        fail("Server non raggiungibile! Assicurati che tool_server.py sia in esecuzione.")
        return results
    
    test_health()  # Non critico
    
    # ──────────────────────────────────────────────────────
    # BROWSER TESTS
    # ──────────────────────────────────────────────────────
    
    header("2. BROWSER SESSION")
    
    info("Avvio browser con Google...")
    session_id = test_browser_start(TEST_URL)
    
    if not session_id:
        results["failed"] += 1
        fail("Impossibile avviare browser - test interrotti")
        return results
    
    results["passed"] += 1
    
    # Attendi caricamento pagina
    info("Attendo caricamento pagina (3 sec)...")
    time.sleep(3)
    
    test_browser_sessions()
    
    # ──────────────────────────────────────────────────────
    # SCREENSHOT TESTS
    # ──────────────────────────────────────────────────────
    
    header("3. SCREENSHOT")
    
    if test_screenshot(session_id, "browser"):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    if test_desktop_screenshot():
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    # ──────────────────────────────────────────────────────
    # DOM TREE
    # ──────────────────────────────────────────────────────
    
    header("4. DOM / ACCESSIBILITY TREE")
    
    if test_dom_tree(session_id):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    if test_current_url(session_id):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    # ──────────────────────────────────────────────────────
    # ACTIONS
    # ──────────────────────────────────────────────────────
    
    header("5. ACTIONS (Click, Type, Scroll, Keypress)")
    
    # Click sulla search box di Google (circa al centro)
    info("Click al centro della pagina...")
    if test_click(session_id, 640, 360):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    time.sleep(0.5)
    
    # Type
    info("Digito testo...")
    if test_type(session_id, "Tool Server Test"):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    time.sleep(0.5)
    
    # Keypress
    info("Premo Tab...")
    if test_keypress(session_id, "Tab"):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    time.sleep(0.5)
    
    # Scroll
    info("Scroll down...")
    if test_scroll(session_id, "down"):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    # ──────────────────────────────────────────────────────
    # NAVIGATION
    # ──────────────────────────────────────────────────────
    
    header("6. NAVIGATION")
    
    info("Navigo a Bing...")
    if test_navigate(session_id, "https://www.bing.com"):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    time.sleep(2)
    
    # Verifica URL cambiato
    test_current_url(session_id)
    
    # ──────────────────────────────────────────────────────
    # CLEANUP
    # ──────────────────────────────────────────────────────
    
    header("7. CLEANUP")
    
    info("Chiudo browser...")
    if test_browser_stop(session_id):
        results["passed"] += 1
    else:
        results["failed"] += 1
    
    # ──────────────────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────────────────
    
    header("RISULTATI")
    
    total = results["passed"] + results["failed"]
    
    print(f"  {Colors.GREEN}Passed: {results['passed']}{Colors.RESET}")
    print(f"  {Colors.RED}Failed: {results['failed']}{Colors.RESET}")
    print(f"  Total:  {total}")
    print()
    
    if results["failed"] == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}  🎉 TUTTI I TEST PASSATI! Tool Server pronto per .exe{Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}  ⚠️  Alcuni test falliti. Verifica i log sopra.{Colors.RESET}")
    
    print()
    return results

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test interrotti dall'utente{Colors.RESET}")
    except Exception as e:
        print(f"\n{Colors.RED}Errore critico: {e}{Colors.RESET}")
