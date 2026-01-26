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


# ============================================================================
# AUTO-RILEVAMENTO ROOT DEL PROGETTO
# ============================================================================

def find_project_root():
    """
    Trova la root del progetto risalendo la gerarchia delle cartelle.
    Cerca package.json e src/main.js come marker del progetto Electron.

    Funziona sia quando:
    - Eseguito come script Python (launcher.py)
    - Eseguito come exe PyInstaller (da qualsiasi posizione)
    """
    # Determina la directory di partenza
    if getattr(sys, 'frozen', False):
        # PyInstaller exe - usa la posizione dell'eseguibile
        start_dir = Path(sys.executable).parent
    else:
        # Script Python normale
        start_dir = Path(__file__).parent

    # Risali fino a 5 livelli cercando i marker del progetto
    current = start_dir
    for _ in range(5):
        # Cerca package.json E src/main.js (marker progetto Electron)
        if (current / "package.json").exists() and (current / "src" / "main.js").exists():
            return current
        current = current.parent

    # Fallback: prova percorsi noti (hardcoded per sicurezza)
    known_paths = [
        Path("D:/downloads/Lux/app lux 1/architects-hand-bridge"),
        Path("C:/architects-hand-bridge"),
        Path.home() / "architects-hand-bridge",
    ]
    for path in known_paths:
        if path.exists() and (path / "package.json").exists():
            return path

    # Ultimo fallback: directory di partenza
    return start_dir


# Configurazione con auto-rilevamento
PROJECT_ROOT = find_project_root()
PYTHON_SERVICE_DIR = PROJECT_ROOT / "python-service"
TASKER_SERVICE_SCRIPT = PYTHON_SERVICE_DIR / "tasker_service.py"
TOOL_SERVER_SCRIPT = PYTHON_SERVICE_DIR / "tool_server.py"

# Processi globali
tasker_process = None
tool_server_process = None
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
    """Trova npm e restituisce il percorso completo"""
    # Su Windows, cerca npm.cmd nel PATH
    if sys.platform == "win32":
        # Prova percorsi comuni
        common_paths = [
            Path("C:/Program Files/nodejs/npm.cmd"),
            Path(os.environ.get("APPDATA", "")) / "npm/npm.cmd",
            Path(os.environ.get("ProgramFiles", "")) / "nodejs/npm.cmd",
        ]
        for npm_path in common_paths:
            if npm_path.exists():
                return str(npm_path)

        # Prova con where
        try:
            result = subprocess.run(
                ["where", "npm.cmd"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except:
            pass

    # Fallback: prova npm direttamente
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
    print(f"[LAUNCHER] Script: {TASKER_SERVICE_SCRIPT}")
    print(f"[LAUNCHER] CWD: {PYTHON_SERVICE_DIR}")

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


def start_tool_server():
    """Avvia Tool Server (Python FastAPI su porta 8766)"""
    global tool_server_process

    python_cmd = find_python()
    print(f"[LAUNCHER] Avvio Tool Server con {python_cmd}...")
    print(f"[LAUNCHER] Script: {TOOL_SERVER_SCRIPT}")
    print(f"[LAUNCHER] CWD: {PYTHON_SERVICE_DIR}")

    # Avvia in una nuova finestra console
    if sys.platform == "win32":
        tool_server_process = subprocess.Popen(
            [python_cmd, str(TOOL_SERVER_SCRIPT)],
            cwd=str(PYTHON_SERVICE_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        tool_server_process = subprocess.Popen(
            [python_cmd, str(TOOL_SERVER_SCRIPT)],
            cwd=str(PYTHON_SERVICE_DIR)
        )

    print(f"[LAUNCHER] Tool Server avviato (PID: {tool_server_process.pid})")
    return tool_server_process


def start_electron_bridge():
    """Avvia Electron Bridge (npm start)"""
    global electron_process

    npm_cmd = find_npm()
    if not npm_cmd:
        print("[LAUNCHER] ERRORE: npm non trovato!")
        return None

    print(f"[LAUNCHER] Avvio Electron Bridge da: {PROJECT_ROOT}")
    print(f"[LAUNCHER] npm path: {npm_cmd}")

    # Avvia in una nuova finestra console
    if sys.platform == "win32":
        # Usa cmd.exe /k per aprire una nuova console che rimane aperta
        # e esegue npm start dalla directory corretta
        cmd_line = f'cmd.exe /k "cd /d {PROJECT_ROOT} && "{npm_cmd}" start"'
        print(f"[LAUNCHER] Comando: {cmd_line}")

        electron_process = subprocess.Popen(
            cmd_line,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        electron_process = subprocess.Popen(
            [npm_cmd, "start"],
            cwd=str(PROJECT_ROOT)
        )

    print(f"[LAUNCHER] Electron Bridge avviato (PID: {electron_process.pid})")
    return electron_process


def stop_all():
    """Ferma tutti i processi"""
    global running, tasker_process, tool_server_process, electron_process
    running = False

    print("\n[LAUNCHER] Arresto servizi...")

    if electron_process and electron_process.poll() is None:
        print("[LAUNCHER] Arresto Electron Bridge...")
        electron_process.terminate()
        try:
            electron_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            electron_process.kill()

    if tool_server_process and tool_server_process.poll() is None:
        print("[LAUNCHER] Arresto Tool Server...")
        tool_server_process.terminate()
        try:
            tool_server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tool_server_process.kill()

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

    if not TOOL_SERVER_SCRIPT.exists():
        print(f"[ERRORE] File non trovato: {TOOL_SERVER_SCRIPT}")
        input("Premi INVIO per uscire...")
        return

    # Registra handler per Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Avvia Tasker Service
    start_tasker_service()
    print("[LAUNCHER] Attendo avvio Tasker Service (2 sec)...")
    time.sleep(2)

    # Avvia Tool Server
    start_tool_server()
    print("[LAUNCHER] Attendo avvio Tool Server (2 sec)...")
    time.sleep(2)

    # Avvia Electron Bridge
    start_electron_bridge()

    print()
    print("=" * 50)
    print("  SERVIZI AVVIATI")
    print("  - Tasker Service: http://127.0.0.1:8765")
    print("  - Tool Server:    http://127.0.0.1:8766")
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
            self.root.geometry("400x350")
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

            # Status Tool Server
            tool_server_frame = ttk.Frame(main_frame)
            tool_server_frame.pack(fill=tk.X, pady=5)
            ttk.Label(tool_server_frame, text="Tool Server (8766):").pack(side=tk.LEFT)
            self.tool_server_status = ttk.Label(tool_server_frame, text="⏹ Fermo", style="Red.TLabel")
            self.tool_server_status.pack(side=tk.RIGHT)

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

            # Log percorsi per debug
            self.log(f"Root: {PROJECT_ROOT}")
            self.log(f"Tasker: {TASKER_SERVICE_SCRIPT.exists()}")
            self.log(f"Tool Server: {TOOL_SERVER_SCRIPT.exists()}")

            if not TASKER_SERVICE_SCRIPT.exists():
                self.log(f"ERRORE: Tasker non trovato!")
                self.start_btn.config(state=tk.NORMAL)
                return

            if not TOOL_SERVER_SCRIPT.exists():
                self.log(f"ERRORE: Tool Server non trovato!")
                self.start_btn.config(state=tk.NORMAL)
                return

            self.log("Avvio Tasker Service...")

            # Avvia in thread separato
            def start_thread():
                start_tasker_service()
                self.root.after(0, lambda: self.log("Tasker Service avviato"))
                self.root.after(0, lambda: self.tasker_status.config(text="⏳ Avvio...", style="Orange.TLabel"))

                time.sleep(2)

                self.root.after(0, lambda: self.log("Avvio Tool Server..."))
                start_tool_server()
                self.root.after(0, lambda: self.log("Tool Server avviato"))
                self.root.after(0, lambda: self.tool_server_status.config(text="⏳ Avvio...", style="Orange.TLabel"))

                time.sleep(2)

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

            # Aggiorna status Tool Server
            if tool_server_process and tool_server_process.poll() is None:
                self.tool_server_status.config(text="✓ Attivo", style="Green.TLabel")
            else:
                self.tool_server_status.config(text="⏹ Fermo", style="Red.TLabel")

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


def log_paths():
    """Stampa i percorsi rilevati per debug"""
    print("=" * 50)
    print("[LAUNCHER] Percorsi rilevati:")
    print(f"  PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"  PYTHON_SERVICE_DIR: {PYTHON_SERVICE_DIR}")
    print(f"  TASKER_SERVICE_SCRIPT: {TASKER_SERVICE_SCRIPT}")
    print(f"  TOOL_SERVER_SCRIPT: {TOOL_SERVER_SCRIPT}")
    print(f"  TASKER exists: {TASKER_SERVICE_SCRIPT.exists()}")
    print(f"  TOOL_SERVER exists: {TOOL_SERVER_SCRIPT.exists()}")
    print(f"  package.json exists: {(PROJECT_ROOT / 'package.json').exists()}")
    print("=" * 50)


def main():
    # Log percorsi per debug
    log_paths()

    # Cambia directory di lavoro
    os.chdir(PROJECT_ROOT)

    # Controlla argomenti
    if "--no-gui" in sys.argv or "-c" in sys.argv:
        run_console_mode()
    else:
        run_gui_mode()


if __name__ == "__main__":
    main()
