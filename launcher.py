#!/usr/bin/env python3
"""
Architect's Hand Bridge Launcher
================================
Avvia Tasker Service + Electron Bridge con un solo click.

Uso:
  python launcher.py          # Avvia tutto
  python launcher.py --no-gui # Avvia senza finestra GUI

Build .exe:
  pyinstaller --onefile --windowed --icon=assets/icon.ico --name="ArchitectsHandBridge" launcher.py
"""

import subprocess
import sys
import os
import time
import signal
import threading
from pathlib import Path

# Configurazione
SCRIPT_DIR = Path(__file__).parent.resolve()
PYTHON_SERVICE_DIR = SCRIPT_DIR / "python-service"
TASKER_SERVICE_SCRIPT = PYTHON_SERVICE_DIR / "tasker_service.py"

# Processi globali
tasker_process = None
electron_process = None
running = True


def find_python():
    """Trova l'interprete Python corretto"""
    # Prova prima python, poi python3, poi py
    for cmd in ["python", "python3", "py"]:
        try:
            result = subprocess.run(
                [cmd, "--version"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            if result.returncode == 0:
                return cmd
        except FileNotFoundError:
            continue
    return "python"


def find_npm():
    """Trova npm"""
    try:
        result = subprocess.run(
            ["npm", "--version"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        if result.returncode == 0:
            return "npm"
    except FileNotFoundError:
        pass
    return None


def start_tasker_service():
    """Avvia Tasker Service (Python FastAPI su porta 8765)"""
    global tasker_process

    python_cmd = find_python()
    print(f"[LAUNCHER] Avvio Tasker Service con {python_cmd}...")

    # Avvia in una nuova finestra console
    if sys.platform == "win32":
        tasker_process = subprocess.Popen(
            [python_cmd, str(TASKER_SERVICE_SCRIPT)],
            cwd=str(PYTHON_SERVICE_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        tasker_process = subprocess.Popen(
            [python_cmd, str(TASKER_SERVICE_SCRIPT)],
            cwd=str(PYTHON_SERVICE_DIR)
        )

    print(f"[LAUNCHER] Tasker Service avviato (PID: {tasker_process.pid})")
    return tasker_process


def start_electron_bridge():
    """Avvia Electron Bridge (npm start)"""
    global electron_process

    npm_cmd = find_npm()
    if not npm_cmd:
        print("[LAUNCHER] ERRORE: npm non trovato!")
        return None

    print(f"[LAUNCHER] Avvio Electron Bridge...")

    # Avvia in una nuova finestra console
    if sys.platform == "win32":
        electron_process = subprocess.Popen(
            ["npm", "start"],
            cwd=str(SCRIPT_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            shell=True
        )
    else:
        electron_process = subprocess.Popen(
            ["npm", "start"],
            cwd=str(SCRIPT_DIR)
        )

    print(f"[LAUNCHER] Electron Bridge avviato (PID: {electron_process.pid})")
    return electron_process


def stop_all():
    """Ferma tutti i processi"""
    global running, tasker_process, electron_process
    running = False

    print("\n[LAUNCHER] Arresto servizi...")

    if electron_process and electron_process.poll() is None:
        print("[LAUNCHER] Arresto Electron Bridge...")
        electron_process.terminate()
        try:
            electron_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            electron_process.kill()

    if tasker_process and tasker_process.poll() is None:
        print("[LAUNCHER] Arresto Tasker Service...")
        tasker_process.terminate()
        try:
            tasker_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tasker_process.kill()

    print("[LAUNCHER] Tutti i servizi arrestati.")


def signal_handler(signum, frame):
    """Gestisce Ctrl+C"""
    stop_all()
    sys.exit(0)


def run_console_mode():
    """Modalità console (senza GUI)"""
    print("=" * 50)
    print("  ARCHITECT'S HAND BRIDGE LAUNCHER")
    print("=" * 50)
    print()

    # Verifica file
    if not TASKER_SERVICE_SCRIPT.exists():
        print(f"[ERRORE] File non trovato: {TASKER_SERVICE_SCRIPT}")
        input("Premi INVIO per uscire...")
        return

    # Registra handler per Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Avvia Tasker Service
    start_tasker_service()
    print("[LAUNCHER] Attendo avvio Tasker Service (3 sec)...")
    time.sleep(3)

    # Avvia Electron Bridge
    start_electron_bridge()

    print()
    print("=" * 50)
    print("  SERVIZI AVVIATI")
    print("  - Tasker Service: http://127.0.0.1:8765")
    print("  - Electron Bridge: in esecuzione")
    print()
    print("  Premi Ctrl+C per arrestare tutto")
    print("=" * 50)

    # Attendi che i processi terminino
    try:
        while running:
            # Controlla se i processi sono ancora attivi
            tasker_alive = tasker_process and tasker_process.poll() is None
            electron_alive = electron_process and electron_process.poll() is None

            if not tasker_alive and not electron_alive:
                print("[LAUNCHER] Tutti i processi terminati.")
                break

            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()


def run_gui_mode():
    """Modalità GUI con tkinter"""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("[LAUNCHER] tkinter non disponibile, uso modalità console")
        run_console_mode()
        return

    class LauncherGUI:
        def __init__(self):
            self.root = tk.Tk()
            self.root.title("Architect's Hand Bridge")
            self.root.geometry("400x300")
            self.root.resizable(False, False)

            # Stile
            style = ttk.Style()
            style.configure("Green.TLabel", foreground="green")
            style.configure("Red.TLabel", foreground="red")
            style.configure("Orange.TLabel", foreground="orange")

            # Frame principale
            main_frame = ttk.Frame(self.root, padding=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            # Titolo
            title = ttk.Label(main_frame, text="Architect's Hand Bridge", font=("Helvetica", 16, "bold"))
            title.pack(pady=(0, 20))

            # Status Tasker Service
            tasker_frame = ttk.Frame(main_frame)
            tasker_frame.pack(fill=tk.X, pady=5)
            ttk.Label(tasker_frame, text="Tasker Service (8765):").pack(side=tk.LEFT)
            self.tasker_status = ttk.Label(tasker_frame, text="⏹ Fermo", style="Red.TLabel")
            self.tasker_status.pack(side=tk.RIGHT)

            # Status Electron Bridge
            electron_frame = ttk.Frame(main_frame)
            electron_frame.pack(fill=tk.X, pady=5)
            ttk.Label(electron_frame, text="Electron Bridge:").pack(side=tk.LEFT)
            self.electron_status = ttk.Label(electron_frame, text="⏹ Fermo", style="Red.TLabel")
            self.electron_status.pack(side=tk.RIGHT)

            # Separatore
            ttk.Separator(main_frame).pack(fill=tk.X, pady=20)

            # Pulsanti
            btn_frame = ttk.Frame(main_frame)
            btn_frame.pack(fill=tk.X)

            self.start_btn = ttk.Button(btn_frame, text="▶ Avvia Tutto", command=self.start_all)
            self.start_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

            self.stop_btn = ttk.Button(btn_frame, text="⏹ Ferma Tutto", command=self.stop_all_gui, state=tk.DISABLED)
            self.stop_btn.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=5)

            # Log
            ttk.Label(main_frame, text="Log:").pack(anchor=tk.W, pady=(20, 5))
            self.log_text = tk.Text(main_frame, height=5, width=40, state=tk.DISABLED)
            self.log_text.pack(fill=tk.BOTH, expand=True)

            # Gestione chiusura
            self.root.protocol("WM_DELETE_WINDOW", self.on_close)

            # Update loop
            self.update_status()

        def log(self, message):
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"{message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        def start_all(self):
            self.start_btn.config(state=tk.DISABLED)
            self.log("Avvio Tasker Service...")

            # Avvia in thread separato
            def start_thread():
                start_tasker_service()
                self.root.after(0, lambda: self.log("Tasker Service avviato"))
                self.root.after(0, lambda: self.tasker_status.config(text="⏳ Avvio...", style="Orange.TLabel"))

                time.sleep(3)

                self.root.after(0, lambda: self.log("Avvio Electron Bridge..."))
                start_electron_bridge()
                self.root.after(0, lambda: self.log("Electron Bridge avviato"))
                self.root.after(0, lambda: self.stop_btn.config(state=tk.NORMAL))

            threading.Thread(target=start_thread, daemon=True).start()

        def stop_all_gui(self):
            self.log("Arresto servizi...")
            stop_all()
            self.log("Servizi arrestati")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

        def update_status(self):
            # Aggiorna status Tasker
            if tasker_process and tasker_process.poll() is None:
                self.tasker_status.config(text="✓ Attivo", style="Green.TLabel")
            else:
                self.tasker_status.config(text="⏹ Fermo", style="Red.TLabel")

            # Aggiorna status Electron
            if electron_process and electron_process.poll() is None:
                self.electron_status.config(text="✓ Attivo", style="Green.TLabel")
            else:
                self.electron_status.config(text="⏹ Fermo", style="Red.TLabel")

            # Ripeti ogni secondo
            self.root.after(1000, self.update_status)

        def on_close(self):
            stop_all()
            self.root.destroy()

        def run(self):
            self.root.mainloop()

    gui = LauncherGUI()
    gui.run()


def main():
    # Cambia directory di lavoro
    os.chdir(SCRIPT_DIR)

    # Controlla argomenti
    if "--no-gui" in sys.argv or "-c" in sys.argv:
        run_console_mode()
    else:
        run_gui_mode()


if __name__ == "__main__":
    main()
