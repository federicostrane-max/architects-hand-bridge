#!/usr/bin/env python3
"""
unified_services.py - Unified Service Launcher
===============================================

Launcher unificato che gestisce:
- Tool Server (porta 8766) - Browser automation via Playwright
- Tasker Service (porta 8765) - AI task execution con Lux/Gemini

Funzionalità:
1. Avvia entrambi i servizi come subprocess
2. Monitora con health check periodici
3. Riavvia automaticamente se crashano
4. Singolo entry point per Claude Launcher
5. Graceful shutdown quando il processo padre termina
6. AUTO-CLEANUP: Libera automaticamente le porte occupate prima dell'avvio

Uso:
    python unified_services.py [--no-tool-server] [--no-tasker]

    Opzioni:
        --no-tool-server  Non avviare Tool Server
        --no-tasker       Non avviare Tasker Service
"""

import asyncio
import subprocess
import sys
import signal
import os
import time
import argparse
import logging
import socket
import psutil
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import aiohttp

# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "1.1.0"  # Aggiunto auto-cleanup porte

# Percorsi dei servizi (nella stessa directory di questo script)
SCRIPT_DIR = Path(__file__).parent.absolute()

SERVICES = {
    "tool_server": {
        "name": "Tool Server",
        "script": SCRIPT_DIR / "tool_server.py",
        "port": 8766,
        "health_endpoint": "/",
        "enabled": True
    },
    "tasker_service": {
        "name": "Tasker Service",
        "script": SCRIPT_DIR / "tasker_service.py",
        "port": 8765,
        "health_endpoint": "/status",
        "enabled": True
    }
}

# Health check settings
HEALTH_CHECK_INTERVAL = 10  # secondi tra health check
HEALTH_CHECK_TIMEOUT = 5    # timeout per singola richiesta
MAX_RESTART_ATTEMPTS = 3    # tentativi massimi di restart
RESTART_DELAY = 2           # secondi tra restart

# Logging setup
LOG_DIR = Path.home() / ".claude-launcher"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "unified-services.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# PORT UTILITIES - Verifica e pulizia porte occupate
# ============================================================================

def is_port_in_use(port: int) -> bool:
    """Verifica se una porta è in uso."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return False
        except OSError:
            return True


def get_process_using_port(port: int) -> Optional[Tuple[int, str, str]]:
    """
    Trova il processo che sta usando una porta specifica.
    Ritorna (pid, name, cmdline) oppure None.
    """
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == 'LISTEN':
                try:
                    proc = psutil.Process(conn.pid)
                    cmdline = ' '.join(proc.cmdline()) if proc.cmdline() else proc.name()
                    return (conn.pid, proc.name(), cmdline)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return (conn.pid, "unknown", "unknown")
    except Exception as e:
        logger.warning(f"Errore nel trovare processo su porta {port}: {e}")
    return None


def kill_process_on_port(port: int, force: bool = False) -> bool:
    """
    Termina il processo che sta usando una porta.

    Args:
        port: La porta da liberare
        force: Se True, usa SIGKILL invece di SIGTERM

    Returns:
        True se la porta è stata liberata, False altrimenti
    """
    proc_info = get_process_using_port(port)

    if not proc_info:
        logger.info(f"[Port {port}] Nessun processo in ascolto")
        return True

    pid, name, cmdline = proc_info
    logger.info(f"[Port {port}] Trovato processo PID {pid} ({name})")
    logger.info(f"[Port {port}] Cmdline: {cmdline[:100]}...")

    try:
        proc = psutil.Process(pid)

        # Prima prova con SIGTERM (graceful)
        logger.info(f"[Port {port}] Invio SIGTERM a PID {pid}")
        proc.terminate()

        # Attendi fino a 5 secondi
        try:
            proc.wait(timeout=5)
            logger.info(f"[Port {port}] Processo {pid} terminato gracefully")
        except psutil.TimeoutExpired:
            if force:
                logger.warning(f"[Port {port}] Timeout, invio SIGKILL a PID {pid}")
                proc.kill()
                proc.wait(timeout=3)
                logger.info(f"[Port {port}] Processo {pid} terminato forzatamente")
            else:
                logger.warning(f"[Port {port}] Processo {pid} non risponde a SIGTERM")
                return False

        # Verifica che la porta sia libera
        time.sleep(0.5)  # Attendi che il SO rilasci la porta
        if is_port_in_use(port):
            logger.warning(f"[Port {port}] Porta ancora in uso dopo kill")
            return False

        logger.info(f"[Port {port}] ✅ Porta liberata con successo")
        return True

    except psutil.NoSuchProcess:
        logger.info(f"[Port {port}] Processo {pid} non esiste più")
        return True
    except psutil.AccessDenied:
        logger.error(f"[Port {port}] Accesso negato per terminare PID {pid}")
        return False
    except Exception as e:
        logger.error(f"[Port {port}] Errore terminando processo: {e}")
        return False


def cleanup_ports(ports: List[int], force: bool = True) -> Dict[int, bool]:
    """
    Libera una lista di porte se occupate.

    Args:
        ports: Lista di porte da controllare/liberare
        force: Se True, forza la terminazione se SIGTERM non funziona

    Returns:
        Dict con porta -> True/False (liberata/fallita)
    """
    results = {}

    logger.info(f"=== Verifica porte: {ports} ===")

    for port in ports:
        if is_port_in_use(port):
            logger.warning(f"[Port {port}] ⚠️ OCCUPATA - tentativo di liberarla...")
            results[port] = kill_process_on_port(port, force=force)
        else:
            logger.info(f"[Port {port}] ✅ Libera")
            results[port] = True

    # Riepilogo
    freed = sum(1 for r in results.values() if r)
    blocked = sum(1 for r in results.values() if not r)
    logger.info(f"=== Riepilogo porte: {freed} libere, {blocked} bloccate ===")

    return results


# ============================================================================
# SERVICE MANAGER
# ============================================================================

class ServiceProcess:
    """Gestisce un singolo processo di servizio."""

    def __init__(self, service_id: str, config: dict):
        self.service_id = service_id
        self.name = config["name"]
        self.script = config["script"]
        self.port = config["port"]
        self.health_endpoint = config["health_endpoint"]
        self.process: Optional[subprocess.Popen] = None
        self.restart_count = 0
        self.last_health_check: Optional[float] = None
        self.healthy = False

    def start(self) -> bool:
        """Avvia il servizio."""
        if self.process and self.process.poll() is None:
            logger.warning(f"[{self.name}] Già in esecuzione (PID: {self.process.pid})")
            return True

        if not self.script.exists():
            logger.error(f"[{self.name}] Script non trovato: {self.script}")
            return False

        try:
            # Avvia il processo Python
            self.process = subprocess.Popen(
                [sys.executable, str(self.script)],
                cwd=str(SCRIPT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            )
            logger.info(f"[{self.name}] Avviato (PID: {self.process.pid}, porta: {self.port})")
            return True
        except Exception as e:
            logger.error(f"[{self.name}] Errore avvio: {e}")
            return False

    def stop(self) -> bool:
        """Ferma il servizio."""
        if not self.process:
            return True

        try:
            if sys.platform == "win32":
                # Windows: invia CTRL_BREAK_EVENT
                os.kill(self.process.pid, signal.CTRL_BREAK_EVENT)
            else:
                # Unix: invia SIGTERM
                self.process.terminate()

            # Attendi graceful shutdown
            try:
                self.process.wait(timeout=5)
                logger.info(f"[{self.name}] Terminato gracefully")
            except subprocess.TimeoutExpired:
                # Forza kill
                self.process.kill()
                self.process.wait()
                logger.warning(f"[{self.name}] Terminato forzatamente")

            self.process = None
            self.healthy = False
            return True
        except Exception as e:
            logger.error(f"[{self.name}] Errore stop: {e}")
            return False

    def is_running(self) -> bool:
        """Verifica se il processo è in esecuzione."""
        if not self.process:
            return False
        return self.process.poll() is None

    async def health_check(self) -> bool:
        """Esegue health check via HTTP."""
        url = f"http://localhost:{self.port}{self.health_endpoint}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=HEALTH_CHECK_TIMEOUT)) as resp:
                    self.healthy = resp.status == 200
                    self.last_health_check = time.time()
                    return self.healthy
        except Exception:
            self.healthy = False
            self.last_health_check = time.time()
            return False


class UnifiedServiceManager:
    """Manager principale che gestisce tutti i servizi."""

    def __init__(self):
        self.services: Dict[str, ServiceProcess] = {}
        self.running = False
        self._shutdown_event = asyncio.Event()

    def add_service(self, service_id: str, config: dict):
        """Aggiunge un servizio da gestire."""
        self.services[service_id] = ServiceProcess(service_id, config)

    async def start_all(self):
        """Avvia tutti i servizi configurati."""
        logger.info(f"=== Unified Services Launcher v{VERSION} ===")
        logger.info(f"Servizi da avviare: {len(self.services)}")

        # FASE 1: Libera le porte occupate prima di avviare i servizi
        ports_to_check = [s.port for s in self.services.values()]
        port_results = cleanup_ports(ports_to_check, force=True)

        # Verifica che tutte le porte siano state liberate
        blocked_ports = [p for p, ok in port_results.items() if not ok]
        if blocked_ports:
            logger.error(f"⚠️ Impossibile liberare porte: {blocked_ports}")
            logger.error("Alcuni servizi potrebbero non avviarsi correttamente")

        # FASE 2: Avvia i servizi
        for service_id, service in self.services.items():
            # Salta se la porta non è stata liberata
            if service.port in blocked_ports:
                logger.error(f"[{service.name}] Skipped - porta {service.port} bloccata")
                continue

            if service.start():
                # Attendi che il servizio sia pronto
                await self._wait_for_service(service)
            else:
                logger.error(f"Impossibile avviare {service.name}")

    async def _wait_for_service(self, service: ServiceProcess, timeout: int = 30):
        """Attende che un servizio sia pronto."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if await service.health_check():
                logger.info(f"[{service.name}] Pronto e funzionante")
                return True
            await asyncio.sleep(1)
        logger.warning(f"[{service.name}] Timeout attesa avvio")
        return False

    async def monitor_loop(self):
        """Loop principale di monitoraggio."""
        self.running = True
        logger.info("Avvio monitoraggio servizi...")

        while self.running and not self._shutdown_event.is_set():
            for service_id, service in self.services.items():
                # Verifica se il processo è ancora in esecuzione
                if not service.is_running():
                    logger.warning(f"[{service.name}] Processo terminato inaspettatamente")
                    await self._handle_service_crash(service)
                else:
                    # Health check
                    healthy = await service.health_check()
                    if not healthy:
                        logger.warning(f"[{service.name}] Health check fallito")

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=HEALTH_CHECK_INTERVAL
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout, continua il loop

    async def _handle_service_crash(self, service: ServiceProcess):
        """Gestisce il crash di un servizio."""
        if service.restart_count >= MAX_RESTART_ATTEMPTS:
            logger.error(f"[{service.name}] Raggiunto limite massimo restart ({MAX_RESTART_ATTEMPTS})")
            return

        service.restart_count += 1
        logger.info(f"[{service.name}] Tentativo restart {service.restart_count}/{MAX_RESTART_ATTEMPTS}")

        await asyncio.sleep(RESTART_DELAY)

        # Verifica e libera la porta prima del restart
        if is_port_in_use(service.port):
            logger.warning(f"[{service.name}] Porta {service.port} ancora occupata, tento di liberarla...")
            if not kill_process_on_port(service.port, force=True):
                logger.error(f"[{service.name}] Impossibile liberare porta {service.port}")
                return

        if service.start():
            await self._wait_for_service(service)
        else:
            logger.error(f"[{service.name}] Restart fallito")

    async def stop_all(self):
        """Ferma tutti i servizi."""
        logger.info("Arresto di tutti i servizi...")
        self.running = False
        self._shutdown_event.set()

        for service_id, service in self.services.items():
            service.stop()

        logger.info("Tutti i servizi arrestati")

    def get_status(self) -> dict:
        """Ritorna lo stato di tutti i servizi."""
        return {
            "version": VERSION,
            "services": {
                sid: {
                    "name": s.name,
                    "port": s.port,
                    "running": s.is_running(),
                    "healthy": s.healthy,
                    "restart_count": s.restart_count,
                    "last_health_check": s.last_health_check
                }
                for sid, s in self.services.items()
            }
        }


# ============================================================================
# MAIN
# ============================================================================

manager: Optional[UnifiedServiceManager] = None

def signal_handler(signum, frame):
    """Handler per segnali di terminazione."""
    logger.info(f"Ricevuto segnale {signum}, arresto in corso...")
    if manager:
        # Programma lo shutdown nel event loop
        asyncio.create_task(manager.stop_all())

async def main():
    global manager

    # Parse arguments
    parser = argparse.ArgumentParser(description="Unified Services Launcher")
    parser.add_argument("--no-tool-server", action="store_true", help="Non avviare Tool Server")
    parser.add_argument("--no-tasker", action="store_true", help="Non avviare Tasker Service")
    args = parser.parse_args()

    # Configura manager
    manager = UnifiedServiceManager()

    # Aggiungi servizi abilitati
    for service_id, config in SERVICES.items():
        if service_id == "tool_server" and args.no_tool_server:
            logger.info("Tool Server disabilitato da riga di comando")
            continue
        if service_id == "tasker_service" and args.no_tasker:
            logger.info("Tasker Service disabilitato da riga di comando")
            continue
        manager.add_service(service_id, config)

    if not manager.services:
        logger.error("Nessun servizio da avviare!")
        return

    # Setup signal handlers
    if sys.platform == "win32":
        # Windows
        signal.signal(signal.SIGBREAK, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Avvia tutti i servizi
        await manager.start_all()

        # Stampa stato iniziale
        status = manager.get_status()
        logger.info(f"Stato servizi: {status}")

        # Avvia loop di monitoraggio
        await manager.monitor_loop()

    except KeyboardInterrupt:
        logger.info("Interruzione da tastiera")
    finally:
        await manager.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
