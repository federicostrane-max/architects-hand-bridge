#!/usr/bin/env python3
"""
Tool Server Launcher
====================
Avvia solo il Tool Server (porta 8766) per browser automation.

Uso:
  python launcher.py          # Avvia con GUI
  python launcher.py --no-gui # Avvia senza GUI (console only)

Build .exe:
  pyinstaller --onefile --windowed --icon=assets/icon.ico --name="ArchitectsHandBridge" launcher.py
"""

import subprocess
import sys
import os
import signal
from pathlib import Path


# ============================================================================
# CONFIGURAZIONE
# ============================================================================

def find_project_root():
    """Trova la root del progetto"""
    if getattr(sys, 'frozen', False):
        start_dir = Path(sys.executable).parent
    else:
        start_dir = Path(__file__).parent

    # Cerca python-service/tool_server.py come marker
    current = start_dir
    for _ in range(5):
        if (current / "python-service" / "tool_server.py").exists():
            return current
        current = current.parent

    return start_dir


PROJECT_ROOT = find_project_root()
PYTHON_SERVICE_DIR = PROJECT_ROOT / "python-service"
TOOL_SERVER_SCRIPT = PYTHON_SERVICE_DIR / "tool_server.py"

# Processo globale
tool_server_process = None
running = True


# ============================================================================
# FUNZIONI
# ============================================================================

def find_python():
    """Trova l'interprete Python"""
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


def start_tool_server():
    """Avvia Tool Server (porta 8766)"""
    global tool_server_process

    python_cmd = find_python()
    print(f"[LAUNCHER] Avvio Tool Server...")
    print(f"[LAUNCHER] Script: {TOOL_SERVER_SCRIPT}")

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


def stop_all():
    """Ferma Tool Server"""
    global running, tool_server_process
    running = False

    print("\n[LAUNCHER] Arresto Tool Server...")

    if tool_server_process and tool_server_process.poll() is None:
        tool_server_process.terminate()
        try:
            tool_server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tool_server_process.kill()

    print("[LAUNCHER] Tool Server arrestato.")


def signal_handler(signum, frame):
    """Gestisce Ctrl+C"""
    stop_all()
    sys.exit(0)


# ============================================================================
# MODALITA' CONSOLE
# ============================================================================

def run_console_mode():
    """Avvia in modalità console"""
    print("=" * 50)
    print("  TOOL SERVER LAUNCHER")
    print("=" * 50)
    print()

    if not TOOL_SERVER_SCRIPT.exists():
        print(f"[ERRORE] File non trovato: {TOOL_SERVER_SCRIPT}")
        input("Premi INVIO per uscire...")
        return

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    start_tool_server()

    print()
    print("=" * 50)
    print("  Tool Server: http://127.0.0.1:8766")
    print()
    print("  Premi Ctrl+C per arrestare")
    print("=" * 50)

    try:
        while running:
            if tool_server_process and tool_server_process.poll() is not None:
                print("[LAUNCHER] Tool Server terminato.")
                break
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()


# ============================================================================
# MODALITA' GUI
# ============================================================================

def run_gui_mode():
    """Avvia con GUI tkinter"""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("[LAUNCHER] tkinter non disponibile, uso console")
        run_console_mode()
        return

    import threading
    import time

    class LauncherGUI:
        def __init__(self):
            self.root = tk.Tk()
            self.root.title("Tool Server Launcher")
            self.root.geometry("350x200")
            self.root.resizable(False, False)

            style = ttk.Style()
            style.configure("Green.TLabel", foreground="green")
            style.configure("Red.TLabel", foreground="red")
            style.configure("Orange.TLabel", foreground="orange")

            main_frame = ttk.Frame(self.root, padding=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            title = ttk.Label(main_frame, text="Tool Server Launcher", font=("Helvetica", 14, "bold"))
            title.pack(pady=(0, 15))

            # Status Tool Server
            status_frame = ttk.Frame(main_frame)
            status_frame.pack(fill=tk.X, pady=10)
            ttk.Label(status_frame, text="Tool Server (8766):").pack(side=tk.LEFT)
            self.status_label = ttk.Label(status_frame, text="⏹ Fermo", style="Red.TLabel")
            self.status_label.pack(side=tk.RIGHT)

            ttk.Separator(main_frame).pack(fill=tk.X, pady=15)

            # Pulsanti
            btn_frame = ttk.Frame(main_frame)
            btn_frame.pack(fill=tk.X)

            self.start_btn = ttk.Button(btn_frame, text="▶ Avvia", command=self.start_server)
            self.start_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

            self.stop_btn = ttk.Button(btn_frame, text="⏹ Ferma", command=self.stop_server, state=tk.DISABLED)
            self.stop_btn.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=5)

            self.root.protocol("WM_DELETE_WINDOW", self.on_close)
            self.update_status()

        def start_server(self):
            self.start_btn.config(state=tk.DISABLED)

            if not TOOL_SERVER_SCRIPT.exists():
                self.status_label.config(text="✗ File non trovato", style="Red.TLabel")
                self.start_btn.config(state=tk.NORMAL)
                return

            def start_thread():
                self.root.after(0, lambda: self.status_label.config(text="⏳ Avvio...", style="Orange.TLabel"))
                start_tool_server()
                time.sleep(2)
                self.root.after(0, lambda: self.stop_btn.config(state=tk.NORMAL))

            threading.Thread(target=start_thread, daemon=True).start()

        def stop_server(self):
            stop_all()
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

        def update_status(self):
            if tool_server_process and tool_server_process.poll() is None:
                self.status_label.config(text="✓ Attivo", style="Green.TLabel")
            else:
                self.status_label.config(text="⏹ Fermo", style="Red.TLabel")

            self.root.after(1000, self.update_status)

        def on_close(self):
            stop_all()
            self.root.destroy()

        def run(self):
            self.root.mainloop()

    gui = LauncherGUI()
    gui.run()


# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"[LAUNCHER] Tool Server: {TOOL_SERVER_SCRIPT}")
    print(f"[LAUNCHER] Exists: {TOOL_SERVER_SCRIPT.exists()}")

    os.chdir(PROJECT_ROOT)

    if "--no-gui" in sys.argv or "-c" in sys.argv:
        run_console_mode()
    else:
        run_gui_mode()


if __name__ == "__main__":
    main()
