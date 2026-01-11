# Tool Server v8.0 - API Quick Reference
## Cheat Sheet per Sviluppatore Web App

**Base URL:** `http://127.0.0.1:8765`

---

## 📸 Screenshot

```
POST /screenshot
{
  "scope": "browser" | "desktop",
  "optimize_for": "lux" | "gemini" | "both"
}
→ {success, original: {image_base64, width, height}, lux_optimized: {..., scale_x, scale_y}}
```

---

## 🖱️ Click

```
POST /click
{
  "scope": "browser" | "desktop",
  "x": 400,
  "y": 200,
  "coordinate_origin": "viewport" | "lux_sdk" | "screen",
  "click_type": "single" | "double" | "right"
}
→ {success, executed_with, details: {viewport_coords, original_coords}}
```

---

## ⌨️ Type

```
POST /type
{
  "scope": "browser" | "desktop",
  "text": "Hello world àèìòù",
  "method": "clipboard" | "keystrokes",
  "selector": "input.email"  // optional, browser only
}
→ {success, executed_with, details: {text_length}}
```

---

## 📜 Scroll

```
POST /scroll
{
  "scope": "browser" | "desktop",
  "direction": "up" | "down" | "left" | "right",
  "amount": 300
}
→ {success, details: {direction, amount}}
```

---

## ⌨️ Keypress

```
POST /keypress
{
  "scope": "browser" | "desktop",
  "key": "Enter" | "Ctrl+C" | "Alt+Tab"
}
→ {success, details: {key}}
```

---

## 🌐 Browser Session

```
POST /browser/start
{"start_url": "https://...", "headless": false}
→ {success, session_id, current_url}

POST /browser/stop?session_id=xxx
→ {success}

GET /browser/status?session_id=xxx
→ {session_id, is_alive, current_url, tabs_count}
```

---

## 🧭 Browser Navigation (API, no coordinate)

```
POST /browser/navigate
{"session_id": "xxx", "url": "https://..."}
→ {success, url}

POST /browser/reload?session_id=xxx
→ {success, url}

POST /browser/back?session_id=xxx
→ {success, url}

POST /browser/forward?session_id=xxx
→ {success, url}
```

---

## 📑 Browser Tabs

```
GET /browser/tabs?session_id=xxx
→ {tabs: [{id, url, is_current}]}

POST /browser/tab/new
{"session_id": "xxx", "url": "https://..."}
→ {success, tab_id, url}

POST /browser/tab/close
{"session_id": "xxx", "tab_id": 1}
→ {success, remaining_tabs}

POST /browser/tab/switch
{"session_id": "xxx", "tab_id": 0}
→ {success, tab_id, url}
```

---

## 🌳 Browser DOM

```
GET /browser/dom/tree?session_id=xxx
→ {success, tree: "[WebArea]...[link] Inbox..."}

GET /browser/current_url?session_id=xxx
→ {success, url}
```

---

## 📐 Coordinate Utilities

```
POST /coordinates/convert
{
  "x": 400, "y": 200,
  "from_space": "lux_sdk",
  "to_space": "viewport"
}
→ {success, x, y, reference_dimensions}

POST /coordinates/validate
{
  "scope": "browser",
  "x": 400, "y": 200,
  "coordinate_origin": "lux_sdk"
}
→ {success, valid, in_viewport, element_info: {tag, id, text, clickable}}
```

---

## 📊 Status

```
GET /status
→ {status, version, browser_sessions, capabilities: {pyautogui, playwright, ...}}

GET /screen
→ {lux_sdk_reference, viewport_reference, screen, lux_scale}
```

---

## 🔄 Flusso Tipico

```
1. POST /browser/start           → avvia browser
2. POST /browser/navigate        → vai a URL
3. POST /screenshot              → cattura viewport
4. [Web App chiama Lux/Gemini]   → riceve coordinate
5. POST /click                   → esegui click
6. Ripeti 3-5
```

---

## ⚠️ Note Importanti

- **Browser scope**: coordinate relative al viewport (0,0 = angolo contenuto pagina)
- **Desktop scope**: coordinate schermo intero (0,0 = angolo schermo)
- **lux_sdk**: coordinate 1260x700, convertite automaticamente
- **Azioni chrome** (refresh, back, tabs): usa API, NON coordinate
- **Tastiera italiana**: usa `method: "clipboard"` per caratteri speciali
