"""API FastAPI pour la gestion des fichiers médias."""
import os
import json
import asyncio
from pathlib import Path
from typing import Optional, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.models import (
    MediaFile, MediaType, ProcessingStatus,
    MediaFileResponse, MediaFileUpdate, ManualMatchRequest,
    TMDBSearchResult, ScanRequest, StatsResponse,
    get_session
)
from app.services.tmdb import tmdb_service
from app.services.scanner import media_scanner
from app.services.linker import file_linker
from app.services.config_manager import config_manager, AppConfig
from app.services.arr_integration import radarr_service, sonarr_service
from app.services.auto_scanner import auto_scanner
from app.events import event_manager, EventType


router = APIRouter(prefix="/api", tags=["media"])


# ============== SSE Events ==============

async def event_generator() -> AsyncGenerator[str, None]:
    """Génère les événements SSE."""
    queue = event_manager.subscribe()
    try:
        while True:
            try:
                # Attendre un événement avec timeout pour envoyer des heartbeats
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                data = json.dumps({
                    "type": event.type.value,
                    "data": event.data
                })
                yield f"data: {data}\n\n"
            except asyncio.TimeoutError:
                # Envoyer un heartbeat pour garder la connexion ouverte
                yield f": heartbeat\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        event_manager.unsubscribe(queue)


@router.get("/events")
async def sse_events():
    """Endpoint SSE pour les événements en temps réel."""
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ============== Config ==============

class ConfigUpdateRequest(BaseModel):
    """Requête de mise à jour de la configuration."""
    source_mode: Optional[str] = None
    source_path: Optional[str] = None
    source_movies_path: Optional[str] = None
    source_tv_path: Optional[str] = None
    movies_path: Optional[str] = None
    tv_path: Optional[str] = None
    radarr_url: Optional[str] = None
    radarr_api_key: Optional[str] = None
    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    require_arr: Optional[bool] = None
    auto_scan_enabled: Optional[bool] = None
    auto_scan_interval: Optional[int] = None
    auto_scan_unit: Optional[str] = None
    tmdb_language: Optional[str] = None
    min_video_size_mb: Optional[int] = None
    video_extensions: Optional[list[str]] = None


class DirectoryItem(BaseModel):
    """Item d'un dossier."""
    name: str
    path: str
    is_dir: bool


@router.get("/config", response_model=AppConfig)
async def get_config():
    """Récupère la configuration actuelle."""
    return config_manager.load()


@router.put("/config", response_model=AppConfig)
async def update_config(request: ConfigUpdateRequest):
    """Met à jour la configuration."""
    # Valider le mode
    if request.source_mode and request.source_mode not in ["unified", "separate"]:
        raise HTTPException(status_code=400, detail="Mode invalide: utilisez 'unified' ou 'separate'")
    
    # Chemins destination à créer si nécessaire
    dest_paths = ["movies_path", "tv_path"]
    for path_field in dest_paths:
        path_value = getattr(request, path_field)
        if path_value:
            path = Path(path_value)
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Impossible de créer le dossier {path_value}: {e}"
                )
    
    # Vérifier si les paramètres d'auto-scan ont changé
    old_config = config_manager.load()
    auto_scan_changed = (
        request.auto_scan_enabled is not None and request.auto_scan_enabled != old_config.auto_scan_enabled
    ) or (
        request.auto_scan_interval is not None and request.auto_scan_interval != old_config.auto_scan_interval
    ) or (
        request.auto_scan_unit is not None and request.auto_scan_unit != old_config.auto_scan_unit
    )
    
    result = config_manager.update(**request.model_dump(exclude_unset=True))
    
    # Redémarrer l'auto-scanner si la config a changé
    if auto_scan_changed:
        await auto_scanner.restart()
    
    return result


@router.get("/auto-scan/status")
async def get_auto_scan_status():
    """Retourne le statut de l'auto-scan."""
    return auto_scanner.get_status()


@router.post("/auto-scan/restart")
async def restart_auto_scan():
    """Redémarre l'auto-scanner."""
    await auto_scanner.restart()
    return {"message": "Auto-scanner redémarré", "status": auto_scanner.get_status()}


@router.post("/config/test-radarr")
async def test_radarr():
    """Teste la connexion à Radarr."""
    success, message = await radarr_service.test_connection()
    return {"success": success, "message": message}


@router.post("/config/test-sonarr")
async def test_sonarr():
    """Teste la connexion à Sonarr."""
    success, message = await sonarr_service.test_connection()
    return {"success": success, "message": message}


class CreateFolderRequest(BaseModel):
    """Requête pour créer un dossier."""
    path: str
    name: str


@router.post("/browse/create")
async def create_directory(request: CreateFolderRequest):
    """Crée un nouveau dossier."""
    parent = Path(request.path)
    
    if not parent.exists():
        raise HTTPException(status_code=404, detail="Dossier parent introuvable")
    
    # Nettoyer le nom du dossier
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nom de dossier invalide")
    
    # Caractères interdits
    invalid_chars = '<>:"|?*\\'
    for char in invalid_chars:
        if char in name:
            raise HTTPException(status_code=400, detail=f"Caractère interdit dans le nom: {char}")
    
    new_path = parent / name
    
    if new_path.exists():
        raise HTTPException(status_code=400, detail="Ce dossier existe déjà")
    
    try:
        new_path.mkdir(parents=True, exist_ok=False)
        return {"message": "Dossier créé", "path": str(new_path)}
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission refusée")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {e}")


@router.get("/browse", response_model=list[DirectoryItem])
async def browse_directory(path: str = "/mnt"):
    """Navigue dans les dossiers du système."""
    target = Path(path)
    
    # Si le chemin n'existe pas, retourner à /mnt
    if not target.exists():
        target = Path("/mnt")
    
    if not target.is_dir():
        target = Path("/mnt")
    
    items = []
    
    # Ajouter le parent si on n'est pas à la racine /mnt
    if str(target) != "/mnt" and str(target) != "/":
        items.append(DirectoryItem(
            name=".. (retour)",
            path=str(target.parent),
            is_dir=True
        ))
    
    try:
        for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            # Ignorer les fichiers/dossiers cachés
            if item.name.startswith('.'):
                continue
            
            try:
                # Vérifier si c'est un dossier accessible
                is_dir = item.is_dir()
                items.append(DirectoryItem(
                    name=item.name,
                    path=str(item),
                    is_dir=is_dir
                ))
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        raise HTTPException(status_code=403, detail="Accès refusé à ce dossier")
    
    return items


# ============== Stats ==============

@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Retourne les statistiques du système avec détails par type."""
    stats = await media_scanner.get_stats(session)
    return stats


# ============== Files ==============

class GroupedMediaResponse(BaseModel):
    """Réponse pour les médias groupés."""
    key: str
    title: str
    tmdb_id: Optional[int] = None
    media_type: str
    year: Optional[int] = None
    poster: Optional[str] = None
    total_files: int = 0
    linked_files: int = 0
    pending_files: int = 0
    manual_files: int = 0
    failed_files: int = 0
    seasons: Optional[dict] = None  # Pour les séries: {1: [episodes], 2: [episodes]}
    files: Optional[list] = None    # Pour les films


@router.get("/files/grouped")
async def list_files_grouped(
    status: Optional[ProcessingStatus] = None,
    media_type: Optional[MediaType] = None,
    search: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """Liste les fichiers groupés par média."""
    query = select(MediaFile)
    
    if status:
        query = query.where(MediaFile.status == status)
    
    if media_type:
        query = query.where(MediaFile.media_type == media_type)
    
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            (MediaFile.source_filename.ilike(search_pattern)) |
            (MediaFile.parsed_title.ilike(search_pattern)) |
            (MediaFile.tmdb_title.ilike(search_pattern))
        )
    
    query = query.order_by(MediaFile.tmdb_title, MediaFile.parsed_season, MediaFile.parsed_episode)
    
    result = await session.execute(query)
    files = result.scalars().all()
    
    # Grouper par média
    groups = {}
    
    for f in files:
        # Clé de groupement: tmdb_id + type ou titre parsé
        media_type_str = f.media_type.value if f.media_type else "unknown"
        if f.tmdb_id:
            key = f"{f.tmdb_id}_{media_type_str}"
        else:
            key = f"{f.parsed_title or f.source_filename}_{media_type_str}"
        
        if key not in groups:
            groups[key] = {
                "key": key,
                "title": f.tmdb_title or f.parsed_title or f.source_filename,
                "tmdb_id": f.tmdb_id,
                "media_type": media_type_str,
                "year": f.tmdb_year or f.parsed_year,
                "poster": f.tmdb_poster,
                "total_files": 0,
                "linked_files": 0,
                "pending_files": 0,
                "manual_files": 0,
                "failed_files": 0,
                "seasons": {} if f.media_type == MediaType.TV else None,
                "files": [] if f.media_type != MediaType.TV else None,
            }
        
        group = groups[key]
        group["total_files"] += 1
        
        # Compter les statuts
        if f.status == ProcessingStatus.LINKED:
            group["linked_files"] += 1
        elif f.status == ProcessingStatus.PENDING:
            group["pending_files"] += 1
        elif f.status == ProcessingStatus.MANUAL:
            group["manual_files"] += 1
        elif f.status == ProcessingStatus.FAILED:
            group["failed_files"] += 1
        
        # Fichier simplifié
        file_data = {
            "id": f.id,
            "source_filename": f.source_filename,
            "source_path": f.source_path,
            "status": f.status.value,
            "season": f.parsed_season,
            "episode": f.parsed_episode,
            "error_message": f.error_message,
        }
        
        # Ajouter au groupe approprié
        if f.media_type == MediaType.TV:
            season = f.parsed_season if f.parsed_season is not None else 0
            if season not in group["seasons"]:
                group["seasons"][season] = []
            group["seasons"][season].append(file_data)
        else:
            group["files"].append(file_data)
    
    # Trier les saisons et épisodes
    for key, group in groups.items():
        if group["seasons"]:
            # Trier les saisons
            sorted_seasons = {}
            for s in sorted(group["seasons"].keys()):
                # Trier les épisodes dans chaque saison
                sorted_seasons[s] = sorted(
                    group["seasons"][s],
                    key=lambda x: x["episode"] or 0
                )
            group["seasons"] = sorted_seasons
    
    # Convertir en liste et trier par titre
    result_list = sorted(groups.values(), key=lambda x: x["title"].lower() if x["title"] else "")
    
    return result_list


@router.get("/files", response_model=list[MediaFileResponse])
async def list_files(
    status: Optional[ProcessingStatus] = None,
    media_type: Optional[MediaType] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    session: AsyncSession = Depends(get_session)
):
    """Liste les fichiers médias avec filtres."""
    query = select(MediaFile)
    
    if status:
        query = query.where(MediaFile.status == status)
    
    if media_type:
        query = query.where(MediaFile.media_type == media_type)
    
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            (MediaFile.source_filename.ilike(search_pattern)) |
            (MediaFile.parsed_title.ilike(search_pattern)) |
            (MediaFile.tmdb_title.ilike(search_pattern))
        )
    
    query = query.order_by(MediaFile.created_at.desc())
    query = query.limit(limit).offset(offset)
    
    result = await session.execute(query)
    files = result.scalars().all()
    
    return [MediaFileResponse.model_validate(f) for f in files]


@router.get("/files/{file_id}", response_model=MediaFileResponse)
async def get_file(file_id: int, session: AsyncSession = Depends(get_session)):
    """Récupère un fichier par son ID."""
    result = await session.execute(
        select(MediaFile).where(MediaFile.id == file_id)
    )
    media_file = result.scalar_one_or_none()
    
    if not media_file:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    return MediaFileResponse.model_validate(media_file)


@router.patch("/files/{file_id}", response_model=MediaFileResponse)
async def update_file(
    file_id: int,
    update: MediaFileUpdate,
    session: AsyncSession = Depends(get_session)
):
    """Met à jour un fichier."""
    result = await session.execute(
        select(MediaFile).where(MediaFile.id == file_id)
    )
    media_file = result.scalar_one_or_none()
    
    if not media_file:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    # Mettre à jour les champs fournis
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(media_file, key, value)
    
    await session.commit()
    await session.refresh(media_file)
    
    return MediaFileResponse.model_validate(media_file)


@router.delete("/files/{file_id}")
async def delete_file(file_id: int, session: AsyncSession = Depends(get_session)):
    """Supprime un fichier de la base et son lien."""
    result = await session.execute(
        select(MediaFile).where(MediaFile.id == file_id)
    )
    media_file = result.scalar_one_or_none()
    
    if not media_file:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    # Supprimer le lien si existant
    if media_file.destination_path:
        file_linker.remove_link(Path(media_file.destination_path))
    
    await session.delete(media_file)
    await session.commit()
    
    return {"message": "Fichier supprimé"}


@router.post("/files/{file_id}/ignore", response_model=MediaFileResponse)
async def ignore_file(file_id: int, session: AsyncSession = Depends(get_session)):
    """Marque un fichier comme ignoré."""
    result = await session.execute(
        select(MediaFile).where(MediaFile.id == file_id)
    )
    media_file = result.scalar_one_or_none()
    
    if not media_file:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    media_file.status = ProcessingStatus.IGNORED
    await session.commit()
    await session.refresh(media_file)
    
    # Émettre événement de mise à jour
    await event_manager.emit_file_updated(media_scanner.file_to_dict(media_file))
    stats = await media_scanner.get_stats(session)
    await event_manager.emit_stats_updated(stats)
    
    return MediaFileResponse.model_validate(media_file)


@router.post("/files/{file_id}/reprocess", response_model=MediaFileResponse)
async def reprocess_file(file_id: int, session: AsyncSession = Depends(get_session)):
    """Relance le traitement d'un fichier avec re-parsing."""
    result = await session.execute(
        select(MediaFile).where(MediaFile.id == file_id)
    )
    media_file = result.scalar_one_or_none()
    
    if not media_file:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    # Supprimer l'ancien lien si existant
    if media_file.destination_path:
        file_linker.remove_link(Path(media_file.destination_path))
        media_file.destination_path = None
    
    # Re-parser le nom du fichier pour obtenir les nouvelles valeurs
    from app.services.parser import parser
    file_path = Path(media_file.source_path)
    parsed = parser.parse_path(file_path)
    
    # Mettre à jour les valeurs parsées
    media_file.parsed_title = parsed.title
    media_file.parsed_year = parsed.year
    media_file.parsed_season = parsed.season
    media_file.parsed_episode = parsed.episode
    if parsed.media_type != MediaType.UNKNOWN:
        media_file.media_type = parsed.media_type
    
    # Remettre en attente et nettoyer les infos TMDB
    media_file.status = ProcessingStatus.PENDING
    media_file.error_message = None
    media_file.tmdb_id = None
    media_file.tmdb_title = None
    media_file.tmdb_year = None
    media_file.tmdb_poster = None
    await session.commit()
    
    # Retraiter
    media_file = await media_scanner.process_file(session, media_file)
    await session.commit()
    
    # Émettre événement de mise à jour
    await event_manager.emit_file_updated(media_scanner.file_to_dict(media_file))
    stats = await media_scanner.get_stats(session)
    await event_manager.emit_stats_updated(stats)
    
    return MediaFileResponse.model_validate(media_file)


@router.post("/files/reprocess-all")
async def reprocess_all_files(session: AsyncSession = Depends(get_session)):
    """Relance le traitement de tous les fichiers en statut MANUAL ou FAILED."""
    from app.services.parser import parser
    
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.status.in_([ProcessingStatus.MANUAL, ProcessingStatus.FAILED])
        )
    )
    files_to_reprocess = result.scalars().all()
    
    count = len(files_to_reprocess)
    processed = 0
    linked = 0
    
    for media_file in files_to_reprocess:
        # Supprimer l'ancien lien si existant
        if media_file.destination_path:
            file_linker.remove_link(Path(media_file.destination_path))
            media_file.destination_path = None
        
        # Re-parser le nom du fichier
        file_path = Path(media_file.source_path)
        parsed = parser.parse_path(file_path)
        
        # Mettre à jour les valeurs parsées
        media_file.parsed_title = parsed.title
        media_file.parsed_year = parsed.year
        media_file.parsed_season = parsed.season
        media_file.parsed_episode = parsed.episode
        if parsed.media_type != MediaType.UNKNOWN:
            media_file.media_type = parsed.media_type
        
        # Remettre en attente
        media_file.status = ProcessingStatus.PENDING
        media_file.error_message = None
        media_file.tmdb_id = None
        media_file.tmdb_title = None
        media_file.tmdb_year = None
        media_file.tmdb_poster = None
        
        # Retraiter
        media_file = await media_scanner.process_file(session, media_file)
        processed += 1
        
        if media_file.status == ProcessingStatus.LINKED:
            linked += 1
        
        # Émettre événement de mise à jour
        await event_manager.emit_file_updated(media_scanner.file_to_dict(media_file))
    
    await session.commit()
    
    # Émettre stats mises à jour
    stats = await media_scanner.get_stats(session)
    await event_manager.emit_stats_updated(stats)
    
    return {
        "message": f"{processed} fichiers retraités, {linked} liés",
        "total": count,
        "processed": processed,
        "linked": linked
    }


# ============== Manual Match ==============

@router.post("/files/{file_id}/match", response_model=MediaFileResponse)
async def manual_match(
    file_id: int,
    match: ManualMatchRequest,
    session: AsyncSession = Depends(get_session)
):
    """Associe manuellement un fichier à un média TMDB."""
    result = await session.execute(
        select(MediaFile).where(MediaFile.id == file_id)
    )
    media_file = result.scalar_one_or_none()
    
    if not media_file:
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    # Récupérer les détails TMDB
    if match.media_type == MediaType.MOVIE:
        details = await tmdb_service.get_movie_details(match.tmdb_id)
        if details:
            media_file.tmdb_title = details.get("title")
            release_date = details.get("release_date", "")
            media_file.tmdb_year = int(release_date[:4]) if release_date else None
            poster = details.get("poster_path")
            media_file.tmdb_poster = f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
    else:
        details = await tmdb_service.get_tv_details(match.tmdb_id)
        if details:
            media_file.tmdb_title = details.get("name")
            first_air = details.get("first_air_date", "")
            media_file.tmdb_year = int(first_air[:4]) if first_air else None
            poster = details.get("poster_path")
            media_file.tmdb_poster = f"https://image.tmdb.org/t/p/w500{poster}" if poster else None
    
    if not details:
        raise HTTPException(status_code=404, detail="Média TMDB non trouvé")
    
    # Mettre à jour les infos
    media_file.tmdb_id = match.tmdb_id
    media_file.media_type = match.media_type
    
    if match.season is not None:
        media_file.parsed_season = match.season
    if match.episode is not None:
        media_file.parsed_episode = match.episode
    
    media_file.status = ProcessingStatus.MATCHED
    media_file.error_message = None
    
    await session.commit()
    
    # Supprimer l'ancien lien si existant
    if media_file.destination_path:
        file_linker.remove_link(Path(media_file.destination_path))
    
    # Créer le nouveau lien
    media_file = await media_scanner.create_link(session, media_file)
    
    # Émettre événement de mise à jour
    await event_manager.emit_file_updated(media_scanner.file_to_dict(media_file))
    stats = await media_scanner.get_stats(session)
    await event_manager.emit_stats_updated(stats)
    
    return MediaFileResponse.model_validate(media_file)


# ============== TMDB Search ==============

@router.get("/tmdb/search", response_model=list[TMDBSearchResult])
async def search_tmdb(
    query: str,
    year: Optional[int] = None,
    media_type: Optional[MediaType] = None
):
    """Recherche sur TMDB."""
    if not query:
        return []
    
    if media_type == MediaType.MOVIE:
        return await tmdb_service.search_movie(query, year)
    elif media_type == MediaType.TV:
        return await tmdb_service.search_tv(query, year)
    else:
        return await tmdb_service.search_multi(query, year)


# ============== Scanner ==============

# Variable globale pour suivre l'état du scan
_scan_in_progress = False


async def _run_scan_background(directory: Optional[Path] = None):
    """Exécute le scan en arrière-plan."""
    global _scan_in_progress
    try:
        await media_scanner.scan_and_process(directory, event_manager)
    finally:
        _scan_in_progress = False


@router.post("/scan")
async def scan_files(request: ScanRequest = None):
    """Lance un scan des fichiers en arrière-plan."""
    global _scan_in_progress
    
    # Vérifier si un scan est déjà en cours
    if _scan_in_progress:
        raise HTTPException(
            status_code=409,
            detail="Un scan est déjà en cours"
        )
    
    config = config_manager.load()
    
    # Vérifier si Radarr/Sonarr sont obligatoires
    if config.require_arr:
        radarr_ok, radarr_msg = await radarr_service.test_connection()
        sonarr_ok, sonarr_msg = await sonarr_service.test_connection()
        
        if not radarr_ok:
            raise HTTPException(
                status_code=400,
                detail=f"Radarr non connecté: {radarr_msg}. Configurez Radarr ou désactivez l'option 'Exiger Radarr/Sonarr'."
            )
        if not sonarr_ok:
            raise HTTPException(
                status_code=400,
                detail=f"Sonarr non connecté: {sonarr_msg}. Configurez Sonarr ou désactivez l'option 'Exiger Radarr/Sonarr'."
            )
    
    directory = Path(request.path) if request and request.path else None
    
    # Marquer le scan comme en cours
    _scan_in_progress = True
    
    # Lancer le scan en arrière-plan (non bloquant)
    asyncio.create_task(_run_scan_background(directory))
    
    return {
        "message": "Scan démarré en arrière-plan",
        "status": "started"
    }


@router.post("/process-pending")
async def process_pending(session: AsyncSession = Depends(get_session)):
    """Traite tous les fichiers en attente."""
    result = await session.execute(
        select(MediaFile).where(MediaFile.status == ProcessingStatus.PENDING)
    )
    pending_files = result.scalars().all()
    
    processed = 0
    linked = 0
    failed = 0
    
    for media_file in pending_files:
        media_file = await media_scanner.process_file(session, media_file)
        processed += 1
        
        if media_file.status == ProcessingStatus.LINKED:
            linked += 1
        elif media_file.status in [ProcessingStatus.FAILED, ProcessingStatus.MANUAL]:
            failed += 1
    
    return {
        "message": "Traitement terminé",
        "processed": processed,
        "linked": linked,
        "failed": failed
    }


@router.post("/retry-failed")
async def retry_failed(session: AsyncSession = Depends(get_session)):
    """Retraite tous les fichiers en échec ou manuels."""
    # Récupérer les fichiers en échec, manuels et en attente
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.status.in_([
                ProcessingStatus.FAILED,
                ProcessingStatus.MANUAL,
                ProcessingStatus.PENDING
            ])
        )
    )
    files_to_retry = result.scalars().all()
    
    processed = 0
    linked = 0
    still_failed = 0
    
    for media_file in files_to_retry:
        # Réinitialiser le statut
        media_file.status = ProcessingStatus.PENDING
        media_file.error_message = None
        
        # Supprimer l'ancien lien si existant
        if media_file.destination_path:
            file_linker.remove_link(Path(media_file.destination_path))
            media_file.destination_path = None
        
        await session.commit()
        
        # Retraiter
        media_file = await media_scanner.process_file(session, media_file)
        processed += 1
        
        # Émettre événement de mise à jour
        await event_manager.emit_file_updated(media_scanner.file_to_dict(media_file))
        
        if media_file.status == ProcessingStatus.LINKED:
            linked += 1
        elif media_file.status in [ProcessingStatus.FAILED, ProcessingStatus.MANUAL]:
            still_failed += 1
    
    # Émettre stats mises à jour
    stats = await media_scanner.get_stats(session)
    await event_manager.emit_stats_updated(stats)
    
    return {
        "message": "Retraitement terminé",
        "processed": processed,
        "linked": linked,
        "still_failed": still_failed
    }


@router.post("/cleanup-ignored")
async def cleanup_ignored_files(session: AsyncSession = Depends(get_session)):
    """Supprime les fichiers qui correspondent aux patterns d'ignorance (extras, creditless, etc.)."""
    result = await session.execute(select(MediaFile))
    all_files = result.scalars().all()
    
    deleted_count = 0
    deleted_files = []
    
    for media_file in all_files:
        if media_scanner.should_ignore_file(media_file.source_filename):
            # Supprimer le lien si existant
            if media_file.destination_path:
                file_linker.remove_link(Path(media_file.destination_path))
            
            deleted_files.append(media_file.source_filename[:50])
            await session.delete(media_file)
            deleted_count += 1
            
            # Émettre événement de suppression
            await event_manager.emit_file_deleted({"id": media_file.id})
    
    await session.commit()
    
    # Émettre stats mises à jour
    stats = await media_scanner.get_stats(session)
    await event_manager.emit_stats_updated(stats)
    
    return {
        "message": f"{deleted_count} fichiers ignorés supprimés",
        "deleted_count": deleted_count,
        "examples": deleted_files[:10]
    }


@router.post("/wipe")
async def wipe_database(session: AsyncSession = Depends(get_session)):
    """Supprime tous les fichiers de la base de données et leurs liens."""
    # Récupérer tous les fichiers avec un lien
    result = await session.execute(
        select(MediaFile).where(MediaFile.destination_path.isnot(None))
    )
    linked_files = result.scalars().all()
    
    links_removed = 0
    errors = []
    
    # Supprimer les liens
    for media_file in linked_files:
        if media_file.destination_path:
            try:
                dest_path = Path(media_file.destination_path)
                if dest_path.exists() or dest_path.is_symlink():
                    dest_path.unlink()
                    links_removed += 1
                    
                    # Nettoyer les dossiers vides
                    parent = dest_path.parent
                    try:
                        while parent and str(parent) not in [
                            str(config_manager.get_movies_path()),
                            str(config_manager.get_tv_path())
                        ]:
                            if parent.is_dir() and not any(parent.iterdir()):
                                parent.rmdir()
                                parent = parent.parent
                            else:
                                break
                    except Exception:
                        pass
            except Exception as e:
                errors.append(f"{media_file.destination_path}: {e}")
    
    # Supprimer tous les enregistrements de la base
    await session.execute(select(MediaFile).execution_options(synchronize_session="fetch"))
    result = await session.execute(select(MediaFile))
    all_files = result.scalars().all()
    
    for f in all_files:
        await session.delete(f)
    
    await session.commit()
    
    # Émettre événement de stats vidées
    await event_manager.emit_stats_updated({
        "total_files": 0,
        "pending": 0,
        "matched": 0,
        "linked": 0,
        "manual": 0,
        "failed": 0,
        "ignored": 0,
        "movies_total": 0,
        "tv_total": 0,
        "series_count": 0,
        "series_linked": 0,
        "pending_movies": 0,
        "pending_tv": 0,
        "linked_movies": 0,
        "linked_tv": 0,
        "manual_movies": 0,
        "manual_tv": 0,
        "failed_movies": 0,
        "failed_tv": 0
    })
    
    return {
        "message": "Base de données vidée",
        "links_removed": links_removed,
        "errors": errors if errors else None
    }
