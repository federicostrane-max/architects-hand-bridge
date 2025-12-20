"""
LUX Behavior Analyzer
=====================
Sistema completo di analisi e logging per capire esattamente cosa fa LUX.

Funzionalità:
1. Cattura ogni azione (click, type, scroll, etc.)
2. Salva screenshot con marker visivi delle coordinate
3. Registra coordinate in CSV per analisi
4. Genera report HTML interattivo
5. Calcola statistiche sugli errori di coordinate

Uso:
    analyzer = LuxAnalyzer(session_name="booking_test")
    analyzer.log_action("click", x=242, y=601, metadata={"target": "destination field"})
    analyzer.capture_screenshot_with_markers(x=242, y=601)
    analyzer.generate_report()
"""

import os
import sys
import json
import csv
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any, Tuple
import threading

# Conditional imports
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️ PIL not available - visual markers disabled")

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("⚠️ PyAutoGUI not available - screenshots disabled")


@dataclass
class LuxAction:
    """Rappresenta una singola azione di LUX"""
    timestamp: float
    step_number: int
    action_type: str  # click, type, scroll, drag, hotkey, wait
    
    # Coordinate (per click, drag)
    x: Optional[int] = None
    y: Optional[int] = None
    x_end: Optional[int] = None  # Per drag
    y_end: Optional[int] = None
    
    # Dati azione
    text: Optional[str] = None  # Per type
    scroll_amount: Optional[int] = None  # Per scroll
    keys: Optional[List[str]] = None  # Per hotkey
    
    # Analisi
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    x_percent: Optional[float] = None  # X come % dello schermo
    y_percent: Optional[float] = None  # Y come % dello schermo
    
    # Screenshot paths
    screenshot_before: Optional[str] = None
    screenshot_after: Optional[str] = None
    screenshot_with_markers: Optional[str] = None
    
    # Metadata aggiuntiva
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Risultato
    success: Optional[bool] = None
    error_message: Optional[str] = None
    execution_time_ms: Optional[float] = None


class LuxAnalyzer:
    """
    Sistema di analisi del comportamento di LUX.
    Traccia ogni azione, salva screenshot, genera report.
    """
    
    def __init__(self, session_name: str = None, output_dir: str = "lux_analysis"):
        """
        Inizializza l'analyzer.
        
        Args:
            session_name: Nome della sessione (default: timestamp)
            output_dir: Directory per output (default: lux_analysis)
        """
        self.session_name = session_name or f"session_{int(time.time())}"
        self.session_start = time.time()
        self.step_counter = 0
        
        # Setup directories
        self.output_dir = Path(output_dir)
        self.session_dir = self.output_dir / self.session_name
        self.screenshots_dir = self.session_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # Storage
        self.actions: List[LuxAction] = []
        self.coordinate_history: List[Tuple[int, int, str]] = []  # (x, y, action_type)
        
        # Screen info
        if PYAUTOGUI_AVAILABLE:
            self.screen_width, self.screen_height = pyautogui.size()
        else:
            self.screen_width, self.screen_height = 1920, 1200  # Default
        
        # LUX reference resolution
        self.lux_ref_width = 1920
        self.lux_ref_height = 1080
        
        # Marker colors
        self.colors = {
            'click': '#FF0000',      # Red
            'type': '#00FF00',       # Green
            'scroll': '#0000FF',     # Blue
            'drag_start': '#FF00FF', # Magenta
            'drag_end': '#00FFFF',   # Cyan
            'expected': '#00FF00',   # Green (expected position)
            'actual': '#FF0000',     # Red (actual LUX position)
        }
        
        print(f"📊 LUX Analyzer initialized")
        print(f"   Session: {self.session_name}")
        print(f"   Output: {self.session_dir}")
        print(f"   Screen: {self.screen_width}x{self.screen_height}")
        print(f"   LUX Ref: {self.lux_ref_width}x{self.lux_ref_height}")
    
    def log_action(self, 
                   action_type: str,
                   x: int = None, 
                   y: int = None,
                   x_end: int = None,
                   y_end: int = None,
                   text: str = None,
                   scroll_amount: int = None,
                   keys: List[str] = None,
                   metadata: Dict[str, Any] = None,
                   capture_screenshots: bool = True) -> LuxAction:
        """
        Registra un'azione di LUX.
        
        Args:
            action_type: Tipo di azione (click, type, scroll, drag, hotkey, wait)
            x, y: Coordinate per click/drag
            x_end, y_end: Coordinate finali per drag
            text: Testo per type
            scroll_amount: Quantità scroll
            keys: Tasti per hotkey
            metadata: Dati aggiuntivi
            capture_screenshots: Se catturare screenshot
            
        Returns:
            LuxAction registrata
        """
        self.step_counter += 1
        timestamp = time.time()
        
        # Calcola percentuali coordinate
        x_percent = (x / self.screen_width * 100) if x is not None else None
        y_percent = (y / self.screen_height * 100) if y is not None else None
        
        # Crea action
        action = LuxAction(
            timestamp=timestamp,
            step_number=self.step_counter,
            action_type=action_type,
            x=x,
            y=y,
            x_end=x_end,
            y_end=y_end,
            text=text,
            scroll_amount=scroll_amount,
            keys=keys,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
            x_percent=x_percent,
            y_percent=y_percent,
            metadata=metadata or {}
        )
        
        # Salva coordinate history
        if x is not None and y is not None:
            self.coordinate_history.append((x, y, action_type))
        
        # Cattura screenshots
        if capture_screenshots and PYAUTOGUI_AVAILABLE and PIL_AVAILABLE:
            # Screenshot before
            before_path = self.screenshots_dir / f"step_{self.step_counter:03d}_before.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(before_path)
            action.screenshot_before = str(before_path)
            
            # Screenshot with markers
            if x is not None and y is not None:
                markers_path = self.screenshots_dir / f"step_{self.step_counter:03d}_markers.png"
                self._add_markers_to_screenshot(screenshot, action, markers_path)
                action.screenshot_with_markers = str(markers_path)
        
        # Log to console
        self._log_to_console(action)
        
        # Salva action
        self.actions.append(action)
        
        # Salva CSV incrementale
        self._append_to_csv(action)
        
        return action
    
    def mark_action_complete(self, 
                            action: LuxAction, 
                            success: bool = True, 
                            error_message: str = None):
        """
        Marca un'azione come completata e cattura screenshot after.
        """
        action.success = success
        action.error_message = error_message
        action.execution_time_ms = (time.time() - action.timestamp) * 1000
        
        # Cattura screenshot after
        if PYAUTOGUI_AVAILABLE:
            after_path = self.screenshots_dir / f"step_{action.step_number:03d}_after.png"
            pyautogui.screenshot().save(after_path)
            action.screenshot_after = str(after_path)
    
    def _add_markers_to_screenshot(self, 
                                   screenshot: 'Image', 
                                   action: LuxAction,
                                   output_path: Path):
        """
        Aggiunge marker visivi allo screenshot.
        """
        if not PIL_AVAILABLE:
            return
        
        # Copia per non modificare originale
        img = screenshot.copy()
        draw = ImageDraw.Draw(img)
        
        x, y = action.x, action.y
        
        # Marker principale (dove LUX vuole cliccare)
        marker_size = 30
        color = self.colors.get(action.action_type, '#FFFFFF')
        
        # Cerchio
        draw.ellipse([x - marker_size, y - marker_size, 
                     x + marker_size, y + marker_size],
                    outline=color, width=4)
        
        # Croce al centro
        cross_size = 15
        draw.line([(x - cross_size, y), (x + cross_size, y)], fill=color, width=3)
        draw.line([(x, y - cross_size), (x, y + cross_size)], fill=color, width=3)
        
        # Label con info
        label_y = y - marker_size - 60
        if label_y < 10:
            label_y = y + marker_size + 10
        
        # Background per label
        label_text = [
            f"Step {action.step_number}: {action.action_type.upper()}",
            f"Coords: ({x}, {y})",
            f"Screen %: ({action.x_percent:.1f}%, {action.y_percent:.1f}%)",
        ]
        
        if action.text:
            label_text.append(f"Text: '{action.text[:30]}...'")
        
        # Draw label background
        padding = 5
        line_height = 18
        max_width = 300
        
        draw.rectangle([x - max_width//2, label_y - padding,
                       x + max_width//2, label_y + len(label_text) * line_height + padding],
                      fill='white', outline='black')
        
        # Draw label text
        for i, line in enumerate(label_text):
            draw.text((x - max_width//2 + padding, label_y + i * line_height),
                     line, fill='black')
        
        # Info box in angolo
        info_box = [
            f"Session: {self.session_name}",
            f"Screen: {self.screen_width}x{self.screen_height}",
            f"LUX Ref: {self.lux_ref_width}x{self.lux_ref_height}",
            f"Scale Y: {self.screen_height/self.lux_ref_height:.3f}",
            f"Time: {datetime.fromtimestamp(action.timestamp).strftime('%H:%M:%S.%f')[:-3]}",
        ]
        
        draw.rectangle([10, 10, 280, 10 + len(info_box) * line_height + 10],
                      fill='rgba(255,255,255,200)', outline='black')
        
        for i, line in enumerate(info_box):
            draw.text((15, 15 + i * line_height), line, fill='black')
        
        # Coordinate grid overlay (opzionale, ogni 10%)
        for pct in range(10, 100, 10):
            # Vertical lines
            x_line = int(self.screen_width * pct / 100)
            draw.line([(x_line, 0), (x_line, self.screen_height)], 
                     fill='rgba(128,128,128,50)', width=1)
            draw.text((x_line + 2, 5), f"{pct}%", fill='gray')
            
            # Horizontal lines
            y_line = int(self.screen_height * pct / 100)
            draw.line([(0, y_line), (self.screen_width, y_line)],
                     fill='rgba(128,128,128,50)', width=1)
            draw.text((5, y_line + 2), f"{pct}%", fill='gray')
        
        img.save(output_path)
    
    def _log_to_console(self, action: LuxAction):
        """Log formattato a console."""
        
        print(f"\n{'='*60}")
        print(f"📍 STEP {action.step_number}: {action.action_type.upper()}")
        print(f"{'='*60}")
        
        if action.x is not None:
            print(f"  Coordinates: ({action.x}, {action.y})")
            print(f"  As % of screen: X={action.x_percent:.1f}%, Y={action.y_percent:.1f}%")
            
            # Calcola cosa sarebbe in LUX reference
            x_in_lux = int(action.x * self.lux_ref_width / self.screen_width)
            y_in_lux = int(action.y * self.lux_ref_height / self.screen_height)
            print(f"  In LUX ref (1080p): ({x_in_lux}, {y_in_lux})")
        
        if action.text:
            display_text = action.text if len(action.text) <= 50 else action.text[:50] + "..."
            print(f"  Text: '{display_text}'")
        
        if action.scroll_amount:
            print(f"  Scroll: {action.scroll_amount}")
        
        if action.keys:
            print(f"  Keys: {' + '.join(action.keys)}")
        
        if action.metadata:
            print(f"  Metadata: {json.dumps(action.metadata, indent=4)}")
        
        print(f"  Time: {datetime.fromtimestamp(action.timestamp).strftime('%H:%M:%S.%f')[:-3]}")
    
    def _append_to_csv(self, action: LuxAction):
        """Salva azione in CSV incrementale."""
        csv_path = self.session_dir / "actions.csv"
        
        # Determina se scrivere header
        write_header = not csv_path.exists()
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            
            if write_header:
                writer.writerow([
                    'step', 'timestamp', 'action_type',
                    'x', 'y', 'x_percent', 'y_percent',
                    'x_end', 'y_end', 'text', 'scroll', 'keys',
                    'screen_w', 'screen_h', 'success', 'error', 'exec_time_ms'
                ])
            
            writer.writerow([
                action.step_number,
                action.timestamp,
                action.action_type,
                action.x,
                action.y,
                f"{action.x_percent:.2f}" if action.x_percent else "",
                f"{action.y_percent:.2f}" if action.y_percent else "",
                action.x_end,
                action.y_end,
                action.text,
                action.scroll_amount,
                ",".join(action.keys) if action.keys else "",
                action.screen_width,
                action.screen_height,
                action.success,
                action.error_message,
                f"{action.execution_time_ms:.2f}" if action.execution_time_ms else ""
            ])
    
    def get_coordinate_stats(self) -> Dict[str, Any]:
        """
        Calcola statistiche sulle coordinate registrate.
        """
        if not self.coordinate_history:
            return {"error": "No coordinates recorded"}
        
        x_coords = [c[0] for c in self.coordinate_history]
        y_coords = [c[1] for c in self.coordinate_history]
        
        # Calcola bounds
        x_min, x_max = min(x_coords), max(x_coords)
        y_min, y_max = min(y_coords), max(y_coords)
        
        # Calcola percentuali
        x_pcts = [x / self.screen_width * 100 for x in x_coords]
        y_pcts = [y / self.screen_height * 100 for y in y_coords]
        
        # Conta azioni per tipo
        action_counts = {}
        for _, _, action_type in self.coordinate_history:
            action_counts[action_type] = action_counts.get(action_type, 0) + 1
        
        # Identifica cluster (zone dove LUX clicca spesso)
        # Semplice: dividi schermo in griglia 10x10
        grid = [[0 for _ in range(10)] for _ in range(10)]
        for x, y, _ in self.coordinate_history:
            grid_x = min(int(x / self.screen_width * 10), 9)
            grid_y = min(int(y / self.screen_height * 10), 9)
            grid[grid_y][grid_x] += 1
        
        # Trova hotspots (celle con più click)
        hotspots = []
        for gy in range(10):
            for gx in range(10):
                if grid[gy][gx] > 0:
                    hotspots.append({
                        'grid': f"({gx}, {gy})",
                        'screen_range': f"X:{gx*10}-{(gx+1)*10}%, Y:{gy*10}-{(gy+1)*10}%",
                        'count': grid[gy][gx]
                    })
        
        hotspots.sort(key=lambda h: h['count'], reverse=True)
        
        return {
            'total_coordinates': len(self.coordinate_history),
            'x_range': {'min': x_min, 'max': x_max, 'span': x_max - x_min},
            'y_range': {'min': y_min, 'max': y_max, 'span': y_max - y_min},
            'x_percent_range': {'min': min(x_pcts), 'max': max(x_pcts)},
            'y_percent_range': {'min': min(y_pcts), 'max': max(y_pcts)},
            'actions_by_type': action_counts,
            'hotspots': hotspots[:5],  # Top 5 hotspots
            'screen_size': f"{self.screen_width}x{self.screen_height}",
            'lux_reference': f"{self.lux_ref_width}x{self.lux_ref_height}",
        }
    
    def generate_report(self) -> str:
        """
        Genera report HTML completo della sessione.
        
        Returns:
            Path al file HTML generato
        """
        stats = self.get_coordinate_stats()
        
        # Genera HTML
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>LUX Analysis Report - {self.session_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }}
        .stat-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .stat-card h3 {{ margin-top: 0; color: #007bff; }}
        .action-row {{ background: white; margin: 10px 0; padding: 15px; border-radius: 8px; 
                      box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; gap: 20px; align-items: flex-start; }}
        .action-row img {{ max-width: 400px; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; }}
        .action-row img:hover {{ transform: scale(1.02); }}
        .action-info {{ flex: 1; }}
        .action-type {{ display: inline-block; padding: 4px 12px; border-radius: 4px; color: white; font-weight: bold; }}
        .action-type.click {{ background: #dc3545; }}
        .action-type.type {{ background: #28a745; }}
        .action-type.scroll {{ background: #007bff; }}
        .action-type.drag {{ background: #6f42c1; }}
        .action-type.hotkey {{ background: #fd7e14; }}
        .action-type.wait {{ background: #6c757d; }}
        .coords {{ font-family: monospace; background: #f8f9fa; padding: 8px; border-radius: 4px; margin: 10px 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; }}
        .heatmap {{ display: grid; grid-template-columns: repeat(10, 1fr); gap: 2px; max-width: 500px; }}
        .heatmap-cell {{ aspect-ratio: 1; display: flex; align-items: center; justify-content: center;
                        font-size: 12px; border-radius: 4px; }}
        .timeline {{ position: relative; padding-left: 30px; }}
        .timeline::before {{ content: ''; position: absolute; left: 10px; top: 0; bottom: 0; width: 2px; background: #ddd; }}
        .timeline-item {{ position: relative; margin: 20px 0; }}
        .timeline-item::before {{ content: ''; position: absolute; left: -24px; width: 12px; height: 12px; 
                                 border-radius: 50%; background: #007bff; }}
        .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
                 background: rgba(0,0,0,0.9); z-index: 1000; cursor: pointer; }}
        .modal img {{ max-width: 95%; max-height: 95%; position: absolute; top: 50%; left: 50%; 
                     transform: translate(-50%, -50%); }}
        .summary-table {{ margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 LUX Behavior Analysis Report</h1>
        <p><strong>Session:</strong> {self.session_name}</p>
        <p><strong>Duration:</strong> {time.time() - self.session_start:.1f} seconds</p>
        <p><strong>Total Actions:</strong> {len(self.actions)}</p>
        
        <h2>📊 Statistics</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Screen Configuration</h3>
                <table>
                    <tr><td>Your Screen</td><td><strong>{self.screen_width} x {self.screen_height}</strong></td></tr>
                    <tr><td>LUX Reference</td><td>{self.lux_ref_width} x {self.lux_ref_height}</td></tr>
                    <tr><td>Scale Factor X</td><td>{self.screen_width/self.lux_ref_width:.3f}</td></tr>
                    <tr><td>Scale Factor Y</td><td>{self.screen_height/self.lux_ref_height:.3f}</td></tr>
                </table>
            </div>
            
            <div class="stat-card">
                <h3>Coordinate Ranges</h3>
                <table>
                    <tr><td>X Range</td><td>{stats.get('x_range', {}).get('min', 'N/A')} - {stats.get('x_range', {}).get('max', 'N/A')} px</td></tr>
                    <tr><td>Y Range</td><td>{stats.get('y_range', {}).get('min', 'N/A')} - {stats.get('y_range', {}).get('max', 'N/A')} px</td></tr>
                    <tr><td>X % Range</td><td>{stats.get('x_percent_range', {}).get('min', 0):.1f}% - {stats.get('x_percent_range', {}).get('max', 0):.1f}%</td></tr>
                    <tr><td>Y % Range</td><td>{stats.get('y_percent_range', {}).get('min', 0):.1f}% - {stats.get('y_percent_range', {}).get('max', 0):.1f}%</td></tr>
                </table>
            </div>
            
            <div class="stat-card">
                <h3>Actions by Type</h3>
                <table>
                    {"".join(f'<tr><td>{k}</td><td><strong>{v}</strong></td></tr>' for k, v in stats.get('actions_by_type', {}).items())}
                </table>
            </div>
            
            <div class="stat-card">
                <h3>Top Hotspots</h3>
                <table>
                    <tr><th>Zone</th><th>Clicks</th></tr>
                    {"".join(f"<tr><td>{h['screen_range']}</td><td>{h['count']}</td></tr>" for h in stats.get('hotspots', [])[:5])}
                </table>
            </div>
        </div>
        
        <h2>📋 Action Timeline</h2>
        <div class="timeline">
"""
        
        # Aggiungi ogni azione
        for action in self.actions:
            action_class = action.action_type.lower()
            
            coords_html = ""
            if action.x is not None:
                coords_html = f"""
                <div class="coords">
                    <strong>Coordinates:</strong> ({action.x}, {action.y})<br>
                    <strong>Screen %:</strong> X={action.x_percent:.1f}%, Y={action.y_percent:.1f}%<br>
                    <strong>In LUX ref:</strong> ({int(action.x * self.lux_ref_width / self.screen_width)}, {int(action.y * self.lux_ref_height / self.screen_height)})
                </div>
                """
            
            text_html = f"<p><strong>Text:</strong> <code>{action.text}</code></p>" if action.text else ""
            scroll_html = f"<p><strong>Scroll:</strong> {action.scroll_amount}</p>" if action.scroll_amount else ""
            keys_html = f"<p><strong>Keys:</strong> {' + '.join(action.keys)}</p>" if action.keys else ""
            
            screenshot_html = ""
            if action.screenshot_with_markers:
                rel_path = os.path.relpath(action.screenshot_with_markers, self.session_dir)
                screenshot_html = f'<img src="{rel_path}" onclick="showModal(this.src)" alt="Screenshot">'
            
            html += f"""
            <div class="timeline-item">
                <div class="action-row">
                    <div class="action-info">
                        <span class="action-type {action_class}">{action.action_type.upper()}</span>
                        <span> Step {action.step_number}</span>
                        <span style="color: #888; margin-left: 10px;">
                            {datetime.fromtimestamp(action.timestamp).strftime('%H:%M:%S.%f')[:-3]}
                        </span>
                        {coords_html}
                        {text_html}
                        {scroll_html}
                        {keys_html}
                    </div>
                    {screenshot_html}
                </div>
            </div>
            """
        
        html += """
        </div>
        
        <h2>📈 Coordinate Heatmap</h2>
        <p>Shows click density across screen (10x10 grid)</p>
        <div class="heatmap" id="heatmap"></div>
        
        <h2>📁 Files Generated</h2>
        <ul>
            <li><a href="actions.csv">actions.csv</a> - All actions in CSV format</li>
            <li><a href="actions.json">actions.json</a> - All actions in JSON format</li>
            <li><a href="screenshots/">screenshots/</a> - All screenshots</li>
        </ul>
    </div>
    
    <div class="modal" id="modal" onclick="hideModal()">
        <img id="modalImg" src="">
    </div>
    
    <script>
        function showModal(src) {
            document.getElementById('modalImg').src = src;
            document.getElementById('modal').style.display = 'block';
        }
        
        function hideModal() {
            document.getElementById('modal').style.display = 'none';
        }
        
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') hideModal();
        });
    </script>
</body>
</html>
"""
        
        # Salva HTML
        report_path = self.session_dir / "report.html"
        with open(report_path, 'w') as f:
            f.write(html)
        
        # Salva anche JSON completo
        json_path = self.session_dir / "actions.json"
        with open(json_path, 'w') as f:
            json.dump({
                'session': self.session_name,
                'screen': {'width': self.screen_width, 'height': self.screen_height},
                'lux_reference': {'width': self.lux_ref_width, 'height': self.lux_ref_height},
                'stats': stats,
                'actions': [asdict(a) for a in self.actions]
            }, f, indent=2)
        
        print(f"\n📊 Report generated: {report_path}")
        print(f"📋 JSON data: {json_path}")
        print(f"📁 CSV data: {self.session_dir / 'actions.csv'}")
        
        return str(report_path)


# Singleton instance per uso globale
_analyzer_instance: Optional[LuxAnalyzer] = None


def get_analyzer(session_name: str = None) -> LuxAnalyzer:
    """
    Ottieni istanza globale dell'analyzer.
    """
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = LuxAnalyzer(session_name)
    return _analyzer_instance


def reset_analyzer():
    """Reset analyzer globale."""
    global _analyzer_instance
    _analyzer_instance = None


# ============================================================
# INTEGRATION HELPERS
# ============================================================

def wrap_pyautogui_click(original_click):
    """
    Wrapper per pyautogui.click che logga automaticamente.
    """
    def wrapped_click(x=None, y=None, **kwargs):
        analyzer = get_analyzer()
        action = analyzer.log_action('click', x=x, y=y, metadata=kwargs)
        
        try:
            result = original_click(x=x, y=y, **kwargs)
            analyzer.mark_action_complete(action, success=True)
            return result
        except Exception as e:
            analyzer.mark_action_complete(action, success=False, error_message=str(e))
            raise
    
    return wrapped_click


def wrap_pyautogui_write(original_write):
    """
    Wrapper per pyautogui.write che logga automaticamente.
    """
    def wrapped_write(text, **kwargs):
        analyzer = get_analyzer()
        action = analyzer.log_action('type', text=text, metadata=kwargs)
        
        try:
            result = original_write(text, **kwargs)
            analyzer.mark_action_complete(action, success=True)
            return result
        except Exception as e:
            analyzer.mark_action_complete(action, success=False, error_message=str(e))
            raise
    
    return wrapped_write


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    # Test mode
    print("🧪 Running LUX Analyzer test...")
    
    analyzer = LuxAnalyzer(session_name="test_session")
    
    # Simula alcune azioni
    analyzer.log_action('click', x=242, y=601, metadata={'target': 'booking destination'})
    time.sleep(0.5)
    
    analyzer.log_action('type', x=242, y=601, text='Bergamo', metadata={'field': 'destination'})
    time.sleep(0.3)
    
    analyzer.log_action('click', x=500, y=400, metadata={'target': 'date picker'})
    time.sleep(0.2)
    
    analyzer.log_action('scroll', scroll_amount=-3)
    
    # Genera report
    report = analyzer.generate_report()
    
    # Mostra stats
    print("\n📊 Statistics:")
    stats = analyzer.get_coordinate_stats()
    print(json.dumps(stats, indent=2))
    
    print(f"\n✅ Test complete! Report at: {report}")
