"""Service de scan des fichiers médias."""
import os
import re
import asyncio
from pathlib import Path
from typing import Optional
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    MediaFile, MediaType, ProcessingStatus,
    MediaFileCreate, MediaFileResponse, async_session
)
from app.services.parser import parser, ParsedMedia
from app.services.tmdb import tmdb_service
from app.services.linker import file_linker
from app.services.config_manager import config_manager


class MediaScanner:
    """Service de scan et traitement des fichiers médias."""
    
    # Nombre de fichiers traités en parallèle
    PARALLEL_WORKERS = 15
    # Fréquence des mises à jour SSE (tous les N fichiers)
    SSE_UPDATE_FREQUENCY = 50
    
    # Patterns de fichiers à ignorer (génériques anime uniquement)
    # Note: pas de flags inline (?i), on utilise re.IGNORECASE à la compilation
    IGNORE_PATTERNS = [
        r'creditless',          # Creditless versions (OP/ED sans crédits)
        r'\bNCOP\b',            # No Credit Opening
        r'\bNCED\b',            # No Credit Ending
    ]
    
    # Patterns spécifiques pour OP/ED qui ne sont pas des épisodes
    # Format: "ED1 Creditless", "OP2", "ED Creditless" etc (pas S01E01)
    OPED_PATTERN = r'^(?:.*\s)?(?:OP|ED)\d*(?:\s|v\d|$)'
    
    def __init__(self):
        self._ignore_regex = re.compile('|'.join(self.IGNORE_PATTERNS), re.IGNORECASE)
        self._oped_regex = re.compile(self.OPED_PATTERN, re.IGNORECASE)
    
    @property
    def source_mode(self) -> str:
        return config_manager.get_source_mode()
    
    @property
    def source_path(self) -> Path:
        return config_manager.get_source_path()
    
    @property
    def source_movies_path(self) -> Path:
        return config_manager.get_source_movies_path()
    
    @property
    def source_tv_path(self) -> Path:
        return config_manager.get_source_tv_path()
    
    @property
    def video_extensions(self) -> set[str]:
        return config_manager.get_video_extensions()
    
    @property
    def min_video_size(self) -> int:
        return config_manager.get_min_video_size()
    
    def should_ignore_file(self, filename: str) -> bool:
        """Vérifie si un fichier doit être ignoré (extras, creditless, etc.)."""
        # Si c'est un vrai épisode (S01E01), ne pas ignorer
        if re.search(r'S\d{1,2}E\d{1,2}', filename, re.IGNORECASE):
            return False
        
        # Vérifier les patterns généraux d'ignorance
        if self._ignore_regex.search(filename):
            return True
        
        # Vérifier les patterns OP/ED spécifiques (qui ne sont pas des épisodes)
        if self._oped_regex.search(filename):
            return True
        
        return False
    
    def is_video_file(self, path: Path) -> bool:
        """Vérifie si un fichier est une vidéo valide."""
        if not path.is_file():
            return False
        
        # Vérifier l'extension
        if path.suffix.lower() not in self.video_extensions:
            return False
        
        # Vérifier si le fichier doit être ignoré (extras, creditless, etc.)
        if self.should_ignore_file(path.name):
            return False
        
        # Vérifier la taille minimum
        try:
            if path.stat().st_size < self.min_video_size:
                return False
        except OSError:
            return False
        
        return True
    
    def scan_directory(self, directory: Optional[Path] = None, force_type: Optional[MediaType] = None) -> list[tuple[Path, Optional[MediaType]]]:
        """Scanne un dossier et retourne les fichiers vidéo avec leur type forcé.
        
        Returns:
            Liste de tuples (path, forced_media_type)
        """
        scan_path = directory or self.source_path
        
        if not scan_path.exists():
            return []
        
        video_files = []
        
        for root, dirs, files in os.walk(scan_path):
            # Ignorer les dossiers cachés
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for file in files:
                # Ignorer les fichiers cachés
                if file.startswith('.'):
                    continue
                
                file_path = Path(root) / file
                if self.is_video_file(file_path):
                    video_files.append((file_path, force_type))
        
        return video_files
    
    def scan_all_sources(self) -> list[tuple[Path, Optional[MediaType]]]:
        """Scanne tous les dossiers sources selon le mode configuré."""
        if self.source_mode == "separate":
            # Mode séparé: scanner les deux dossiers avec type forcé
            movies_files = self.scan_directory(self.source_movies_path, MediaType.MOVIE)
            tv_files = self.scan_directory(self.source_tv_path, MediaType.TV)
            return movies_files + tv_files
        else:
            # Mode unifié: scanner un seul dossier sans type forcé
            return self.scan_directory(self.source_path, None)
    
    async def get_or_create_file(
        self,
        session: AsyncSession,
        file_path: Path,
        forced_type: Optional[MediaType] = None
    ) -> tuple[MediaFile, bool]:
        """Récupère ou crée un fichier dans la base de données.
        
        Args:
            session: Session de base de données
            file_path: Chemin du fichier
            forced_type: Type de média forcé (si provient d'un dossier dédié)
        
        Returns:
            Tuple (MediaFile, created)
        """
        # Vérifier si le fichier existe déjà
        result = await session.execute(
            select(MediaFile).where(MediaFile.source_path == str(file_path))
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            return existing, False
        
        # Parser le nom du fichier
        parsed = parser.parse_path(file_path)
        
        # Utiliser le type forcé si fourni, sinon le type parsé
        media_type = forced_type if forced_type else parsed.media_type
        
        # Créer le nouveau fichier
        media_file = MediaFile(
            source_path=str(file_path),
            source_filename=file_path.name,
            file_size=file_path.stat().st_size if file_path.exists() else 0,
            parsed_title=parsed.title,
            parsed_year=parsed.year,
            parsed_season=parsed.season,
            parsed_episode=parsed.episode,
            media_type=media_type,
            status=ProcessingStatus.PENDING,
        )
        
        session.add(media_file)
        return media_file, True
    
    async def process_file(self, session: AsyncSession, media_file: MediaFile) -> MediaFile:
        """Traite un fichier: recherche TMDB et création de lien."""
        try:
            # Rechercher sur TMDB
            match = await tmdb_service.match_media(
                title=media_file.parsed_title or "",
                year=media_file.parsed_year,
                media_type=media_file.media_type,
            )
            
            if not match:
                media_file.status = ProcessingStatus.MANUAL
                media_file.error_message = "Aucune correspondance TMDB trouvée"
                
                # Créer un lien temporaire dans le dossier _Manual
                source_path = Path(media_file.source_path)
                success, message, dest_path = file_linker.link_manual(
                    source_path=source_path,
                    media_type=media_file.media_type
                )
                if success:
                    media_file.destination_path = str(dest_path)
                
                return media_file
            
            # Mettre à jour avec les infos TMDB
            media_file.tmdb_id = match.id
            media_file.tmdb_title = match.title
            media_file.tmdb_year = match.year
            media_file.tmdb_poster = match.poster_path
            media_file.media_type = match.media_type
            media_file.status = ProcessingStatus.MATCHED
            
            # Créer le lien
            await self.create_link(session, media_file)
            
            return media_file
            
        except Exception as e:
            media_file.status = ProcessingStatus.FAILED
            media_file.error_message = str(e)
            return media_file
    
    async def create_link(self, session: AsyncSession, media_file: MediaFile) -> MediaFile:
        """Crée le hardlink pour un fichier."""
        if not media_file.tmdb_id or not media_file.tmdb_title:
            media_file.status = ProcessingStatus.FAILED
            media_file.error_message = "Informations TMDB manquantes"
            return media_file
        
        source_path = Path(media_file.source_path)
        
        try:
            if media_file.media_type == MediaType.MOVIE:
                success, message, dest_path = file_linker.link_movie(
                    source_path=source_path,
                    title=media_file.tmdb_title,
                    year=media_file.tmdb_year,
                    tmdb_id=media_file.tmdb_id,
                )
            elif media_file.media_type == MediaType.TV:
                # Vérifier qu'on a les infos de saison/épisode
                if media_file.parsed_season is None or media_file.parsed_episode is None:
                    media_file.status = ProcessingStatus.MANUAL
                    media_file.error_message = "Saison ou épisode manquant"
                    return media_file
                
                success, message, dest_path = file_linker.link_tv_episode(
                    source_path=source_path,
                    title=media_file.tmdb_title,
                    year=media_file.tmdb_year,
                    tmdb_id=media_file.tmdb_id,
                    season=media_file.parsed_season,
                    episode=media_file.parsed_episode,
                )
            else:
                media_file.status = ProcessingStatus.MANUAL
                media_file.error_message = "Type de média inconnu"
                return media_file
            
            if success:
                media_file.destination_path = str(dest_path)
                media_file.status = ProcessingStatus.LINKED
                media_file.processed_at = datetime.utcnow()
            else:
                media_file.status = ProcessingStatus.FAILED
                media_file.error_message = message
            
            return media_file
            
        except Exception as e:
            media_file.status = ProcessingStatus.FAILED
            media_file.error_message = str(e)
            return media_file
    
    async def get_stats(self, session: AsyncSession) -> dict:
        """Récupère les statistiques actuelles avec détails par type."""
        total = await session.scalar(select(func.count(MediaFile.id)))
        
        stats = {"total_files": total or 0}
        
        # Stats par statut
        for status in ProcessingStatus:
            count = await session.scalar(
                select(func.count(MediaFile.id)).where(MediaFile.status == status)
            )
            stats[status.value] = count or 0
        
        # Stats par type de média (nombre de fichiers)
        movies_total = await session.scalar(
            select(func.count(MediaFile.id)).where(MediaFile.media_type == MediaType.MOVIE)
        )
        tv_total = await session.scalar(
            select(func.count(MediaFile.id)).where(MediaFile.media_type == MediaType.TV)
        )
        stats["movies_total"] = movies_total or 0
        stats["tv_total"] = tv_total or 0  # Nombre d'épisodes
        
        # Nombre de séries distinctes (basé sur tmdb_id unique)
        series_count = await session.scalar(
            select(func.count(func.distinct(MediaFile.tmdb_id))).where(
                MediaFile.media_type == MediaType.TV,
                MediaFile.tmdb_id.isnot(None)
            )
        )
        stats["series_count"] = series_count or 0
        
        # Nombre de séries liées distinctes
        series_linked = await session.scalar(
            select(func.count(func.distinct(MediaFile.tmdb_id))).where(
                MediaFile.media_type == MediaType.TV,
                MediaFile.tmdb_id.isnot(None),
                MediaFile.status == ProcessingStatus.LINKED
            )
        )
        stats["series_linked"] = series_linked or 0
        
        # Stats détaillées par statut ET type
        for status in [ProcessingStatus.LINKED, ProcessingStatus.PENDING, ProcessingStatus.MANUAL, ProcessingStatus.FAILED]:
            movies_count = await session.scalar(
                select(func.count(MediaFile.id)).where(
                    MediaFile.status == status,
                    MediaFile.media_type == MediaType.MOVIE
                )
            )
            tv_count = await session.scalar(
                select(func.count(MediaFile.id)).where(
                    MediaFile.status == status,
                    MediaFile.media_type == MediaType.TV
                )
            )
            stats[f"{status.value}_movies"] = movies_count or 0
            stats[f"{status.value}_tv"] = tv_count or 0
        
        return stats
    
    def file_to_dict(self, media_file: MediaFile) -> dict:
        """Convertit un MediaFile en dictionnaire pour les événements."""
        return {
            "id": media_file.id,
            "source_path": media_file.source_path,
            "source_filename": media_file.source_filename,
            "file_size": media_file.file_size,
            "parsed_title": media_file.parsed_title,
            "parsed_year": media_file.parsed_year,
            "parsed_season": media_file.parsed_season,
            "parsed_episode": media_file.parsed_episode,
            "media_type": media_file.media_type.value if media_file.media_type else None,
            "tmdb_id": media_file.tmdb_id,
            "tmdb_title": media_file.tmdb_title,
            "tmdb_year": media_file.tmdb_year,
            "tmdb_poster": media_file.tmdb_poster,
            "destination_path": media_file.destination_path,
            "status": media_file.status.value if media_file.status else None,
            "error_message": media_file.error_message,
            "created_at": media_file.created_at.isoformat() if media_file.created_at else None,
            "updated_at": media_file.updated_at.isoformat() if media_file.updated_at else None,
            "processed_at": media_file.processed_at.isoformat() if media_file.processed_at else None,
        }
    
    async def cleanup_deleted_files(self, session: AsyncSession, event_manager=None) -> int:
        """Supprime les entrées dont le fichier source n'existe plus.
        
        Returns:
            Nombre de fichiers supprimés
        """
        # Récupérer tous les fichiers de la base
        result = await session.execute(select(MediaFile))
        all_files = result.scalars().all()
        
        deleted_count = 0
        
        for media_file in all_files:
            source_path = Path(media_file.source_path)
            
            # Vérifier si le fichier source existe toujours
            if not source_path.exists():
                # Supprimer le lien de destination si existant
                if media_file.destination_path:
                    dest_path = Path(media_file.destination_path)
                    try:
                        if dest_path.exists() or dest_path.is_symlink():
                            dest_path.unlink()
                            
                            # Nettoyer les dossiers vides
                            parent = dest_path.parent
                            while parent and str(parent) not in [
                                str(config_manager.get_movies_path()),
                                str(config_manager.get_tv_path())
                            ]:
                                try:
                                    if parent.is_dir() and not any(parent.iterdir()):
                                        parent.rmdir()
                                        parent = parent.parent
                                    else:
                                        break
                                except Exception:
                                    break
                    except Exception:
                        pass
                
                # Émettre événement de suppression
                if event_manager:
                    await event_manager.emit_file_deleted({"id": media_file.id})
                
                # Supprimer de la base
                await session.delete(media_file)
                deleted_count += 1
        
        if deleted_count > 0:
            await session.commit()
            
            # Émettre stats mises à jour
            if event_manager:
                current_stats = await self.get_stats(session)
                await event_manager.emit_stats_updated(current_stats)
        
        return deleted_count
    
    async def _process_batch(
        self,
        files_batch: list[tuple[Path, Optional[MediaType]]],
        semaphore: asyncio.Semaphore,
        stats: dict,
        stats_lock: asyncio.Lock,
        event_manager=None,
        processed_counter: dict = None
    ):
        """Traite un batch de fichiers avec contrôle de concurrence."""
        
        async def process_single(file_path: Path, forced_type: Optional[MediaType]):
            async with semaphore:
                # Utiliser une session dédiée par fichier pour éviter les conflits
                async with async_session() as session:
                    try:
                        # Créer ou récupérer le fichier
                        media_file, created = await self.get_or_create_file(session, file_path, forced_type)
                        
                        if created:
                            async with stats_lock:
                                stats["new"] += 1
                        
                        # Traiter seulement les fichiers en attente
                        if media_file.status == ProcessingStatus.PENDING:
                            media_file = await self.process_file(session, media_file)
                            
                            async with stats_lock:
                                stats["processed"] += 1
                                
                                if media_file.status == ProcessingStatus.LINKED:
                                    stats["linked"] += 1
                                elif media_file.status == ProcessingStatus.FAILED:
                                    stats["failed"] += 1
                                elif media_file.status == ProcessingStatus.MANUAL:
                                    stats["manual"] += 1
                        
                        # Commit immédiatement pour cette session
                        await session.commit()
                        
                        # Incrémenter le compteur et émettre progression périodiquement
                        if processed_counter is not None:
                            async with stats_lock:
                                processed_counter["count"] += 1
                                count = processed_counter["count"]
                                total = processed_counter["total"]
                                
                                # Émettre progression tous les N fichiers
                                if event_manager and count % self.SSE_UPDATE_FREQUENCY == 0:
                                    await event_manager.emit_scan_progress(count, total, f"{count}/{total} fichiers traités")
                        
                        return media_file, created
                        
                    except Exception as e:
                        print(f"ERROR processing {file_path}: {e}")
                        return None, False
        
        # Traiter tous les fichiers du batch en parallèle
        tasks = [process_single(fp, ft) for fp, ft in files_batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return results
    
    async def scan_and_process(self, directory: Optional[Path] = None, event_manager=None) -> dict:
        """Scanne et traite tous les nouveaux fichiers avec traitement parallèle."""
        # Si un dossier spécifique est fourni, scanner uniquement celui-ci
        if directory:
            video_files = self.scan_directory(directory, None)
        else:
            # Sinon, utiliser scan_all_sources pour respecter le mode
            video_files = self.scan_all_sources()
        
        stats = {
            "scanned": len(video_files),
            "new": 0,
            "processed": 0,
            "linked": 0,
            "failed": 0,
            "manual": 0,
            "deleted": 0,
        }
        
        # Émettre événement de début
        if event_manager:
            await event_manager.emit_scan_started()
            await event_manager.emit_scan_progress(0, len(video_files), f"Scan de {len(video_files)} fichiers...")
        
        # Semaphore pour limiter les requêtes TMDB concurrentes
        semaphore = asyncio.Semaphore(self.PARALLEL_WORKERS)
        stats_lock = asyncio.Lock()
        processed_counter = {"count": 0, "total": len(video_files)}
        
        # Traiter par batches
        BATCH_SIZE = 100
        
        for i in range(0, len(video_files), BATCH_SIZE):
            batch = video_files[i:i + BATCH_SIZE]
            
            await self._process_batch(
                files_batch=batch,
                semaphore=semaphore,
                stats=stats,
                stats_lock=stats_lock,
                event_manager=event_manager,
                processed_counter=processed_counter
            )
            
            # Émettre stats mises à jour après chaque batch
            if event_manager:
                async with async_session() as session:
                    current_stats = await self.get_stats(session)
                    await event_manager.emit_stats_updated(current_stats)
        
        # Nettoyer les fichiers supprimés (sources qui n'existent plus)
        async with async_session() as session:
            deleted_count = await self.cleanup_deleted_files(session, event_manager)
            stats["deleted"] = deleted_count
            
            # Émettre événement de fin
            if event_manager:
                final_stats = await self.get_stats(session)
                await event_manager.emit_stats_updated(final_stats)
                await event_manager.emit_scan_completed(stats)
        
        return stats


# Instance globale
media_scanner = MediaScanner()
