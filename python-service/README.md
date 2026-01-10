# Tasker Service v7.0 - Hybrid Mode (DOM + Vision)

## 🎯 Overview

Questa versione implementa l'approccio **Hybrid Mode** ispirato a Stagehand, che combina:
- **DOM-based actions**: Usa selettori CSS/XPath via Accessibility Tree
- **Vision-based actions**: Usa coordinate pixel via screenshot

Il modello **Gemini 3 Flash** decide autonomamente quale approccio usare per ogni azione.

## 📊 Confronto con Versioni Precedenti

| Aspetto | v6.0.7 (CUA) | v7.0 (Hybrid) |
|---------|--------------|---------------|
| Modello | Gemini 2.5 Computer Use | Gemini 3 Flash |
| Approccio | Solo Vision (coordinate) | DOM + Vision |
| Input | Screenshot | Screenshot + Accessibility Tree |
| Self-healing | No | Sì (DOM → Vision fallback) |
| Selettori | No | Sì (CSS, XPath, text) |

## 🔧 Installazione

```bash
# Dipendenze
pip install fastapi uvicorn playwright google-genai

# Installa browser
playwright install chromium
playwright install msedge
```

## 🚀 Avvio

```bash
python tasker_service_v7.py
```

Il servizio sarà disponibile su `http://localhost:8765`

## 📡 API Endpoints

### `GET /`
Health check e info sul servizio.

### `GET /status`
Stato dell'agente (attivo/inattivo).

### `POST /execute`
Esegue un task.

```json
{
  "api_key": "YOUR_GEMINI_API_KEY",
  "task_description": "Cerca 'browser automation' su Google",
  "initial_url": "https://google.com",
  "max_steps": 20,
  "headless": false,
  "mode": "hybrid"
}
```

### `POST /stop`
Ferma l'esecuzione corrente.

## 🧠 Come Funziona l'Hybrid Mode

### 1. Ad ogni step, il sistema:
1. Cattura screenshot della pagina
2. Estrae l'Accessibility Tree (struttura semantica)
3. Invia entrambi a Gemini 3 Flash
4. Il modello sceglie il tool appropriato

### 2. Tool Disponibili

**DOM-based (preferiti quando possibile):**
- `act(selector, instruction)` - Azione su selettore CSS/XPath

**Vision-based (quando DOM non è affidabile):**
- `click(x, y)` - Click su coordinate
- `type(text, x?, y?)` - Digita testo

**Control:**
- `scroll(delta_y)` - Scroll
- `navigate(url)` - Naviga a URL
- `wait(duration_ms)` - Attendi
- `done(summary)` - Task completato

### 3. Self-Healing Automatico

Se un'azione DOM fallisce (selettore non trovato), il sistema:
1. Prova selettori alternativi
2. Se specificato, usa le coordinate di fallback
3. Riporta quale metodo ha funzionato

```
[12:34:56.789] [WARN] DOM selector failed, falling back to coordinates (850, 420)
[12:34:57.123] [INFO] ✓ Action succeeded (fallback used)
```

## 📋 Esempio di Output

```json
{
  "success": true,
  "task": "Cerca 'AI automation' su Google",
  "total_steps": 5,
  "successful_steps": 5,
  "failed_steps": 0,
  "fallback_used": 1,
  "dom_actions": 3,
  "vision_actions": 2,
  "final_url": "https://google.com/search?q=AI+automation",
  "steps": [
    {"turn": 1, "action_type": "act", "success": true, "fallback": false},
    {"turn": 2, "action_type": "type", "success": true, "fallback": false},
    {"turn": 3, "action_type": "click", "success": true, "fallback": false},
    {"turn": 4, "action_type": "act", "success": true, "fallback": true},
    {"turn": 5, "action_type": "done", "success": true, "fallback": false}
  ]
}
```

## 🔐 Persistent Context

Il browser usa un profilo persistente per mantenere i login:

```
~/.hybrid-browser-profile/
```

### Setup Login (Prima Volta)
1. Avvia il servizio
2. Esegui un task con `headless: false`
3. Fai login manualmente nei siti che ti servono
4. Chiudi il browser
5. I prossimi task saranno già loggati

## ⚙️ Configurazione

### Modelli
```python
GEMINI_HYBRID_MODEL = "gemini-3-flash-preview"  # Per Hybrid Mode
GEMINI_CUA_MODEL = "gemini-2.5-computer-use-preview-10-2025"  # Per CUA puro
```

### Viewport
```python
VIEWPORT_WIDTH = 1288   # Ottimale per Computer Use
VIEWPORT_HEIGHT = 711
```

### Profile Directory
```python
HYBRID_PROFILE_DIR = Path.home() / ".hybrid-browser-profile"
```

## 🐛 Debug

I log mostrano chiaramente quale approccio viene usato:

```
[12:34:56.789] [DOM] Executing act with selector: button[type="submit"]
[12:34:57.123] [VISION] Clicking at (850, 420)
[12:34:57.456] [ACTION] TYPE: text='search query' at (640, 380)
```

## 📝 Note Importanti

1. **Gemini 3 Flash** è diverso da **Gemini 2.5 Computer Use**:
   - 3 Flash: Hybrid (DOM + Vision), usa tool custom
   - 2.5 CU: Solo Vision, usa tool `computer_use` built-in

2. **Browser**: Usa Microsoft Edge per evitare conflitti con Chrome

3. **Selettori supportati**:
   - CSS: `#id`, `.class`, `[attr="value"]`
   - XPath: `//button[@type="submit"]`
   - Text: `text="Click me"`

4. **Quando il modello sceglie Vision**:
   - Canvas/SVG
   - Shadow DOM
   - Elementi dinamici
   - Icone senza testo
   - Quando DOM fallisce

## 🔄 Migrazione da v6.0.7

Il nuovo sistema è retrocompatibile. Puoi usare:

```json
{
  "mode": "hybrid"  // Nuovo: DOM + Vision
}
```

oppure

```json
{
  "mode": "cua"  // Legacy: Solo Vision (richiede implementazione separata)
}
```

## 📚 Riferimenti

- [Stagehand Documentation](https://docs.stagehand.dev)
- [Gemini 3 Flash](https://ai.google.dev/gemini-api)
- [Playwright Accessibility](https://playwright.dev/docs/accessibility-testing)
