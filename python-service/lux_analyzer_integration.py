"""
LUX Analyzer Integration for tasker_service.py
================================================

Aggiungi questo file al python-service e importalo in tasker_service.py
per abilitare il logging completo del comportamento di LUX.

Uso:
    1. Copia lux_analyzer.py e lux_analyzer_integration.py nella cartella python-service
    2. Aggiungi in tasker_service.py:
       
       from lux_analyzer_integration import LuxTracker
       
       # All'inizio di execute_instruction:
       tracker = LuxTracker.start_session("booking_test")
       
       # Prima di ogni click:
       tracker.before_click(x, y, {"target": "description"})
       
       # Prima di ogni type:
       tracker.before_type(text, {"field": "field_name"})
       
       # Alla fine:
       tracker.end_session()

"""

import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Import analyzer
try:
    from lux_analyzer import LuxAnalyzer, LuxAction
    ANALYZER_AVAILABLE = True
except ImportError:
    ANALYZER_AVAILABLE = False
    print("⚠️ LuxAnalyzer not available")

# Import pyautogui per info schermo
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


class LuxTracker:
    """
    Tracker semplificato per integrare l'analyzer nel tasker_service.
    """
    
    _instance: Optional['LuxTracker'] = None
    
    def __init__(self, session_name: str = None):
        if not ANALYZER_AVAILABLE:
            print("⚠️ LuxAnalyzer not available - tracking disabled")
            self.analyzer = None
            return
        
        self.session_name = session_name or f"lux_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.analyzer = LuxAnalyzer(
            session_name=self.session_name,
            output_dir="lux_analysis"
        )
        self.current_action: Optional[LuxAction] = None
        
        print(f"📊 LUX Tracker started: {self.session_name}")
    
    @classmethod
    def start_session(cls, session_name: str = None) -> 'LuxTracker':
        """Avvia nuova sessione di tracking."""
        cls._instance = cls(session_name)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> Optional['LuxTracker']:
        """Ottieni istanza corrente."""
        return cls._instance
    
    def before_click(self, x: int, y: int, metadata: Dict[str, Any] = None) -> Optional[LuxAction]:
        """
        Chiama PRIMA di eseguire un click.
        Logga coordinate e cattura screenshot.
        """
        if not self.analyzer:
            return None
        
        self.current_action = self.analyzer.log_action(
            action_type='click',
            x=x,
            y=y,
            metadata=metadata or {}
        )
        return self.current_action
    
    def after_click(self, success: bool = True, error: str = None):
        """Chiama DOPO un click."""
        if self.current_action and self.analyzer:
            self.analyzer.mark_action_complete(
                self.current_action,
                success=success,
                error_message=error
            )
            self.current_action = None
    
    def before_type(self, text: str, metadata: Dict[str, Any] = None) -> Optional[LuxAction]:
        """Chiama PRIMA di digitare testo."""
        if not self.analyzer:
            return None
        
        # Ottieni posizione corrente mouse come riferimento
        if PYAUTOGUI_AVAILABLE:
            x, y = pyautogui.position()
        else:
            x, y = None, None
        
        self.current_action = self.analyzer.log_action(
            action_type='type',
            x=x,
            y=y,
            text=text,
            metadata=metadata or {}
        )
        return self.current_action
    
    def after_type(self, success: bool = True, error: str = None):
        """Chiama DOPO aver digitato."""
        if self.current_action and self.analyzer:
            self.analyzer.mark_action_complete(
                self.current_action,
                success=success,
                error_message=error
            )
            self.current_action = None
    
    def before_scroll(self, amount: int, metadata: Dict[str, Any] = None):
        """Chiama PRIMA di scroll."""
        if not self.analyzer:
            return None
        
        if PYAUTOGUI_AVAILABLE:
            x, y = pyautogui.position()
        else:
            x, y = None, None
        
        self.current_action = self.analyzer.log_action(
            action_type='scroll',
            x=x,
            y=y,
            scroll_amount=amount,
            metadata=metadata or {}
        )
        return self.current_action
    
    def after_scroll(self, success: bool = True, error: str = None):
        """Chiama DOPO scroll."""
        if self.current_action and self.analyzer:
            self.analyzer.mark_action_complete(
                self.current_action,
                success=success,
                error_message=error
            )
            self.current_action = None
    
    def before_hotkey(self, keys: list, metadata: Dict[str, Any] = None):
        """Chiama PRIMA di hotkey."""
        if not self.analyzer:
            return None
        
        self.current_action = self.analyzer.log_action(
            action_type='hotkey',
            keys=keys,
            metadata=metadata or {}
        )
        return self.current_action
    
    def after_hotkey(self, success: bool = True, error: str = None):
        """Chiama DOPO hotkey."""
        if self.current_action and self.analyzer:
            self.analyzer.mark_action_complete(
                self.current_action,
                success=success,
                error_message=error
            )
            self.current_action = None
    
    def log_raw_lux_response(self, response: Dict[str, Any]):
        """
        Logga la risposta raw di LUX per analisi.
        """
        if not self.analyzer:
            return
        
        # Salva in file separato
        raw_log_path = Path(self.analyzer.session_dir) / "lux_raw_responses.jsonl"
        
        import json
        with open(raw_log_path, 'a') as f:
            f.write(json.dumps({
                'timestamp': time.time(),
                'response': response
            }) + '\n')
    
    def end_session(self) -> str:
        """
        Termina sessione e genera report.
        
        Returns:
            Path al report HTML
        """
        if not self.analyzer:
            return ""
        
        report_path = self.analyzer.generate_report()
        
        print(f"\n{'='*60}")
        print(f"📊 LUX ANALYSIS SESSION COMPLETE")
        print(f"{'='*60}")
        print(f"Session: {self.session_name}")
        print(f"Actions recorded: {len(self.analyzer.actions)}")
        print(f"Report: {report_path}")
        print(f"{'='*60}")
        
        return report_path
    
    def get_stats(self) -> Dict[str, Any]:
        """Ottieni statistiche correnti."""
        if not self.analyzer:
            return {}
        return self.analyzer.get_coordinate_stats()


# ============================================================
# ESEMPIO DI INTEGRAZIONE CON TASKER_SERVICE
# ============================================================

INTEGRATION_EXAMPLE = """
# ============================================================
# COME INTEGRARE IN tasker_service.py
# ============================================================

# 1. Aggiungi import all'inizio del file:
from lux_analyzer_integration import LuxTracker

# 2. Modifica execute_instruction per iniziare tracking:

@app.post("/execute")
async def execute_instruction(request: ExecuteRequest):
    # START TRACKING
    tracker = LuxTracker.start_session(f"task_{int(time.time())}")
    
    try:
        # ... codice esistente ...
        
        # 3. Prima di ogni CLICK:
        if action_type == "CLICK":
            x = int(action_data.get('x', 0))
            y = int(action_data.get('y', 0))
            
            # LOG BEFORE CLICK
            tracker.before_click(x, y, {"step": step_number, "instruction": instruction})
            
            try:
                pyautogui.click(x, y)
                tracker.after_click(success=True)
            except Exception as e:
                tracker.after_click(success=False, error=str(e))
                raise
        
        # 4. Prima di ogni TYPE:
        elif action_type == "TYPE":
            text = action_data.get('text', '')
            
            # LOG BEFORE TYPE
            tracker.before_type(text, {"step": step_number})
            
            try:
                # ... typing code ...
                tracker.after_type(success=True)
            except Exception as e:
                tracker.after_type(success=False, error=str(e))
                raise
        
        # 5. Prima di ogni SCROLL:
        elif action_type == "SCROLL":
            amount = int(action_data.get('amount', 0))
            
            tracker.before_scroll(amount)
            try:
                pyautogui.scroll(amount)
                tracker.after_scroll(success=True)
            except Exception as e:
                tracker.after_scroll(success=False, error=str(e))
                raise
        
    finally:
        # 6. Alla fine, genera report:
        report_path = tracker.end_session()
        debug_log(f"Analysis report: {report_path}", "INFO")

# ============================================================
# OUTPUT GENERATO
# ============================================================

# Dopo l'esecuzione troverai in lux_analysis/<session_name>/:
#
# ├── report.html          # Report interattivo con timeline e stats
# ├── actions.csv          # Tutte le azioni in CSV
# ├── actions.json         # Tutte le azioni in JSON  
# ├── lux_raw_responses.jsonl  # Risposte raw di LUX
# └── screenshots/
#     ├── step_001_before.png   # Screenshot prima dell'azione
#     ├── step_001_markers.png  # Screenshot con marker coordinate
#     ├── step_001_after.png    # Screenshot dopo l'azione
#     └── ...
"""


if __name__ == "__main__":
    print(INTEGRATION_EXAMPLE)
    
    # Quick test
    print("\n🧪 Quick test...")
    
    tracker = LuxTracker.start_session("integration_test")
    
    tracker.before_click(242, 601, {"target": "booking field"})
    time.sleep(0.3)
    tracker.after_click(success=True)
    
    tracker.before_type("Bergamo", {"field": "destination"})
    time.sleep(0.2)
    tracker.after_type(success=True)
    
    report = tracker.end_session()
    print(f"\n✅ Test complete! Report: {report}")
