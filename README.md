# Architect's Hand - Local Bridge

Desktop application that bridges your cloud-based AI agents (running on Lovable/Supabase) with local browser automation using Lux + Playwright.

---

## 🇮🇹 ISTRUZIONI RAPIDE (per Fede)

### Come Ottenere il File .exe

**Passo 1: Crea Repository GitHub**
1. Vai su https://github.com/new
2. Nome: `architects-hand-bridge`
3. Lascia "Public" selezionato
4. Clicca "Create repository"

**Passo 2: Carica i File**
1. Nella pagina del nuovo repo, clicca il link "uploading an existing file"
2. Trascina TUTTA questa cartella (tutti i file e sottocartelle)
3. Scrivi un messaggio tipo "Initial upload"
4. Clicca "Commit changes"

**Passo 3: Aspetta la Compilazione (5-10 min)**
1. Clicca sulla tab "Actions" in alto
2. Vedrai "Build Windows App" con un pallino giallo 🟡
3. Aspetta che diventi verde ✅

**Passo 4: Scarica l'App**
1. Clicca sul workflow verde completato
2. Scorri in basso fino a "Artifacts"
3. Clicca "architects-hand-bridge-windows"
4. Si scarica un .zip → estrailo
5. Dentro c'è il .exe → installalo!

---

## Features

- 🔗 **Real-time connection** to Supabase for receiving tasks and steps
- 🤖 **Lux integration** for intelligent browser automation
- 🌐 **Playwright browser** control with visual feedback
- 📁 **Local file access** for uploads and downloads
- 📸 **Screenshot capture** for verification
- 📊 **Live dashboard** showing tasks, steps, and logs

## Installation

### Option 1: Download from GitHub Actions (Recommended)

1. Go to the "Actions" tab in this repository
2. Click on the latest successful "Build Windows App" workflow
3. Download the artifact "architects-hand-bridge-windows"
4. Extract the zip and run the installer

### Option 2: Build from Source

```bash
npm install
npx playwright install chromium
npm run build
```

## Configuration

On first launch, go to **Settings** and configure:

1. **Supabase URL**: Your Supabase project URL
2. **Supabase Service Role Key**: Found in Supabase Dashboard → Settings → API
3. **OpenAGI (Lux) API Key**: Your Lux API key from developer.agiopen.org
4. **Output Folder**: Where to save downloaded files

⚠️ **Security Note**: All API keys are stored locally on your PC in encrypted config. They are never sent anywhere except to their respective APIs.

## How It Works

```
Cloud (Lovable/Supabase)                    Local (This App)
┌────────────────────────┐                  ┌────────────────────────┐
│                        │                  │                        │
│  Architetto Agent      │                  │  Bridge App            │
│        ↓               │                  │        ↓               │
│  Interface Expert      │   Supabase       │  Lux API               │
│        ↓               │   Realtime       │        ↓               │
│  browser_steps table ──┼──────────────────┼→ Playwright Browser    │
│        ↑               │                  │        ↓               │
│  Results + Screenshots ←┼──────────────────┼─ Execute Actions       │
│                        │                  │                        │
└────────────────────────┘                  └────────────────────────┘
```

1. Your Interface Expert creates steps in `browser_steps` table
2. This app receives steps via Supabase Realtime
3. App sends screenshot + instruction to Lux API
4. Lux returns actions (click, type, scroll, etc.)
5. App executes actions using Playwright
6. App captures screenshot and updates step status
7. Interface Expert verifies completion and sends next step

## Database Tables Required

The app expects two tables in your Supabase:

- `browser_tasks` - Main task records
- `browser_steps` - Individual steps for each task

See the Lovable prompt in the project documentation for the complete schema.

## Troubleshooting

### "Connection failed"
- Check your Supabase URL and Service Role Key
- Ensure your IP isn't blocked by Supabase

### "Lux API error"
- Verify your OpenAGI API key is valid
- Check your API usage limits

### Browser doesn't open
- The app uses Chromium via Playwright
- On first run, it may take time to download the browser

### Steps not being received
- Ensure Realtime is enabled on your Supabase tables
- Check that RLS policies allow the service role to read

## License

MIT

## Support

For issues with:
- **This app**: Open a GitHub issue
- **Lux API**: Contact OpenAGI support
- **Supabase**: Check Supabase documentation
