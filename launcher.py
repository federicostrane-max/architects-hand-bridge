#!/usr/bin/env python3
"""
Tool Server Auto-Launcher
=========================
Avvia automaticamente il Tool Server (porta 8766) senza GUI.

Build .exe:
  pyinstaller --onefile --console --icon=assets/icon.ico --name="ArchitectsHandBridge" launcher.py
"""

import subprocess
import sys
import os
import signal
import time
from pathlib import Path


# ============================================================================
# CONFIGURAZIONE
# ============================================================================

def find_tool_server():
    """Trova tool_server.py cercando in varie posizioni"""
    if getattr(sys, 'frozen', False):
        # Eseguito come exe
        exe_dir = Path(sys.executable).parent
    else:
        # Eseguito come script Python
        exe_dir = Path(__file__).parent

    # Posizioni da cercare (in ordine di priorità)
    search_paths = [
        # Stesso livello dell'exe (per release/)
        exe_dir / "tool_server.py",
        # python-service/ nella stessa cartella
        exe_dir / "python-service" / "tool_server.py",
        # Risali di un livello e cerca python-service/
        exe_dir.parent / "python-service" / "tool_server.py",
        # Percorso hardcoded come fallback
        Path("D:/downloads/Lux/app lux 1/architects-hand-bridge/python-service/tool_server.py"),
    ]

    for path in search_paths:
        if path.exists():
            print(f"[LAUNCHER] Trovato tool_server.py: {path}")
            return path

    return None


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
                print(f"[LAUNCHER] Python trovato: {cmd}")
                return cmd
        except FileNotFoundError:
            continue
    return "python"


def start_tool_server(script_path: Path):
    """Avvia Tool Server (porta 8766)"""
    global tool_server_process

    python_cmd = find_python()
    print(f"[LAUNCHER] Avvio Tool Server...")
    print(f"[LAUNCHER] Script: {script_path}")
    print(f"[LAUNCHER] CWD: {script_path.parent}")

    if sys.platform == "win32":
        tool_server_process = subprocess.Popen(
            [python_cmd, str(script_path)],
            cwd=str(script_path.parent),
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        tool_server_process = subprocess.Popen(
            [python_cmd, str(script_path)],
            cwd=str(script_path.parent)
        )

    print(f"[LAUNCHER] Tool Server avviato (PID: {tool_server_process.pid})")
    return tool_server_process


def stop_tool_server():
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
    stop_tool_server()
    sys.exit(0)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 50)
    print("  TOOL SERVER AUTO-LAUNCHER v12.6")
    print("=" * 50)
    print()

    # Trova tool_server.py
    tool_server_script = find_tool_server()

    if not tool_server_script:
        print("[ERRORE] tool_server.py non trovato!")
        print("[ERRORE] Assicurati che tool_server.py sia nella stessa cartella")
        print("[ERRORE] o in python-service/")
        input("\nPremi INVIO per uscire...")
        return

    # Registra handler per Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Avvia automaticamente
    start_tool_server(tool_server_script)

    print()
    print("=" * 50)
    print("  Tool Server ATTIVO: http://127.0.0.1:8766")
    print()
    print("  Chiudi questa finestra per arrestare")
    print("=" * 50)
    print()

    # Attendi che il processo termini
    try:
        while running:
            if tool_server_process and tool_server_process.poll() is not None:
                exit_code = tool_server_process.returncode
                print(f"[LAUNCHER] Tool Server terminato (exit code: {exit_code})")
                if exit_code != 0:
                    print("[LAUNCHER] Tool Server crashed! Controlla gli errori sopra.")
                    input("\nPremi INVIO per uscire...")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_tool_server()


if __name__ == "__main__":
    main()
