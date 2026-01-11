# Tool Server v8.0 - API Documentation for Web App Developer
## Architect's Hand - Desktop App "Hands Only" Server

---

# 📋 OVERVIEW

Il Tool Server è un'applicazione desktop che fornisce **solo capacità di esecuzione** ("le mani").
Tutta l'intelligenza (pianificazione, decisioni, self-healing) deve stare nella **Web App**.

**Base URL:** `http://127.0.0.1:8765`

**Architettura:**
```
WEB APP (Lovable)                              TOOL SERVER (Desktop)
─────────────────                              ────────────────────

1. Richiede screenshot         ──────────────► POST /screenshot
2. Riceve immagine            ◄──────────────  {image_base64}
3. Chiama Lux/Gemini API (cloud)
4. Riceve coordinate + azione
5. Esegue azione              ──────────────► POST /click, /type, etc.
6. Riceve risultato           ◄──────────────  {success, details}
```

---

# 🔧 ENDPOINTS

## Status & Info

### GET /
Root endpoint - verifica che il server sia attivo.

**Response:**
```json
{
  "service": "Architect's Hand Tool Server",
  "version": "8.0.0"
}
```

---

### GET /status
Stato del servizio e capabilities.

**Response:**
```json
{
  "status": "running",
  "version": "8.0.0",
  "browser_sessions": 1,
  "capabilities": {
    "pyautogui": true,
    "pyperclip": true,
    "playwright": true,
    "pil": true
  }
}
```

---

### GET /screen
Informazioni sullo schermo e fattori di scala.

**Response:**
```json
{
  "lux_sdk_reference": {"width": 1260, "height": 700},
  "viewport_reference": {"width": 1280, "height": 720},
  "screen": {"width": 1920, "height": 1080},
  "lux_scale": {"x": 1.524, "y": 1.543}
}
```

---

## Screenshot

### POST /screenshot
Cattura screenshot del browser (viewport) o desktop (schermo intero).

**Request:**
```json
{
  "scope": "browser" | "desktop",
  "session_id": "session-xxx",       // opzionale, se non specificato usa sessione attiva
  "optimize_for": "lux" | "gemini" | "both" | null
}
```

**Response:**
```json
{
  "success": true,
  "original": {
    "image_base64": "iVBORw0KGgo...",
    "width": 1280,
    "height": 720
  },
  "lux_optimized": {
    "image_base64": "iVBORw0KGgo...",
    "width": 1260,
    "height": 700,
    "original_width": 1280,
    "original_height": 720,
    "scale_x": 1.016,
    "scale_y": 1.029
  }
}
```

**Note:**
- `scope: "browser"` → cattura SOLO il viewport (contenuto pagina), NO toolbar/tabs
- `scope: "desktop"` → cattura SCHERMO INTERO (per automazione Excel, Outlook, etc.)
- `optimize_for: "lux"` → ridimensiona a 1260x700 (risoluzione SDK Lux)
- `optimize_for: "both"` → restituisce sia originale che ottimizzato
- `scale_x/scale_y` → usare per convertire coordinate Lux → coordinate reali

---

## Click

### POST /click
Esegue click alle coordinate specificate.

**Request:**
```json
{
  "scope": "browser" | "desktop",
  "x": 400,
  "y": 200,
  "coordinate_origin": "viewport" | "screen" | "lux_sdk",
  "click_type": "single" | "double" | "right",
  "session_id": "session-xxx"        // opzionale
}
```

**Response (successo):**
```json
{
  "success": true,
  "executed_with": "playwright",
  "details": {
    "scope": "browser",
    "click_type": "single",
    "viewport_coords": {"x": 406, "y": 206},
    "original_coords": {"x": 400, "y": 200},
    "coordinate_origin": "lux_sdk"
  }
}
```

**Response (errore - fuori viewport):**
```json
{
  "success": false,
  "error": "Coordinates (1500, 200) outside viewport bounds (1280x720)",
  "details": {
    "viewport": {"width": 1280, "height": 720},
    "requested": {"x": 1500, "y": 200}
  }
}
```

**Note:**
- `coordinate_origin: "lux_sdk"` → converte automaticamente da 1260x700 a dimensioni reali
- `coordinate_origin: "viewport"` → usa coordinate così come sono (per browser)
- `coordinate_origin: "screen"` → coordinate assolute schermo (per desktop)
- Browser usa Playwright, Desktop usa PyAutoGUI

---

## Type

### POST /type
Digita testo.

**Request:**
```json
{
  "scope": "browser" | "desktop",
  "text": "Testo da digitare con caratteri speciali: àèìòù",
  "method": "clipboard" | "keystrokes",
  "selector": "input.email",         // opzionale, solo browser - focus prima di digitare
  "session_id": "session-xxx"
}
```

**Response:**
```json
{
  "success": true,
  "executed_with": "playwright",
  "details": {
    "text_length": 42,
    "selector": "input.email"
  }
}
```

**Note:**
- `method: "clipboard"` → usa Ctrl+V (necessario per tastiera italiana e caratteri speciali)
- `method: "keystrokes"` → digita carattere per carattere (solo ASCII)
- `selector` → se specificato, clicca prima sull'elemento per dargli focus

---

## Scroll

### POST /scroll
Scrolla nella direzione specificata.

**Request:**
```json
{
  "scope": "browser" | "desktop",
  "direction": "up" | "down" | "left" | "right",
  "amount": 300,                     // pixel
  "session_id": "session-xxx"
}
```

**Response:**
```json
{
  "success": true,
  "executed_with": "playwright",
  "details": {
    "direction": "down",
    "amount": 300
  }
}
```

---

## Keypress

### POST /keypress
Preme un tasto o combinazione di tasti.

**Request:**
```json
{
  "scope": "browser" | "desktop",
  "key": "Enter",                    // oppure "Ctrl+C", "Alt+Tab", "Escape"
  "session_id": "session-xxx"
}
```

**Response:**
```json
{
  "success": true,
  "executed_with": "playwright",
  "details": {
    "key": "Ctrl+C"
  }
}
```

**Tasti supportati:**
- Singoli: `Enter`, `Escape`, `Tab`, `Backspace`, `Delete`, `ArrowUp`, `ArrowDown`, etc.
- Combinazioni: `Ctrl+C`, `Ctrl+V`, `Ctrl+A`, `Alt+Tab`, `Ctrl+Shift+T`, etc.

---

## Browser Session Management

### POST /browser/start
Avvia una nuova sessione browser (Edge con profilo persistente).

**Request:**
```json
{
  "start_url": "https://gmail.com",  // opzionale
  "headless": false
}
```

**Response:**
```json
{
  "success": true,
  "session_id": "session-20260112-143052",
  "current_url": "https://gmail.com"
}
```

**Note:**
- Usa Microsoft Edge con profilo persistente (`~/.edge-automation-profile`)
- I login rimangono salvati tra le sessioni
- Viewport fisso: 1280x720

---

### POST /browser/stop
Chiude una sessione browser.

**Query params:** `?session_id=session-xxx`

**Response:**
```json
{
  "success": true,
  "session_id": "session-xxx"
}
```

---

### GET /browser/status
Stato delle sessioni browser.

**Query params:** `?session_id=session-xxx` (opzionale, se omesso ritorna tutte)

**Response (singola sessione):**
```json
{
  "session_id": "session-xxx",
  "is_alive": true,
  "current_url": "https://gmail.com",
  "tabs_count": 2
}
```

**Response (tutte le sessioni):**
```json
{
  "sessions": [
    {
      "session_id": "session-xxx",
      "is_alive": true,
      "current_url": "https://gmail.com"
    }
  ]
}
```

---

## Browser Navigation (API-based, NO coordinate)

Queste azioni usano le API Playwright direttamente, non richiedono Vision.

### POST /browser/navigate
Naviga a un URL.

**Request:**
```json
{
  "session_id": "session-xxx",
  "url": "https://outlook.com"
}
```

**Response:**
```json
{
  "success": true,
  "url": "https://outlook.com/mail/inbox"
}
```

---

### POST /browser/reload
Ricarica la pagina corrente.

**Query params:** `?session_id=session-xxx`

**Response:**
```json
{
  "success": true,
  "url": "https://gmail.com/mail/inbox"
}
```

---

### POST /browser/back
Torna indietro nella cronologia.

**Query params:** `?session_id=session-xxx`

**Response:**
```json
{
  "success": true,
  "url": "https://gmail.com"
}
```

---

### POST /browser/forward
Vai avanti nella cronologia.

**Query params:** `?session_id=session-xxx`

**Response:**
```json
{
  "success": true,
  "url": "https://gmail.com/mail/inbox"
}
```

---

## Browser Tabs

### GET /browser/tabs
Lista tutte le tab aperte.

**Query params:** `?session_id=session-xxx`

**Response:**
```json
{
  "success": true,
  "tabs": [
    {"id": 0, "url": "https://gmail.com", "title": "", "is_current": true},
    {"id": 1, "url": "https://outlook.com", "title": "", "is_current": false}
  ]
}
```

---

### POST /browser/tab/new
Apre una nuova tab.

**Request:**
```json
{
  "session_id": "session-xxx",
  "url": "https://calendar.google.com"  // opzionale
}
```

**Response:**
```json
{
  "success": true,
  "tab_id": 2,
  "url": "https://calendar.google.com"
}
```

---

### POST /browser/tab/close
Chiude una tab.

**Request:**
```json
{
  "session_id": "session-xxx",
  "tab_id": 1                        // opzionale, default = tab corrente
}
```

**Response:**
```json
{
  "success": true,
  "remaining_tabs": 1
}
```

---

### POST /browser/tab/switch
Cambia tab attiva.

**Request:**
```json
{
  "session_id": "session-xxx",
  "tab_id": 0
}
```

**Response:**
```json
{
  "success": true,
  "tab_id": 0,
  "url": "https://gmail.com"
}
```

---

## Browser DOM

### GET /browser/dom/tree
Ottiene l'Accessibility Tree della pagina (per analisi DOM).

**Query params:** `?session_id=session-xxx`

**Response:**
```json
{
  "success": true,
  "tree": "[WebArea] \"Gmail\"\n  [navigation] \"Main\"\n    [link] \"Inbox\"\n    [link] \"Sent\"\n  [main]\n    [list] \"Email list\"\n      [listitem] \"Meeting tomorrow - John\"\n      [listitem] \"Project update - Sarah\""
}
```

**Note:**
- L'Accessibility Tree è una rappresentazione strutturata della pagina
- Utile per capire la struttura senza dover analizzare l'immagine
- Può essere usato dall'Agent per pianificare azioni

---

### GET /browser/current_url
Ottiene l'URL corrente.

**Query params:** `?session_id=session-xxx`

**Response:**
```json
{
  "success": true,
  "url": "https://gmail.com/mail/inbox"
}
```

---

## Coordinate Utilities

### POST /coordinates/convert
Converte coordinate tra diversi spazi.

**Request:**
```json
{
  "x": 400,
  "y": 200,
  "from_space": "lux_sdk",
  "to_space": "viewport",
  "session_id": "session-xxx"        // opzionale, per dimensioni viewport reali
}
```

**Response:**
```json
{
  "success": true,
  "x": 406,
  "y": 206,
  "from_space": "lux_sdk",
  "to_space": "viewport",
  "reference_dimensions": {"width": 1280, "height": 720}
}
```

**Spazi supportati:**
- `lux_sdk` → coordinate Lux (1260x700)
- `viewport` → coordinate viewport browser
- `screen` → coordinate assolute schermo

---

### POST /coordinates/validate
Verifica se le coordinate puntano a un elemento cliccabile.

**Request:**
```json
{
  "scope": "browser",
  "x": 400,
  "y": 200,
  "coordinate_origin": "lux_sdk",
  "session_id": "session-xxx"
}
```

**Response (browser):**
```json
{
  "success": true,
  "valid": true,
  "in_viewport": true,
  "viewport_coords": {"x": 406, "y": 206},
  "original_coords": {"x": 400, "y": 200},
  "element_info": {
    "found": true,
    "tag": "button",
    "id": "compose-btn",
    "className": "compose-button primary",
    "text": "Compose",
    "clickable": true,
    "rect": {"x": 380, "y": 180, "width": 100, "height": 40}
  },
  "viewport_bounds": {"x": 0, "y": 80, "width": 1280, "height": 720, "chrome_height": 80}
}
```

**Response (desktop):**
```json
{
  "success": true,
  "valid": true,
  "in_screen": true,
  "screen_coords": {"x": 610, "y": 309},
  "original_coords": {"x": 400, "y": 200},
  "pixel_color": [66, 133, 244],
  "screen_bounds": {"width": 1920, "height": 1080}
}
```

**Note:**
- Per browser: restituisce info sull'elemento DOM a quelle coordinate
- Per desktop: restituisce il colore del pixel
- Utile per validare coordinate prima di cliccare

---

# 🧠 LOGICHE DA IMPLEMENTARE NELLA WEB APP

Queste logiche erano nel `tasker_service_v7.py` e devono essere implementate nella Web App.

## 1. Loop Detection

Rileva quando l'automazione sta ripetendo la stessa azione senza successo.

```javascript
// Pseudo-codice per Web App

class LoopDetector {
  constructor() {
    this.actionHistory = [];
  }
  
  addAction(action) {
    this.actionHistory.push({
      action: action.type,
      x: action.x,
      y: action.y,
      selector: action.selector,
      timestamp: Date.now()
    });
    
    // Mantieni solo ultime 10 azioni
    if (this.actionHistory.length > 10) {
      this.actionHistory.shift();
    }
  }
  
  detectLoop() {
    if (this.actionHistory.length < 3) return false;
    
    const last3 = this.actionHistory.slice(-3);
    const actionTypes = last3.map(a => a.action);
    
    // Stesso tipo di azione 3+ volte
    if (new Set(actionTypes).size === 1) {
      // Verifica se coordinate simili (entro 50px)
      if (actionTypes[0] === 'click') {
        const coords = last3.map(a => ({x: a.x, y: a.y}));
        const xRange = Math.max(...coords.map(c => c.x)) - Math.min(...coords.map(c => c.x));
        const yRange = Math.max(...coords.map(c => c.y)) - Math.min(...coords.map(c => c.y));
        
        if (xRange < 50 && yRange < 50) {
          return true; // LOOP RILEVATO
        }
      }
    }
    
    return false;
  }
  
  getSuggestedWorkaround() {
    // Se loop rilevato, suggerisci alternative
    return [
      "Prova double_click invece di single click",
      "Prova a scrollare per rendere visibile l'elemento",
      "Verifica se l'elemento è dentro un iframe",
      "Prova ad usare un selettore diverso"
    ];
  }
}
```

---

## 2. Self-Healing Bidirezionale

Quando un'azione fallisce, prova strategia alternativa.

```javascript
// Pseudo-codice per Web App

async function executeWithSelfHealing(action, toolServerUrl) {
  // TENTATIVO 1: Strategia primaria
  let result = await fetch(`${toolServerUrl}/click`, {
    method: 'POST',
    body: JSON.stringify({
      scope: 'browser',
      x: action.x,
      y: action.y,
      coordinate_origin: action.coordinate_origin
    })
  }).then(r => r.json());
  
  if (result.success) return result;
  
  // TENTATIVO 2: Valida coordinate e trova elemento
  const validation = await fetch(`${toolServerUrl}/coordinates/validate`, {
    method: 'POST',
    body: JSON.stringify({
      scope: 'browser',
      x: action.x,
      y: action.y,
      coordinate_origin: action.coordinate_origin
    })
  }).then(r => r.json());
  
  if (validation.element_info?.found) {
    // Usa coordinate centro dell'elemento trovato
    const rect = validation.element_info.rect;
    const centerX = rect.x + rect.width / 2;
    const centerY = rect.y + rect.height / 2;
    
    result = await fetch(`${toolServerUrl}/click`, {
      method: 'POST',
      body: JSON.stringify({
        scope: 'browser',
        x: centerX,
        y: centerY,
        coordinate_origin: 'viewport'
      })
    }).then(r => r.json());
    
    if (result.success) {
      result.healed = true;
      result.healingMethod = 'dom_element_center';
      return result;
    }
  }
  
  // TENTATIVO 3: Double click
  result = await fetch(`${toolServerUrl}/click`, {
    method: 'POST',
    body: JSON.stringify({
      scope: 'browser',
      x: action.x,
      y: action.y,
      coordinate_origin: action.coordinate_origin,
      click_type: 'double'
    })
  }).then(r => r.json());
  
  if (result.success) {
    result.healed = true;
    result.healingMethod = 'double_click';
    return result;
  }
  
  // Tutti i tentativi falliti
  return {
    success: false,
    error: 'All healing attempts failed',
    attempts: ['single_click', 'dom_element_center', 'double_click']
  };
}
```

---

## 3. Strategia Provider Vision (Lux vs Gemini)

Logica per scegliere quando usare Lux e quando Gemini.

```javascript
// Pseudo-codice per Web App

function chooseVisionProvider(task, context) {
  // REGOLA 1: Desktop = sempre Lux
  if (context.scope === 'desktop') {
    return 'lux';
  }
  
  // REGOLA 2: UI custom/artistica = Gemini (migliore reasoning)
  if (task.uiType === 'custom' || task.uiType === 'artistic') {
    return 'gemini';
  }
  
  // REGOLA 3: Icone standard Windows/Office = Lux (addestrato su questi)
  if (context.app === 'excel' || context.app === 'outlook' || context.app === 'windows') {
    return 'lux';
  }
  
  // REGOLA 4: Form e testo piccolo = confronta entrambi
  if (task.hasSmallText || task.hasComplexForm) {
    return 'both'; // Chiedi a entrambi e confronta
  }
  
  // DEFAULT: Gemini per browser (più stabile per web)
  return 'gemini';
}

async function getCoordinatesWithFallback(screenshot, task, toolServerUrl) {
  const provider = chooseVisionProvider(task, task.context);
  
  if (provider === 'both') {
    // Chiedi a entrambi
    const [luxResult, geminiResult] = await Promise.all([
      callLuxAPI(screenshot, task),
      callGeminiAPI(screenshot, task)
    ]);
    
    // Confronta risultati
    const distance = Math.sqrt(
      Math.pow(luxResult.x - geminiResult.x, 2) +
      Math.pow(luxResult.y - geminiResult.y, 2)
    );
    
    if (distance < 30) {
      // Concordano - alta confidenza
      return {
        ...luxResult,
        confidence: 'high',
        agreedBy: ['lux', 'gemini']
      };
    } else {
      // Discordano - chiedi all'Agent B un workaround
      return {
        conflict: true,
        luxResult,
        geminiResult,
        needsAgentB: true
      };
    }
  }
  
  // Provider singolo
  try {
    if (provider === 'lux') {
      return await callLuxAPI(screenshot, task);
    } else {
      return await callGeminiAPI(screenshot, task);
    }
  } catch (error) {
    // Fallback all'altro provider
    console.log(`${provider} failed, trying fallback...`);
    if (provider === 'lux') {
      return await callGeminiAPI(screenshot, task);
    } else {
      return await callLuxAPI(screenshot, task);
    }
  }
}
```

---

## 4. Rilevamento Comportamento Browser dalla Task Description

Analizza la descrizione del task per capire se aprire nuova tab, etc.

```javascript
// Pseudo-codice per Web App

function detectBrowserBehavior(taskDescription) {
  const taskLower = taskDescription.toLowerCase();
  
  const NEW_TAB_PATTERNS = [
    'nuova pagina', 'nuova tab', 'nuovo tab', 'nuova scheda',
    'apri una nuova', 'in una nuova', 'apri nuova',
    'new tab', 'new page', 'open new', 'in a new',
    'altra pagina', 'altra tab', 'altra scheda'
  ];
  
  const CLOSE_PATTERNS = [
    'chiudi e apri', 'riavvia browser', 'nuovo browser',
    'close and open', 'restart browser', 'fresh browser',
    'ricomincia', 'da zero', 'from scratch'
  ];
  
  const SAME_PAGE_PATTERNS = [
    'stessa pagina', 'questa pagina', 'pagina corrente',
    'same page', 'current page', 'this page',
    'continua', 'prosegui', 'vai avanti'
  ];
  
  let result = { newTab: false, closeCurrent: false };
  
  for (const pattern of NEW_TAB_PATTERNS) {
    if (taskLower.includes(pattern)) {
      result.newTab = true;
      break;
    }
  }
  
  for (const pattern of CLOSE_PATTERNS) {
    if (taskLower.includes(pattern)) {
      result.closeCurrent = true;
      break;
    }
  }
  
  for (const pattern of SAME_PAGE_PATTERNS) {
    if (taskLower.includes(pattern)) {
      result.newTab = false;
      result.closeCurrent = false;
      break;
    }
  }
  
  return result;
}
```

---

## 5. Azioni Deterministiche vs Vision

Distingui quando usare API dirette vs coordinate da Vision.

```javascript
// Pseudo-codice per Web App

function categorizeAction(action) {
  // AZIONI DETERMINISTICHE (usa API, no Vision necessaria)
  const DETERMINISTIC_ACTIONS = {
    'navigate': '/browser/navigate',
    'go_to_url': '/browser/navigate',
    'refresh': '/browser/reload',
    'reload': '/browser/reload',
    'back': '/browser/back',
    'go_back': '/browser/back',
    'forward': '/browser/forward',
    'go_forward': '/browser/forward',
    'new_tab': '/browser/tab/new',
    'open_tab': '/browser/tab/new',
    'close_tab': '/browser/tab/close',
    'switch_tab': '/browser/tab/switch'
  };
  
  // Controlla se è un'azione deterministica
  for (const [keyword, endpoint] of Object.entries(DETERMINISTIC_ACTIONS)) {
    if (action.type.toLowerCase().includes(keyword)) {
      return {
        type: 'deterministic',
        endpoint: endpoint,
        needsVision: false
      };
    }
  }
  
  // AZIONI CHE RICHIEDONO VISION (coordinate)
  return {
    type: 'vision_required',
    needsVision: true,
    possibleEndpoints: ['/click', '/type', '/scroll']
  };
}

async function executeAction(action, toolServerUrl, visionProvider) {
  const category = categorizeAction(action);
  
  if (category.type === 'deterministic') {
    // Esegui direttamente senza Vision
    return await fetch(`${toolServerUrl}${category.endpoint}`, {
      method: 'POST',
      body: JSON.stringify(action.params)
    }).then(r => r.json());
  }
  
  // Richiedi screenshot e coordinate da Vision
  const screenshot = await fetch(`${toolServerUrl}/screenshot`, {
    method: 'POST',
    body: JSON.stringify({ scope: 'browser', optimize_for: visionProvider })
  }).then(r => r.json());
  
  const coordinates = await callVisionAPI(visionProvider, screenshot, action);
  
  return await fetch(`${toolServerUrl}/click`, {
    method: 'POST',
    body: JSON.stringify({
      scope: 'browser',
      x: coordinates.x,
      y: coordinates.y,
      coordinate_origin: 'lux_sdk'
    })
  }).then(r => r.json());
}
```

---

## 6. Gestione Errori e Retry

```javascript
// Pseudo-codice per Web App

async function executeWithRetry(action, toolServerUrl, maxRetries = 3) {
  let lastError = null;
  
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const result = await executeAction(action, toolServerUrl);
      
      if (result.success) {
        return result;
      }
      
      lastError = result.error;
      
      // Analizza errore per decidere se ritentare
      if (result.error.includes('outside viewport')) {
        // Coordinate fuori - non ritentare, richiedi nuovo screenshot
        console.log('Coordinates outside viewport, need fresh screenshot');
        break;
      }
      
      if (result.error.includes('Session not found')) {
        // Browser chiuso - riavvia
        await fetch(`${toolServerUrl}/browser/start`, { method: 'POST' });
        continue;
      }
      
      // Attendi prima di ritentare
      await sleep(500 * attempt);
      
    } catch (error) {
      lastError = error.message;
      await sleep(1000);
    }
  }
  
  return {
    success: false,
    error: `Failed after ${maxRetries} attempts: ${lastError}`
  };
}
```

---

# 📊 QUICK REFERENCE

## Endpoint per Scope

| Scope | Screenshot | Click | Type | Navigation |
|-------|------------|-------|------|------------|
| **browser** | viewport only | Playwright | Playwright | API (/navigate, /reload, etc.) |
| **desktop** | full screen | PyAutoGUI | PyAutoGUI (clipboard) | N/A |

## Coordinate Origins

| Origin | Usare quando | Conversione |
|--------|--------------|-------------|
| `viewport` | Coordinate già relative al viewport | Nessuna |
| `lux_sdk` | Coordinate da Lux API (1260x700) | Automatica |
| `screen` | Coordinate assolute schermo | Sottrae offset |

## Flusso Tipico

1. `POST /browser/start` → avvia browser
2. `POST /browser/navigate` → vai a URL
3. `POST /screenshot` → cattura schermo
4. **Chiama Lux/Gemini API** (nella Web App)
5. `POST /click` o `/type` → esegui azione
6. Ripeti 3-5 fino a task completato

---

# 🔗 ESEMPI COMPLETI

## Esempio: Forward Email

```javascript
async function forwardEmail(toolServerUrl, luxApiKey, recipientEmail) {
  // 1. Avvia browser
  const session = await fetch(`${toolServerUrl}/browser/start`, {
    method: 'POST',
    body: JSON.stringify({ start_url: 'https://webmail.register.it' })
  }).then(r => r.json());
  
  // 2. Screenshot per Lux
  const screenshot = await fetch(`${toolServerUrl}/screenshot`, {
    method: 'POST',
    body: JSON.stringify({ scope: 'browser', optimize_for: 'lux' })
  }).then(r => r.json());
  
  // 3. Chiedi a Lux dove cliccare per aprire prima email
  const luxResponse = await fetch('https://api.agiopen.org/v1/act', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${luxApiKey}` },
    body: JSON.stringify({
      image: screenshot.lux_optimized.image_base64,
      task: 'Click on the first unread email in the inbox'
    })
  }).then(r => r.json());
  
  // 4. Clicca
  await fetch(`${toolServerUrl}/click`, {
    method: 'POST',
    body: JSON.stringify({
      scope: 'browser',
      x: luxResponse.x,
      y: luxResponse.y,
      coordinate_origin: 'lux_sdk'
    })
  });
  
  // 5. Attendi caricamento, nuovo screenshot
  await sleep(1000);
  
  // ... continua con forward ...
}
```
