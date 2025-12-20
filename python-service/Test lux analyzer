"""
LUX Analyzer - Standalone Test & Demo
======================================

Esegui questo script per vedere come funziona l'analyzer.
NON richiede LUX - simula le azioni per mostrare l'output.

Uso:
    python test_lux_analyzer.py

Output:
    - lux_analysis/demo_session/report.html
    - lux_analysis/demo_session/actions.csv
    - lux_analysis/demo_session/screenshots/
"""

import sys
import time
import os

# Add current dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from lux_analyzer import LuxAnalyzer
    print("✅ LuxAnalyzer imported successfully")
except ImportError as e:
    print(f"❌ Failed to import LuxAnalyzer: {e}")
    print("   Make sure lux_analyzer.py is in the same directory")
    sys.exit(1)

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
    screen_w, screen_h = pyautogui.size()
    print(f"✅ PyAutoGUI available - Screen: {screen_w}x{screen_h}")
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    screen_w, screen_h = 1920, 1200
    print(f"⚠️ PyAutoGUI not available - Using default: {screen_w}x{screen_h}")

try:
    from PIL import Image
    print("✅ PIL available - Visual markers enabled")
except ImportError:
    print("⚠️ PIL not available - Visual markers disabled")


def run_demo():
    """
    Esegue demo dell'analyzer simulando una sessione di booking.
    """
    print("\n" + "="*60)
    print("  LUX ANALYZER DEMO")
    print("="*60 + "\n")
    
    # Crea analyzer
    analyzer = LuxAnalyzer(
        session_name="demo_booking_session",
        output_dir="lux_analysis"
    )
    
    print("\n📍 Simulando azioni LUX per booking.com...\n")
    
    # Simula sequenza di azioni tipica per booking.com
    
    # Step 1: Click sul campo destinazione
    print("\n--- Step 1: Click campo destinazione ---")
    action1 = analyzer.log_action(
        action_type='click',
        x=242,  # Coordinata "sbagliata" che LUX invia
        y=601,
        metadata={
            'target': 'destination_field',
            'instruction': 'Click on the destination input field',
            'lux_confidence': 0.92
        }
    )
    time.sleep(0.5)
    analyzer.mark_action_complete(action1, success=True)
    
    # Step 2: Type "Bergamo"
    print("\n--- Step 2: Type 'Bergamo' ---")
    action2 = analyzer.log_action(
        action_type='type',
        x=242,
        y=601,
        text='Bergamo',
        metadata={
            'target': 'destination_field',
            'instruction': 'Type the destination city'
        }
    )
    time.sleep(0.3)
    analyzer.mark_action_complete(action2, success=True)
    
    # Step 3: Click su suggerimento dropdown
    print("\n--- Step 3: Click dropdown suggestion ---")
    action3 = analyzer.log_action(
        action_type='click',
        x=280,
        y=680,
        metadata={
            'target': 'dropdown_suggestion',
            'instruction': 'Select first suggestion from dropdown'
        }
    )
    time.sleep(0.4)
    analyzer.mark_action_complete(action3, success=True)
    
    # Step 4: Click su date picker
    print("\n--- Step 4: Click date picker ---")
    action4 = analyzer.log_action(
        action_type='click',
        x=500,
        y=601,
        metadata={
            'target': 'check_in_date',
            'instruction': 'Open date picker'
        }
    )
    time.sleep(0.3)
    analyzer.mark_action_complete(action4, success=True)
    
    # Step 5: Click su data specifica
    print("\n--- Step 5: Select date ---")
    action5 = analyzer.log_action(
        action_type='click',
        x=650,
        y=720,
        metadata={
            'target': 'calendar_date',
            'instruction': 'Select check-in date'
        }
    )
    time.sleep(0.3)
    analyzer.mark_action_complete(action5, success=True)
    
    # Step 6: Scroll per vedere più opzioni
    print("\n--- Step 6: Scroll down ---")
    action6 = analyzer.log_action(
        action_type='scroll',
        scroll_amount=-5,
        metadata={
            'instruction': 'Scroll to see more options'
        }
    )
    time.sleep(0.2)
    analyzer.mark_action_complete(action6, success=True)
    
    # Step 7: Click search button
    print("\n--- Step 7: Click search ---")
    action7 = analyzer.log_action(
        action_type='click',
        x=900,
        y=601,
        metadata={
            'target': 'search_button',
            'instruction': 'Click search button to find hotels'
        }
    )
    time.sleep(0.5)
    analyzer.mark_action_complete(action7, success=True)
    
    # Genera report
    print("\n" + "="*60)
    print("  GENERATING REPORT")
    print("="*60)
    
    report_path = analyzer.generate_report()
    
    # Mostra statistiche
    print("\n📊 COORDINATE STATISTICS:")
    print("-" * 40)
    stats = analyzer.get_coordinate_stats()
    
    print(f"Total coordinates recorded: {stats.get('total_coordinates', 0)}")
    print(f"\nX Range: {stats.get('x_range', {})}")
    print(f"Y Range: {stats.get('y_range', {})}")
    
    print(f"\nActions by type:")
    for action_type, count in stats.get('actions_by_type', {}).items():
        print(f"  - {action_type}: {count}")
    
    print(f"\nHotspots (where LUX clicked most):")
    for hotspot in stats.get('hotspots', [])[:3]:
        print(f"  - {hotspot['screen_range']}: {hotspot['count']} clicks")
    
    print("\n" + "="*60)
    print("  DEMO COMPLETE!")
    print("="*60)
    print(f"\n📄 Open the report to see visual analysis:")
    print(f"   {report_path}")
    print(f"\n📁 All files in: lux_analysis/demo_booking_session/")
    print(f"   - report.html     (interactive report)")
    print(f"   - actions.csv     (spreadsheet data)")
    print(f"   - actions.json    (full JSON data)")
    print(f"   - screenshots/    (visual captures)")
    
    return report_path


def run_live_capture():
    """
    Cattura coordinate del mouse in tempo reale per 30 secondi.
    Utile per vedere dove si trova realmente un elemento.
    """
    if not PYAUTOGUI_AVAILABLE:
        print("❌ PyAutoGUI required for live capture")
        return
    
    print("\n" + "="*60)
    print("  LIVE COORDINATE CAPTURE")
    print("="*60)
    print("\nMove your mouse to the element you want to check.")
    print("Press Ctrl+C to stop.\n")
    
    analyzer = LuxAnalyzer(session_name="live_capture", output_dir="lux_analysis")
    
    try:
        step = 0
        while True:
            x, y = pyautogui.position()
            x_pct = x / screen_w * 100
            y_pct = y / screen_h * 100
            
            # In LUX reference (1080p)
            x_lux = int(x * 1920 / screen_w)
            y_lux = int(y * 1080 / screen_h)
            
            print(f"\r🖱️  Screen: ({x:4d}, {y:4d}) | "
                  f"Percent: ({x_pct:5.1f}%, {y_pct:5.1f}%) | "
                  f"LUX ref: ({x_lux:4d}, {y_lux:4d})   ", end='')
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n\n✅ Capture stopped")
        
        # Chiedi se salvare posizione corrente
        x, y = pyautogui.position()
        save = input(f"\nSave current position ({x}, {y}) to log? [y/N]: ")
        
        if save.lower() == 'y':
            analyzer.log_action(
                action_type='click',
                x=x,
                y=y,
                metadata={'capture_type': 'manual', 'note': 'User-identified element position'}
            )
            analyzer.generate_report()
            print(f"✅ Position saved to lux_analysis/live_capture/")


def compare_coordinates():
    """
    Compara coordinate LUX con coordinate reali trovate manualmente.
    """
    print("\n" + "="*60)
    print("  COORDINATE COMPARISON TOOL")
    print("="*60)
    
    print("\nEnter LUX coordinates (what LUX sent):")
    try:
        lux_x = int(input("  LUX X: "))
        lux_y = int(input("  LUX Y: "))
    except ValueError:
        print("❌ Invalid input")
        return
    
    print("\nEnter REAL coordinates (where element actually is):")
    try:
        real_x = int(input("  Real X: "))
        real_y = int(input("  Real Y: "))
    except ValueError:
        print("❌ Invalid input")
        return
    
    # Calcola errori
    x_error = lux_x - real_x
    y_error = lux_y - real_y
    
    x_error_pct = x_error / screen_w * 100
    y_error_pct = y_error / screen_h * 100
    
    print("\n" + "-"*40)
    print("ANALYSIS:")
    print("-"*40)
    
    print(f"\nLUX sent:     ({lux_x}, {lux_y})")
    print(f"Real target:  ({real_x}, {real_y})")
    print(f"Error:        ({x_error:+d}, {y_error:+d}) pixels")
    print(f"Error %:      ({x_error_pct:+.1f}%, {y_error_pct:+.1f}%)")
    
    # Suggerimenti
    print("\n" + "-"*40)
    print("DIAGNOSIS:")
    print("-"*40)
    
    if abs(x_error) < 50 and abs(y_error) < 50:
        print("✅ Coordinates are close! Minor adjustment needed.")
    elif abs(x_error) > 200:
        print(f"❌ X error is significant ({x_error:+d}px)")
        print("   LUX might be detecting wrong element")
    
    if screen_h != 1080:
        expected_y_scaled = int(lux_y * screen_h / 1080)
        y_error_after_scale = expected_y_scaled - real_y
        print(f"\nY with resolution scaling:")
        print(f"   LUX Y ({lux_y}) × ({screen_h}/1080) = {expected_y_scaled}")
        print(f"   Error after scaling: {y_error_after_scale:+d}px")
        
        if abs(y_error_after_scale) < abs(y_error):
            print("   ✅ Y scaling would HELP! Apply resolution fix.")
        else:
            print("   ⚠️ Y scaling alone won't fix this.")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  LUX ANALYZER - TEST & TOOLS")
    print("="*60)
    print("\nOptions:")
    print("  1. Run demo (simulate booking session)")
    print("  2. Live capture (track mouse position)")
    print("  3. Compare coordinates (LUX vs real)")
    print("  4. Exit")
    
    try:
        choice = input("\nSelect option [1-4]: ").strip()
        
        if choice == '1':
            run_demo()
        elif choice == '2':
            run_live_capture()
        elif choice == '3':
            compare_coordinates()
        elif choice == '4':
            print("Bye!")
        else:
            print("Running demo by default...")
            run_demo()
            
    except KeyboardInterrupt:
        print("\n\nBye!")
