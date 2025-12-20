"""
Windows-specific keyboard input handling - v4.2
Based on OAGI official implementation from KB.
Uses SendInput with KEYEVENTF_UNICODE for direct Unicode input.

v4.2 Changes:
- Explicit wVk = 0 (KB requirement for KEYEVENTF_UNICODE)
- SendInput return value verification
- GetLastError on failure
- Debug output for troubleshooting
"""

import ctypes
import time
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [
            ("ki", KEYBDINPUT),
            ("mi", MOUSEINPUT),
            ("hi", HARDWAREINPUT),
        ]

    _anonymous_ = ("i",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("i", _I),
    ]


# Get SendInput function with use_last_error for proper error handling
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

# Debug flag - set to True for verbose output
DEBUG_SENDINPUT = True


def _debug_print(msg: str) -> None:
    """Print debug message if debugging is enabled."""
    if DEBUG_SENDINPUT:
        print(f"[_windows.py] {msg}")


def get_foreground_window_info() -> dict:
    """Get information about the current foreground window."""
    try:
        hwnd = _user32.GetForegroundWindow()
        
        # Get window title
        length = _user32.GetWindowTextLengthW(hwnd) + 1
        buffer = ctypes.create_unicode_buffer(length)
        _user32.GetWindowTextW(hwnd, buffer, length)
        title = buffer.value
        
        # Get process ID
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        
        return {
            "hwnd": hwnd,
            "title": title[:50] + "..." if len(title) > 50 else title,
            "pid": pid.value
        }
    except Exception as e:
        return {"error": str(e)}


def check_uipi_status() -> dict:
    """
    Check UIPI (User Interface Privilege Isolation) related info.
    If our process has lower integrity than the target, SendInput fails silently.
    """
    try:
        import os
        
        # Get our process info
        our_pid = os.getpid()
        
        # Get foreground window's process
        fg_info = get_foreground_window_info()
        
        return {
            "our_pid": our_pid,
            "target_pid": fg_info.get("pid"),
            "target_window": fg_info.get("title"),
            "note": "If target runs elevated and we don't, SendInput is silently blocked"
        }
    except Exception as e:
        return {"error": str(e)}


def typewrite_exact(text: str, interval: float = 0.01) -> None:
    """
    Type text exactly using Unicode input - ignores capslock, keyboard layout, etc.
    
    Per Microsoft KB:
    - KEYEVENTF_UNICODE: "wVk parameter must be zero"
    - wScan contains the Unicode character
    """
    # Log foreground window info for debugging
    fg_info = get_foreground_window_info()
    _debug_print(f"Foreground window: {fg_info}")
    
    total_events = 0
    failed_chars = []
    
    for char in text:
        inputs = (INPUT * 2)()

        # Key down - MUST set wVk = 0 for KEYEVENTF_UNICODE (KB requirement)
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].ki.wVk = 0  # CRITICAL: Must be 0 for Unicode
        inputs[0].ki.wScan = ord(char)
        inputs[0].ki.dwFlags = KEYEVENTF_UNICODE
        inputs[0].ki.time = 0
        inputs[0].ki.dwExtraInfo = None

        # Key up - MUST set wVk = 0 for KEYEVENTF_UNICODE (KB requirement)
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].ki.wVk = 0  # CRITICAL: Must be 0 for Unicode
        inputs[1].ki.wScan = ord(char)
        inputs[1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        inputs[1].ki.time = 0
        inputs[1].ki.dwExtraInfo = None

        # Call SendInput and check return value
        # Returns: Number of events successfully inserted
        # Should return 2 (key down + key up)
        result = _user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        
        if result != 2:
            error_code = ctypes.get_last_error()
            failed_chars.append((char, result, error_code))
            _debug_print(f"SendInput FAILED for '{char}' (U+{ord(char):04X}): returned {result}, error={error_code}")
        else:
            total_events += 2

        if interval > 0:
            time.sleep(interval)
    
    # Summary
    if DEBUG_SENDINPUT:
        if failed_chars:
            _debug_print(f"WARNING: {len(failed_chars)} chars failed: {failed_chars}")
        else:
            _debug_print(f"SUCCESS: All {len(text)} chars typed ({total_events} events)")


def typewrite_single_debug(char: str) -> dict:
    """
    Type a single character with detailed debug info.
    Returns dict with success status and debug details.
    """
    inputs = (INPUT * 2)()

    # Key down
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ki.wVk = 0
    inputs[0].ki.wScan = ord(char)
    inputs[0].ki.dwFlags = KEYEVENTF_UNICODE
    inputs[0].ki.time = 0
    inputs[0].ki.dwExtraInfo = None

    # Key up
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].ki.wVk = 0
    inputs[1].ki.wScan = ord(char)
    inputs[1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    inputs[1].ki.time = 0
    inputs[1].ki.dwExtraInfo = None

    # Debug: Print structure layout
    debug_info = {
        "char": char,
        "unicode": f"U+{ord(char):04X}",
        "input_size": ctypes.sizeof(INPUT),
        "keybdinput_size": ctypes.sizeof(KEYBDINPUT),
        "key_down": {
            "type": inputs[0].type,
            "wVk": inputs[0].ki.wVk,
            "wScan": inputs[0].ki.wScan,
            "dwFlags": hex(inputs[0].ki.dwFlags),
        },
        "key_up": {
            "type": inputs[1].type,
            "wVk": inputs[1].ki.wVk,
            "wScan": inputs[1].ki.wScan,
            "dwFlags": hex(inputs[1].ki.dwFlags),
        }
    }
    
    result = _user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
    error_code = ctypes.get_last_error()
    
    debug_info["result"] = result
    debug_info["expected"] = 2
    debug_info["success"] = result == 2
    debug_info["last_error"] = error_code
    
    return debug_info
