# Architect's Hand - Tasker Service v7.1.2

## Multi-Provider Computer Use (Lux + Gemini)

Servizio unificato che supporta **5 modalità** di automazione:

| Mode | Provider | Modello | Controllo |
|------|----------|---------|-----------|
| `actor` | Lux | lux-actor-1 | Il tuo PC (PyAutoGUI) |
| `thinker` | Lux | lux-thinker-1 | Il tuo PC (PyAutoGUI) |
| `tasker` | Lux | lux-actor-1 + todos | Il tuo PC (PyAutoGUI) |
| `gemini_cua` | Gemini | **gemini-2.5-computer-use-preview-10-2025** | Browser Edge |
| `gemini_hybrid` | Gemini | **gemini-3-flash-preview** | Browser Edge |

## Installazione

```bash
# 1. Dipendenze Python
pip install fastapi uvicorn pydantic pyautogui pyperclip pillow

# 2. Provider Lux (OAGI)
pip install oagi

# 3. Provider Gemini
pip install google-genai playwright
playwright install msedge

# 4. Configura API keys
export OAGI_API_KEY="your-openagi-key"
export GEMINI_API_KEY="your-gemini-key"
```

## Avvio

```bash
python tasker_service_v7.py
```

## API Endpoints

### POST /execute

**Lux Actor:**
```json
{
  "task_description": "Apri Chrome e cerca Anthropic",
  "mode": "actor",
  "max_steps": 20
}
```

**Lux Tasker (con todos):**
```json
{
  "mode": "tasker",
  "task_description": "Gestisci email",
  "todos": ["Apri Gmail", "Trova email da Mario", "Inoltra a Luigi"],
  "max_steps_per_todo": 15
}
```

**Gemini Hybrid:**
```json
{
  "task_description": "Cerca voli Roma-Milano",
  "start_url": "https://google.com/flights",
  "mode": "gemini_hybrid",
  "max_steps": 25
}
```

## Differenze tra Modalità

### Lux: Actor vs Thinker vs Tasker
- **actor**: lux-actor-1, veloce, task semplici
- **thinker**: lux-thinker-1, più lento, task complessi/ambigui
- **tasker**: TaskerAgent con lista todos strutturata

### Gemini: CUA vs Hybrid
- **gemini_cua**: Gemini 2.5 Computer Use, solo Vision (coordinate)
- **gemini_hybrid**: Gemini 3 Flash, DOM + Vision con scelta automatica

## Self-Healing Bidirezionale (v7.1.0)

```
┌─────────────────────────────────────────────────────────────────┐
│                SELF-HEALING BIDIREZIONALE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  DOM fallisce?                                                  │
│  ────────────                                                   │
│  1. page.click(selector) ❌                                     │
│  2. → query_selector → bounding_box → mouse.click(x,y) ✅      │
│                                                                 │
│  VISION fallisce?                                               │
│  ───────────────                                                │
│  1. mouse.click(x, y) ❌                                        │
│  2. → elementFromPoint(x,y) → trova elemento reale             │
│  3. → click su coordinate corrette ✅                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **Screenshot resize** per Lux (1920x1200)
- **Clipboard typing** per tastiere non-US (italiana)
- **Profili persistenti** per login salvati in Edge
- **Self-healing bidirezionale** in hybrid mode
- **Observer reports HTML** in tasker mode

## Changelog

### v7.1.2
- ✅ Fix SDK: `google-genai` invece di `google-generativeai`

### v7.1.1
- ✅ Fix import: `oagi` invece di `openagi`

### v7.1.0
- ✅ Modelli aggiornati: Gemini 3 Flash + Gemini 2.5 Computer Use
- ✅ Self-healing bidirezionale (DOM↔Vision)
- ✅ Log dettagliati per fallback

### v7.0.0
- Unificazione Lux + Gemini
- Hybrid mode (DOM + Vision)
