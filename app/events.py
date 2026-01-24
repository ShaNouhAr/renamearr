"""Système d'événements en temps réel avec SSE."""
import asyncio
import json
from typing import AsyncGenerator
from dataclasses import dataclass, asdict
from enum import Enum


class EventType(str, Enum):
    FILE_ADDED = "file_added"
    FILE_UPDATED = "file_updated"
    FILE_DELETED = "file_deleted"
    SCAN_STARTED = "scan_started"
    SCAN_PROGRESS = "scan_progress"
    SCAN_COMPLETED = "scan_completed"
    STATS_UPDATED = "stats_updated"
    REPROCESS_STARTED = "reprocess_started"
    REPROCESS_PROGRESS = "reprocess_progress"
    REPROCESS_COMPLETED = "reprocess_completed"


@dataclass
class Event:
    type: EventType
    data: dict


class EventManager:
    """Gestionnaire d'événements pour SSE."""
    
    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []
    
    def subscribe(self) -> asyncio.Queue:
        """Crée une nouvelle souscription aux événements."""
        queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue
    
    def unsubscribe(self, queue: asyncio.Queue):
        """Retire une souscription."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)
    
    async def emit(self, event_type: EventType, data: dict):
        """Émet un événement à tous les abonnés."""
        event = Event(type=event_type, data=data)
        for queue in self._subscribers:
            await queue.put(event)
    
    async def emit_file_added(self, file_data: dict):
        """Émet un événement d'ajout de fichier."""
        await self.emit(EventType.FILE_ADDED, file_data)
    
    async def emit_file_updated(self, file_data: dict):
        """Émet un événement de mise à jour de fichier."""
        await self.emit(EventType.FILE_UPDATED, file_data)
    
    async def emit_file_deleted(self, file_data: dict):
        """Émet un événement de suppression de fichier."""
        await self.emit(EventType.FILE_DELETED, file_data)
    
    async def emit_stats_updated(self, stats: dict):
        """Émet un événement de mise à jour des stats."""
        await self.emit(EventType.STATS_UPDATED, stats)
    
    async def emit_scan_started(self):
        """Émet un événement de début de scan."""
        await self.emit(EventType.SCAN_STARTED, {})
    
    async def emit_scan_progress(self, current: int, total: int, filename: str):
        """Émet un événement de progression du scan."""
        await self.emit(EventType.SCAN_PROGRESS, {
            "current": current,
            "total": total,
            "filename": filename
        })
    
    async def emit_scan_completed(self, stats: dict):
        """Émet un événement de fin de scan."""
        await self.emit(EventType.SCAN_COMPLETED, stats)
    
    async def emit_reprocess_started(self, total: int):
        """Émet un événement de début de retraitement."""
        await self.emit(EventType.REPROCESS_STARTED, {"total": total})
    
    async def emit_reprocess_progress(self, current: int, total: int, linked: int, filename: str):
        """Émet un événement de progression du retraitement."""
        await self.emit(EventType.REPROCESS_PROGRESS, {
            "current": current,
            "total": total,
            "linked": linked,
            "filename": filename
        })
    
    async def emit_reprocess_completed(self, stats: dict):
        """Émet un événement de fin de retraitement."""
        await self.emit(EventType.REPROCESS_COMPLETED, stats)


# Instance globale
event_manager = EventManager()
