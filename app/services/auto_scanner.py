"""Service de scan automatique périodique."""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from app.services.config_manager import config_manager
from app.services.scanner import media_scanner
from app.events import event_manager

logger = logging.getLogger(__name__)


class AutoScanner:
    """Gestionnaire de scan automatique."""
    
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_scan: Optional[datetime] = None
        self._next_scan: Optional[datetime] = None
    
    @property
    def is_running(self) -> bool:
        """Indique si l'auto-scan est actif."""
        return self._running
    
    @property
    def last_scan(self) -> Optional[datetime]:
        """Dernière date de scan."""
        return self._last_scan
    
    @property
    def next_scan(self) -> Optional[datetime]:
        """Prochaine date de scan prévue."""
        return self._next_scan
    
    def get_status(self) -> dict:
        """Retourne le statut de l'auto-scan."""
        config = config_manager.load()
        return {
            "enabled": config.auto_scan_enabled,
            "interval": config.auto_scan_interval,
            "unit": config.auto_scan_unit,
            "running": self._running,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "next_scan": self._next_scan.isoformat() if self._next_scan else None,
        }
    
    async def start(self):
        """Démarre le service d'auto-scan."""
        if self._task and not self._task.done():
            logger.info("Auto-scanner déjà démarré")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Auto-scanner démarré")
    
    async def stop(self):
        """Arrête le service d'auto-scan."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._next_scan = None
        logger.info("Auto-scanner arrêté")
    
    async def restart(self):
        """Redémarre le service (utile après changement de config)."""
        await self.stop()
        await self.start()
    
    async def _run_loop(self):
        """Boucle principale de l'auto-scan."""
        while self._running:
            try:
                config = config_manager.load()
                
                if not config.auto_scan_enabled:
                    # Auto-scan désactivé, attendre et revérifier
                    self._next_scan = None
                    await asyncio.sleep(30)  # Vérifier toutes les 30s
                    continue
                
                # Calculer l'intervalle en secondes selon l'unité
                if config.auto_scan_unit == "seconds":
                    interval_seconds = config.auto_scan_interval
                else:  # minutes par défaut
                    interval_seconds = config.auto_scan_interval * 60
                
                # Calculer le prochain scan
                self._next_scan = datetime.now()
                
                # Lancer le scan
                logger.info("Auto-scan: Démarrage du scan automatique...")
                try:
                    await media_scanner.scan_and_process(event_manager=event_manager)
                    self._last_scan = datetime.now()
                    logger.info("Auto-scan: Scan terminé avec succès")
                except Exception as e:
                    logger.error(f"Auto-scan: Erreur pendant le scan: {e}")
                
                # Attendre jusqu'au prochain scan
                self._next_scan = datetime.fromtimestamp(
                    datetime.now().timestamp() + interval_seconds
                )
                unit_label = "secondes" if config.auto_scan_unit == "seconds" else "minutes"
                logger.info(f"Auto-scan: Prochain scan dans {config.auto_scan_interval} {unit_label}")
                
                await asyncio.sleep(interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Auto-scan: Erreur inattendue: {e}")
                await asyncio.sleep(60)  # Attendre 1 minute en cas d'erreur


# Instance globale
auto_scanner = AutoScanner()
