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
from pathlib import Path
from typing import Optional, Dict
import aiohttp

# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "1.0.0"

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

        for service_id, service in self.services.items():
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
