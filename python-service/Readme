# 🤖 Tasker Service v5.0

FastAPI service that bridges the Lovable web app with local LUX execution using the **official OAGI SDK**.

## 📦 Files

| File | Description |
|------|-------------|
| `tasker_service.py` | Main service using official OAGI SDK patterns |
| `lux_analyzer.py` | Coordinate analysis & debugging system |
| `lux_analyzer_integration.py` | Integration helper for analyzer |
| `test_lux_analyzer.py` | Demo & diagnostic tools |
| `find_real_coordinates.py` | Playwright-based DOM coordinate finder |
| `_windows.py` | Windows Unicode input handler |
| `requirements.txt` | Python dependencies |

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run service
python tasker_service.py

# Service runs on http://127.0.0.1:8765
# API docs at http://127.0.0.1:8765/docs
```

## 🔧 Architecture

### v5.0 Changes (Official SDK Pattern)

**Before (v4.x):** Custom implementation
```python
# 300+ lines of custom code
for step in range(max_steps):
    screenshot = take_screenshot_bytes()  # Custom
    step_result = actor.step(screenshot)
    for action in step_result.actions:
        execute_action(action)  # 200 lines custom
```

**After (v5.0):** Official SDK
```python
# 10 lines using SDK
agent = AsyncDefaultAgent(max_steps=20)
completed = await agent.execute(
    instruction="Search hotels in Bergamo",
    action_handler=AsyncPyautoguiActionHandler(),
    image_provider=AsyncScreenshotMaker(),
)
```

## 📡 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Service status and availability |
| `/health` | GET | Health check with detailed info |
| `/execute` | POST | Execute task (main endpoint) |
| `/execute_step` | POST | Single step execution (debug) |
| `/stop` | POST | Stop current task |
| `/analysis/sessions` | GET | List analysis sessions |
| `/analysis/latest` | GET | Get latest analysis report |

### Execute Request Example

```json
{
    "api_key": "your-oagi-api-key",
    "task_description": "Search for hotels in Bergamo on booking.com",
    "mode": "actor",
    "model": "lux-actor-1",
    "max_steps": 20,
    "start_url": "https://www.booking.com",
    "enable_analysis": true
}
```

## 🔍 LUX Analyzer

Integrated debugging system for coordinate issues.

### Features
- Captures every LUX action with screenshots
- Visual markers showing click coordinates
- HTML report with timeline
- CSV export for analysis
- Coordinate heatmap

### Quick Test
```bash
# Run demo (no LUX required)
python test_lux_analyzer.py
# Choose option 1

# Live mouse tracking
python test_lux_analyzer.py
# Choose option 2

# Compare LUX vs real coordinates
python test_lux_analyzer.py
# Choose option 3
```

### Output
After execution, find in `lux_analysis/<session>/`:
```
├── report.html          # Interactive report
├── actions.csv          # Excel-compatible data
├── actions.json         # Full JSON data
└── screenshots/
    ├── step_001_before.png
    ├── step_001_markers.png  # With visual markers
    ├── step_001_after.png
    └── ...
```

## 🎯 Coordinate Debugging

If LUX clicks in wrong positions:

### 1. Check Screen Resolution
```
Your screen: 1920x1200
LUX reference: 1920x1080
Y Scale factor: 1.111
```

### 2. Run Live Capture
```bash
python test_lux_analyzer.py
# Option 2: Move mouse to target element
# Note the coordinates
```

### 3. Find Real Coordinates (Playwright)
```bash
# Chrome must be open with --remote-debugging-port=9222
python find_real_coordinates.py
```

### 4. Analyze Report
Open `lux_analysis/<session>/report.html` to see:
- Where LUX clicked vs where it should have clicked
- Coordinate percentages
- Hotspot patterns

## ⚙️ Configuration

### PyAutoGUI Settings
```python
TaskRequest(
    drag_duration=0.5,      # Drag speed
    scroll_amount=30,       # Scroll steps
    wait_duration=1.0,      # Wait actions
    action_pause=0.1,       # Pause between actions
    step_delay=0.3,         # Delay after each step
)
```

### LUX Modes
| Mode | Model | Use Case |
|------|-------|----------|
| `actor` | `lux-actor-1` | Fast, immediate tasks |
| `thinker` | `lux-thinker-1` | Complex reasoning |
| `tasker` | TaskerAgent | Structured todo workflows |

## 📝 Logging

Logs are saved to `debug_logs/service_<timestamp>.log`

Analysis reports are in `lux_analysis/<session>/`

## 🔗 Integration with Lovable

The Lovable web app sends POST requests to `/execute` with:
- OAGI API key
- Task description
- Start URL
- Execution mode

The service:
1. Opens Chrome with dedicated LUX profile
2. Executes task using OAGI SDK
3. Returns success/failure with summary
4. Optionally generates analysis report

## 📚 Official OAGI SDK

Based on: https://github.com/agiopen-org/oagi-python

Key SDK components used:
- `AsyncDefaultAgent` - Main execution agent
- `AsyncPyautoguiActionHandler` - Action execution
- `AsyncScreenshotMaker` - Screenshot capture
- `PyautoguiConfig` - Timing configuration
- `TaskerAgent` - Structured workflows

## 🐛 Troubleshooting

### OAGI SDK not available
```bash
pip install oagi
```

### PyAutoGUI issues on Linux
```bash
sudo apt-get install python3-tk python3-dev
```

### Chrome not found
The service automatically tries multiple Chrome paths. If none work, it falls back to the default browser.

### Coordinate issues
1. Enable analysis: `enable_analysis: true`
2. Run task
3. Open report in `lux_analysis/`
4. Compare LUX coordinates with actual element positions
